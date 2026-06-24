from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
import re
import json
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from django.db import models
from django.db import transaction, close_old_connections
from django.utils import timezone
from django.utils.dateparse import parse_date
from management.models import (
    Project,
    UserProjectPermission,
    Iteration,
    ProjectAsset,
    UserIterationPermission,
    JvIteration,
    ConsolidatedIteration,
    ProjectConsolidationAsset,
    UnitIteration_Assetco,
    DimPeriod,
    DimDataItem,
    DimGlobalDataItem,
    AssetIteration_Landco,
    AssetIteration_Devco,
    NormalisedIteration,
    GlobalInputsIteration,
    InflationProfile,
    IrrDecomposition,
    SensitivityScenario,
    SensitivityIteration,
    GoalSeekIteration,
)
from management.serializers import (
    ProjectSerializer,
    ProjectCreateSerializer,
    UserProjectPermissionSerializer,
    AssignUserPermissionSerializer,
    ScenarioSerializer,
    ProjectAssetSerializer,
    ProjectAssetCreateSerializer,
    ProjectAssetUpdateSerializer
)
from management.permissions import IsMSALAuthenticated, MSALAuthentication
from management.decorators import require_project_permission
from django.conf import settings
from management.utils.gcs_helper import gcs_helper
import os
from django.http import HttpResponse, FileResponse
from mainapp.utils.normalisation import landco_norm_v1, devco_norm_v1, assetco_norm, assetco_hospitality_norm, jv_consolidation_norm, consolidated_norm_v1, consolidated_norm
from mainapp.utils.sensitivity import landco_module as landco_sensitivity_module
from mainapp.utils.sensitivity import devco_model as devco_sensitivity_module
from mainapp.utils.sensitivity import assetco_model as assetco_sensitivity_module

def _cloud_run_log(level, message, *args):
    timestamp = datetime.utcnow().isoformat() + "Z"
    try:
        formatted = message % args if args else message
    except Exception:
        formatted = message
    print(f"{timestamp} {level} {formatted}", flush=True)


def _is_zero_or_null_value(value):
            if value is None:
                return True
            if isinstance(value, str):
                text = value.strip().lower()
                if text in {"", "null", "none"}:
                    return True
                try:
                    return float(text) == 0.0
                except ValueError:
                    return False
            if isinstance(value, (int, float)):
                return float(value) == 0.0
            return False
        
def _dashboard_only_response(normalized_data):
    """Return response-safe normalized data with only normalized_dashboard_payload."""
    response_payload = {}
    if not isinstance(normalized_data, dict):
        return response_payload

    for module_key, module_payload in normalized_data.items():
        rows = []
        if isinstance(module_payload, dict):
            candidate = module_payload.get("normalized_dashboard_payload")
            if isinstance(candidate, list):
                rows = [
                    row for row in candidate
                    if not (
                        isinstance(row, dict)
                        and _is_zero_or_null_value(row.get("Value"))
                    )
                ]
        elif isinstance(module_payload, list):
            rows = [
                row for row in module_payload
                if not (
                    isinstance(row, dict)
                    and _is_zero_or_null_value(row.get("Value"))
                )
            ]

        response_payload[module_key] = {
            "normalized_dashboard_payload": rows,
        }

    return response_payload


def save_sensitivity_to_db(module_result, module_name, iteration):
    """
    Persist sensitivity all_records and goal_seek from a sensitivity module result.

    module_result format:
        {
            "all_records": [
                {
                    "asset": str, "period": "YYYY-MM-DD", "value": float,
                    "scenario": str, "scenario_code": str,
                    "param1": str, "param1_pct": str,
                    "param2": str, "param2_pct": str,
                }
            ],
            "goal_seek": {   # optional
                "variable": str, "target_metric": str, "target_value": float,
                "base_metric_value": float, "pct_change_required": float,
                "achieved_metric_value": float, "metric_error": float,
                "model_evaluations": int, "linear_pct_change": float,
            }
        }

    Returns dict with counts: {"scenarios": N, "rows": M, "goal_seek": 0|1}.
    """
    # ── 1. Clear existing data for this iteration+module ─────────────────────
    SensitivityScenario.objects.filter(iteration=iteration, module=module_name).delete()  # cascades SensitivityIteration
    GoalSeekIteration.objects.filter(iteration=iteration, module=module_name).delete()

    if not isinstance(module_result, dict):
        return {"scenarios": 0, "rows": 0, "goal_seek": 0}

    all_records = module_result.get("all_records") or []
    goal_seek = module_result.get("goal_seek")

    if not all_records and not goal_seek:
        return {"scenarios": 0, "rows": 0, "goal_seek": 0}

    # ── 2. Build period lookup: "YYYY-MM-DD" → DimPeriod.id ──────────────────
    period_lookup: dict = {}
    for p in DimPeriod.objects.filter(period_type="month").values("id", "period_start", "period_end"):
        period_lookup[str(p["period_start"])] = p["id"]
        period_lookup.setdefault(str(p["period_end"]), p["id"])

    # ── 3. Collect unique scenarios (keyed by scenario_code) ─────────────────
    scenarios_seen: dict = {}  # scenario_code → first record with that code
    for rec in all_records:
        code = str(rec.get("scenario_code") or "")
        if code not in scenarios_seen:
            scenarios_seen[code] = rec

    scenario_objs = [
        SensitivityScenario(
            iteration=iteration,
            module=module_name,
            scenario_label=str(rec.get("scenario") or ""),
            scenario_code=str(rec.get("scenario_code") or ""),
            param1=str(rec.get("param1") or ""),
            param1_pct=str(rec.get("param1_pct") or ""),
            param2=str(rec.get("param2") or ""),
            param2_pct=str(rec.get("param2_pct") or ""),
        )
        for rec in scenarios_seen.values()
    ]
    SensitivityScenario.objects.bulk_create(scenario_objs, batch_size=500, ignore_conflicts=False)

    # Build code → id map after insert
    scenario_id_map: dict = {
        obj.scenario_code: obj.id
        for obj in SensitivityScenario.objects.filter(
            iteration=iteration, module=module_name
        ).only("id", "scenario_code")
    }

    # ── 4. Build asset lookup maps for FK resolution ─────────────────────────
    # key: asset_name (lowercased+stripped) → asset iteration id
    asset_landco_map: dict = {}
    asset_devco_map: dict = {}
    # AssetCo: asset is iteration.asset_assoc (ProjectAsset) — resolved directly below
    asset_project_id_for_assetco: int | None = None

    if module_name == "landco":
        for obj in AssetIteration_Landco.objects.filter(iteration=iteration).values("id", "asset_name", "asset_unique_id"):
            key = str(obj["asset_name"] or obj["asset_unique_id"] or "").strip()
            if key:
                asset_landco_map[key] = obj["id"]
                asset_landco_map[key.lower()] = obj["id"]

    elif module_name == "devco":
        for obj in AssetIteration_Devco.objects.filter(iteration=iteration).values("id", "asset_name", "asset_unique_id"):
            key = str(obj["asset_name"] or obj["asset_unique_id"] or "").strip()
            if key:
                asset_devco_map[key] = obj["id"]
                asset_devco_map[key.lower()] = obj["id"]

    elif module_name == "assetco":
        # Single-asset model — asset is stored directly on the iteration
        asset_project_id_for_assetco = iteration.asset_assoc_id

    # ── 5. Bulk-create SensitivityIteration rows ─────────────────────────────
    bulk_rows = []
    for rec in all_records:
        code = str(rec.get("scenario_code") or "")
        scenario_id = scenario_id_map.get(code)
        if scenario_id is None:
            continue

        period_date = str(rec.get("period") or "")[:10]
        period_id = period_lookup.get(period_date)
        if period_id is None:
            continue

        try:
            value = float(rec["value"])
        except (KeyError, TypeError, ValueError):
            continue

        asset_name_key = str(rec.get("asset") or "").strip()
        asset_landco_id = asset_landco_map.get(asset_name_key) or asset_landco_map.get(asset_name_key.lower())
        asset_devco_id = asset_devco_map.get(asset_name_key) or asset_devco_map.get(asset_name_key.lower())

        bulk_rows.append(
            SensitivityIteration(
                iteration=iteration,
                module=module_name,
                scenario_id=scenario_id,
                asset_landco_id=asset_landco_id,
                asset_devco_id=asset_devco_id,
                asset_unit_id=None,
                asset_project_id=asset_project_id_for_assetco,
                period_id=period_id,
                value=value,
            )
        )

    if bulk_rows:
        SensitivityIteration.objects.bulk_create(bulk_rows, batch_size=2000)

    # ── 5. Persist goal-seek result ───────────────────────────────────────────
    goal_seek_saved = 0
    if isinstance(goal_seek, dict):
        def _float_or_none(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        GoalSeekIteration.objects.create(
            iteration=iteration,
            module=module_name,
            variable=str(goal_seek.get("variable") or ""),
            target_metric=str(goal_seek.get("target_metric") or ""),
            target_value=_float_or_none(goal_seek.get("target_value")),
            base_metric_value=_float_or_none(goal_seek.get("base_metric_value")),
            pct_change_required=_float_or_none(goal_seek.get("pct_change_required")),
            achieved_metric_value=_float_or_none(goal_seek.get("achieved_metric_value")),
            metric_error=_float_or_none(goal_seek.get("metric_error")),
            model_evaluations=int(goal_seek["model_evaluations"]) if goal_seek.get("model_evaluations") is not None else None,
            linear_pct_change=_float_or_none(goal_seek.get("linear_pct_change")),
        )
        goal_seek_saved = 1

    return {"scenarios": len(scenario_objs), "rows": len(bulk_rows), "goal_seek": goal_seek_saved}


def save_inflation_profiles_to_db(inflation_profiles, iteration):
    # Remove old records for this iteration
    InflationProfile.objects.filter(iteration=iteration).delete()
    if not isinstance(inflation_profiles, dict) or not inflation_profiles:
        return {}
    bulk_objs = []
    for profile_name, year_dict in inflation_profiles.items():
        if not isinstance(year_dict, dict):
            continue
        for year, value in year_dict.items():
            bulk_objs.append(
                InflationProfile(
                    iteration=iteration,
                    profile_name=profile_name,
                    year=int(year),
                    value=float(value)
                )
            )
    InflationProfile.objects.bulk_create(bulk_objs)

    # Return {profile_name: {year: id}} so caller can attach DB ids back to payload.
    id_map = {}
    rows = InflationProfile.objects.filter(iteration=iteration).values("id", "profile_name", "year")
    for row in rows:
        profile_name = row.get("profile_name")
        year = str(row.get("year"))
        if profile_name not in id_map:
            id_map[profile_name] = {}
        id_map[profile_name][year] = row.get("id")
    return id_map


def save_irr_decomposition_to_db(irr_decomposition_payload, iteration):
    # Replace mode: remove old IRR decomposition metrics for this iteration.
    IrrDecomposition.objects.filter(iteration=iteration).delete()

    if not isinstance(irr_decomposition_payload, dict) or not irr_decomposition_payload:
        return {}

    bulk_objs = []
    for metric_name, value in irr_decomposition_payload.items():
        if metric_name in [None, ""]:
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue

        bulk_objs.append(
            IrrDecomposition(
                iteration=iteration,
                metric_name=str(metric_name),
                value=numeric_value,
            )
        )

    if bulk_objs:
        IrrDecomposition.objects.bulk_create(bulk_objs)

    id_map = {}
    rows = IrrDecomposition.objects.filter(iteration=iteration).values("id", "metric_name")
    for row in rows:
        id_map[row.get("metric_name")] = row.get("id")
    return id_map

def _build_jv_consolidation_from_db(project, user, input_payload):
    """Resolve JV consolidation source scenarios from JvIteration rows."""
    if not isinstance(input_payload, dict):
        raise ValueError("input_json must be an object for jv_consolidation")

    selected_scenarios = input_payload.get("selected_scenarios")
    if not isinstance(selected_scenarios, list) or len(selected_scenarios) == 0:
        raise ValueError("selected_scenarios must be a non-empty array")

    allowed_types = {"landco_devco", "assetco_consolidation"}
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

    jv_rows = {
        row.id: row
        for row in JvIteration.objects.filter(
            id__in=items_by_id.keys(),
            iteration_assoc__project_assoc_id=project.id,
            iteration_assoc__is_deleted=False,
        ).select_related("iteration_assoc")
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

    named_ranges = input_payload.get("namedRanges")
    if not isinstance(named_ranges, list):
        named_ranges = input_payload.get("namedranges")
    if isinstance(named_ranges, list):
        result["namedranges"] = named_ranges

    for jv_iteration_id, source_type in items_by_id.items():
        row = jv_rows.get(jv_iteration_id)
        if not row:
            raise ValueError(f"JV scenario {jv_iteration_id} not found or does not belong to this project")

        source_iteration = row.iteration_assoc
        if not (source_iteration.user_assoc_id == user.id or source_iteration.id in shared_iteration_ids):
            raise PermissionError(f"You don't have access to scenario {source_iteration.id}")

        result[source_type] = row.output_json or {}

    return result


def _build_project_consolidation_from_db(project, user, source_selection, named_ranges):
    """Resolve project-consolidation sources from DB and include named ranges."""
    if not isinstance(source_selection, dict):
        raise ValueError("source_selection is required for project_consolidation")

    selections_by_type_raw = source_selection.get("selections_by_type") or []
    if not isinstance(selections_by_type_raw, list):
        raise ValueError("selections_by_type must be an array")

    selections_by_type = {}
    required_ids = []
    for item in selections_by_type_raw:
        if isinstance(item, dict):
            source_type = item.get("source_type")
            consolidated_id = item.get("consolidated_iteration_id")
            if source_type:
                selections_by_type.setdefault(source_type, []).append(item)
            if consolidated_id:
                required_ids.append(consolidated_id)

    if not selections_by_type.get("landco_devco"):
        raise ValueError("Please select one LandCo/DevCo scenario")
    if not selections_by_type.get("assetco_consolidation"):
        raise ValueError("Please select one AssetCo consolidation scenario")

    rows = {
        row.id: row
        for row in ConsolidatedIteration.objects.filter(
            id__in=required_ids,
            iteration_assoc__project_assoc_id=project.id,
            iteration_assoc__is_deleted=False,
        ).select_related("iteration_assoc")
    }

    shared_iteration_ids = set(
        UserIterationPermission.objects.filter(
            user_assoc_id=user.id,
            read_access=True,
        ).values_list("iteration_assoc_id", flat=True)
    )

    def _get_output(selection_item, expected_type, label):
        consolidated_id = selection_item.get("consolidated_iteration_id")
        if not consolidated_id:
            raise ValueError(f"Invalid {label} selection: consolidated_iteration_id is required")

        row = rows.get(consolidated_id)
        if not row:
            raise ValueError(
                f"{label} consolidated scenario {consolidated_id} not found or does not belong to this project"
            )
        if row.iteration_type != expected_type:
            raise ValueError(f"{label} scenario has unexpected type '{row.iteration_type}'")

        source_iteration = row.iteration_assoc
        if not (source_iteration.user_assoc_id == user.id or source_iteration.id in shared_iteration_ids):
            raise PermissionError(f"You don't have access to scenario {source_iteration.id}")

        return row.output_json or {}

    landco_devco_output = _get_output(
        selections_by_type["landco_devco"][0], "landco_devco", "LandCo/DevCo"
    )
    assetco_output = _get_output(
        selections_by_type["assetco_consolidation"][0], "assetco_consolidation", "AssetCo consolidation"
    )

    jv_output = {}
    jv_list = selections_by_type.get("jv_consolidation") or []
    if jv_list:
        jv_output = _get_output(jv_list[0], "jv_consolidation", "JV consolidation")

    landco_payload = landco_devco_output.get("landco", {}) if isinstance(landco_devco_output, dict) else {}
    devco_payload = landco_devco_output.get("devco", {}) if isinstance(landco_devco_output, dict) else {}

    if not isinstance(landco_payload, dict) or not isinstance(devco_payload, dict):
        raise ValueError("Invalid LandCo/DevCo source output found in DB")

    return {
        "landco": landco_payload,
        "devco": devco_payload,
        "assetco_consolidated": assetco_output,
        "jv_consolidation": jv_output if isinstance(jv_output, dict) else {},
        "namedRanges": named_ranges,
    }


class UserDetailsView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def get(self, request):
        user_payload = getattr(request, "msal_user", None)
        return Response({
            "user": user_payload
        })

class ProjectCountView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def get(self, request):
        count = Project.objects.count()
        user_count = User.objects.count()
        return Response({"project_count": count, "user_count": user_count})


class ProjectDetailsView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]
    

    def get(self, request, project_id=None):
        @require_project_permission(read=True)
        def handler(self, request, project_id=None):
            if project_id:
                project = get_object_or_404(Project, id=project_id, is_deleted=False)
                return Response(ProjectSerializer(project).data)
            else:
                projects = Project.objects.filter(is_deleted=False).order_by('-created_at')
                return Response(ProjectSerializer(projects, many=True).data)
        return handler(self, request, project_id=project_id)


class CreateProjectView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request):
        serializer = ProjectCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project_name = str(serializer.validated_data.get("name") or "").strip()

        acting_user = None
        if hasattr(request, 'user') and isinstance(request.user, User):
            acting_user = request.user
        else:
            acting_user = User.objects.first()
        if acting_user is None:
            return Response({"detail": "No user available to set as creator."}, status=status.HTTP_400_BAD_REQUEST)

        if project_name.lower() == "roshn consolidation":
            existing_roshn = Project.objects.filter(name__iexact=project_name, is_deleted=False).first()
            if existing_roshn:
                return Response(
                    {"detail": "Project name 'ROSHN Consolidation' is reserved and cannot be created manually."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            project = Project.objects.create(
                name=project_name,
                created_by=acting_user,
                updated_by=acting_user,
                is_deleted=False,
            )
            return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)

        project = Project.objects.create(
            name=serializer.validated_data['name'],
            template_link=serializer.validated_data.get('template_link'),
            created_by=acting_user,
            updated_by=acting_user,
        )
        return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)


class UploadTemplateView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, project_id):
        def handler(self, request, project_id):
            project = get_object_or_404(Project, id=project_id, is_deleted=False)
            
            # Check if GCS is available
            if not gcs_helper.is_available:
                return Response(
                    {"detail": "File upload is not available in local development mode. GCS credentials not configured."}, 
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            # Check if file is uploaded
            file_obj = request.FILES.get('template_file')
            
            if not file_obj:
                return Response(
                    {"detail": "template_file is required in multipart/form-data"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate file type (optional)
            allowed_extensions = ['.xlsx', '.xlsm', '.xls', '.xlsb']
            file_extension = os.path.splitext(file_obj.name)[1].lower()
            if file_extension not in allowed_extensions:
                return Response(
                    {"detail": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                # Delete existing template file if it exists
                if project.template_link:
                    try:
                        # Extract blob name from the existing URL
                        # The blob name is the path after the bucket name in the URL
                        old_blob_name = project.template_link.split(f"{settings.GCS_BUCKET_NAME}/")[-1].split("?")[0]
                        gcs_helper.delete_file(old_blob_name)
                    except Exception as e:
                        # Log the error but continue with upload
                        print(f"Warning: Failed to delete old template: {str(e)}")
                
                # Generate destination path in GCS (without timestamp for consistency)
                # Format: projects/{project_id}/templates/{filename}
                destination_path = f"projects/{project_id}/templates/{file_obj.name}"
                
                # Upload to GCS
                upload_result = gcs_helper.upload_file(
                    file_obj=file_obj,
                    destination_path=destination_path,
                    content_type=file_obj.content_type
                )
                
                # Update project with GCS URL
                project.template_link = upload_result['url']
                
                acting_user = None
                if hasattr(request, 'user') and isinstance(request.user, User):
                    acting_user = request.user
                else:
                    acting_user = User.objects.first()
                if acting_user is not None:
                    project.updated_by = acting_user
                
                project.save()
                
                return Response({
                    **ProjectSerializer(project).data,
                    'upload_info': {
                        'gcs_url': upload_result['url'],
                        'blob_name': upload_result['blob_name'],
                        'file_name': file_obj.name,
                        'file_size': file_obj.size,
                        'replaced_existing': bool(project.template_link)
                    }
                })
                
            except Exception as e:
                return Response(
                    {"detail": f"Upload failed: {str(e)}"}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        return handler(self, request, project_id=project_id)
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        template_link = request.data.get('template_link')
        if not template_link:
            return Response({"detail": "template_link is required"}, status=status.HTTP_400_BAD_REQUEST)
        project.template_link = template_link
        acting_user = None
        if hasattr(request, 'user') and isinstance(request.user, User):
            acting_user = request.user
        else:
            acting_user = User.objects.first()
        if acting_user is not None:
            project.updated_by = acting_user
        project.save()
        return Response(ProjectSerializer(project).data)


class EditProjectView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def patch(self, request, project_id):
        # @require_project_permission(write=True)
        def handler(self, request, project_id):
            project = get_object_or_404(Project, id=project_id, is_deleted=False)
            data = {k: v for k, v in request.data.items() if k in ['name', 'template_link', 'base_landco_devco_template']}
            for k, v in data.items():
                setattr(project, k, v)
            acting_user = None
            if hasattr(request, 'user') and isinstance(request.user, User):
                acting_user = request.user
            else:
                acting_user = User.objects.first()
            if acting_user is not None:
                project.updated_by = acting_user
            project.save()
            return Response(ProjectSerializer(project).data)

        return handler(self, request, project_id=project_id)


class ProjectUsersView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def get(self, request, project_id):
        # @require_project_permission(read=True)
        def handler(self, request, project_id):
            project = get_object_or_404(Project, id=project_id, is_deleted=False)
            perms = UserProjectPermission.objects.filter(project_assoc=project).select_related('user_assoc')
            return Response(UserProjectPermissionSerializer(perms, many=True).data)

        return handler(self, request, project_id=project_id)


class AssignUserView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, project_id):
        # @require_project_permission(write=True)
        def handler(self, request, project_id):
            project = get_object_or_404(Project, id=project_id)
            serializer = AssignUserPermissionSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            user = get_object_or_404(User, username=serializer.validated_data['user_id'])
            acting_user = None
            if hasattr(request, 'user') and isinstance(request.user, User):
                acting_user = request.user
            else:
                acting_user = User.objects.first()
            
            # Get read and write access from request, with defaults
            read_access = serializer.validated_data.get('read_access', True)
            write_access = serializer.validated_data.get('write_access', False)
            
            perm, created = UserProjectPermission.objects.update_or_create(
                user_assoc=user,
                project_assoc=project,
                defaults={
                    'read_access': read_access,
                    'write_access': write_access,
                    'updated_by': acting_user if acting_user else user,
                    'created_by': acting_user if acting_user else user,
                }
            )
            return Response(UserProjectPermissionSerializer(perm).data, status=status.HTTP_201_CREATED)

        return handler(self, request, project_id=project_id)


class EditUserPermissionView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def patch(self, request, project_id, user_id):
        # @require_project_permission(write=True)
        def handler(self, request, project_id, user_id):
            project = get_object_or_404(Project, id=project_id, is_deleted=False)
            perm = get_object_or_404(UserProjectPermission, user_assoc__username=user_id, project_assoc=project)
            read_access = request.data.get('read_access')
            write_access = request.data.get('write_access')
            if read_access is not None:
                perm.read_access = bool(read_access)
            if write_access is not None:
                perm.write_access = bool(write_access)
            acting_user = None
            if hasattr(request, 'user') and isinstance(request.user, User):
                acting_user = request.user
            else:
                acting_user = User.objects.first()
            if acting_user is not None:
                perm.updated_by = acting_user
            perm.save()
            return Response(UserProjectPermissionSerializer(perm).data)

        return handler(self, request, project_id=project_id, user_id=user_id)


class ToggleProjectStatusView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, project_id):
        # @require_project_permission(write=True)
        def handler(self, request, project_id):
            project = get_object_or_404(Project, id=project_id)
            
            # Get the is_deleted status from request body, default to True for backward compatibility
            is_deleted = request.data.get('is_deleted', True)
            
            if not isinstance(is_deleted, bool):
                return Response(
                    {"detail": "is_deleted must be a boolean value"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            project.is_deleted = is_deleted
            acting_user = None
            if hasattr(request, 'user') and isinstance(request.user, User):
                acting_user = request.user
            else:
                acting_user = User.objects.first()
            if acting_user is not None:
                project.updated_by = acting_user
            project.save()
            
            action = "deactivated" if is_deleted else "activated"
            return Response({
                "detail": f"Project {action}",
                "project_id": project.id,
                "is_deleted": project.is_deleted
            })

        return handler(self, request, project_id=project_id)


# Keep DeactivateProjectView for backward compatibility (optional)
class DeactivateProjectView(ToggleProjectStatusView):
    """
    Deprecated: Use ToggleProjectStatusView instead.
    Maintained for backward compatibility.
    """
    pass


class ListUsersView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def get(self, request):
        users = User.objects.filter(is_active=True).order_by('username')
        from management.serializers import UserSerializer, UserProjectPermissionSerializer

        # Collect all UserProjectPermissions for these users
        user_permissions_map = {}
        permissions = UserProjectPermission.objects.select_related('project_assoc').filter(user_assoc__in=users)
        for perm in permissions:
            user_id = perm.user_assoc.id
            if user_id not in user_permissions_map:
                user_permissions_map[user_id] = []
            user_permissions_map[user_id].append(UserProjectPermissionSerializer(perm).data)

        serialized_users = []
        for user in users:
            u_data = UserSerializer(user).data
            u_data['projects'] = user_permissions_map.get(user.id, [])
            serialized_users.append(u_data)

        return Response(serialized_users)


class ListProjectsView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def get(self, request):
        projects = Project.objects.all().order_by('-created_at')
        
        # Get user counts for each project
        project_user_counts = {}
        permissions = UserProjectPermission.objects.filter(project_assoc__in=projects).values('project_assoc').annotate(
            user_count=models.Count('user_assoc', distinct=True)
        )
        for perm in permissions:
            project_user_counts[perm['project_assoc']] = perm['user_count']
        
        # Serialize projects and add user count
        serialized_projects = []
        for project in projects:
            project_data = ProjectSerializer(project).data
            project_data['user_count'] = project_user_counts.get(project.id, 0)
            serialized_projects.append(project_data)
        
        return Response(serialized_projects)
    

class ExistingScenariosSaveView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request):
        project_id = request.data.get('project_id')
        user_id = request.data.get('user_id')
        scenarios_id = request.data.get('scenarios_id')
        payload = request.data.get('scenarios', {})
        
        if not project_id:
            return Response(
                {"detail": "project_id is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not user_id:
            return Response(
                {"detail": "user_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not scenarios_id:
            return Response(
                {"detail": "scenarios_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not payload:
            return Response(
                {"detail": "scenarios payload is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify project exists and is not deleted
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        print("Project found:", project.id)
        
        # Verify user exists
        # user = get_object_or_404(User, username=user_id)
        # print("User found:", user.username)
        # Get the scenario and verify ownership
        try:
            scenario = Iteration.objects.get(
                id=scenarios_id,
                project_assoc=project,
                user_assoc= user_id,
                is_deleted=False
            )
            print("Scenario found:", scenario.id)
        except Iteration.DoesNotExist:
            return Response(
                {"detail": "Scenario not found or you don't have permission to edit this scenario"},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get existing output_json or initialize empty dict
        existing_output = scenario.output_json if scenario.output_json else {}
        
        # Define valid scenario types that can be updated
        valid_types = ['LANDCO', 'DEVCO', 'ASSETCO', 'CONSOLIDATED']
        
        # Merge only the valid keys from payload into existing output
        updated_keys = []
        for key in valid_types:
            if key in payload:
                existing_output[key] = payload[key]
                updated_keys.append(key)
        
        if not updated_keys:
            return Response(
                {"detail": f"No valid scenario types provided. Valid types: {', '.join(valid_types)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Store the merged data back to output_json
        scenario.output_json = existing_output
        scenario.save()
        
        return Response({
            "project_id": project_id,
            "scenario_id": scenarios_id,
            "user_id": user_id,
            "message": "Scenario data saved successfully",
            "updated_types": updated_keys,
            "total_types_in_output": list(existing_output.keys())
        }, status=status.HTTP_200_OK)

class ScenariosDeleteView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request):
        project_id = request.data.get('project_id')
        scenarios_id = request.data.get('scenarios_id')
        
        if not project_id:
            return Response(
                {"detail": "project_id is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        if not scenarios_id:
            return Response(
                {"detail": "scenarios_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify project exists and is not deleted
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        
        # Soft delete the specified scenario
        try:
            scenario = Iteration.objects.get(
                project_assoc=project,
                id=scenarios_id,
                is_deleted=False
            )
            
            scenario.is_deleted = True
            scenario.save()
            
            return Response({
                "project_id": project_id,
                "scenario_id": scenarios_id,
                "deleted": True,
                "message": "Scenario successfully deleted"
            })
            
        except Iteration.DoesNotExist:
            return Response(
                {"detail": "Scenario not found or already deleted"},
                status=status.HTTP_404_NOT_FOUND
            )
    
class ScenariosActivateView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request):
        project_id = request.data.get('project_id')
        scenarios_id = request.data.get('scenarios_id')
        
        if not project_id:
            return Response(
                {"detail": "project_id is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        if not scenarios_id:
            return Response(
                {"detail": "scenarios_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify project exists (can be deleted or active)
        project = get_object_or_404(Project, id=project_id)
        
        # Reactivate the specified scenario
        try:
            scenario = Iteration.objects.get(
                project_assoc=project,
                id=scenarios_id,
                is_deleted=True
            )
            
            scenario.is_deleted = False
            scenario.save()
            
            return Response({
                "project_id": project_id,
                "scenario_id": scenarios_id,
                "activated": True,
                "message": "Scenario successfully activated"
            })
            
        except Iteration.DoesNotExist:
            return Response(
                {"detail": "Scenario not found or already active"},
                status=status.HTTP_404_NOT_FOUND
            )
           
    
class ScenariosView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request):
        project_id = request.data.get('project_id')
        
        if not project_id:
            return Response(
                {"detail": "project_id is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify project exists and is not deleted
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        
        # Filter scenarios by project and select related user
        scenarios = Iteration.objects.filter(
            project_assoc=project,
            
            is_deleted=False
        ).select_related('user_assoc').order_by('-created_at')
        
        # Build response with scenario IDs and user associations
        scenarios_data = [
            {
                "id": scenario.id,
                "user_assoc": scenario.user_assoc.username,
                "name": scenario.name,
            }
            for scenario in scenarios
        ]
        
        return Response({
            "project_id": project_id,
            "scenarios": scenarios_data,
            "count": len(scenarios_data)
        })

class ReportView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request):
        project_id = request.data.get('project_id')
        scenarios_id = request.data.get('scenarios_id')
        
        return Response([{
            
    "land_area": 10000,
    "buildable_area": 8000,
    "units": 50,
    "unit_mix": {
        "1BR": 20,
        "2BR": 20,
        "3BR": 10
    },
    "costs": {
        "land_cost_per_sqft": 100,
        "construction_cost_per_sqft": 200
    },
    "revenue": {
        "avg_price_per_unit": 500000
    }

        }])

class SyncUsersView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request):
        from management.serializers import UserSyncRequestSerializer
        
        # Preprocess the data to convert invalid emails to synthetic ones
        request_data = request.data.copy()
        if 'users' in request_data:
            for user in request_data['users']:
                email_value = user.get('email', '')
                # If email doesn't contain @ or is not a valid email, create synthetic one
                if '@' not in email_value and user.get('user_id'):
                    user['email'] = f"{user['user_id']}@placeholder.local"
        
        serializer = UserSyncRequestSerializer(data=request_data)
        serializer.is_valid(raise_exception=True)
        
        incoming_users = serializer.validated_data['users']
        group_id = serializer.validated_data.get('group_id', '')
        
        # Extract incoming user IDs (use user_id as unique identifier)
        incoming_user_ids = {user['user_id'] for user in incoming_users if user.get('user_id')}
        
        # Get all existing users (both active and inactive) by their username
        existing_users = User.objects.all()
        existing_user_ids = {user.username for user in existing_users}
        existing_active_user_ids = {user.username for user in existing_users if user.is_active}
        
        # Determine users to add and remove
        users_to_add_ids = incoming_user_ids - existing_user_ids
        users_to_remove_ids = existing_active_user_ids - incoming_user_ids
        
        added_users = []
        removed_users = []
        updated_users = []
        
        # Add or update users
        for user_data in incoming_users:
            user_id = user_data.get('user_id')
            if not user_id:
                continue
            
            # Use the email from validated data (already converted if needed)
            email_value = user_data.get('email', f"{user_id}@placeholder.local")
            
            if user_id in users_to_add_ids:
                # Create new user with user_id as username
                user = User.objects.create(
                    username=user_id,
                    email=email_value,
                    first_name=user_data.get('first_name', ''),
                    last_name=user_data.get('last_name', ''),
                    is_active=True
                )
                
                added_users.append({
                    'user_id': user_id,
                    'username': user_id,
                    'email': email_value,
                    'first_name': user.first_name,
                    'last_name': user.last_name
                })
            else:
                # Update existing user info (whether active or inactive)
                try:
                    user = User.objects.get(username=user_id)
                    
                    # Track if user was reactivated
                    was_inactive = not user.is_active
                    
                    # Reactivate if was soft-deleted
                    if not user.is_active:
                        user.is_active = True
                    
                    # Update user information
                    updated = False
                    
                    if user.email != email_value:
                        user.email = email_value
                        updated = True
                    
                    if user_data.get('first_name') and user.first_name != user_data['first_name']:
                        user.first_name = user_data['first_name']
                        updated = True
                    
                    if user_data.get('last_name') and user.last_name != user_data['last_name']:
                        user.last_name = user_data['last_name']
                        updated = True
                    
                    if updated or was_inactive:
                        user.save()
                        updated_users.append({
                            'user_id': user_id,
                            'username': user.username,
                            'email': user.email,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'reactivated': was_inactive
                        })
                except User.DoesNotExist:
                    pass
        
        # Soft delete removed users (set is_active to False)
        for user_id in users_to_remove_ids:
            try:
                user = User.objects.get(username=user_id, is_active=True)
                user.is_active = False
                user.save()
                
                # Also remove user from all project permissions
                UserProjectPermission.objects.filter(user_assoc=user).delete()
                
                removed_users.append({
                    'user_id': user_id,
                    'username': user.username,
                    'email': user.email
                })
            except User.DoesNotExist:
                pass
        
        return Response({
            'status': 'success',
            'message': 'User synchronization completed',
            'summary': {
                'total_incoming': len(incoming_users),
                'added': len(added_users),
                'removed': len(removed_users),
                'updated': len(updated_users),
            },
            'details': {
                'added_users': added_users,
                'removed_users': removed_users,
                'updated_users': updated_users,
            },
            'group_id': group_id
        }, status=status.HTTP_200_OK)


class DatabaseCredentialsView(APIView):
    # authentication_classes = [MSALAuthentication]
    # permission_classes = [IsMSALAuthenticated]

    def get(self, request):
        db_configs = settings.DATABASES
        safe_configs = {}
        for alias, cfg in db_configs.items():
            safe_configs[alias] = {
                'ENGINE': cfg.get('ENGINE'),
                'NAME': str(cfg.get('NAME')),
                'HOST': cfg.get('HOST'),
                'PORT': cfg.get('PORT'),
                'USER': cfg.get('USER'),
                'PASSWORD': cfg.get('PASSWORD'),
                'OPTIONS': cfg.get('OPTIONS'),
            }
        return Response(safe_configs)


class DownloadTemplateView(APIView):
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def get(self, request, project_id):
        @require_project_permission(read=True)
        def handler(self, request, project_id):
            project = get_object_or_404(Project, id=project_id, is_deleted=False)
            
            if not project.template_link:
                return Response(
                    {"detail": "No template file found for this project"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Check if GCS is available
            if not gcs_helper.is_available:
                return Response(
                    {"detail": "File download is not available in local development mode. GCS credentials not configured."}, 
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            try:
                # Extract blob name from the template_link
                # Handle both gs:// and https:// URLs
                if project.template_link.startswith('gs://'):
                    # Format: gs://bucket-name/path/to/file
                    blob_name = project.template_link.replace(f"gs://{settings.GCS_BUCKET_NAME}/", "")
                else:
                    # Format: https://storage.googleapis.com/bucket-name/path/to/file
                    blob_name = project.template_link.split(f"{settings.GCS_BUCKET_NAME}/")[-1].split("?")[0]
                
                # Download file from GCS
                file_content, content_type = gcs_helper.download_file(blob_name)
                
                # Extract filename from blob_name
                filename = os.path.basename(blob_name)
                
                # Create response with file content
                response = HttpResponse(file_content, content_type=content_type or 'application/octet-stream')
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                response['Content-Length'] = len(file_content)
                
                return response
                
            except Exception as e:
                return Response(
                    {"detail": f"Download failed: {str(e)}"}, 
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        return handler(self, request, project_id=project_id)

# ================ Asset Management APIs ================

class ProjectAssetsListView(APIView):
    """
    List all assets for a project or create a new asset.
    GET: Returns list of assets for the project
    POST: Creates a new asset for the project
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def get(self, request, project_id):
        """Get assets for a project, optionally including soft deleted ones."""
        project = get_object_or_404(Project, id=project_id)

        include_deleted_raw = request.query_params.get('include_deleted', 'false')
        include_deleted = str(include_deleted_raw).lower() in {'1', 'true', 'yes'}

        asset_query = ProjectAsset.objects.filter(project_assoc=project)
        # if not include_deleted:
        #     asset_query = asset_query.filter(is_deleted=False)

        assets = asset_query.order_by('asset_name')
        
        serializer = ProjectAssetSerializer(assets, many=True)
        return Response({
            'project_id': project_id,
            'project_name': project.name,
            'total_assets': len(assets),
            'assets': serializer.data
        }, status=status.HTTP_200_OK)

    def post(self, request, project_id):
        """Create a new asset for a project"""
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        
        serializer = ProjectAssetCreateSerializer(data=request.data, context={'project': project})
        serializer.is_valid(raise_exception=True)
        
        # Get acting user
        acting_user = None
        if hasattr(request, 'user') and isinstance(request.user, User):
            acting_user = request.user
        else:
            acting_user = User.objects.first()
        
        if acting_user is None:
            return Response(
                {"detail": "No user available to set as creator"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create the asset
        asset = ProjectAsset.objects.create(
            project_assoc=project,
            asset_unique_identifier=serializer.validated_data['asset_unique_identifier'],
            asset_name=serializer.validated_data['asset_name'],
            asset_base_file_link=serializer.validated_data.get('asset_base_file_link'),
            is_hospitality=serializer.validated_data.get('is_hospitality', False),
            created_by=acting_user,
            updated_by=acting_user
        )
        
        return Response(
            ProjectAssetSerializer(asset).data,
            status=status.HTTP_201_CREATED
        )


class ProjectAssetDetailView(APIView):
    """
    Retrieve, update, or delete a specific asset.
    GET: Returns asset details
    PATCH: Updates asset information
    DELETE: Soft deletes the asset
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def get(self, request, project_id, asset_id):
        """Get asset details"""
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        asset = get_object_or_404(
            ProjectAsset,
            id=asset_id,
            project_assoc=project,
            is_deleted=False
        )
        
        serializer = ProjectAssetSerializer(asset)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, project_id, asset_id):
        """Update asset details"""
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        asset = get_object_or_404(
            ProjectAsset,
            id=asset_id,
            project_assoc=project,
            is_deleted=False
        )
        
        serializer = ProjectAssetUpdateSerializer(asset, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        # Get acting user
        acting_user = None
        if hasattr(request, 'user') and isinstance(request.user, User):
            acting_user = request.user
        else:
            acting_user = User.objects.first()
        
        if acting_user is not None:
            asset.updated_by = acting_user
        
        serializer.save()
        return Response(
            ProjectAssetSerializer(asset).data,
            status=status.HTTP_200_OK
        )

    def delete(self, request, project_id, asset_id):
        """Soft delete an asset"""
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        asset = get_object_or_404(
            ProjectAsset,
            id=asset_id,
            project_assoc=project,
            is_deleted=False
        )
        
        # Soft delete
        asset.is_deleted = True
        
        # Get acting user
        acting_user = None
        if hasattr(request, 'user') and isinstance(request.user, User):
            acting_user = request.user
        else:
            acting_user = User.objects.first()
        
        if acting_user is not None:
            asset.updated_by = acting_user
        
        asset.save()
        
        return Response({
            'detail': 'Asset deleted successfully',
            'asset_id': asset_id,
            'project_id': project_id
        }, status=status.HTTP_200_OK)


class ToggleAssetStatusView(APIView):
    """
    Toggle asset status between active and inactive (soft delete).
    Similar to ToggleProjectStatusView but for assets.
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, project_id, asset_id):
        """Toggle asset active/inactive status"""
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        asset = get_object_or_404(
            ProjectAsset,
            id=asset_id,
            project_assoc=project
        )
        
        # Get the is_deleted status from request body
        is_deleted = request.data.get('is_deleted', False)
        
        if not isinstance(is_deleted, bool):
            return Response(
                {"detail": "is_deleted must be a boolean"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        asset.is_deleted = is_deleted
        
        # Get acting user
        acting_user = None
        if hasattr(request, 'user') and isinstance(request.user, User):
            acting_user = request.user
        else:
            acting_user = User.objects.first()
        
        if acting_user is not None:
            asset.updated_by = acting_user
        
        asset.save()
        
        action = "deactivated" if is_deleted else "activated"
        return Response({
            "detail": f"Asset {action}",
            "asset_id": asset.id,
            "asset_name": asset.asset_name,
            "is_deleted": asset.is_deleted
        }, status=status.HTTP_200_OK)


class ProjectAssetUploadBaseFileView(APIView):
    """
    Upload or update the base file URL for an asset.
    This view is used by admin to associate a base template file with an asset.
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, project_id, asset_id):
        """Upload/update base file URL for an asset"""
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        asset = get_object_or_404(
            ProjectAsset,
            id=asset_id,
            project_assoc=project,
            is_deleted=False
        )
        
        asset_base_file_link = request.data.get('asset_base_file_link')
        
        if not asset_base_file_link:
            return Response(
                {"detail": "asset_base_file_link is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate URL format (basic check)
        if not (asset_base_file_link.startswith('gs://') or 
                asset_base_file_link.startswith('http://') or
                asset_base_file_link.startswith('https://')):
            return Response(
                {"detail": "asset_base_file_link must be a valid URL (gs://, http://, or https://)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update the asset
        asset.asset_base_file_link = asset_base_file_link
        
        # Get acting user
        acting_user = None
        if hasattr(request, 'user') and isinstance(request.user, User):
            acting_user = request.user
        else:
            acting_user = User.objects.first()
        
        if acting_user is not None:
            asset.updated_by = acting_user
        
        asset.save()
        
        return Response({
            'detail': 'Asset base file URL updated successfully',
            'asset_id': asset_id,
            'asset_name': asset.asset_name,
            'asset_base_file_link': asset.asset_base_file_link,
            'updated_at': asset.updated_at
        }, status=status.HTTP_200_OK)

    def patch(self, request, project_id, asset_id):
        """Alias for POST - allows PATCH requests as well"""
        return self.post(request, project_id, asset_id)


# ================ File Upload Views ================

class UploadProjectBaseLandcoDevcoTemplateView(APIView):
    """
    Upload LandCo/DevCo base template file for a project.
    This is the base sheet that will be used for all LandCo/DevCo iterations.
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, project_id):
        """Upload base LandCo/DevCo template file to GCS"""
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        
        # Check if GCS is available
        if not gcs_helper.is_available:
            return Response(
                {"detail": "File upload is not available in local development mode. GCS credentials not configured."}, 
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        # Check if file is uploaded
        file_obj = request.FILES.get('template_file')
        
        if not file_obj:
            return Response(
                {"detail": "template_file is required in multipart/form-data"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate file type
        allowed_extensions = ['.xlsx', '.xlsm', '.xls', '.xlsb']
        file_extension = os.path.splitext(file_obj.name)[1].lower()
        if file_extension not in allowed_extensions:
            return Response(
                {"detail": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Delete existing base template if it exists
            if project.base_landco_devco_template:
                try:
                    old_blob_name = project.base_landco_devco_template.split(f"{settings.GCS_BUCKET_NAME}/")[-1].split("?")[0]
                    gcs_helper.delete_file(old_blob_name)
                except Exception as e:
                    print(f"Warning: Failed to delete old base template: {str(e)}")
            
            # Generate destination path in GCS
            # Format: projects/{project_id}/base-templates/landco-devco/{filename}
            destination_path = f"projects/{project_id}/base-templates/landco-devco/{file_obj.name}"
            
            # Upload to GCS
            upload_result = gcs_helper.upload_file(
                file_obj=file_obj,
                destination_path=destination_path,
                content_type=file_obj.content_type
            )
            
            # Update project with GCS URL
            project.base_landco_devco_template = upload_result['url']
            
            acting_user = None
            if hasattr(request, 'user') and isinstance(request.user, User):
                acting_user = request.user
            else:
                acting_user = User.objects.first()
            if acting_user is not None:
                project.updated_by = acting_user
            
            project.save()
            
            return Response({
                **ProjectSerializer(project).data,
                'upload_info': {
                    'file_type': 'base_landco_devco_template',
                    'gcs_url': upload_result['url'],
                    'blob_name': upload_result['blob_name'],
                    'file_name': file_obj.name,
                    'file_size': file_obj.size
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {"detail": f"Upload failed: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UploadAssetBaseFileView(APIView):
    """
    Upload base file for an asset.
    Each asset can have its own base template file for AssetCo calculations.
    """
    authentication_classes = [MSALAuthentication]
    permission_classes = [IsMSALAuthenticated]

    def post(self, request, project_id, asset_id):
        """Upload asset base file to GCS"""
        project = get_object_or_404(Project, id=project_id, is_deleted=False)
        asset = get_object_or_404(
            ProjectAsset,
            id=asset_id,
            project_assoc=project,
            is_deleted=False
        )
        
        # Check if GCS is available
        if not gcs_helper.is_available:
            return Response(
                {"detail": "File upload is not available in local development mode. GCS credentials not configured."}, 
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        # Check if file is uploaded
        file_obj = request.FILES.get('asset_file')
        
        if not file_obj:
            return Response(
                {"detail": "asset_file is required in multipart/form-data"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate file type
        allowed_extensions = ['.xlsx', '.xlsm', '.xls', '.xlsb']
        file_extension = os.path.splitext(file_obj.name)[1].lower()
        if file_extension not in allowed_extensions:
            return Response(
                {"detail": f"Invalid file type. Allowed: {', '.join(allowed_extensions)}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Delete existing asset base file if it exists
            if asset.asset_base_file_link:
                try:
                    old_blob_name = asset.asset_base_file_link.split(f"{settings.GCS_BUCKET_NAME}/")[-1].split("?")[0]
                    gcs_helper.delete_file(old_blob_name)
                except Exception as e:
                    print(f"Warning: Failed to delete old asset base file: {str(e)}")
            
            # Generate destination path in GCS
            # Format: projects/{project_id}/assets/{asset_id}/base-files/{filename}
            destination_path = f"projects/{project_id}/assets/{asset_id}/base-files/{file_obj.name}"
            
            # Upload to GCS
            upload_result = gcs_helper.upload_file(
                file_obj=file_obj,
                destination_path=destination_path,
                content_type=file_obj.content_type
            )
            
            # Update asset with GCS URL
            asset.asset_base_file_link = upload_result['url']
            
            acting_user = None
            if hasattr(request, 'user') and isinstance(request.user, User):
                acting_user = request.user
            else:
                acting_user = User.objects.first()
            if acting_user is not None:
                asset.updated_by = acting_user
            
            asset.save()
            
            return Response({
                **ProjectAssetSerializer(asset).data,
                'upload_info': {
                    'file_type': 'asset_base_file',
                    'gcs_url': upload_result['url'],
                    'blob_name': upload_result['blob_name'],
                    'file_name': file_obj.name,
                    'file_size': file_obj.size
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response(
                {"detail": f"Upload failed: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ================ JSON Normalization API ================

class NormalisationView(APIView):
    """
    Normalize LandCo/DevCo data using iteration input_json.
    """
    # authentication_classes = [MSALAuthentication]
    # permission_classes = [IsMSALAuthenticated]

    @staticmethod
    def _normalize_period_type(value_type):
        normalized = str(value_type or "").strip().lower()
        if normalized in {"monthly", "month"}:
            return "month"
        if normalized in {"annual", "yearly", "year"}:
            return "year"
        return None

    @staticmethod
    def _normalize_label(value):
        text = str(value or "").strip().lower()
        text = text.replace("&", " and ")
        text = re.sub(r"[^a-z0-9\s]", " ", text)
        text = " ".join(text.split())
        return text

    @classmethod
    def _normalized_variants(cls, value):
        base = cls._normalize_label(value)
        variants = {base}

        token_swaps = {
            "expenses": "expense",
            "expense": "expenses",
            "costs": "cost",
            "cost": "costs",
            "fees": "fee",
            "fee": "fees",
        }

        tokens = base.split()
        for idx, token in enumerate(tokens):
            swapped = token_swaps.get(token)
            if swapped:
                alt_tokens = tokens.copy()
                alt_tokens[idx] = swapped
                variants.add(" ".join(alt_tokens))

        if base.endswith("s"):
            variants.add(base[:-1])
        else:
            variants.add(f"{base}s")
        return {v for v in variants if v}

    @classmethod
    def _build_data_item_cache(cls):
        # Local import keeps this resilient even if a stale process loaded old globals.
        from management.models import DimDataItem
        child_cache = {}
        child_by_parent_cache = {}
        parent_cache = {}

        for row in DimDataItem.objects.values(
            "id", "module", "category", "item", "parent_id"
        ):
            module = cls._normalize_label(row.get("module"))
            categories = cls._normalized_variants(row.get("category"))
            items = cls._normalized_variants(row.get("item"))

            target_cache = parent_cache if row.get("parent_id") is None else child_cache
            for category in categories:
                for item in items:
                    target_cache.setdefault((module, category, item), row["id"])

            if row.get("parent_id") is not None:
                for item in items:
                    child_by_parent_cache.setdefault(
                        (module, row.get("parent_id"), item), row["id"]
                    )

        return {
            "child": child_cache,
            "child_by_parent": child_by_parent_cache,
            "parent": parent_cache,
        }

    def _resolve_data_item_id(self, item, module_key, dataitem_cache):
        cashflow_section = item.get("Cashflow Section")
        main_category = item.get("Main Category")
        line_item = item.get("Line Item")
        if not main_category:
            return None

        module = self._normalize_label(module_key)
        child_cache = dataitem_cache.get("child", {})
        child_by_parent_cache = dataitem_cache.get("child_by_parent", {})
        parent_cache = dataitem_cache.get("parent", {})

        section_variants = self._normalized_variants(cashflow_section)
        main_category_variants = self._normalized_variants(main_category)

        # Some normalizers emit blank Line Item and place the actual leaf label in Main Category.
        normalized_line_item = self._normalize_label(line_item)
        if normalized_line_item:
            line_item_variants = self._normalized_variants(line_item)
        else:
            line_item_variants = set()

        if not normalized_line_item:
            # Blank line-item rows can represent either a parent-level bucket or a
            # leaf item emitted directly into Main Category by the normalizer.
            for section in section_variants:
                for main in main_category_variants:
                    dataitem_id = child_cache.get((module, section, main))
                    if dataitem_id:
                        return dataitem_id

            # No third-level line item: resolve to the parent-level item.
            for section in section_variants:
                for main in main_category_variants:
                    parent_id = parent_cache.get((module, section, main))
                    if parent_id:
                        return parent_id

            for main in main_category_variants:
                dataitem_id = child_cache.get((module, main, main))
                if dataitem_id:
                    return dataitem_id

            for main in main_category_variants:
                parent_id = parent_cache.get((module, main, main))
                if parent_id:
                    return parent_id

            return None

        resolved_parent_id = None
        for section in section_variants:
            for main in main_category_variants:
                parent_id = parent_cache.get((module, section, main))
                if parent_id:
                    resolved_parent_id = parent_id
                    break
            if resolved_parent_id:
                break

        if resolved_parent_id:
            for line in line_item_variants:
                dataitem_id = child_by_parent_cache.get((module, resolved_parent_id, line))
                if dataitem_id:
                    return dataitem_id

        # Preferred schema: category = Cashflow Section, item = Line Item.
        for section in section_variants:
            for line in line_item_variants:
                dataitem_id = child_cache.get((module, section, line))
                if dataitem_id:
                    return dataitem_id

        # Preferred parent fallback: category = Cashflow Section, item = Main Category.
        for section in section_variants:
            for main in main_category_variants:
                parent_id = parent_cache.get((module, section, main))
                if parent_id:
                    return parent_id

        # Backward-compatible schema fallback: category = Main Category, item = Line Item.
        for main in main_category_variants:
            for line in line_item_variants:
                dataitem_id = child_cache.get((module, main, line))
                if dataitem_id:
                    return dataitem_id

        # Backward-compatible parent fallback: category = Main Category, item = Main Category.
        for main in main_category_variants:
            parent_id = parent_cache.get((module, main, main))
            if parent_id:
                return parent_id

        return None

    @staticmethod
    def _resolve_data_item_module_key(module_key, is_hospitality=False):
        module_name = NormalisationView._normalize_label(module_key)
        if module_name == "project consolidation":
            return "consolidated"
        if module_name == "jv consolidation":
            return "jv"
        if is_hospitality and module_name == "assetco":
            return "hospitality"
        return module_name

    @staticmethod
    def _parse_period_start(raw_period_start):
        if raw_period_start in [None, ""]:
            return None

        if isinstance(raw_period_start, datetime):
            return raw_period_start.date()

        if isinstance(raw_period_start, (int, float)):
            timestamp = float(raw_period_start)
            # Normalizers can emit epoch time in milliseconds.
            if timestamp > 10**11:
                timestamp = timestamp / 1000.0
            try:
                return datetime.utcfromtimestamp(timestamp).date()
            except (OverflowError, OSError, ValueError):
                return None

        if isinstance(raw_period_start, str):
            cleaned = raw_period_start.strip()
            if cleaned.isdigit():
                return NormalisationView._parse_period_start(float(cleaned))

            parsed_date = parse_date(cleaned)
            if parsed_date is not None:
                return parsed_date

            iso_candidate = cleaned.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(iso_candidate).date()
            except ValueError:
                return None

        return None

    def _resolve_period_id(self, item, period_cache):
        value_type = item.get("Value Type")
        period_type = self._normalize_period_type(value_type)
        if not period_type:
            return None

        period_start = self._parse_period_start(item.get("Period Start"))

        raw_year = item.get("Year")
        try:
            year = int(raw_year) if raw_year is not None else None
        except (TypeError, ValueError):
            year = None

        if period_type == "month":
            if not period_start:
                return None
            cache_key = ("month", period_start)
            if cache_key not in period_cache:
                period_cache[cache_key] = (
                    DimPeriod.objects.filter(
                        period_type__iexact="month",
                        period_start=period_start,
                    )
                    .values_list("id", flat=True)
                    .first()
                )
            return period_cache[cache_key]

        # Annual rows: allow Period Start to be null and resolve by Year.
        target_year = year or (period_start.year if period_start else None)
        if target_year is None:
            return None

        cache_key = ("year", target_year)
        if cache_key not in period_cache:
            period_cache[cache_key] = (
                DimPeriod.objects.filter(
                    period_type__iexact="year",
                    period_start__year=target_year,
                )
                .values_list("id", flat=True)
                .first()
            )
        return period_cache[cache_key]

    @staticmethod
    def _build_period_bounds(period_type, period_start, year):
        if period_type == "month" and period_start:
            period_end = date(period_start.year, period_start.month, monthrange(period_start.year, period_start.month)[1])
            return period_start, period_end

        if year is None:
            return None, None

        return date(year, 1, 1), date(year, 12, 31)

    def _resolve_or_create_period_id(self, item, period_cache):
        period_id = self._resolve_period_id(item, period_cache)
        if period_id:
            return period_id

        period_type = self._normalize_period_type(item.get("Value Type"))
        if not period_type:
            return None

        period_start = self._parse_period_start(item.get("Period Start"))
        raw_year = item.get("Year")
        try:
            year = int(raw_year) if raw_year is not None else None
        except (TypeError, ValueError):
            year = None

        if period_type == "year" and year is None and period_start:
            year = period_start.year

        resolved_start, resolved_end = self._build_period_bounds(period_type, period_start, year)
        if resolved_start is None or resolved_end is None:
            return None

        cache_key = (period_type, resolved_start if period_type == "month" else year)
        if cache_key in period_cache and period_cache[cache_key]:
            return period_cache[cache_key]

        period_id = (
            DimPeriod.objects.filter(
                period_type__iexact=period_type,
                period_start=resolved_start,
                period_end=resolved_end,
            )
            .values_list("id", flat=True)
            .first()
        )
        if not period_id:
            period_id = DimPeriod.objects.create(
                period_type=period_type,
                period_start=resolved_start,
                period_end=resolved_end,
            ).id

        period_cache[cache_key] = period_id
        return period_id

    def _attach_dim_period_ids(self, normalized_data, is_hospitality=False):
        period_cache = {}
        dataitem_cache = self._build_data_item_cache()

        for module_key, module_payload in normalized_data.items():
            rows = self._extract_dashboard_rows(module_payload)
            data_item_module_key = self._resolve_data_item_module_key(module_key, is_hospitality=is_hospitality)

            for item in rows:
                if not isinstance(item, dict):
                    continue
                item["Period ID"] = self._resolve_or_create_period_id(item, period_cache)
                item["DataItem ID"] = self._resolve_data_item_id(item, data_item_module_key, dataitem_cache)
                item.pop("Value Type", None)
                item.pop("Period Start", None)
                item.pop("Year", None)

    @staticmethod
    def _text_or_empty(value):
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _decimal_or_none(value):
        if value in [None, ""]:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None

    @staticmethod
    def _float_or_none(value):
        if value in [None, ""]:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _date_or_none(value):
        if value in [None, ""]:
            return None
        if isinstance(value, str):
            try:
                parsed = parse_date(value)
                if parsed is not None:
                    return parsed
            except Exception:
                pass
            try:
                parsed_dt = datetime.fromisoformat(value)
                return parsed_dt.date() if isinstance(parsed_dt, datetime) else parsed_dt
            except Exception:
                return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return None

    @staticmethod
    def _extract_dashboard_rows(module_payload):
        if isinstance(module_payload, dict):
            rows = module_payload.get("normalized_dashboard_payload")
            return rows if isinstance(rows, list) else []
        if isinstance(module_payload, list):
            return module_payload
        return []

    @staticmethod
    def _extract_model_assumptions(module_payload):
        if not isinstance(module_payload, dict):
            return []
        rows = module_payload.get("ModelAssumptions")
        if isinstance(rows, list):
            return rows
        if isinstance(rows, dict):
            flattened_rows = []
            for category, values in rows.items():
                if isinstance(values, dict):
                    for item, value in values.items():
                        flattened_rows.append(
                            {
                                "Category": category,
                                "Item": item,
                                "Value": value,
                            }
                        )
                else:
                    flattened_rows.append(
                        {
                            "Category": "ModelAssumptions",
                            "Item": category,
                            "Value": values,
                        }
                    )
            return flattened_rows
        return []

    @staticmethod
    def _extract_global_inputs(module_payload):
        if not isinstance(module_payload, dict):
            return []

        rows = []

        # Nested in ModelAssumptions.Global (new style)
        model_assumptions = module_payload.get("ModelAssumptions")
        if isinstance(model_assumptions, dict):
            nested_global = model_assumptions.get("Global")
            if isinstance(nested_global, dict):
                for category, values in nested_global.items():
                    if not isinstance(values, dict):
                        continue
                    for item, value in values.items():
                        rows.append({
                            "Category": category,
                            "Item": item,
                            "Value": value,
                        })

        return rows

    @staticmethod
    def _extract_input_details(module_payload):
        if not isinstance(module_payload, dict):
            return []
        rows = module_payload.get("InputDetails")
        if isinstance(rows, list):
            return rows
        if isinstance(rows, dict):
            return list(rows.values())
        return []

    def _attach_asset_iteration_ids(self, normalized_data, iteration):
        module_models = {
            "landco": AssetIteration_Landco,
            "devco": AssetIteration_Devco,
            "project_consolidation": ProjectConsolidationAsset,
        }
        asset_defaults_by_module = {"landco": {}, "devco": {}, "project_consolidation": {}}
        asset_cache_by_module = {"landco": {}, "devco": {}, "project_consolidation": {}}
        fields_to_pop = [
            "Region",
            "City",
            "Asset Class",
            "Sub Category",
            "Typology",
            "Construction Phase",
            "Business Model",
            "Exit Counterparty",
            "Asset",
            "Asset Unique ID",
            "Category",
        ]

        def _base_defaults(item):
            return {
                "region": self._text_or_empty(item.get("Region") or item.get("region")),
                "city": self._text_or_empty(item.get("City") or item.get("city")),
                "asset_class": self._text_or_empty(item.get("Asset Class") or item.get("asset_class")),
                "sub_category": self._text_or_empty(item.get("Sub Category") or item.get("sub_category")),
                "typology": self._text_or_empty(item.get("Typology") or item.get("typology")),
                "construction_phase": self._decimal_or_none(item.get("Construction Phase") or item.get("construction_phase")),
                "asset_order": self._decimal_or_none(item.get("asset_order") or item.get("Asset")),
                "asset_name": self._text_or_empty(
                    item.get("Asset Name")
                    or item.get("asset_name")
                    or item.get("Unique ID")
                    or item.get("Asset No")
                    or item.get("asset_no")
                ),
                "asset_unique_identifier": self._text_or_empty(
                    item.get("Asset Unique Identifier")
                    or item.get("Asset Unique ID")
                    or item.get("asset_unique_identifier")
                    or item.get("Unique ID")
                    or item.get("Asset No")
                    or item.get("asset_no")
                ),
                "business_model": self._text_or_empty(item.get("Business Model") or item.get("business_model")),
                "exit_counterparty": self._text_or_empty(item.get("Exit Counterparty") or item.get("exit_counterparty")),
                "units": self._float_or_none(item.get("units") or item.get("Units")),
                "developable_land_area": self._float_or_none(item.get("developable_land_area") or item.get("Developable Land Area")),
                "master_plan_efficiency": self._float_or_none(item.get("master_plan_efficiency") or item.get("Master Plan Efficiency")),
                "gross_land_area": self._float_or_none(item.get("gross_land_area") or item.get("Gross Land Area")),
                "site_coverage_ratio": self._float_or_none(item.get("site_coverage_ratio") or item.get("Site Coverage Ratio")),
                "site_coverage_area": self._float_or_none(item.get("site_coverage_area") or item.get("Site Coverage Area")),
                "gross_floor_area": self._float_or_none(item.get("gross_floor_area") or item.get("Gross Floor Area")),
                "built_up_area": self._float_or_none(item.get("built_up_area") or item.get("Built Up Area")),
                "floor_plan_efficiency": self._float_or_none(item.get("floor_plan_efficiency") or item.get("Floor Plan Efficiency")),
                "total_nsa_gla": self._float_or_none(item.get("total_nsa_gla") or item.get("total_nsa__gla") or item.get("Total NSA/GLA") or item.get("Total NSA GLA")),
                "floor_area_ratio": self._float_or_none(item.get("floor_area_ratio") or item.get("Floor Area Ratio")),
                "parking_bays": self._float_or_none(item.get("parking_bays") or item.get("Parking Bays")),
                "jvjda_inclusion": self._text_or_empty(item.get("jvjda_inclusion") or item.get("JV/JDA Inclusion") or item.get("JVJDA Inclusion")),
                "venture_type": self._text_or_empty(item.get("venture_type") or item.get("Venture Type")),
                "land_bank_override": self._text_or_empty(item.get("land_bank_override") or item.get("Land Bank Override")),
                "holding_period": self._text_or_empty(item.get("holding_period") or item.get("Holding Period")),
                "devco_inclusion": self._text_or_empty(item.get("devco_inclusion") or item.get("DevCo Inclusion")),
                "asset_devco_inclusion": self._text_or_empty(item.get("asset_devco_inclusion") or item.get("Asset DevCo Inclusion")),
                "sales_override": self._text_or_empty(item.get("sales_override") or item.get("Sales Override")),
                "sales_value": self._float_or_none(item.get("sales_value") or item.get("Sales Value")),
                "landco_inclusion": self._text_or_empty(item.get("landco_inclusion") or item.get("LandCo Inclusion") or item.get("Land Co Inclusion")),
                "asset_landco_inclusion": self._text_or_empty(item.get("asset_landco_inclusion") or item.get("Asset LandCo Inclusion")),
                "land_sales_price": self._float_or_none(item.get("land_sales_price") or item.get("Land Sales Price") or item.get("sales_price") or item.get("Sales Price")),
                "land_sales_override": self._text_or_empty(item.get("land_sales_override") or item.get("Land Sales Override")),
                "land_development": self._text_or_empty(item.get("land_development") or item.get("Land Development")),
                "vertical_development": self._text_or_empty(item.get("vertical_development") or item.get("Vertical Development")),
                "asset_operations": self._text_or_empty(item.get("asset_operations") or item.get("Asset Operations")),
                "secondary_infrastructure_override": self._text_or_empty(item.get("secondary_infrastructure_override") or item.get("Secondary Infrastructure Override") or item.get("Secondary Infrastructure Module Override")),
                "secondary_infrastructure_module_construction_start_date": self._date_or_none(item.get("secondary_infrastructure_module_construction_start_date") or item.get("Secondary Infrastructure Module Construction Start Date") or item.get("Secondary Infrastructure Construction Start Date")),
                "primary_infrastructure_module_override": self._text_or_empty(item.get("primary_infrastructure_module_override") or item.get("Primary Infrastructure Module Override") or item.get("Primary Infrastructure Override")),
                "primary_infrastructure_module_construction_start_date": self._date_or_none(item.get("primary_infrastructure_module_construction_start_date") or item.get("Primary Infrastructure Module Construction Start Date") or item.get("Primary Infrastructure Construction Start Date")),
            }

        def _normalize_for_module(module_name, defaults):
            if module_name == "landco":
                return {
                    **{
                        k: v
                        for k, v in defaults.items()
                        if k not in {
                            "asset_unique_identifier",
                            "devco_inclusion",
                            "asset_devco_inclusion",
                            "sales_override",
                            "sales_value",
                        }
                    },
                    "asset_unique_id": defaults.get("asset_unique_identifier", ""),
                    "landco_inclusion": defaults.get("landco_inclusion", ""),
                    "asset_landco_inclusion": defaults.get("asset_landco_inclusion", ""),
                    "land_sales_price": defaults.get("land_sales_price"),
                    "land_sales_override": defaults.get("land_sales_override", ""),
                    "land_development": defaults.get("land_development", ""),
                    "vertical_development": defaults.get("vertical_development", ""),
                    "asset_operations": defaults.get("asset_operations", ""),
                    "secondary_infrastructure_override": defaults.get("secondary_infrastructure_override", ""),
                    "secondary_infrastructure_module_construction_start_date": defaults.get("secondary_infrastructure_module_construction_start_date"),
                    "primary_infrastructure_module_override": defaults.get("primary_infrastructure_module_override", ""),
                    "primary_infrastructure_module_construction_start_date": defaults.get("primary_infrastructure_module_construction_start_date"),
                }
            if module_name == "project_consolidation":
                return {
                    "asset_name": defaults.get("asset_name", ""),
                    "asset_unique_identifier": defaults.get("asset_unique_identifier", ""),
                }
            allowed_devco_keys = {
                "region",
                "city",
                "asset_class",
                "sub_category",
                "typology",
                "construction_phase",
                "asset_name",
                "business_model",
                "exit_counterparty",
                "units",
                "developable_land_area",
                "master_plan_efficiency",
                "gross_land_area",
                "site_coverage_ratio",
                "site_coverage_area",
                "gross_floor_area",
                "built_up_area",
                "floor_plan_efficiency",
                "total_nsa_gla",
                "floor_area_ratio",
                "parking_bays",
                "jvjda_inclusion",
                "venture_type",
                "land_bank_override",
                "holding_period",
                "asset_order",
            }
            return {
                **{k: v for k, v in defaults.items() if k in allowed_devco_keys},
                "asset_unique_id": defaults.get("asset_unique_identifier", ""),
                "devco_inclusion": defaults.get("devco_inclusion", ""),
                "asset_devco_inclusion": defaults.get("asset_devco_inclusion", ""),
                "sales_override": defaults.get("sales_override", ""),
                "sales_value": defaults.get("sales_value"),
            }

        def _merge_defaults(existing, incoming):
            for key, value in incoming.items():
                if key not in existing or existing.get(key) in (None, ""):
                    if value not in (None, ""):
                        existing[key] = value

        def _extract_asset_key(item, module_name=None):
            if not isinstance(item, dict):
                return None

            if module_name == "project_consolidation":
                for key in (
                    "Unique ID",
                    "Asset No",
                    "asset_no",
                    "Asset Unique Identifier",
                    "Asset Unique ID",
                    "Asset Name",
                    "asset_name",
                ):
                    value = item.get(key)
                    if value is not None and str(value).strip() != "":
                        return str(value).strip()
                return None

            for key in (
                "Asset Unique ID",
                "Asset Unique Identifier",
                "Unique ID",
                "Asset No",
                "asset_unique_identifier",
                "asset_no",
            ):
                value = item.get(key)
                if value is not None and str(value).strip() != "":
                    return str(value).strip()
            return None

        # Pass 1: collect rows from each module's normalized dashboard payload.
        for module_key, module_payload in normalized_data.items():
            module_name = str(module_key or "").strip().lower()
            if module_name not in module_models:
                continue
            rows = self._extract_dashboard_rows(module_payload)

            for item in rows:
                if not isinstance(item, dict):
                    continue

                if module_name != "project_consolidation":
                    if str(item.get("Category") or "").strip().lower() != "asset":
                        continue

                asset_key = _extract_asset_key(item, module_name)
                if not asset_key:
                    continue

                module_defaults = asset_defaults_by_module[module_name]
                defaults = module_defaults.setdefault(asset_key, _normalize_for_module(module_name, _base_defaults(item)))

                incoming = _normalize_for_module(module_name, _base_defaults(item))
                _merge_defaults(defaults, incoming)

        # InputDetails now exist for both landco and devco and enrich asset-level dimensions.
        for module_name in ("landco", "devco"):
            for detail in self._extract_input_details(normalized_data.get(module_name)):
                if not isinstance(detail, dict):
                    continue

                asset_unique_id = (
                    detail.get("Asset Unique ID")
                    or detail.get("asset_unique_id")
                    or detail.get("asset_unique_identifier")
                )
                if not asset_unique_id:
                    continue

                asset_unique_id = str(asset_unique_id)
                module_defaults = asset_defaults_by_module[module_name]
                defaults = module_defaults.setdefault(asset_unique_id, _normalize_for_module(module_name, _base_defaults(detail)))

                incoming = _normalize_for_module(module_name, _base_defaults(detail))
                if module_name == "landco":
                    incoming["landco_inclusion"] = self._text_or_empty(detail.get("landco_inclusion") or detail.get("LandCo Inclusion"))
                    incoming["asset_landco_inclusion"] = self._text_or_empty(detail.get("asset_landco_inclusion") or detail.get("Asset LandCo Inclusion"))
                elif module_name == "devco":
                    incoming["devco_inclusion"] = self._text_or_empty(detail.get("devco_inclusion") or detail.get("DevCo Inclusion"))
                    incoming["asset_devco_inclusion"] = self._text_or_empty(detail.get("asset_devco_inclusion") or detail.get("Asset DevCo Inclusion"))
                _merge_defaults(defaults, incoming)

                # For core asset identity fields, prefer InputDetails values when present.
                for key in (
                    "region",
                    "city",
                    "asset_class",
                    "sub_category",
                    "typology",
                    "construction_phase",
                    "asset_order",
                    "asset_name",
                    "business_model",
                    "exit_counterparty",
                ):
                    value = incoming.get(key)
                    if value not in (None, ""):
                        defaults[key] = value

        for module_name, model_cls in module_models.items():
            module_defaults = asset_defaults_by_module[module_name]
            if not module_defaults:
                continue

            if module_name == "project_consolidation":
                # Scope lookup to this iteration — unique_together is now
                # (iteration, asset_unique_identifier), so the same UID can exist
                # across different iterations without conflict.
                all_uids = list(module_defaults.keys())
                existing_assets = model_cls.objects.filter(
                    iteration=iteration,
                    asset_unique_identifier__in=all_uids,
                ).values_list("asset_unique_identifier", "id")
                asset_cache_by_module[module_name] = {
                    uid: asset_id for uid, asset_id in existing_assets
                }

                missing_uids = [
                    uid for uid in all_uids
                    if uid not in asset_cache_by_module[module_name]
                ]
                if missing_uids:
                    assets_to_create = [
                        model_cls(
                            project_assoc=iteration.project_assoc,
                            iteration=iteration,
                            asset_unique_identifier=uid,
                        )
                        for uid in missing_uids
                    ]
                    # ignore_conflicts guards against concurrent requests inserting
                    # the same (iteration, uid) pair simultaneously.
                    model_cls.objects.bulk_create(
                        assets_to_create, batch_size=1000, ignore_conflicts=True
                    )
                    newly_fetched = model_cls.objects.filter(
                        iteration=iteration,
                        asset_unique_identifier__in=missing_uids,
                    ).values_list("asset_unique_identifier", "id")
                    asset_cache_by_module[module_name].update(
                        {uid: asset_id for uid, asset_id in newly_fetched}
                    )
            else:
                assets_to_create = [
                    model_cls(
                        iteration=iteration,
                        asset_unique_id=asset_unique_id,
                        **{k: v for k, v in defaults.items() if k != "asset_unique_id"},
                    )
                    for asset_unique_id, defaults in module_defaults.items()
                ]
                model_cls.objects.bulk_create(assets_to_create, batch_size=1000)

                existing_assets = model_cls.objects.filter(
                    iteration=iteration,
                    asset_unique_id__in=list(module_defaults.keys()),
                ).values_list("asset_unique_id", "id")
                asset_cache_by_module[module_name] = {
                    asset_unique_id: asset_id for asset_unique_id, asset_id in existing_assets
                }

        for module_key, module_payload in normalized_data.items():
            module_name = str(module_key or "").strip().lower()
            rows = self._extract_dashboard_rows(module_payload)

            for item in rows:
                if not isinstance(item, dict):
                    continue

                category = str(item.get("Category") or "").strip().lower()
                if module_name != "project_consolidation" and category != "asset":
                    item["AssetIteration ID"] = None
                    for field in fields_to_pop:
                        item.pop(field, None)
                    continue

                asset_key = _extract_asset_key(item, module_name)
                if not asset_key:
                    item["AssetIteration ID"] = None
                    for field in fields_to_pop:
                        item.pop(field, None)
                    continue

                item["AssetIteration ID"] = asset_cache_by_module.get(module_name, {}).get(asset_key)
                for field in fields_to_pop:
                    item.pop(field, None)

        return sum(len(cache) for cache in asset_cache_by_module.values())

    @staticmethod
    def _normalize_global_item_key(value):
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    def _persist_global_input_iterations(self, normalized_data, iteration, is_hospitality=False):
        assumptions_payload = []
        for module_key, module_payload in normalized_data.items():
            module_name = str(module_key or "").lower()

            # LandCo / DevCo global inputs are emitted under ModelAssumptions directly.
            if module_name in {"landco", "devco", "project_consolidation"}:
                for row in self._extract_model_assumptions(module_payload):
                    if isinstance(row, dict):
                        assumptions_payload.append((module_name, row))

            # Hospitality global inputs are emitted under assetco -> ModelAssumptions directly.
            if is_hospitality and module_name == "assetco":
                for row in self._extract_model_assumptions(module_payload):
                    if isinstance(row, dict):
                        assumptions_payload.append((module_name, row))

            # AssetCo global inputs are emitted under ModelAssumptions.Global.
            for row in self._extract_global_inputs(module_payload):
                if isinstance(row, dict):
                    assumptions_payload.append((module_name, row))

        if not assumptions_payload:
            return 0

        dim_lookup = {
            (
                self._normalize_global_item_key(row.category),
                self._normalize_global_item_key(row.item),
            ): row.id
            for row in DimGlobalDataItem.objects.all()
        }

        rows_to_create = []
        for module_name, row in assumptions_payload:
            category = row.get("Category") or row.get("category") or row.get("Main Category") or row.get("main_category")
            item_name = row.get("Item") or row.get("item") or row.get("Line Item") or row.get("line_item")
            value = row.get("Value") if "Value" in row else row.get("value")

            if category is None or item_name is None:
                continue

            key = (
                self._normalize_global_item_key(category),
                self._normalize_global_item_key(item_name),
            )
            dim_id = dim_lookup.get(key)
            if not dim_id:
                # create missing dim if not found
                dim_id = DimGlobalDataItem.objects.create(category=category, item=item_name).id
                dim_lookup[key] = dim_id

            rows_to_create.append(
                GlobalInputsIteration(
                    global_data_item_id=dim_id,
                    value=None if value is None else str(value),
                    iteration=iteration,
                    module=module_name,
                )
            )

        if rows_to_create:
            GlobalInputsIteration.objects.bulk_create(rows_to_create, batch_size=1000)
        return len(rows_to_create)

    @staticmethod
    def _reset_global_input_iterations(iteration):
        GlobalInputsIteration.objects.filter(iteration=iteration).delete()

    @staticmethod
    def _reset_asset_iterations(iteration):
        # Replace mode: remove previously generated asset iteration rows for this iteration.
        AssetIteration_Landco.objects.filter(iteration=iteration).delete()
        AssetIteration_Devco.objects.filter(iteration=iteration).delete()

    @staticmethod
    def _reset_normalised_iterations(iteration):
        # Replace mode: remove previously generated normalized rows for this iteration.
        NormalisedIteration.objects.filter(iteration=iteration).delete()

    @staticmethod
    def _reset_unit_iteration_assetco(iteration):
        UnitIteration_Assetco.objects.filter(iteration=iteration).delete()

    def _persist_unit_iteration_assetco(self, normalized_data, iteration):
        assetco_payload = normalized_data.get("assetco") or {}
        if not isinstance(assetco_payload, dict):
            return 0

        model_assumptions = assetco_payload.get("ModelAssumptions") or {}
        units = []
        if isinstance(model_assumptions, dict):
            units = model_assumptions.get("Units") or []

        if not isinstance(units, list) or not units:
            return 0

        project_asset = iteration.asset_assoc
        existing = UnitIteration_Assetco.objects.filter(iteration=iteration)
        existing_key = {
            (str(u.unit_id or "").strip(), str(u.sno or "").strip()): u
            for u in existing
        }

        count = 0
        for row in units:
            if not isinstance(row, dict):
                continue
            unit_id = str(row.get("unit_id") or "").strip()
            if not unit_id:
                continue
            sno = row.get("sno")
            key = (unit_id, str(sno or "").strip())

            obj = existing_key.get(key)
            if obj is None:
                obj = UnitIteration_Assetco.objects.create(
                    iteration=iteration,
                    project_asset=project_asset,
                    sno=sno,
                    asset_name=row.get("asset_name") or "",
                    asset_id=row.get("asset_id") or "",
                    asset_address=str(row.get("asset_address") or ""),
                    unit_id=unit_id,
                    unit_type=row.get("unit_type") or "",
                    sub_unit_type=row.get("sub_unit_type") or "",
                    gross_leasable_area=self._float_or_none(row.get("gross_leasable_area")),
                    market_rent=self._float_or_none(row.get("market_rent")),
                    tenant_id=row.get("tenant_id") or "",
                    tenant_name=row.get("tenant_name") or "",
                    lease_start_date=row.get("lease_start_date") or None,
                    lease_tenure=self._float_or_none(row.get("lease_tenure")),
                    rent_free_duration=self._float_or_none(row.get("rent_free_duration")),
                    cash_collection_start_date=row.get("cash_collection_start_date") or None,
                    lease_expiration_date=row.get("lease_expiration_date") or None,
                    break_option_exercised=row.get("break_option_exercised") or "",
                    break_option_date=row.get("break_option_date") or None,
                    sales_density=self._float_or_none(row.get("sales_density")),
                    second_tenant=row.get("second_tenant") or "",
                    void_period_months=str(row.get("void_period_months") or ""),
                    forecast_base_rent=self._float_or_none(row.get("forecast_base_rent")),
                    renewal_probability=row.get("renewal_probability") or "",
                    tenant_2_id=row.get("tenant_2_id") or "",
                    tenant_2_name=row.get("tenant_2_name") or "",
                    tenant_2_lease_start_date=row.get("tenant_2_lease_start_date") or None,
                    tenant_2_lease_tenure=self._float_or_none(row.get("tenant_2_lease_tenure")),
                    tenant_2_rent_free_duration=self._float_or_none(row.get("tenant_2_rent_free_duration")),
                    tenant_2_cash_collection_start_date=row.get("tenant_2_cash_collection_start_date") or None,
                    tenant_2_lease_expiration_date=row.get("tenant_2_lease_expiration_date") or None,
                    tenant_2_break_option_exercised=row.get("tenant_2_break_option_exercised") or "",
                    tenant_2_break_option_date=row.get("tenant_2_break_option_date") or None,
                    tenant_2_sales_density=self._float_or_none(row.get("tenant_2_sales_density")),
                    tenant_2_forecast_base_rent=self._float_or_none(row.get("tenant_2_forecast_base_rent"))
                )
                existing_key[key] = obj
                count += 1
            else:
                updated = False
                for field, value in {
                    "asset_name": row.get("asset_name"),
                    "asset_id": row.get("asset_id"),
                    "asset_address": str(row.get("asset_address") or ""),
                    "unit_type": row.get("unit_type"),
                    "sub_unit_type": row.get("sub_unit_type"),
                    "gross_leasable_area": self._float_or_none(row.get("gross_leasable_area")),
                    "market_rent": self._float_or_none(row.get("market_rent")),
                    "tenant_id": row.get("tenant_id"),
                    "tenant_name": row.get("tenant_name"),
                    "lease_start_date": row.get("lease_start_date"),
                    "lease_tenure": self._float_or_none(row.get("lease_tenure")),
                    "rent_free_duration": self._float_or_none(row.get("rent_free_duration")),
                    "cash_collection_start_date": row.get("cash_collection_start_date"),
                    "lease_expiration_date": row.get("lease_expiration_date"),
                    "break_option_exercised": row.get("break_option_exercised"),
                    "break_option_date": row.get("break_option_date"),
                    "sales_density": self._float_or_none(row.get("sales_density")),
                    "second_tenant": row.get("second_tenant"),
                    "void_period_months": str(row.get("void_period_months") or ""),
                    "tenant_2_id": row.get("tenant_2_id"),
                    "tenant_2_name": row.get("tenant_2_name"),
                    "tenant_2_lease_start_date": row.get("tenant_2_lease_start_date"),
                    "tenant_2_lease_tenure": self._float_or_none(row.get("tenant_2_lease_tenure")),
                    "tenant_2_rent_free_duration": self._float_or_none(row.get("tenant_2_rent_free_duration")),
                    "tenant_2_cash_collection_start_date": row.get("tenant_2_cash_collection_start_date"),
                    "tenant_2_lease_expiration_date": row.get("tenant_2_lease_expiration_date"),
                    "tenant_2_break_option_exercised": row.get("tenant_2_break_option_exercised"),
                    "tenant_2_break_option_date": row.get("tenant_2_break_option_date"),
                    "tenant_2_sales_density": self._float_or_none(row.get("tenant_2_sales_density")),
                    "tenant_2_forecast_base_rent": self._float_or_none(row.get("tenant_2_forecast_base_rent")),
                    "renewal_probability": row.get("renewal_probability") or "",
                    "forecast_base_rent": self._float_or_none(row.get("forecast_base_rent")),
                }.items():
                    if value not in (None, "") and getattr(obj, field) != value:
                        setattr(obj, field, value)
                        updated = True
                if updated:
                    obj.save()
            row["unit_iteration_assetco_id"] = obj.id

        return count

    @staticmethod
    def _attach_assetco_unit_iteration_ids(normalized_data, iteration):
        assetco_payload = normalized_data.get("assetco") or {}
        if not isinstance(assetco_payload, dict):
            return

        unit_lookup = {
            str(unit.unit_id or "").strip(): unit.id
            for unit in UnitIteration_Assetco.objects.filter(iteration=iteration)
        }
        for item in NormalisationView._extract_dashboard_rows(assetco_payload):
            if not isinstance(item, dict):
                continue
            raw_unit_id = item.get("unit_id")
            if raw_unit_id in (None, ""):
                raw_unit_id = item.get("Unit ID")
            if raw_unit_id in (None, ""):
                item["UnitIteration ID"] = None
                continue
            item["UnitIteration ID"] = unit_lookup.get(str(raw_unit_id).strip())

    @staticmethod
    def _persist_normalised_iterations(normalized_data, iteration):
        rows_to_create = []

        for module_key, module_payload in normalized_data.items():
            module_name = str(module_key or "").strip().lower()
            rows = NormalisationView._extract_dashboard_rows(module_payload)

            for item in rows:
                if not isinstance(item, dict):
                    continue

                period_id = item.get("Period ID")
                if not period_id:
                    continue

                value = item.get("Value")
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue

                asset_landco_id = item.get("AssetIteration ID") if module_name == "landco" else None
                asset_devco_id = item.get("AssetIteration ID") if module_name == "devco" else None
                asset_project_consolidation_id = item.get("AssetIteration ID") if module_name == "project_consolidation" else None
                asset_unit_id = None
                if module_name == "assetco":
                    asset_unit_id = item.get("UnitIteration ID")
                    if asset_unit_id in (None, ""):
                        asset_unit_id = item.get("unit_iteration_assetco_id")

                rows_to_create.append(
                    NormalisedIteration(
                        period_id=period_id,
                        data_item_id=item.get("DataItem ID"),
                        value=value,
                        iteration=iteration,
                        asset_landco_id=asset_landco_id,
                        asset_devco_id=asset_devco_id,
                        asset_project_consolidation_id=asset_project_consolidation_id,
                        asset_unit_id=asset_unit_id,
                        is_jv=False,
                    )
                )

        if rows_to_create:
            NormalisedIteration.objects.bulk_create(rows_to_create, batch_size=1000)
        return len(rows_to_create)

    def _run_normalisation(self, iteration_id, run_sensitivity=False, iteration_type_override=None):
        _cloud_run_log("INFO", "[normalisation] START iteration_id=%s sensitivity=%s", iteration_id, run_sensitivity)
        try:
            close_old_connections()
            iteration = get_object_or_404(Iteration, id=iteration_id, is_deleted=False)
            iteration_type = iteration_type_override or iteration.iteration_type
            is_hospitality = False
            _cloud_run_log("INFO", "[normalisation] iteration_id=%s type=%s", iteration_id, iteration_type)

            # ════════════════════════════════════════════════════════════════════════
            # SENSITIVITY PATH: Run sensitivity analysis only (no normal normalization)
            # ════════════════════════════════════════════════════════════════════════
            if run_sensitivity:
                input_json = iteration.input_json
                if input_json is None:
                    _cloud_run_log("WARNING", "[normalisation] iteration_id=%s input_json is empty", iteration_id)
                    return {"error": "Iteration input_json is empty"}

                sensitivity_row_counts: dict = {}
                landco_sens = None
                devco_sens = None
                assetco_sens = None

                if iteration_type == "landco":
                    _cloud_run_log("INFO", "[normalisation] iteration_id=%s running landco sensitivity", iteration_id)
                    landco_sens = landco_sensitivity_module.fninitialising_all_values(input_json)
                    sensitivity_row_counts["landco"] = save_sensitivity_to_db(landco_sens, "landco", iteration)

                elif iteration_type == "devco":
                    _cloud_run_log("INFO", "[normalisation] iteration_id=%s running devco sensitivity", iteration_id)
                    devco_sens = devco_sensitivity_module.fninitialising_all_values(input_json)
                    sensitivity_row_counts["devco"] = save_sensitivity_to_db(devco_sens, "devco", iteration)

                elif iteration_type in ["landco_devco", None, ""]:
                    _cloud_run_log("INFO", "[normalisation] iteration_id=%s running landco sensitivity", iteration_id)
                    landco_sens = landco_sensitivity_module.fninitialising_all_values(input_json)
                    sensitivity_row_counts["landco"] = save_sensitivity_to_db(landco_sens, "landco", iteration)

                    _cloud_run_log("INFO", "[normalisation] iteration_id=%s running devco sensitivity", iteration_id)
                    devco_sens = devco_sensitivity_module.fninitialising_all_values(input_json)
                    sensitivity_row_counts["devco"] = save_sensitivity_to_db(devco_sens, "devco", iteration)

                elif iteration_type == "assetco":
                    _cloud_run_log("INFO", "[normalisation] iteration_id=%s running assetco sensitivity", iteration_id)
                    assetco_sens = assetco_sensitivity_module.fninitialising_all_values(input_json)
                    sensitivity_row_counts["assetco"] = save_sensitivity_to_db(assetco_sens, "assetco", iteration)

                else:
                    _cloud_run_log(
                        "WARNING",
                        "[normalisation] iteration_id=%s sensitivity not supported for type=%s",
                        iteration_id,
                        iteration_type,
                    )
                    return {
                        "error": f"Sensitivity analysis not supported for iteration_type: {iteration_type}",
                        "status": status.HTTP_400_BAD_REQUEST,
                    }

                result = {
                    "success": True,
                    "message": "Sensitivity analysis completed successfully",
                    "iteration_id": iteration.id,
                    "iteration_type": iteration_type,
                    "sensitivity_row_counts": sensitivity_row_counts,
                    # "landco_sensitivity_rows": {"landco_sens": landco_sens},
                    # "devco_sensitivity_rows": {"devco_sens": devco_sens},
                    # "assetco_sensitivity_rows": {"assetco_sens":assetco_sens},
                }
                _cloud_run_log(
                    "INFO",
                    "[normalisation] DONE (sensitivity) iteration_id=%s type=%s sensitivity_rows=%s",
                    iteration_id,
                    iteration_type,
                    sensitivity_row_counts,
                )
                return result

            # ════════════════════════════════════════════════════════════════════════
            # NORMAL PATH: Run standard normalization (no sensitivity)
            # ════════════════════════════════════════════════════════════════════════
            else:
                if iteration_type in ["landco_devco", None, ""]:
                    input_json = iteration.input_json
                    if input_json is None:
                        _cloud_run_log("WARNING", "[normalisation] iteration_id=%s input_json is empty", iteration_id)
                        return {"error": "Iteration input_json is empty"}
                    normalized_data = {
                        "landco": landco_norm_v1.fninitialising_all_values(input_json),
                        "devco": devco_norm_v1.fninitialising_all_values(input_json),
                    }
                elif iteration_type == "assetco":
                    input_json = iteration.input_json
                    is_hospitality = bool(iteration.asset_assoc and iteration.asset_assoc.is_hospitality)
                    if input_json is None:
                        _cloud_run_log("WARNING", "[normalisation] iteration_id=%s input_json is empty", iteration_id)
                        return {"error": "Iteration input_json is empty"}
                    if is_hospitality:
                        _cloud_run_log("INFO", "[normalisation] iteration_id=%s assetco hospitality=true", iteration_id)
                        normalized_data = {
                            "assetco": assetco_hospitality_norm.fninitialising_all_values(input_json)
                        }
                    else:
                        _cloud_run_log("INFO", "[normalisation] iteration_id=%s assetco hospitality=false", iteration_id)
                        normalized_data = {
                            "assetco": assetco_norm.fninitialising_all_values(input_json)
                        }
                elif iteration_type == "project_consolidation":
                    input_json = iteration.input_json
                    if input_json is None:
                        _cloud_run_log("WARNING", "[normalisation] iteration_id=%s input_json is empty", iteration_id)
                        return {"error": "Iteration input_json is empty"}

                    try:
                        source_selection = input_json.get("source_selection") if isinstance(input_json, dict) else None
                        named_ranges = input_json.get("namedRanges")
                        output_json = iteration.output_json if isinstance(iteration.output_json, dict) else {}
                        resolved_input_json = _build_project_consolidation_from_db(
                            iteration.project_assoc,
                            iteration.user_assoc,
                            source_selection,
                            named_ranges,
                        )
                    except PermissionError as exc:
                        return {"error": str(exc), "status": status.HTTP_403_FORBIDDEN}
                    except ValueError as exc:
                        return {"error": str(exc), "status": status.HTTP_400_BAD_REQUEST}
                    project_payload = consolidated_norm.fninitialising_all_values(resolved_input_json)
                    normalized_data = {"project_consolidation": project_payload}
                elif iteration_type == "jv_consolidation":
                    input_json = iteration.input_json
                    if input_json is None:
                        _cloud_run_log("WARNING", "[normalisation] iteration_id=%s input_json is empty", iteration_id)
                        return {"error": "Iteration input_json is empty"}

                    try:
                        resolved_input_json = _build_jv_consolidation_from_db(
                            project=iteration.project_assoc,
                            user=iteration.user_assoc,
                            input_payload=input_json,
                        )
                    except PermissionError as exc:
                        return {"error": str(exc), "status": status.HTTP_403_FORBIDDEN}
                    except ValueError as exc:
                        return {"error": str(exc), "status": status.HTTP_400_BAD_REQUEST}

                    jv_payload = jv_consolidation_norm.fninitialising_all_values(resolved_input_json)
                    normalized_data = {"jv_consolidation": jv_payload}
                else:
                    _cloud_run_log("WARNING", "[normalisation] iteration_id=%s unsupported type=%s", iteration_id, iteration_type)
                    return {"error": f"Normalization not supported for iteration_type: {iteration_type}", "status": status.HTTP_400_BAD_REQUEST}

                self._attach_dim_period_ids(normalized_data, is_hospitality=is_hospitality)
                irr_decomposition_count = 0
                with transaction.atomic():
                    self._reset_global_input_iterations(iteration)
                    global_input_count = self._persist_global_input_iterations(
                        normalized_data,
                        iteration,
                        is_hospitality=is_hospitality,
                    )
                    self._reset_asset_iterations(iteration)
                    asset_iteration_count = self._attach_asset_iteration_ids(normalized_data, iteration)
                    self._reset_unit_iteration_assetco(iteration)
                    unit_iteration_count = self._persist_unit_iteration_assetco(normalized_data, iteration)
                    self._attach_assetco_unit_iteration_ids(normalized_data, iteration)
                    if iteration_type == "assetco":
                        assetco_payload = normalized_data.get("assetco") or {}
                        if isinstance(assetco_payload, dict):
                            irr_decomposition_payload = assetco_payload.get("IRR_Decomposition", {})
                        else:
                            irr_decomposition_payload = {}

                        # Helper resets existing rows for the same iteration before insert.
                        irr_decomposition_ids = save_irr_decomposition_to_db(irr_decomposition_payload, iteration)
                        irr_decomposition_count = len(irr_decomposition_ids)

                        if isinstance(assetco_payload, dict):
                            assetco_payload["irr_decomposition_ids"] = irr_decomposition_ids

                        if not is_hospitality:
                            inflation_profiles = assetco_payload.get("inflation_profiles", {}) if isinstance(assetco_payload, dict) else {}
                            # Helper resets existing rows for the same iteration before insert.
                            inflation_profile_ids = save_inflation_profiles_to_db(inflation_profiles, iteration)
                            if isinstance(assetco_payload, dict):
                                assetco_payload["inflation_profile_ids"] = inflation_profile_ids
                                assetco_payload.pop("inflation_profiles", None)
                    self._reset_normalised_iterations(iteration)
                    normalised_row_count = self._persist_normalised_iterations(normalized_data, iteration)

                result = {
                    "success": True,
                    "message": "Normalization completed successfully",
                    "iteration_id": iteration.id,
                    "iteration_type": iteration_type,
                    "global_input_count": global_input_count,
                    "asset_iteration_count": asset_iteration_count,
                    "unit_iteration_count": unit_iteration_count,
                    "irr_decomposition_count": irr_decomposition_count,
                    "normalised_row_count": normalised_row_count,
                    # "normalised_data": normalized_data
                }
                if iteration_type == "assetco":
                    result["is_hospitality"] = is_hospitality
                _cloud_run_log(
                    "INFO",
                    "[normalisation] DONE iteration_id=%s type=%s global_inputs=%s asset_iterations=%s unit_iterations=%s normalised_rows=%s",
                    iteration_id, iteration_type, global_input_count, asset_iteration_count, unit_iteration_count, normalised_row_count,
                )
                return result

        except Exception as exc:
            import traceback
            error_trace = traceback.format_exc()
            _cloud_run_log("ERROR", "[normalisation] FAILED iteration_id=%s error=%s", iteration_id, exc)
            print(error_trace, flush=True)
            return {"error": str(exc), "traceback": error_trace, "status": status.HTTP_500_INTERNAL_SERVER_ERROR}

        finally:
            try:
                close_old_connections()
            except Exception:
                pass

    def post(self, request):
        """
        Normalize using iteration input_json.
        Accepts two formats:

        1. Direct call:
           {"iteration_id": 95}

        2. Google Cloud Pub/Sub push envelope:
           {"message": {"data": "<base64(iteration_id)>"}, "subscription": "..."}

        Pub/Sub push deliveries are acknowledged immediately to prevent retries.
        """
        import base64

        payload = request.data or {}
        iteration_id = payload.get("iteration_id")
        run_sensitivity = bool(payload.get("sensitivity", False))
        iteration_type_override = payload.get("iteration_type") or None

        is_pubsub = False

        # Handle Pub/Sub push envelope
        if iteration_id is None and "message" in payload:
            is_pubsub = True
            try:
                raw_data = payload["message"].get("data", "")
                message_id = payload["message"].get("messageId", "unknown")
                decoded = base64.b64decode(raw_data).decode("utf-8").strip()
                # Sensitivity messages are JSON: {"iteration_id": ..., "sensitivity": true, "iteration_type": ...}
                # Legacy normalization messages are plain integers
                try:
                    msg_json = json.loads(decoded)
                    iteration_id = int(msg_json["iteration_id"])
                    run_sensitivity = bool(msg_json.get("sensitivity", False))
                    iteration_type_override = msg_json.get("iteration_type") or None
                except (json.JSONDecodeError, KeyError, TypeError):
                    iteration_id = int(decoded)
                _cloud_run_log(
                    "INFO",
                    "[normalisation] PubSub push received message_id=%s iteration_id=%s sensitivity=%s iteration_type=%s",
                    message_id, iteration_id, run_sensitivity, iteration_type_override,
                )
            except Exception:
                _cloud_run_log("WARNING", "[normalisation] PubSub push with undecodable data: %s", payload.get("message", {}).get("data"))
                return Response(
                    {"detail": "Invalid Pub/Sub message: could not decode iteration_id from message.data"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if not iteration_id:
            return Response(
                {"detail": "iteration_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if is_pubsub:
            _cloud_run_log("INFO", "[normalisation] PubSub push received, processing iteration_id=%s synchronously", iteration_id)

        result = self._run_normalisation(iteration_id, run_sensitivity=run_sensitivity, iteration_type_override=iteration_type_override)
        if "error" in result:
            status_code = result.get("status", status.HTTP_500_INTERNAL_SERVER_ERROR)
            if is_pubsub:
                _cloud_run_log(
                    "INFO",
                    "[normalisation] PubSub push processed iteration_id=%s with error, acknowledging to prevent retry",
                    iteration_id,
                )
                return Response({"detail": result["error"], "traceback": result.get("traceback")}, status=status.HTTP_200_OK)
            return Response({"detail": result["error"], "traceback": result.get("traceback")}, status=status_code)

        if is_pubsub:
            _cloud_run_log(
                "INFO",
                "[normalisation] PubSub push processed iteration_id=%s successfully, acknowledging",
                iteration_id,
            )
        return Response(result, status=status.HTTP_200_OK)
