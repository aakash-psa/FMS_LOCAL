from multiprocessing.util import info
import os
import json
import concurrent.futures
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db import transaction, close_old_connections
from django.db.models import Q, Exists, OuterRef
from django.contrib.auth.models import User

from management.decorators import require_project_permission
from management.models import (
    Project, UserProjectPermission, ProjectAsset, Iteration, UserIterationPermission,
    JvIteration, ConsolidatedIteration, ConsolidationSourceCombination,
    NormalisedIteration,
)
from management.serializers import ProjectSerializer, UserProjectPermissionSerializer, ScenarioSerializer
from management.permissions import IsMSALAuthenticated, MSALAuthentication
from django.http import HttpResponse, FileResponse
import mimetypes
import traceback
import requests
import base64
from google.auth.transport.requests import Request
from google.cloud import pubsub_v1
from django.conf import settings
from management.utils.gcs_helper import gcs_helper
import mainapp.utils.v3.landco_module as v3_utils
import mainapp.utils.v3.devco_model as devco_utils
import mainapp.utils.normalisation.landco_norm_v1 as landco_norm_utils
import mainapp.utils.normalisation.devco_norm_v1 as devco_norm_utils

import mainapp.utils.v3.assetco_model as assetco_utils
import mainapp.utils.v3.assetco_hospitality as assetco_hospitality_utils
import mainapp.utils.v3.assetco_consolidation as assetco_consolidated_utils
import mainapp.utils.v3.consolidated_model as consolidated_utils
import mainapp.utils.v3.jv_consolidation as jv_consolidated_utils
import mainapp.utils.v3.roshn_consolidation as roshn_consolidated_utils

logger = logging.getLogger(__name__)

def _should_publish_to_pubsub():
    """Only skip Pub/Sub publishing when TARGET_ENV is local."""
    target_env = os.environ.get("TARGET_ENV", "").lower()
    return target_env != "local"


def _build_assetco_consolidation_from_db(project, user, selected_assets,is_save):
    """
    Build AssetCo consolidated output from selected asset scenarios stored in DB.

    Args:
        project: Project instance
        user: Current authenticated User
        selected_assets: list of {asset_id, scenario_id}

    Returns:
        tuple(input_json, output_json)
    """
    if not isinstance(selected_assets, list) or len(selected_assets) == 0:
        raise ValueError("selected_assets must be a non-empty array")

    # Validate payload once and collect ids for bulk DB fetch.
    requested_pairs = []
    asset_ids = set()
    scenario_ids = set()
    for selected in selected_assets:
        asset_id = selected.get("asset_id")
        scenario_id = selected.get("scenario_id")

        if not asset_id or not scenario_id:
            raise ValueError("Each selected asset must include asset_id and scenario_id")

        requested_pairs.append((asset_id, scenario_id))
        asset_ids.add(asset_id)
        scenario_ids.add(scenario_id)

    assets_by_id = {
        asset.id: asset
        for asset in ProjectAsset.objects.filter(
            id__in=asset_ids,
            project_assoc_id=project.id,
            is_deleted=False,
        ).only('id', 'asset_unique_identifier', 'asset_name', 'is_hospitality')
    }

    if len(assets_by_id) != len(asset_ids):
        raise ValueError("One or more selected assets were not found in this project")

    scenarios_by_id = {
        scenario.id: scenario
        for scenario in Iteration.objects.filter(
            id__in=scenario_ids,
            project_assoc_id=project.id,
            iteration_type='assetco',
            is_deleted=False,
            asset_assoc__is_deleted=False,
        ).select_related('asset_assoc').only(
            'id',
            'name',
            'asset_assoc_id',
            'user_assoc_id',
            'output_json',
            'asset_assoc__id',
        )
    }

    if len(scenarios_by_id) != len(scenario_ids):
        raise ValueError("One or more selected scenarios were not found or are invalid for this project")

    shared_scenario_ids = set(
        UserIterationPermission.objects.filter(
            user_assoc_id=user.id,
            read_access=True,
        ).values_list("iteration_assoc_id", flat=True)
    )

    consolidated_input = []

    for asset_id, scenario_id in requested_pairs:
        asset = assets_by_id.get(asset_id)
        scenario = scenarios_by_id.get(scenario_id)

        if scenario.asset_assoc_id != asset_id:
            raise ValueError(f"Scenario {scenario_id} does not belong to asset {asset_id}")

        has_access = scenario.user_assoc_id == user.id or scenario.id in shared_scenario_ids
        if not has_access:
            raise PermissionError(f"You don't have access to scenario {scenario_id}")

        # Support both legacy shape (assetco only) and wrapped shape ({assetco: ...})
        scenario_output = scenario.output_json or {}
        assetco_output = scenario_output.get("assetco", scenario_output)

        consolidated_input.append({
            "asset_id": asset_id,
            "asset_identifier": asset.asset_unique_identifier,
            "asset_name": asset.asset_name,
            "is_hospitality": asset.is_hospitality,
            "scenario_id": scenario_id,
            "scenario_name": scenario.name,
            "output_json": assetco_output,
        })

    output_json = assetco_consolidated_utils.fninitialising_assetco_consolidation_values(consolidated_input,is_save)
    if output_json is None:
        raise ValueError("Failed to compute consolidated outputs. Check server logs.")


    return consolidated_input, output_json


def _build_jv_consolidation_from_db(project, user, input_payload):
    """
    Resolve JV consolidation source scenarios using only JvIteration rows.

    Expected input shape:
    {
        "selected_scenarios": [
            {
                "source_type": "landco_devco" | "assetco_consolidation",
                "jv_iteration_id": int,
            }
        ]
    }
    """
    if not isinstance(input_payload, dict):
        raise ValueError("input_json must be an object for jv_consolidation")

    selected_scenarios = input_payload.get("selected_scenarios")
    if not isinstance(selected_scenarios, list) or len(selected_scenarios) == 0:
        raise ValueError("selected_scenarios must be a non-empty array")

    allowed_types = {"landco_devco", "assetco_consolidation"}

    # Validate and collect all jv_iteration_ids in one pass before hitting the DB
    items_by_id = {}
    for item in selected_scenarios:
        if not isinstance(item, dict):
            raise ValueError("Each selected scenario must be an object")

        source_type = str(item.get("source_type") or "").strip().lower()
        if source_type not in allowed_types:
            raise ValueError("source_type must be one of: landco_devco, assetco_consolidation")

        jv_iteration_id = item.get("jv_iteration_id")
        if not jv_iteration_id:
            raise ValueError("Each selected scenario must include jv_iteration_id")

        items_by_id[jv_iteration_id] = source_type

    # Single bulk query: all JvIteration rows + their base iterations
    jv_rows = {
        row.id: row
        for row in JvIteration.objects.filter(
            id__in=items_by_id.keys(),
            iteration_assoc__project_assoc_id=project.id,
            iteration_assoc__is_deleted=False,
        ).select_related('iteration_assoc')
    }

    shared_iteration_ids = set(
        UserIterationPermission.objects.filter(
            user_assoc_id=user.id,
            read_access=True,
        ).values_list("iteration_assoc_id", flat=True)
    )

    result = {
        "landco_devco": {},
        "assetco_consolidation": {},
    }

    namedranges = input_payload.get("namedranges")
    if isinstance(namedranges, list):
        result["namedranges"] = namedranges

    for jv_iteration_id, source_type in items_by_id.items():
        row = jv_rows.get(jv_iteration_id)
        if not row:
            raise ValueError(f"JV scenario {jv_iteration_id} not found or does not belong to this project")

        iteration = row.iteration_assoc
        if not (iteration.user_assoc_id == user.id or iteration.id in shared_iteration_ids):
            raise PermissionError(f"You don't have access to scenario {iteration.id}")

        result[source_type] = row.output_json or {}

    return result


def _build_project_consolidation_from_db(project, user, source_selection, namedRanges):
    """
    Resolve selected project consolidation sources from DB and construct payload
    expected by consolidated_utils.
    """
    if not isinstance(source_selection, dict):
        raise ValueError("source_selection is required for project_consolidation")

    selections_by_type_raw = source_selection.get("selections_by_type") or []
    if not isinstance(selections_by_type_raw, list):
        raise ValueError("selections_by_type must be an array")

    # Group items by source_type and collect all consolidated_iteration_ids in one pass
    selections_by_type = {}
    required_ids = []
    for item in selections_by_type_raw:
        if isinstance(item, dict):
            st = item.get("source_type")
            cid = item.get("consolidated_iteration_id")
            if st:
                selections_by_type.setdefault(st, []).append(item)
            if cid:
                required_ids.append(cid)

    # Validate required selections are present before hitting the DB
    if not selections_by_type.get("landco_devco"):
        raise ValueError("Please select one LandCo/DevCo scenario")
    if not selections_by_type.get("assetco_consolidation"):
        raise ValueError("Please select one AssetCo consolidation scenario")

    # Single bulk query: load all needed ConsolidatedIteration rows + their iterations in one go
    rows = {
        row.id: row
        for row in ConsolidatedIteration.objects.filter(
            id__in=required_ids,
            iteration_assoc__project_assoc_id=project.id,
            iteration_assoc__is_deleted=False,
        ).select_related('iteration_assoc')
    }

    shared_iteration_ids = set(
        UserIterationPermission.objects.filter(
            user_assoc_id=user.id,
            read_access=True,
        ).values_list("iteration_assoc_id", flat=True)
    )

    def _get_output(selection_item, expected_type, label):
        cid = selection_item.get("consolidated_iteration_id")
        if not cid:
            raise ValueError(f"Invalid {label} selection: consolidated_iteration_id is required")

        row = rows.get(cid)
        if not row:
            raise ValueError(f"{label} consolidated scenario {cid} not found or does not belong to this project")
        if row.iteration_type != expected_type:
            raise ValueError(f"{label} scenario has unexpected type '{row.iteration_type}'")

        iteration = row.iteration_assoc
        if not (iteration.user_assoc_id == user.id or iteration.id in shared_iteration_ids):
            raise PermissionError(f"You don't have access to scenario {iteration.id}")

        return row.output_json or {}

    landco_devco_output = _get_output(selections_by_type["landco_devco"][0], 'landco_devco', 'LandCo/DevCo')
    assetco_output = _get_output(selections_by_type["assetco_consolidation"][0], 'assetco_consolidation', 'AssetCo consolidation')

    jv_output = {}
    jv_list = selections_by_type.get("jv_consolidation") or []
    if jv_list:
        jv_output = _get_output(jv_list[0], 'jv_consolidation', 'JV consolidation')

    landco_payload = landco_devco_output.get('landco', {}) if isinstance(landco_devco_output, dict) else {}
    devco_payload = landco_devco_output.get('devco', {}) if isinstance(landco_devco_output, dict) else {}

    if not isinstance(landco_payload, dict) or not isinstance(devco_payload, dict):
        raise ValueError("Invalid LandCo/DevCo source output found in DB")

    return {
        'landco': landco_payload,
        'devco': devco_payload,
        'assetco_consolidated': assetco_output,
        'jv_consolidation': jv_output if isinstance(jv_output, dict) else {},
        'namedRanges': namedRanges if isinstance(namedRanges, list) else [],
    }


def _build_roshn_consolidation_from_db(user, selected_projects):
    """
    Resolve ROSHN consolidation sources from Iteration table.

    Accepted source_selection shapes:
    1) {
         "selected_projects": [
           {"project_id": int, "scenario_id": int}
         ]
       }
    2) {
         "selections_by_type": [
           {
             "source_type": "project_to_project_consolidation",
             "scenario_id" | "iteration_id" | "source_iteration_id": int
           }
         ]
       }
    3) list of objects with any of the id keys above.
    """
    if not selected_projects:
        raise ValueError("selected_projects is required for roshn_consolidation")

    selected_items = []
    if isinstance(selected_projects, dict):
        if isinstance(selected_projects.get("selected_projects"), list):
            selected_items = selected_projects.get("selected_projects") or []
        elif isinstance(selected_projects.get("selections_by_type"), list):
            selected_items = [
                item
                for item in (selected_projects.get("selections_by_type") or [])
                if isinstance(item, dict)
                and str(item.get("source_type") or "").strip().lower() == "project_to_project_consolidation"
            ]
    elif isinstance(selected_projects, list):
        selected_items = selected_projects

    if not isinstance(selected_items, list) or len(selected_items) == 0:
        raise ValueError("No project_to_project_consolidation scenarios were selected")

    requested_iteration_ids = []
    for item in selected_items:
        if not isinstance(item, dict):
            continue

        iteration_id = (
            item.get("scenario_id")
            or item.get("iteration_id")
            or item.get("source_iteration_id")
            or item.get("consolidated_iteration_id")
        )
        if not iteration_id:
            continue

        requested_iteration_ids.append(int(iteration_id))

    if len(requested_iteration_ids) == 0:
        raise ValueError("No valid scenario_id/iteration_id found in source_selection")

    # Preserve user selection order while removing duplicates.
    requested_iteration_ids = list(dict.fromkeys(requested_iteration_ids))

    rows_by_id = {
        row.id: row
        for row in Iteration.objects.filter(
            id__in=requested_iteration_ids,
            iteration_type='project_consolidation',
            asset_assoc__isnull=True,
            is_deleted=False,
            project_assoc__is_deleted=False,
        ).select_related('project_assoc')
    }

    if len(rows_by_id) != len(requested_iteration_ids):
        raise ValueError("One or more selected scenarios were not found or are invalid for ROSHN consolidation")

    shared_iteration_ids = set(
        UserIterationPermission.objects.filter(
            user_assoc_id=user.id,
            read_access=True,
        ).values_list("iteration_assoc_id", flat=True)
    )

    selected_projects = []
    project_to_project_rows = []
    for iteration_id in requested_iteration_ids:
        iteration = rows_by_id.get(iteration_id)

        has_access = iteration.user_assoc_id == user.id or iteration.id in shared_iteration_ids
        if not has_access:
            raise PermissionError(f"You don't have access to scenario {iteration.id}")

        selected_projects.append(
            {
                "project_id": iteration.project_assoc_id,
                "scenario_id": iteration.id,
            }
        )

        project_to_project_rows.append(
            {
                "iteration_id": iteration.id,
                "scenario_id": iteration.id,
                "name": iteration.name,
                "project_id": iteration.project_assoc_id,
                "project_name": iteration.project_assoc.name if iteration.project_assoc else None,
                "created_at": iteration.created_at.isoformat() if iteration.created_at else None,
                "updated_at": iteration.updated_at.isoformat() if iteration.updated_at else None,
                "output_json": iteration.output_json or {},
            }
        )

    return {
        "project_consolidation": project_to_project_rows,
        "selected_projects": selected_projects,
    }


def _persist_consolidation_source_combination(
    project,
    user,
    target_iteration,
    iteration_type,
    selected_assets=None,
    jv_input_json=None,
    project_source_selection=None,
):
    tracked_types = {'assetco_consolidation', 'jv_consolidation', 'project_consolidation','roshn_consolidation'}
    if iteration_type not in tracked_types:
        ConsolidationSourceCombination.objects.filter(target_iteration=target_iteration).delete()
        return

    rows_to_create = []

    if iteration_type == 'assetco_consolidation':
        selections = selected_assets if isinstance(selected_assets, list) else []
        for item in selections:
            if not isinstance(item, dict):
                continue
            scenario_id = item.get('scenario_id')
            asset_id = item.get('asset_id')
            rows_to_create.append(
                ConsolidationSourceCombination(
                    target_iteration=target_iteration,
                    project_assoc=project,
                    user_assoc=user,
                    consolidation_type=iteration_type,
                    source_iteration_ids=int(scenario_id) if scenario_id else None,
                    source_iteration_type='assetco',
                    source_reference_id=int(asset_id) if asset_id else None,
                    scenario_name=item.get('scenario_name'),
                )
            )

    elif iteration_type == 'jv_consolidation':
        selected_scenarios = []
        if isinstance(jv_input_json, dict):
            selected_scenarios = jv_input_json.get('selected_scenarios') or []

        jv_iteration_ids = []
        for item in selected_scenarios:
            if not isinstance(item, dict):
                continue
            jv_id = item.get('jv_iteration_id')
            if jv_id:
                jv_iteration_ids.append(int(jv_id))

        jv_rows = {
            row['id']: row
            for row in JvIteration.objects.filter(id__in=jv_iteration_ids).values(
                'id', 'name', 'iteration_assoc_id', 'iteration_type'
            )
        }

        for item in selected_scenarios:
            if not isinstance(item, dict):
                continue
            jv_id = item.get('jv_iteration_id')
            if not jv_id:
                continue
            row = jv_rows.get(int(jv_id))
            iteration_id = int(row['iteration_assoc_id']) if row and row.get('iteration_assoc_id') else None
            rows_to_create.append(
                ConsolidationSourceCombination(
                    target_iteration=target_iteration,
                    project_assoc=project,
                    user_assoc=user,
                    consolidation_type=iteration_type,
                    source_iteration_ids=iteration_id,
                    source_iteration_type=row.get('iteration_type') if row else None,
                    source_reference_id=int(jv_id),
                    scenario_name=row.get('name') if row else None,
                )
            )

    elif iteration_type == 'project_consolidation':
        selections_by_type = []
        if isinstance(project_source_selection, dict):
            selections_by_type = project_source_selection.get('selections_by_type') or []

        consolidated_ids = []
        normalized_selections = []
        for item in selections_by_type:
            if not isinstance(item, dict):
                continue
            consolidated_id = item.get('consolidated_iteration_id')
            if consolidated_id:
                consolidated_ids.append(int(consolidated_id))
            normalized_selections.append({
                'source_type': item.get('source_type'),
                'consolidated_iteration_id': int(consolidated_id) if consolidated_id else None,
            })

        consolidated_rows = {
            row['id']: row
            for row in ConsolidatedIteration.objects.filter(id__in=consolidated_ids).values(
                'id', 'name', 'iteration_assoc_id', 'iteration_type'
            )
        }

        for item in normalized_selections:
            consolidated_id = item.get('consolidated_iteration_id')
            if not consolidated_id:
                continue
            row = consolidated_rows.get(consolidated_id)
            
            iteration_id = int(row['iteration_assoc_id']) if row and row.get('iteration_assoc_id') else None
            rows_to_create.append(
                ConsolidationSourceCombination(
                    target_iteration=target_iteration,
                    project_assoc=project,
                    user_assoc=user,
                    consolidation_type=iteration_type,
                    source_iteration_ids=iteration_id,
                    source_iteration_type=row.get('iteration_type') if row else None,
                    source_reference_id=int(consolidated_id),
                    scenario_name=row.get('name') if row else None,
                )
            )

    elif iteration_type == 'roshn_consolidation':
        # Accept both saved shapes:
        # 1) input_json.selected_projects
        # 2) source_selection.selections_by_type (project_to_project_consolidation)
        source_payload = {}
        if isinstance(project_source_selection, dict):
            source_payload = project_source_selection
        elif isinstance(jv_input_json, dict):
            source_payload = jv_input_json

        selected_items = []
        if isinstance(source_payload.get('selected_projects'), list):
            selected_items = source_payload.get('selected_projects') or []
        elif isinstance(source_payload.get('selections_by_type'), list):
            selected_items = [
                item
                for item in (source_payload.get('selections_by_type') or [])
                if isinstance(item, dict)
                and str(item.get('source_type') or '').strip().lower() == 'project_to_project_consolidation'
            ]
        elif isinstance(source_payload, list):
            selected_items = source_payload

        source_iteration_ids = []
        for item in selected_items:
            if not isinstance(item, dict):
                continue

            iteration_id = (
                item.get('scenario_id')
                or item.get('iteration_id')
                or item.get('source_iteration_id')
                or item.get('consolidated_iteration_id')
            )
            if not iteration_id:
                continue

            try:
                source_iteration_ids.append(int(iteration_id))
            except (TypeError, ValueError):
                continue

        source_iteration_ids = list(dict.fromkeys(source_iteration_ids))
        iteration_rows = {
            row['id']: row
            for row in Iteration.objects.filter(id__in=source_iteration_ids).values('id', 'name', 'iteration_type')
        }

        for source_iteration_id in source_iteration_ids:
            row = iteration_rows.get(source_iteration_id)
            rows_to_create.append(
                ConsolidationSourceCombination(
                    target_iteration=target_iteration,
                    project_assoc=project,
                    user_assoc=user,
                    consolidation_type=iteration_type,
                    source_iteration_ids=source_iteration_id,
                    source_iteration_type=(row.get('iteration_type') if row else 'project_consolidation'),
                    source_reference_id=source_iteration_id,
                    scenario_name=row.get('name') if row else None,
                )
            )

    # Also persist the consolidation iteration itself as a source record.
    rows_to_create.append(
        ConsolidationSourceCombination(
            target_iteration=target_iteration,
            project_assoc=project,
            user_assoc=user,
            consolidation_type=iteration_type,
            source_iteration_ids=int(target_iteration.id) if target_iteration and target_iteration.id else None,
            source_iteration_type=iteration_type,
            source_reference_id=int(target_iteration.id) if target_iteration and target_iteration.id else None,
            scenario_name=target_iteration.name if target_iteration else None,
        )
    )

    # Keep one row per unique tuple to avoid accidental duplicates.
    deduped_rows = []
    seen = set()
    for row in rows_to_create:
        key = (
            row.target_iteration_id,
            row.consolidation_type,
            row.source_iteration_ids,
            row.source_iteration_type,
            row.source_reference_id,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped_rows.append(row)

    ConsolidationSourceCombination.objects.filter(target_iteration=target_iteration).delete()
    if deduped_rows:
        ConsolidationSourceCombination.objects.bulk_create(deduped_rows)

def _ensure_roshn_container_project(user):
    """
    Ensure exactly one active ROSHN Consolidation project exists.
    If duplicates exist by name, keep the first and soft-delete the rest.
    """
    roshn_name = "ROSHN Consolidation"

    with transaction.atomic():
        matches = list(
            Project.objects.select_for_update()
            .filter(name__iexact=roshn_name, is_deleted=False)
            .order_by("id")
        )

        if not matches:
            project = Project.objects.create(
                name=roshn_name,
                created_by=user,
                updated_by=user,
                is_deleted=False,
            )
            UserProjectPermission.objects.update_or_create(
                user_assoc=user,
                project_assoc=project,
                defaults={
                    "read_access": True,
                    "write_access": True,
                    "created_by": user,
                    "updated_by": user,
                },
            )
            return project

        primary = matches[0]

        # Soft-delete duplicates, do not hard delete (to avoid FK cascade damage)
        duplicate_ids = [p.id for p in matches[1:]]
        if duplicate_ids:
            Project.objects.filter(id__in=duplicate_ids).update(
                is_deleted=True,
                updated_by=user,
            )

        UserProjectPermission.objects.update_or_create(
            user_assoc=user,
            project_assoc=primary,
            defaults={
                "read_access": True,
                "write_access": True,
                "created_by": user,
                "updated_by": user,
            },
        )

        return primary
class UserAssignedProjectsView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def get(self, request, user_id=None):
        """
        Get all projects assigned to a specific user.
        If user_id is not provided, returns projects for the authenticated user.
        """
        user_id = request.query_params.get("user_id", None)
        # If user_id is provided, use that; otherwise use authenticated user
        if user_id:
            user = get_object_or_404(User, username=user_id, is_active=True)
        else:
            # Try to get authenticated user
            if hasattr(request, 'user') and isinstance(request.user, User):
                user = request.user
            else:
                return Response(
                    {"detail": "User not found"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
        
        # Get all project permissions for the user
        permissions = UserProjectPermission.objects.filter(
            user_assoc=user
        ).select_related('project_assoc')
        
        # Build response with project details and permissions
        assigned_projects = []
        for perm in permissions:
            project = perm.project_assoc
            project_data = ProjectSerializer(project).data
            project_data['permissions'] = {
                'read_access': perm.read_access,
                'write_access': perm.write_access,
            }
            assigned_projects.append(project_data)
        
        return Response({
            'user_id': user.username,
            'user_email': user.email,
            'user_name': f"{user.first_name} {user.last_name}".strip() or user.username,
            'total_projects': len(assigned_projects),
            'projects': assigned_projects
        })

class LandCoOutputFromJsonView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, *args, **kwargs):
        payload = request.data
        if payload is None:
            return Response({"detail": "Request body must contain the named range payload."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            outputs = v3_utils.fninitialising_all_values(payload,is_save=False)
            print(f"[LandCoOutputFromJsonView] Successfully processed LandCo payload")
        except ValueError as exc:
            print(f"[LandCoOutputFromJsonView] ValueError: {exc}")
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - safety net
            import traceback
            error_trace = traceback.format_exc()
            print(f"[LandCoOutputFromJsonView] Exception occurred:")
            print(f"  Type: {type(exc).__name__}")
            print(f"  Message: {exc}")
            print(f"  Traceback:\n{error_trace}")
            return Response({
                "detail": f"Unexpected error while processing payload: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        print(f"[LandCoOutputFromJsonView] Returning 200 OK response with outputs")
        return Response(outputs, status=status.HTTP_200_OK)
class DEVCoOutputFromJsonView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, *args, **kwargs):
        payload = request.data
        if payload is None:
            return Response({"detail": "Request body must contain the named range payload."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            outputs = devco_utils.fninitialising_all_values(payload,is_save=False)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - safety net
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Unexpected error while processing payload: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(outputs, status=status.HTTP_200_OK)
class ASSETCoOutputFromJsonView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, *args, **kwargs):
        payload = request.data
        if payload is None:
            return Response({"detail": "Request body must contain the named range payload."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Support both legacy payload (named-range list) and wrapped payload:
            # {"input_json": [...], "is_hospitality": bool}
            if isinstance(payload, dict):
                calc_payload = payload.get("input_json", payload)
                is_hospitality = bool(payload.get("is_hospitality", False))
            else:
                calc_payload = payload
                is_hospitality = False

            if is_hospitality:
                outputs = assetco_hospitality_utils.fninitialising_all_values(calc_payload, is_save=False)
            else:
                outputs = assetco_utils.fninitialising_all_values(calc_payload, is_save=False)
            
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - safety net
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Unexpected error while processing payload: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(outputs, status=status.HTTP_200_OK)
class CONSOLIDATEDOutputFromJsonView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, *args, **kwargs):
        payload = request.data
        if payload is None or not isinstance(payload, dict):
            return Response({"detail": "Request body must contain the named range payload."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            calculation_module = payload.get("calculation_module")
            module_key = str(calculation_module or "").strip().lower()

            supported_modules = {
                "assetco_consolidation",
                "project_consolidation",
                "jv_consolidation",
                "roshn_consolidation",
            }

            if module_key not in supported_modules:
                return Response(
                    {
                        "detail": "Invalid calculation_module. Use one of: assetco_consolidation, project_consolidation, jv_consolidation, roshn_consolidation"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if module_key == "assetco_consolidation":
                project_id = payload.get("project_id")
                selected_assets = payload.get("selected_assets")

                if not selected_assets and isinstance(payload.get("input_json"), dict):
                    selected_assets = payload.get("input_json", {}).get("selected_assets")

                if not project_id:
                    return Response({"detail": "project_id is required for assetco_consolidation"}, status=status.HTTP_400_BAD_REQUEST)

                project = get_object_or_404(Project, id=project_id, is_deleted=False)
                user = User.objects.get(username=request.user['user_id'])
                _, outputs = _build_assetco_consolidation_from_db(project, user, selected_assets,is_save=False)
            elif module_key == "jv_consolidation":
                input_payload = payload.get("input_json")
                if input_payload is None:
                    input_payload = {
                        key: value
                        for key, value in payload.items()
                        if key not in {"calculation_module", "project_id"}
                    }

                project_id = payload.get("project_id")
                if not project_id:
                    return Response(
                        {"detail": "project_id is required for jv_consolidation"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                project = get_object_or_404(Project, id=project_id, is_deleted=False)
                user = User.objects.get(username=request.user['user_id'])
                input_payload = _build_jv_consolidation_from_db(project, user, input_payload)

                outputs = jv_consolidated_utils.fninitialising_all_values(input_payload, is_save=False)
            elif module_key == "project_consolidation":
                project_id = payload.get("project_id")
                if not project_id:
                    return Response(
                        {"detail": "project_id is required for project_consolidation"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                input_payload = payload.get("input_json")
                source_selection = input_payload.get("source_selection") if isinstance(input_payload, dict) else payload.get("source_selection")
                namedRanges = input_payload.get("namedRanges") if isinstance(input_payload, dict) else payload.get("namedRanges")
                if not isinstance(source_selection, dict):
                    return Response(
                        {"detail": "source_selection is required for project_consolidation"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                project = get_object_or_404(Project, id=project_id, is_deleted=False)
                user = User.objects.get(username=request.user['user_id'])
                resolved_payload = _build_project_consolidation_from_db(project, user, source_selection, namedRanges)
                outputs = consolidated_utils.fninitialising_all_values(resolved_payload, is_save=False)
            elif module_key == "roshn_consolidation":
                input_payload = payload.get("input_json")
                if input_payload is None:
                    input_payload = {
                        key: value
                        for key, value in payload.items()
                        if key not in {"calculation_module"}
                    }

                selected_projects = payload.get("selected_projects") if isinstance(input_payload, dict) else payload.get("source_selection")
               
                user = User.objects.get(username=request.user['user_id'])
                input_payload = _build_roshn_consolidation_from_db(user, selected_projects)

                outputs = roshn_consolidated_utils.fninitialising_all_values(input_payload, is_save=False)
            if outputs is None:
                return Response(
                    {"detail": f"Failed to compute outputs for module '{module_key}'. Please check server logs for details."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - safety net
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Unexpected error while processing payload: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(outputs, status=status.HTTP_200_OK)


class LandCoOutputFromJsonSaveView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, *args, **kwargs):
        payload = request.data
        if payload is None:
            return Response({"detail": "Request body must contain the named range payload."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Run the three functions in parallel using ThreadPoolExecutor
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                # Submit all three tasks to run in parallel
                landco_future = executor.submit(v3_utils.fninitialising_all_values, payload["input_json"], is_save=False)
                devco_future = executor.submit(devco_utils.fninitialising_all_values, payload["input_json"], is_save=False)
                assetco_future = executor.submit(assetco_utils.fninitialising_all_values, payload["input_json"], is_save=False)
                
                # Wait for all three to complete and get results
                landco = landco_future.result()
                devco = devco_future.result()
                assetco = assetco_future.result()

            if landco is None or devco is None or assetco is None:
                failed_models = []
                if landco is None:
                    failed_models.append("landco")
                if devco is None:
                    failed_models.append("devco")
                if assetco is None:
                    failed_models.append("assetco")

                return Response(
                    {
                        "detail": "Failed to compute one or more model outputs.",
                        "failed_models": failed_models,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            
            # Build consolidated payload from parallel results
            cons_payload = {
                "landco": landco,
                "devco": devco,
                "assetco": assetco
            }

            # Run consolidated calculations AFTER all three complete
            outputs = consolidated_utils.fninitialising_all_values(cons_payload, is_save=False)
            cons_payload["consolidated"] = outputs
            
            # Save to database
            project_info = Project.objects.get(id=payload["project_id"])
            user_info = User.objects.get(username=request.user['user_id'])
            info = Iteration(
                project_assoc=project_info,
                user_assoc=user_info,
                name=payload["name"],
                input_json=payload["input_json"],
                output_json=cons_payload
            )
            info.save()
            
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except concurrent.futures.TimeoutError:
            return Response({
                "detail": "One or more calculations timed out",
                "error_type": "TimeoutError"
            }, status=status.HTTP_504_GATEWAY_TIMEOUT)
        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Unexpected error while processing payload: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(cons_payload, status=status.HTTP_200_OK)


class DownloadTemplateView(APIView):
    authentication_classes = [MSALAuthentication]
    # permission_classes = [IsMSALAuthenticated]

    def get(self, request, project_id):

        @require_project_permission(read=True)
        def handler(self, request, project_id):


            project = get_object_or_404(Project, id=project_id, is_deleted=False)

            if not project.template_link:
                return Response({"detail": "No template file associated with this project"}, status=status.HTTP_404_NOT_FOUND)

            try:
                template_link = project.template_link.strip()

                # Extract bucket and blob path
                bucket = None
                blob_path = None
                if template_link.startswith("gs://"):
                    # gs://bucket/path/to/blob
                    path = template_link[len("gs://"):]
                    parts = path.split("/", 1)
                    if len(parts) != 2 or not parts[0] or not parts[1]:
                        raise ValueError("Invalid gs:// path")
                    bucket, blob_path = parts[0], parts[1]
                else:
                    # support storage.cloud.google.com/<bucket>/<path> or https://storage.googleapis.com/<bucket>/<path>
                    from urllib.parse import urlparse
                    parsed = urlparse(template_link)
                    path = parsed.path.lstrip("/")
                    parts = path.split("/", 1)
                    if len(parts) == 2:
                        bucket, blob_path = parts[0], parts[1]
                    else:
                        # fallback to configured bucket if only blob path provided
                        bucket = getattr(settings, "GCS_BUCKET_NAME", None)
                        blob_path = template_link.lstrip("/")

                if not bucket or not blob_path:
                    raise ValueError("Unable to determine GCS bucket or object path from template_link")

                # Obtain access token from the storage client credentials and download via signed request
                if not gcs_helper.client or not getattr(gcs_helper, "client", None):
                    raise Exception("GCS client not initialized on backend")

                creds = gcs_helper.client._credentials
                creds.refresh(Request())
                access_token = creds.token

                url = f"https://storage.googleapis.com/{bucket}/{blob_path}"
                headers = {"Authorization": f"Bearer {access_token}"}

                resp = requests.get(url, headers=headers, timeout=60)

                if resp.status_code != 200:
                    return Response(
                        {"detail": f"GCS download failed: {resp.status_code}"},
                        status=status.HTTP_502_BAD_GATEWAY
                    )

                # Determine filename and content type
                filename = blob_path.split("/")[-1]
                content_type = resp.headers.get("Content-Type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"

                # Return as JSON with base64-encoded file so frontend can reconstruct the Excel file:
                file_b64 = base64.b64encode(resp.content).decode("ascii")
                return Response({
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": len(resp.content),
                    "file_base64": file_b64
                }, status=status.HTTP_200_OK)

            except Exception as e:
                return Response({"detail": f"Failed to fetch template file: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return handler(self, request, project_id=project_id)

class ScenarioListView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(read=True)
    def post(self, request, project_id):
        """
        Unified scenarios API supporting multiple operations.
        Expected payload:
        {
            "scenario_id": int (optional, get specific scenario),
            "asset_id": int (optional, get asset scenarios),
            "user_id": str (optional, filter by user)
        }
        
        If scenario_id is provided: Returns specific scenario data
        If asset_id is provided: Returns all scenarios for that asset
        Otherwise: Returns all scenarios for the project (optionally filtered by user)
        """
        project = get_object_or_404(Project.objects.only('id', 'name'), id=project_id, is_deleted=False)
        payload = request.data or {}
        
        scenario_id = payload.get('scenario_id')
        asset_id = payload.get('asset_id')
        user_id = payload.get('user_id')
        iteration_type = payload.get('iteration_type')
        
        # Get current user
        current_user = User.objects.only('id').get(username=request.user['user_id'])
        
        # Check if current user has read access to this project
        has_project_access = UserProjectPermission.objects.filter(
            user_assoc_id=current_user.id,
            project_assoc_id=project_id,
            read_access=True,
        ).exists()

        if not has_project_access:
            return Response({
                'project_id': project_id,
                'total_scenarios': 0,
                'scenarios': []
            }, status=status.HTTP_200_OK)

        shared_iteration_ids = UserIterationPermission.objects.filter(
            user_assoc_id=current_user.id,
            read_access=True,
        ).values_list('iteration_assoc_id', flat=True)
        
        # Case 1: Get specific scenario data
        if scenario_id:
            scenario = get_object_or_404(
                Iteration,
                id=scenario_id,
                project_assoc_id=project_id,
                is_deleted=False
            )
            
            # Check if user created the scenario or it was shared with them
            is_owner = scenario.user_assoc_id == current_user.id
            is_shared = UserIterationPermission.objects.filter(
                iteration_assoc_id=scenario.id,
                user_assoc_id=current_user.id,
                read_access=True
            ).exists()
            
            if not is_owner and not is_shared:
                return Response(
                    {"detail": "You do not have access to this scenario"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            serializer = ScenarioSerializer(scenario)
            return Response({
                'project_id': project_id,
                'scenario_id': scenario_id,
                'scenario': serializer.data
            }, status=status.HTTP_200_OK)
        
        # Case 2: Get asset scenarios
        if asset_id:
            asset = get_object_or_404(
                ProjectAsset.objects.only('id', 'asset_name'),
                id=asset_id,
                project_assoc_id=project_id,
                is_deleted=False
            )

            unique_scenarios = list(
                Iteration.objects.filter(
                    project_assoc_id=project_id,
                    asset_assoc_id=asset_id,
                    iteration_type='assetco',
                    is_deleted=False,
                ).filter(
                    Q(user_assoc_id=current_user.id) | Q(id__in=shared_iteration_ids)
                ).values('id', 'name').order_by('-id')
            )
            
            return Response({
                'project_id': project_id,
                'asset_id': asset_id,
                'asset_name': asset.asset_name,
                'scenario_type': 'assetco',
                'total_scenarios': len(unique_scenarios),
                'scenarios': unique_scenarios
            }, status=status.HTTP_200_OK)
        
        # Case 3: Get project scenarios (optionally filtered by iteration_type)
        # Normalize iteration_type aliases for unified frontend usage
        iteration_type_aliases = {
            'assetco_consolidation': ['assetco_consolidation'],
            'project_consolidation': ['project_consolidation'],
            # keep backward compatibility for historical JV saves under consolidation
            'jv_consolidation': ['jv_consolidation'],
            'roshn_consolidation': ['roshn_consolidation'],
        }

        if iteration_type:
            normalized_types = iteration_type_aliases.get(iteration_type, [iteration_type])

            unique_scenarios = list(
                Iteration.objects.filter(
                    project_assoc_id=project_id,
                    asset_assoc__isnull=True,
                    is_deleted=False,
                    iteration_type__in=normalized_types,
                ).filter(
                    Q(user_assoc_id=current_user.id) | Q(id__in=shared_iteration_ids)
                ).annotate(
                    has_normalised_data=Exists(
                        NormalisedIteration.objects.filter(iteration=OuterRef('pk'))
                    )
                ).values('id', 'name', 'iteration_type', 'has_normalised_data').order_by('-id')
            )

            return Response({
                'project_id': project_id,
                'project_name': project.name,
                'scenario_type': iteration_type,
                'total_scenarios': len(unique_scenarios),
                'scenarios': unique_scenarios
            }, status=status.HTTP_200_OK)
        
        unique_scenarios = list(
            Iteration.objects.filter(
                project_assoc_id=project_id,
                asset_assoc__isnull=True,
                is_deleted=False,
            ).filter(
                Q(user_assoc_id=current_user.id) | Q(id__in=shared_iteration_ids)
            ).filter(
                Q(iteration_type='landco_devco') | Q(iteration_type__isnull=True) | Q(iteration_type='')
            ).annotate(
                has_normalised_data=Exists(
                    NormalisedIteration.objects.filter(iteration=OuterRef('pk'))
                )
            ).values('id', 'name', 'has_normalised_data').order_by('-id')
        )
        
        return Response({
            'project_id': project_id,
            'project_name': project.name,
            'scenario_type': 'landco_devco',
            'total_scenarios': len(unique_scenarios),
            'scenarios': unique_scenarios
        }, status=status.HTTP_200_OK)


class ScenarioDetailView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(read=True)
    def get(self, request, project_id, scenario_id):
        """
        Get a specific scenario by ID.
        """
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        scenario = get_object_or_404(
            Iteration, 
            id=scenario_id, 
            project_assoc=project
        )
        
        serializer = ScenarioSerializer(scenario)
        return Response(serializer.data)
    #
    # @require_project_permission(write=True)
    # def delete(self, request, project_id, iteration_id):
    #     """
    #     Delete a specific iteration.
    #     """
    #     project = get_object_or_404(Project, id=project_id, is_deleted=False)
    #     iteration = get_object_or_404(
    #         Iteration,
    #         id=iteration_id,
    #         project_assoc=project
    #     )
    #
    #     iteration.delete()
    #
    #     return Response({
    #         'detail': 'Iteration deleted successfully',
    #         'iteration_id': iteration_id
    #     }, status=status.HTTP_200_OK)


# ================ Asset-Specific Scenario APIs ================

class AssetScenarioListView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(read=True)
    def get(self, request, project_id, asset_id):
        """
        Get all scenarios for a specific asset.
        Returns only scenario id and name for AssetCo iterations.
        """
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        asset = get_object_or_404(ProjectAsset, id=asset_id, project_assoc=project, is_deleted=False)
        
        # Get scenarios for this specific asset (AssetCo type)
        scenarios = Iteration.objects.filter(
            project_assoc=project,
            asset_assoc=asset,
            iteration_type='assetco'
        ).order_by('-created_at').values('id', 'name')
        
        return Response({
            'project_id': project_id,
            'asset_id': asset_id,
            'asset_name': asset.asset_name,
            'total_scenarios': len(scenarios),
            'scenarios': list(scenarios)
        })


class AssetScenarioDetailView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(read=True)
    def get(self, request, project_id, asset_id, scenario_id):
        """
        Get a specific asset scenario by ID.
        """
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        asset = get_object_or_404(ProjectAsset, id=asset_id, project_assoc=project, is_deleted=False)
        scenario = get_object_or_404(
            Iteration, 
            id=scenario_id, 
            project_assoc=project,
            asset_assoc=asset
        )
        
        serializer = ScenarioSerializer(scenario)
        return Response(serializer.data)


# ================ Save Iteration APIs ================

class AssetCoSaveIterationView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(write=True)
    def post(self, request, *args, **kwargs):
        """
        Save AssetCo iteration for a specific asset.
        Expected payload: {
            "project_id": int,
            "asset_id": int,
            "name": str,
            "input_json": dict,
            "output_json": dict
        }
        """
        payload = request.data
        if not payload:
            return Response(
                {"detail": "Request body must contain iteration data."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            project_id = payload.get("project_id")
            asset_id = payload.get("asset_id")
            name = payload.get("name")
            input_json = payload.get("input_json")
            output_json = payload.get("output_json")

            if not all([project_id, asset_id, name, input_json, output_json]):
                return Response(
                    {"detail": "Missing required fields: project_id, asset_id, name, input_json, output_json"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            project = get_object_or_404(Project, id=project_id, is_deleted=False)
            asset = get_object_or_404(ProjectAsset, id=asset_id, project_assoc=project, is_deleted=False)
            user = User.objects.get(username=request.user['user_id'])

            iteration = Iteration(
                project_assoc=project,
                user_assoc=user,
                asset_assoc=asset,
                name=name,
                iteration_type='assetco',
                input_json=input_json,
                output_json=output_json
            )
            iteration.save()

            return Response({
                "detail": "AssetCo iteration saved successfully",
                "iteration_id": iteration.id,
                "name": iteration.name
            }, status=status.HTTP_201_CREATED)

        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error saving AssetCo iteration: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AssetCoConsolidatedSaveIterationView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(write=True)
    def post(self, request, *args, **kwargs):
        """
        Save AssetCo Consolidated iteration (aggregated across all assets).
        Expected payload: {
            "project_id": int,
            "name": str,
            "input_json": dict,
            "output_json": dict
        }
        """
        payload = request.data
        if not payload:
            return Response(
                {"detail": "Request body must contain iteration data."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            project_id = payload.get("project_id")
            name = payload.get("name")
            input_json = payload.get("input_json")
            output_json = payload.get("output_json")

            if not all([project_id, name, input_json, output_json]):
                return Response(
                    {"detail": "Missing required fields: project_id, name, input_json, output_json"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            project = get_object_or_404(Project, id=project_id, is_deleted=False)
            user = User.objects.get(username=request.user['user_id'])

            iteration = Iteration(
                project_assoc=project,
                user_assoc=user,
                asset_assoc=None,  # Consolidated view has no specific asset
                name=name,
                iteration_type='assetco_consolidated',
                input_json=input_json,
                output_json=output_json
            )
            iteration.save()

            return Response({
                "detail": "AssetCo Consolidated iteration saved successfully",
                "iteration_id": iteration.id,
                "name": iteration.name
            }, status=status.HTTP_201_CREATED)

        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error saving AssetCo Consolidated iteration: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConsolidationSaveIterationView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(write=True)
    def post(self, request, *args, **kwargs):
        """
        Save full project consolidation iteration (LandCo + DevCo + AssetCo).
        Expected payload: {
            "project_id": int,
            "name": str,
            "input_json": dict,
            "output_json": dict
        }
        """
        payload = request.data
        if not payload:
            return Response(
                {"detail": "Request body must contain iteration data."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            project_id = payload.get("project_id")
            name = payload.get("name")
            input_json = payload.get("input_json")
            output_json = payload.get("output_json")

            if not all([project_id, name, input_json, output_json]):
                return Response(
                    {"detail": "Missing required fields: project_id, name, input_json, output_json"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            project = get_object_or_404(Project, id=project_id, is_deleted=False)
            user = User.objects.get(username=request.user['user_id'])

            iteration = Iteration(
                project_assoc=project,
                user_assoc=user,
                asset_assoc=None,  # Consolidation has no specific asset
                name=name,
                iteration_type='consolidation',
                input_json=input_json,
                output_json=output_json
            )
            iteration.save()

            return Response({
                "detail": "Project Consolidation iteration saved successfully",
                "iteration_id": iteration.id,
                "name": iteration.name
            }, status=status.HTTP_201_CREATED)

        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error saving Project Consolidation iteration: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ================ Unified Save Iteration API ================

class UnifiedSaveIterationView(APIView):
    """
    Unified API to save iterations for all model types.
    Supports: landco_devco, assetco, assetco_consolidated, consolidation
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    # @require_project_permission(write=True)
    def post(self, request, *args, **kwargs):
        """
        Save iteration with unified endpoint.
        Expected payload: {
            "project_id": int,
            "asset_id": int (optional, required for assetco),
            "name": str,
            "iteration_type": str (landco_devco, assetco, assetco_consolidation, jv_consolidation, project_consolidation),
            "input_json": dict,
            "iteration_id": int (optional, for overwriting existing iteration)
        }
        """
        payload = request.data
        if not payload:
            return Response(
                {"detail": "Request body must contain iteration data."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            project_id = payload.get("project_id")
            asset_id = payload.get("asset_id")
            name = payload.get("name")
            iteration_type = payload.get("iteration_type", "landco_devco")
            input_json = payload.get("input_json")
            output_json = payload.get("output_json")
            iteration_id = payload.get("iteration_id")  # For overwriting
            selected_assets = payload.get("selected_assets")

            # Backward compatibility: allow selected_assets inside input_json
            if not selected_assets and isinstance(input_json, dict):
                selected_assets = input_json.get("selected_assets")

            # Validate required fields
            if not all([project_id, name]):
                return Response(
                    {"detail": "Missing required fields: project_id, name"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            if iteration_type != 'assetco_consolidation' and input_json is None:
                return Response(
                    {"detail": "input_json is required for this iteration_type"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Validate iteration_type
            valid_types = [
                'landco_devco',
                'assetco',
                'assetco_consolidation',
                'jv_consolidation',
                'project_consolidation',
                'roshn_consolidation'
            ]
            if iteration_type not in valid_types:
                return Response(
                    {"detail": f"Invalid iteration_type. Must be one of: {', '.join(valid_types)}"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # AssetCo requires asset_id
            if iteration_type == 'assetco' and not asset_id:
                return Response(
                    {"detail": "asset_id is required for assetco iteration_type"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get project and asset
            if iteration_type in ['landco_devco', 'assetco', 'project_consolidation', 'jv_consolidation', 'assetco_consolidation']:
                project = get_object_or_404(Project, id=project_id, is_deleted=False)
            asset = None
            if asset_id:
                asset = get_object_or_404(ProjectAsset, id=asset_id, project_assoc=project, is_deleted=False)

            user = User.objects.get(username=request.user['user_id'])
            jv_output = {}
            consolidated_output = {}
            excel_output = {}

            if iteration_type == 'landco_devco':
                # import os
                # import json
                # import datetime
                # from django.conf import settings
                # try:
                #     debug_dir = os.path.join(settings.BASE_DIR, "debug_payloads")
                #     os.makedirs(debug_dir, exist_ok=True)
                #     timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                #     filename = f"output_payload_{timestamp}.json"
                #     filepath = os.path.join(debug_dir, filename)
                        
                #         # Write payload directly without double serialization
                #     with open(filepath, "w", encoding="utf-8") as f:
                #         json.dump(input_json, f, indent=2, ensure_ascii=False, default=str)

                #     filename = f"input_payload_{timestamp}.json"        
                #     filepath = os.path.join(debug_dir, filename)
                        
                #         # Write payload directly without double serialization
                #     with open(filepath, "w", encoding="utf-8") as f:
                #         json.dump(input_json, f, indent=2, ensure_ascii=False, default=str)
                        
                #     print(f"Payload saved to: {filepath}")
                # except Exception as e:
                #         # Log but don't fail the request if saving fails
                #     import traceback
                #     print(f"Warning: Failed to save payload JSON: {e}")
                #     print(traceback.format_exc())
                landco_output = v3_utils.fninitialising_all_values(input_json,is_save=True)
                devco_output = devco_utils.fninitialising_all_values(input_json,is_save=True)

                if landco_output is None or devco_output is None:
                    failed_models = []
                    if landco_output is None:
                        failed_models.append('landco')
                    if devco_output is None:
                        failed_models.append('devco')

                    return Response(
                        {
                            "detail": "Failed to compute LandCo/DevCo outputs.",
                            "failed_models": failed_models,
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                excel_output = {
                    "landco": landco_output.get("exceloutput", {}),
                    "devco": devco_output.get("exceloutput", {}),
                }
                jv_output = {
                    "landco": landco_output.get("jvoutput", {}),
                    "devco": devco_output.get("jvoutput", {}),
                }
                consolidated_output = {
                    "landco": landco_output.get("consolidationoutput", {}),
                    "devco": devco_output.get("consolidationoutput", {}),
                }
                output_json = excel_output
            elif iteration_type == 'assetco':
                if asset and asset.is_hospitality:
                    assetco_output = assetco_hospitality_utils.fninitialising_all_values(input_json,is_save=True)
                else:
                    assetco_output = assetco_utils.fninitialising_all_values(input_json,is_save=True)
                
                # Check if output_json is None (calculation failed)
                if assetco_output is None:
                    return Response(
                        {"detail": "Failed to compute outputs. Please check server logs for details."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
                output_json = assetco_output
            elif iteration_type == 'assetco_consolidation':
                if not selected_assets:
                    return Response(
                        {"detail": "selected_assets is required for assetco_consolidation iteration_type"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                try:
                    input_json, output_json = _build_assetco_consolidation_from_db(
                        project=project,
                        user=user,
                        selected_assets=selected_assets,
                        is_save=True
                    )
                    # input_json is the enriched consolidated_input list that includes
                    # scenario_name on each item — use it for source combination tracking.
                    selected_assets = input_json
                except PermissionError as exc:
                    return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
                except ValueError as exc:
                    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

                assetco_output = output_json
                if isinstance(assetco_output, dict):
                    excel_output = assetco_output.get("exceloutput", {})
                    jv_output = assetco_output.get("jvoutput", {})
                    consolidated_output = assetco_output.get("consolidatedoutput", {})
                else:
                    excel_output = getattr(assetco_output, "exceloutput", {})
                    jv_output = getattr(assetco_output, "jvoutput", {})
                    consolidated_output = getattr(assetco_output, "consolidatedoutput", {})
                output_json = excel_output

                # return Response(
                #     {
                #         "detail": "AssetCo consolidation output computed successfully",
                #         "iteration_type": "assetco_consolidation",
                #         "consolidated_output": consolidated_output,
                #     },
                #     status=status.HTTP_200_OK,
                # )
            elif iteration_type == 'project_consolidation':
                try:
                    source_selection = input_json.get("source_selection") if isinstance(input_json, dict) else payload.get("source_selection")
                    namedRanges = input_json.get("namedRanges") if isinstance(input_json, dict) else payload.get("namedRanges")
                    resolved_input_json = _build_project_consolidation_from_db(project, user, source_selection, namedRanges)
                except PermissionError as exc:
                    return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
                except ValueError as exc:
                    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

                project_conso_output = consolidated_utils.fninitialising_all_values(resolved_input_json, is_save=True)
                
                if project_conso_output is None:
                    return Response(
                        {"detail": "Failed to compute project consolidation outputs. Please check server logs for details."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                if isinstance(project_conso_output, dict):
                    output_json = project_conso_output.get("exceloutput", {})
                else:
                    output_json = getattr(project_conso_output, "exceloutput", {})
                    
            elif iteration_type == 'jv_consolidation':
                try:
                    resolved_input_json = _build_jv_consolidation_from_db(project, user, input_json)
                except PermissionError as exc:
                    return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
                except ValueError as exc:
                    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

                jv_calc_output = jv_consolidated_utils.fninitialising_all_values(resolved_input_json, is_save=True)

                if jv_calc_output is None:
                    return Response(
                        {"detail": "Failed to compute JV consolidation outputs. Please check server logs for details."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                if isinstance(jv_calc_output, dict):
                    output_json = jv_calc_output.get("exceloutput", {})
                    consolidated_output = jv_calc_output.get("consolidationoutput", {})
                else:
                    output_json = getattr(jv_calc_output, "exceloutput", {})
                    consolidated_output = getattr(jv_calc_output, "consolidationoutput", {})
            
            elif iteration_type == "roshn_consolidation":
                user = User.objects.get(username=request.user['user_id'])
                roshn_project = _ensure_roshn_container_project(user)
                project = roshn_project  # Override project to point to Roshni container for all subsequent DB operations in this block 
                input_payload = payload.get("input_json") if isinstance(payload, dict) else payload
                selected_projects = input_payload.get("selected_projects") if isinstance(input_payload, dict) else input_payload.get("source_selection")
                input_payload = _build_roshn_consolidation_from_db(user, selected_projects)

                roshn_outputs = roshn_consolidated_utils.fninitialising_all_values(input_payload, is_save=True)
                if roshn_outputs is None:
                    return Response(
                        {"detail": "Failed to compute project consolidation outputs. Please check server logs for details."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

                if isinstance(roshn_outputs, dict):
                    output_json = roshn_outputs.get("exceloutput", {})
                else:
                    output_json = getattr(roshn_outputs, "exceloutput", {})
            else:
                return Response(
                    {"detail": f"Unsupported iteration_type: {iteration_type}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if overwriting existing iteration
            if iteration_id:
                iteration = get_object_or_404(
                    Iteration, 
                    id=iteration_id, 
                    project_assoc=project,
                    user_assoc=user
                )
                # Update existing iteration
                iteration.name = name
                iteration.input_json = input_json
                iteration.output_json = output_json
                iteration.iteration_type = iteration_type
                iteration.save()

                _persist_consolidation_source_combination(
                    project=project,
                    user=user,
                    target_iteration=iteration,
                    iteration_type=iteration_type,
                    selected_assets=selected_assets,
                    jv_input_json=input_json,
                    project_source_selection=(input_json.get("source_selection") if isinstance(input_json, dict) else payload.get("source_selection")),
                )
                
                iteration_id = iteration.id
                 # Publish iteration ID to Pub/Sub for normalisation
                if iteration_type in ['landco_devco', 'assetco', 'project_consolidation', 'jv_consolidation'] and _should_publish_to_pubsub():
                    try:
                        pubsub_topic = os.environ["PUBSUB_NORMALIZATION_TOPIC"]
                        publisher = pubsub_v1.PublisherClient()
                        message = str(iteration.id).encode("utf-8")
                        future = publisher.publish(pubsub_topic, message)
                        future.result()
                        logger.info("Published iteration_id=%s to topic %s", iteration.id, pubsub_topic)
                    except Exception as pubsub_exc:
                        logger.exception("Failed to publish iteration_id=%s to Pub/Sub: %s", iteration.id, pubsub_exc)
                elif iteration_type in ['landco_devco', 'assetco', 'project_consolidation', 'jv_consolidation']:
                    logger.info("Skipped Pub/Sub publish for iteration_id=%s in local development mode", iteration.id)

                # Publish to Pub/Sub for sensitivity analysis
                if iteration_type in ['landco_devco', 'assetco'] and _should_publish_to_pubsub():
                    try:
                        sensitivity_topic = os.environ["PUBSUB_NORMALIZATION_TOPIC"]
                        sens_publisher = pubsub_v1.PublisherClient()
                        if iteration_type == 'landco_devco':
                            for sens_type in ['landco', 'devco']:
                                sens_msg = json.dumps({"iteration_id": iteration.id, "sensitivity": True, "iteration_type": sens_type}).encode("utf-8")
                                sens_publisher.publish(sensitivity_topic, sens_msg).result()
                                logger.info("Published sensitivity iteration_id=%s type=%s to topic %s", iteration.id, sens_type, sensitivity_topic)
                        elif iteration_type == 'assetco':
                            sens_msg = json.dumps({"iteration_id": iteration.id, "sensitivity": True, "iteration_type": "assetco"}).encode("utf-8")
                            sens_publisher.publish(sensitivity_topic, sens_msg).result()
                            logger.info("Published sensitivity iteration_id=%s type=assetco to topic %s", iteration.id, sensitivity_topic)
                    except Exception as sens_pubsub_exc:
                        logger.exception("Failed to publish sensitivity for iteration_id=%s: %s", iteration.id, sens_pubsub_exc)
                elif iteration_type in ['landco_devco', 'assetco']:
                    logger.info("Skipped sensitivity Pub/Sub publish for iteration_id=%s in local development mode", iteration.id)

                # if iteration_type in ['landco_devco', 'assetco', 'project_consolidation']:
                #     transaction.on_commit(lambda: _trigger_normalisation_fire_and_forget(iteration_id))
                

                if iteration_type in ['landco_devco', 'assetco', 'assetco_consolidation']:
                    JvIteration.objects.update_or_create(
                        iteration_assoc=iteration,
                        defaults={"name": iteration.name, "iteration_type": iteration.iteration_type, "output_json": jv_output},
                    )

                if iteration_type in ['landco_devco', 'assetco', 'assetco_consolidation', 'jv_consolidation']:
                    ConsolidatedIteration.objects.update_or_create(
                        iteration_assoc=iteration,
                        defaults={"name": iteration.name, "iteration_type": iteration.iteration_type, "output_json": consolidated_output},
                    )
                
                return Response({
                    "detail": "Iteration updated successfully",
                    "iteration_id": iteration.id,
                    "name": iteration.name,
                    "updated": True
                }, status=status.HTTP_200_OK)
            else:
                # Create new iteration
                iteration = Iteration(
                    project_assoc=project,
                    user_assoc=user,
                    asset_assoc=asset,
                    name=name,
                    iteration_type=iteration_type,
                    input_json=input_json,
                    output_json=output_json
                )
                iteration.save()

                _persist_consolidation_source_combination(
                    project=project,
                    user=user,
                    target_iteration=iteration,
                    iteration_type=iteration_type,
                    selected_assets=selected_assets,
                    jv_input_json=input_json,
                    project_source_selection=(input_json.get("source_selection") if isinstance(input_json, dict) else payload.get("source_selection")),
                )
                
                iteration_id = iteration.id
                # if iteration_type in ['landco_devco', 'assetco', 'project_consolidation']:
                #     transaction.on_commit(lambda: _trigger_normalisation_fire_and_forget(iteration_id))
                
                if iteration_type in ['landco_devco', 'assetco', 'project_consolidation', 'jv_consolidation'] and _should_publish_to_pubsub():
                    try:
                        pubsub_topic = os.environ["PUBSUB_NORMALIZATION_TOPIC"]
                        publisher = pubsub_v1.PublisherClient()
                        message = str(iteration.id).encode("utf-8")
                        future = publisher.publish(pubsub_topic, message)
                        future.result()
                        logger.info("Published iteration_id=%s to topic %s", iteration.id, pubsub_topic)
                    except Exception as pubsub_exc:
                        logger.exception("Failed to publish iteration_id=%s to Pub/Sub: %s", iteration.id, pubsub_exc)
                elif iteration_type in ['landco_devco', 'assetco', 'project_consolidation', 'jv_consolidation']:
                    logger.info("Skipped Pub/Sub publish for iteration_id=%s in local development mode", iteration.id)

                # Publish to Pub/Sub for sensitivity analysis
                if iteration_type in ['landco_devco', 'assetco'] and _should_publish_to_pubsub():
                    try:
                        sensitivity_topic = os.environ["PUBSUB_NORMALIZATION_TOPIC"]
                        sens_publisher = pubsub_v1.PublisherClient()
                        if iteration_type == 'landco_devco':
                            for sens_type in ['landco', 'devco']:
                                sens_msg = json.dumps({"iteration_id": iteration.id, "sensitivity": True, "iteration_type": sens_type}).encode("utf-8")
                                sens_publisher.publish(sensitivity_topic, sens_msg).result()
                                logger.info("Published sensitivity iteration_id=%s type=%s to topic %s", iteration.id, sens_type, sensitivity_topic)
                        elif iteration_type == 'assetco':
                            sens_msg = json.dumps({"iteration_id": iteration.id, "sensitivity": True, "iteration_type": "assetco"}).encode("utf-8")
                            sens_publisher.publish(sensitivity_topic, sens_msg).result()
                            logger.info("Published sensitivity iteration_id=%s type=assetco to topic %s", iteration.id, sensitivity_topic)
                    except Exception as sens_pubsub_exc:
                        logger.exception("Failed to publish sensitivity for iteration_id=%s: %s", iteration.id, sens_pubsub_exc)
                elif iteration_type in ['landco_devco', 'assetco']:
                    logger.info("Skipped sensitivity Pub/Sub publish for iteration_id=%s in local development mode", iteration.id)

                if iteration_type in ['landco_devco', 'assetco', 'assetco_consolidation']:
                    JvIteration.objects.update_or_create(
                        iteration_assoc=iteration,
                        defaults={"name": iteration.name, "iteration_type": iteration.iteration_type, "output_json": jv_output},
                    )

                if iteration_type in ['landco_devco', 'assetco', 'assetco_consolidation', 'jv_consolidation']:
                    ConsolidatedIteration.objects.update_or_create(
                        iteration_assoc=iteration,
                        defaults={"name": iteration.name, "iteration_type": iteration.iteration_type, "output_json": consolidated_output},
                    )

                return Response({
                    "detail": "Iteration saved successfully",
                    "iteration_id": iteration.id,
                    "name": iteration.name,
                    "updated": False
                }, status=status.HTTP_201_CREATED)

        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error saving iteration: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ShareIterationView(APIView):
    """
    Unified API for sharing iterations with other users.
    Supports parameter-based operations.
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, *args, **kwargs):
        """
        Share iteration with another user (read-only access).
        Expected payload: {
            "iteration_id": int (required),
            "target_user_id": str (required, username)
        }
        
        Operation: Creates UserIterationPermission record with read-only access
        """
        payload = request.data or {}
        
        if not payload:
            return Response(
                {"detail": "Request body must contain share data."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            iteration_id = payload.get("iteration_id")
            target_user_id = payload.get("target_user_id")

            if not all([iteration_id, target_user_id]):
                return Response(
                    {"detail": "Missing required fields: iteration_id, target_user_id"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get the original iteration
            iteration = get_object_or_404(Iteration, id=iteration_id, is_deleted=False)
            project = iteration.project_assoc
            
            # Get source and target users
            source_user = User.objects.get(username=request.user['user_id'])
            target_user = get_object_or_404(User, username=target_user_id, is_active=True)
            
            # Check if permission already exists
            user_iteration_perm, created = UserIterationPermission.objects.get_or_create(
                iteration_assoc=iteration,
                user_assoc=target_user,
                defaults={
                    'read_access': True,
                    'write_access': False,  # Shared scenarios are read-only
                    'created_by': source_user,  # Set who is sharing the iteration
                    'updated_by': source_user   # Set who last updated this permission
                }
            )

            # Update if already exists - ensure read-only access
            if not created:
                user_iteration_perm.read_access = True
                user_iteration_perm.write_access = False  # Enforce read-only
                user_iteration_perm.updated_by = source_user  # Track who updated
                user_iteration_perm.save()

            return Response({
                "detail": f"Iteration shared successfully with {target_user_id}",
                "iteration_id": iteration_id,
                "target_user": target_user_id,
                "read_access": True,
                "write_access": False,
                "created": created
            }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error sharing iteration: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ================ Asset Consolidation APIs ================

class JVScenarioOptionsView(APIView):
    """
    Fetch JV iteration options for JV consolidation dropdowns.
    Returns one list for landco_devco and one for assetco based on JvIteration table.
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            payload = request.data or {}
            project_id = payload.get("project_id")
            if not project_id:
                return Response(
                    {"detail": "project_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not Project.objects.filter(id=project_id, is_deleted=False).exists():
                return Response(
                    {"detail": "Not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            user = User.objects.only('id').get(username=request.user['user_id'])

            has_permission = UserProjectPermission.objects.filter(
                project_assoc_id=project_id,
                user_assoc_id=user.id,
                read_access=True,
            ).exists()

            if not has_permission:
                return Response(
                    {"detail": "You don't have permission to access this project"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            shared_iteration_ids = UserIterationPermission.objects.filter(
                user_assoc_id=user.id,
                read_access=True,
            ).values_list('iteration_assoc_id', flat=True)

            jv_rows = JvIteration.objects.filter(
                iteration_assoc__project_assoc_id=project_id,
                iteration_assoc__is_deleted=False,
                iteration_type__in=['landco_devco', 'assetco_consolidation'],
            ).filter(
                Q(iteration_assoc__user_assoc_id=user.id) | Q(iteration_assoc_id__in=shared_iteration_ids)
            ).values(
                'id',
                'iteration_assoc_id',
                'name',
                'iteration_type',
                'iteration_assoc__name',
            ).order_by('-iteration_assoc__created_at')

            grouped = {
                'landco_devco': [],
                'assetco_consolidation': [],
            }

            for row in jv_rows:
                grouped[row['iteration_type']].append({
                    'jv_iteration_id': row['id'],
                    'iteration_id': row['iteration_assoc_id'],
                    'name': row['name'] or row['iteration_assoc__name'],
                    'iteration_type': row['iteration_type'],
                })

            return Response({
                'project_id': project_id,
                'landco_devco': grouped['landco_devco'],
                'assetco_consolidation': grouped['assetco_consolidation'],
            }, status=status.HTTP_200_OK)

        except Exception as exc:
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error fetching JV scenarios: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ProjectConsolidationScenariosView(APIView):
    """
    Fetch source datasets for project consolidation.

        Returns:
        - ConsolidatedIteration rows for iteration_type in ['landco_devco', 'assetco_consolidation', 'jv_consolidation']
      (also accepts legacy 'assetco_consolidated' and maps it to assetco_consolidation bucket)
    - JV data sourced from ConsolidatedIteration (jv_consolidation)
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def _fetch_project_to_project_consolidation_scenarios(self, user):

        shared_iteration_ids = UserIterationPermission.objects.filter(
            user_assoc_id=user.id,
            read_access=True,
        ).values_list('iteration_assoc_id', flat=True)

        iteration_queryset = Iteration.objects.filter(
            iteration_type='project_consolidation',
            asset_assoc__isnull=True,
            is_deleted=False,
            project_assoc__is_deleted=False,
        ).filter(
            Q(user_assoc_id=user.id) | Q(id__in=shared_iteration_ids)
        )

       
        iteration_rows = iteration_queryset.values(
            'id',
            'name',
            'created_at',
            'project_assoc_id',
            'project_assoc__name',
            'user_assoc__username',
        ).order_by('project_assoc__name', '-created_at')

        assets_by_project = {}
        for row in iteration_rows:
            project_key = row['project_assoc_id']
            if project_key not in assets_by_project:
                project_name = row['project_assoc__name'] or f"Project {project_key}"
                assets_by_project[project_key] = {
                    'id': project_key,
                    'asset_unique_identifier': project_name,
                    'asset_name': project_name,
                    'is_hospitality': False,
                    'is_deleted': False,
                    'scenarios': [],
                }

            assets_by_project[project_key]['scenarios'].append(
                {
                    'id': row['id'],
                    'name': row['name'],
                    'created_at': row['created_at'].isoformat(),
                    'user_assoc': row['user_assoc__username'],
                }
            )

        assets_data = list(assets_by_project.values())

        return Response(
            {
                'iteration_type': 'project_to_project_consolidation',
                'project_consolidation': assets_data,
                'total_assets': len(assets_data),
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, *args, **kwargs):
        try:
            payload = request.data or {}
            
            input_json = payload.get('input_json') if isinstance(payload.get('input_json'), dict) else {}
            requested_iteration_type = (
                input_json.get('iteration_type')
                or payload.get('iteration_type')
            )

            if requested_iteration_type == 'roshn_consolidation':
                user = User.objects.only('id').get(username=request.user['user_id'])
                return self._fetch_project_to_project_consolidation_scenarios(user)

            
            project_id = payload.get("project_id")
            if not project_id:
                return Response(
                    {"detail": "project_id is required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
                
            if not Project.objects.filter(id=project_id, is_deleted=False).exists():
                return Response(
                    {"detail": "Not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            user = User.objects.only('id').get(username=request.user['user_id'])

            has_permission = UserProjectPermission.objects.filter(
                project_assoc_id=project_id,
                user_assoc_id=user.id,
                read_access=True,
            ).exists()

            if not has_permission:
                return Response(
                    {"detail": "You don't have permission to access this project"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            shared_iteration_ids = UserIterationPermission.objects.filter(
                user_assoc_id=user.id,
                read_access=True,
            ).values_list('iteration_assoc_id', flat=True)

            consolidated_rows = ConsolidatedIteration.objects.filter(
                iteration_assoc__project_assoc_id=project_id,
                iteration_assoc__is_deleted=False,
                iteration_type__in=['landco_devco', 'assetco_consolidation', 'jv_consolidation'],
            ).filter(
                Q(iteration_assoc__user_assoc_id=user.id) | Q(iteration_assoc_id__in=shared_iteration_ids)
            ).values(
                'id',
                'iteration_assoc_id',
                'name',
                'iteration_type',
                'created_at',
                'updated_at',
                'iteration_assoc__name',
            ).order_by('-iteration_assoc__created_at')

            response_data = {
                'project_id': project_id,
                'consolidated_iteration': {
                    'landco_devco': [],
                    'assetco_consolidation': [],
                    'jv_consolidation': [],
                },
            }

            for row in consolidated_rows:
                bucket = row['iteration_type']
                if bucket in response_data['consolidated_iteration']:
                    response_data['consolidated_iteration'][bucket].append({
                        'consolidated_iteration_id': row['id'],
                        'iteration_id': row['iteration_assoc_id'],
                        'name': row['name'] or row['iteration_assoc__name'],
                        'iteration_type': row['iteration_type'],
                        # 'output_json': row.output_json or {},
                        'created_at': row['created_at'].isoformat(),
                        'updated_at': row['updated_at'].isoformat(),
                    })

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as exc:
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error fetching consolidation source data: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AllAssetScenariosView(APIView):
    """
    Fetch all assets and their scenarios across a project.
    Used for AssetCo consolidation workflow.
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, *args, **kwargs):
        """
        Get all assets with their scenarios for consolidation selection.
        Returns structure: {
            "assets": [
                {
                    "id": int,
                    "asset_unique_identifier": str,
                    "asset_name": str,
                    "is_hospitality": bool,
                    "scenarios": [
                        {"id": int, "name": str, "created_at": datetime, "user_assoc": str}
                    ]
                }
            ]
        }
        """
        try:
            payload = request.data or {}
            project_id = payload.get("project_id")
            if not project_id:
                return Response(
                    {"detail": "project_id is required"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not Project.objects.filter(id=project_id, is_deleted=False).exists():
                return Response(
                    {"detail": "Not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            user = User.objects.only('id').get(username=request.user['user_id'])

            # Check project permissions
            has_permission = UserProjectPermission.objects.filter(
                project_assoc_id=project_id,
                user_assoc_id=user.id,
                read_access=True
            ).exists()

            if not has_permission:
                return Response(
                    {"detail": "You don't have permission to access this project"},
                    status=status.HTTP_403_FORBIDDEN
                )

            shared_scenario_ids = UserIterationPermission.objects.filter(
                user_assoc_id=user.id,
                read_access=True,
            ).values_list('iteration_assoc_id', flat=True)

            # Get all active assets for the project
            assets = ProjectAsset.objects.filter(
                project_assoc_id=project_id,
                is_deleted=False
            ).order_by('asset_unique_identifier').values(
                'id',
                'asset_unique_identifier',
                'asset_name',
                'is_hospitality',
            )

            # Fetch all accessible asset scenarios for this project in one query.
            scenarios = Iteration.objects.filter(
                project_assoc_id=project_id,
                iteration_type='assetco',
                is_deleted=False,
                asset_assoc__is_deleted=False,
            ).filter(
                Q(user_assoc_id=user.id) | Q(id__in=shared_scenario_ids)
            ).annotate(
                has_normalised_data=Exists(
                    NormalisedIteration.objects.filter(iteration=OuterRef('pk'))
                )
            ).values(
                'id',
                'name',
                # 'created_at',
                'asset_assoc_id',
                # 'user_assoc__username',
                'has_normalised_data',
            ).order_by('asset_assoc_id', '-created_at')

            scenarios_by_asset = {}
            for scenario in scenarios:
                asset_id = scenario['asset_assoc_id']
                scenarios_by_asset.setdefault(asset_id, []).append({
                    "id": scenario['id'],
                    "name": scenario['name'],
                    # "created_at": scenario['created_at'].isoformat(),
                    # "user_assoc": scenario['user_assoc__username'],
                    "has_normalised_data": scenario['has_normalised_data'],
                })

            # Build response with assets and their scenarios
            assets_data = []
            for asset in assets:
                scenarios_data = scenarios_by_asset.get(asset['id'], [])

                # Only include assets that have at least one scenario
                if scenarios_data:
                    assets_data.append({
                        "id": asset['id'],
                        "asset_unique_identifier": asset['asset_unique_identifier'],
                        "asset_name": asset['asset_name'],
                        "is_hospitality": asset['is_hospitality'],
                        "scenarios": scenarios_data
                    })

            return Response({
                "project_id": project_id,
                "assets": assets_data,
                "total_assets": len(assets_data)
            }, status=status.HTTP_200_OK)

        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error fetching asset scenarios: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AssetConsolidationSaveView(APIView):
    """
    Save consolidated AssetCo calculations.
    Accepts selected assets with their scenarios, combines output_json,
    and runs consolidation function.
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, *args, **kwargs):
        """
        Save consolidated asset scenario.
        Expected payload: {
            "project_id": int,
            "name": str,
            "selected_assets": [
                {"asset_id": int, "scenario_id": int}
            ]
        }
        """
        payload = request.data
        if not payload:
            return Response(
                {"detail": "Request body is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            project_id = payload.get("project_id")
            name = payload.get("name")
            selected_assets = payload.get("selected_assets", [])

            if not all([project_id, name, selected_assets]):
                return Response(
                    {"detail": "Missing required fields: project_id, name, selected_assets"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not isinstance(selected_assets, list) or len(selected_assets) == 0:
                return Response(
                    {"detail": "selected_assets must be a non-empty array"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            project = get_object_or_404(Project, id=project_id, is_deleted=False)
            user = User.objects.get(username=request.user['user_id'])
            try:
                input_json, output_json = _build_assetco_consolidation_from_db(
                    project=project,
                    user=user,
                    selected_assets=selected_assets,
                    is_save=True
                )
            except PermissionError as exc:
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_403_FORBIDDEN,
                )
            except ValueError as exc:
                return Response(
                    {"detail": str(exc)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Save as new iteration
            iteration = Iteration(
                project_assoc=project,
                user_assoc=user,
                asset_assoc=None,  # Consolidated scenarios don't have single asset
                name=name,
                iteration_type='assetco_consolidated',
                input_json=input_json,
                output_json=output_json
            )
            iteration.save()

            return Response({
                "detail": "Consolidated scenario saved successfully",
                "iteration_id": iteration.id,
                "name": iteration.name,
                "assets_consolidated": len(selected_assets)
            }, status=status.HTTP_201_CREATED)

        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error saving consolidated scenario: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ================ Template Download APIs ================

class DownloadBaseLandcoDevcoTemplateView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(read=True)
    def get(self, request, project_id):
        """
        Download the base LandCo/DevCo template for a project.
        """
        project = get_object_or_404(Project, id=project_id, is_deleted=False)

        if not project.base_landco_devco_template:
            return Response(
                {"detail": "No LandCo/DevCo template file associated with this project"}, 
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            template_link = project.base_landco_devco_template.strip()

            # Extract bucket and blob path
            bucket = None
            blob_path = None
            if template_link.startswith("gs://"):
                # gs://bucket/path/to/blob
                path = template_link[len("gs://"):]
                parts = path.split("/", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError("Invalid gs:// path")
                bucket, blob_path = parts[0], parts[1]
            else:
                # support storage.cloud.google.com/<bucket>/<path> or https://storage.googleapis.com/<bucket>/<path>
                from urllib.parse import urlparse
                parsed = urlparse(template_link)
                path = parsed.path.lstrip("/")
                parts = path.split("/", 1)
                if len(parts) == 2:
                    bucket, blob_path = parts[0], parts[1]
                else:
                    # fallback to configured bucket if only blob path provided
                    bucket = getattr(settings, "GCS_BUCKET_NAME", None)
                    blob_path = template_link.lstrip("/")

            if not bucket or not blob_path:
                raise ValueError("Unable to determine GCS bucket or object path from template_link")

            # Obtain access token from the storage client credentials and download via signed request
            if not gcs_helper.client or not getattr(gcs_helper, "client", None):
                raise Exception("GCS client not initialized on backend")

            creds = gcs_helper.client._credentials
            creds.refresh(Request())
            access_token = creds.token

            url = f"https://storage.googleapis.com/{bucket}/{blob_path}"
            headers = {"Authorization": f"Bearer {access_token}"}

            resp = requests.get(url, headers=headers, timeout=60)

            if resp.status_code != 200:
                return Response(
                    {"detail": f"GCS download failed: {resp.status_code}"},
                    status=status.HTTP_502_BAD_GATEWAY
                )

            # Determine MIME type
            content_type = resp.headers.get('Content-Type')
            if not content_type:
                content_type, _ = mimetypes.guess_type(blob_path)
                if not content_type:
                    content_type = 'application/octet-stream'

            # Return the file as a response
            response = HttpResponse(resp.content, content_type=content_type)
            
            # Extract filename from blob_path
            filename = blob_path.split('/')[-1]
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            
            return response

        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error downloading template: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DownloadAssetBaseFileView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(read=True)
    def get(self, request, project_id, asset_id):
        """
        Download the base file for a specific asset.
        """
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        asset = get_object_or_404(ProjectAsset, id=asset_id, project_assoc=project, is_deleted=False)

        if not asset.asset_base_file_link:
            return Response(
                {"detail": "No base file associated with this asset"}, 
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            template_link = asset.asset_base_file_link.strip()

            # Extract bucket and blob path
            bucket = None
            blob_path = None
            if template_link.startswith("gs://"):
                # gs://bucket/path/to/blob
                path = template_link[len("gs://"):]
                parts = path.split("/", 1)
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError("Invalid gs:// path")
                bucket, blob_path = parts[0], parts[1]
            else:
                # support storage.cloud.google.com/<bucket>/<path> or https://storage.googleapis.com/<bucket>/<path>
                from urllib.parse import urlparse
                parsed = urlparse(template_link)
                path = parsed.path.lstrip("/")
                parts = path.split("/", 1)
                if len(parts) == 2:
                    bucket, blob_path = parts[0], parts[1]
                else:
                    # fallback to configured bucket if only blob path provided
                    bucket = getattr(settings, "GCS_BUCKET_NAME", None)
                    blob_path = template_link.lstrip("/")

            if not bucket or not blob_path:
                raise ValueError("Unable to determine GCS bucket or object path from asset_base_file_link")

            # Obtain access token from the storage client credentials and download via signed request
            if not gcs_helper.client or not getattr(gcs_helper, "client", None):
                raise Exception("GCS client not initialized on backend")

            creds = gcs_helper.client._credentials
            creds.refresh(Request())
            access_token = creds.token

            url = f"https://storage.googleapis.com/{bucket}/{blob_path}"
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.get(url, headers=headers, timeout=60)

            if resp.status_code != 200:
                return Response(
                    {"detail": f"GCS download failed: {resp.status_code}"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            filename = blob_path.split("/")[-1]
            content_type = (
                resp.headers.get("Content-Type")
                or mimetypes.guess_type(filename)[0]
                or "application/octet-stream"
            )
            file_b64 = base64.b64encode(resp.content).decode("ascii")

            return Response(
                {
                    "source_type": "asset" if asset_id else "project",
                    "project_id": project_id,
                    "asset_id": asset_id if asset_id else None,
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": len(resp.content),
                    "file_base64": file_b64,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            return Response({
                "detail": f"Error downloading asset base file: {exc}",
                "error_type": type(exc).__name__,
                "traceback": error_trace
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UnifiedDownloadFileView(APIView):
    """
    Unified POST API to download Excel files from project-level or asset-level sources.

    Expected payload:
    {
        "asset_id": int (optional)
    }

    Logic:
    - If asset_id is provided: download from ProjectAsset.asset_base_file_link
    - If asset_id is not provided: download from Project.template_link
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(read=True)
    def post(self, request, project_id, *args, **kwargs):
        def _extract_bucket_blob_from_link(file_link):
            import re
            from urllib.parse import urlparse, unquote

            if not file_link:
                return None, None

            cleaned = str(file_link).strip()
            if not cleaned:
                return None, None

            if cleaned.startswith("gs://"):
                path = cleaned[len("gs://"):]
                parts = path.split("/", 1)
                if len(parts) == 2 and parts[0] and parts[1]:
                    return parts[0], parts[1]
                return None, None

            parsed = urlparse(cleaned)
            host = (parsed.netloc or "").lower()
            path = parsed.path.lstrip("/")

            # https://storage.googleapis.com/<bucket>/<blob>
            # https://storage.cloud.google.com/<bucket>/<blob>
            if host in {"storage.googleapis.com", "storage.cloud.google.com"}:
                parts = path.split("/", 1)
                if len(parts) == 2 and parts[0] and parts[1]:
                    return parts[0], parts[1]

            # https://<bucket>.storage.googleapis.com/<blob>
            if host.endswith(".storage.googleapis.com"):
                bucket = host[: -len(".storage.googleapis.com")]
                if bucket and path:
                    return bucket, path

            # https://www.googleapis.com/download/storage/v1/b/<bucket>/o/<encoded_blob>
            match = re.match(r"^download/storage/v1/b/([^/]+)/o/(.+)$", path)
            if match:
                return match.group(1), unquote(match.group(2))

            # Fallback: blob-only path with configured bucket
            bucket = getattr(settings, "GCS_BUCKET_NAME", None)
            blob_path = cleaned.lstrip("/")
            if bucket and blob_path and not blob_path.startswith("http"):
                return bucket, blob_path

            return None, None

        payload = request.data or {}
        asset_id = payload.get("asset_id")

        try:
            project = get_object_or_404(Project, id=project_id, is_deleted=False)

            if asset_id:
                asset = get_object_or_404(
                    ProjectAsset,
                    id=asset_id,
                    project_assoc=project,
                    is_deleted=False,
                )
                file_link = (asset.asset_base_file_link or "").strip()
                if not file_link:
                    return Response(
                        {"detail": "No base file associated with this asset"},
                        status=status.HTTP_404_NOT_FOUND,
                    )
            else:
                file_link = (project.template_link or "").strip()
                if not file_link:
                    return Response(
                        {"detail": "No template file associated with this project"},
                        status=status.HTTP_404_NOT_FOUND,
                    )

            # Extract bucket and blob path
            bucket, blob_path = _extract_bucket_blob_from_link(file_link)

            if not bucket or not blob_path:
                raise ValueError("Unable to determine GCS bucket or object path from file link")

            if not gcs_helper.client or not getattr(gcs_helper, "client", None):
                raise Exception("GCS client not initialized on backend")

            creds = gcs_helper.client._credentials
            creds.refresh(Request())
            access_token = creds.token

            url = f"https://storage.googleapis.com/{bucket}/{blob_path}"
            headers = {"Authorization": f"Bearer {access_token}"}
            resp = requests.get(url, headers=headers, timeout=60)

            if resp.status_code != 200:
                return Response(
                    {"detail": f"GCS download failed: {resp.status_code}"},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

            filename = blob_path.split("/")[-1]
            content_type = (
                resp.headers.get("Content-Type")
                or mimetypes.guess_type(filename)[0]
                or "application/octet-stream"
            )
            file_b64 = base64.b64encode(resp.content).decode("ascii")

            return Response(
                {
                    "source_type": "asset" if asset_id else "project",
                    "project_id": project_id,
                    "asset_id": asset_id if asset_id else None,
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": len(resp.content),
                    "file_base64": file_b64,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            error_trace = traceback.format_exc()
            return Response(
                {
                    "detail": f"Error downloading file: {exc}",
                    "error_type": type(exc).__name__,
                    "traceback": error_trace,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AssetScenarioDetailView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    @require_project_permission(read=True)
    def get(self, request, project_id, asset_id, scenario_id):
        """
        Get a specific asset scenario by ID.
        """
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        asset = get_object_or_404(ProjectAsset, id=asset_id, project_assoc=project, is_deleted=False)
        scenario = get_object_or_404(
            Iteration, 
            id=scenario_id, 
            project_assoc=project,
            asset_assoc=asset
        )
        
        serializer = ScenarioSerializer(scenario)
        return Response(serializer.data)

