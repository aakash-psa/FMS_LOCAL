from django.urls import path
from management.views.addin_apis_views import (
    UserAssignedProjectsView,
    LandCoOutputFromJsonView,
    LandCoOutputFromJsonSaveView,
    DownloadTemplateView,
    ScenarioListView,
    ScenarioDetailView,
    DEVCoOutputFromJsonView,
    ASSETCoOutputFromJsonView,
    CONSOLIDATEDOutputFromJsonView,
    AssetScenarioListView,
    AssetScenarioDetailView,
    AssetCoSaveIterationView,
    AssetCoConsolidatedSaveIterationView,
    ConsolidationSaveIterationView,
    # DownloadBaseLandcoDevcoTemplateView,
    DownloadAssetBaseFileView,
    UnifiedDownloadFileView,
    UnifiedSaveIterationView,
    ShareIterationView,
    JVScenarioOptionsView,
    ProjectConsolidationScenariosView,
    AllAssetScenariosView,
    AssetConsolidationSaveView,
)


urlpatterns = [
    # Get all assigned projects for authenticated user
    path('user/projects/', UserAssignedProjectsView.as_view(), name='user-assigned-projects'),
    path('project/<int:project_id>/download-base-file/', UnifiedDownloadFileView.as_view(), name='download-base-file'),
    path('project/<int:project_id>/download-template', DownloadTemplateView.as_view(), name='download-template'),
    
    
    # Project-level scenario endpoints (LandCo/DevCo) - GET for backward compatibility, POST for unified access
    path('project/<int:project_id>/scenarios/', ScenarioListView.as_view(), name='scenario-list'),
    path('project/<int:project_id>/scenarios/<int:scenario_id>/', ScenarioDetailView.as_view(), name='scenario-detail'),
    
    # Calculation output endpoints
    path('landco/output-json', LandCoOutputFromJsonView.as_view(), name='landco-output-json'),
    path('devco/output-json', DEVCoOutputFromJsonView.as_view(), name='devco-output-json'),
    path('assetco/output-json', ASSETCoOutputFromJsonView.as_view(), name='assetco-output-json'),
    path('consolidated/output-json', CONSOLIDATEDOutputFromJsonView.as_view(), name='consolidated-output-json'),
    
    # Save iteration endpoints
    path('landco/save-iteration/', LandCoOutputFromJsonSaveView.as_view(), name='landco-save-scenario'),
    path('assetco/save-iteration/', AssetCoSaveIterationView.as_view(), name='assetco-save-iteration'),
    path('assetco-consolidated/save-iteration/', AssetCoConsolidatedSaveIterationView.as_view(), name='assetco-consolidated-save-iteration'),
    path('consolidation/save-iteration/', ConsolidationSaveIterationView.as_view(), name='consolidation-save-iteration'),
    
    # Unified save iteration endpoint (supports all model types)
    path('iteration/save/', UnifiedSaveIterationView.as_view(), name='unified-save-iteration'),
    path('iteration/share/', ShareIterationView.as_view(), name='share-iteration'),
    
    # Asset consolidation endpoints
    path('jv-scenarios/', JVScenarioOptionsView.as_view(), name='jv-scenarios'),
    path('project-consolidation-scenarios/', ProjectConsolidationScenariosView.as_view(), name='project-consolidation-scenarios'),
    path('asset-scenarios/', AllAssetScenariosView.as_view(), name='all-asset-scenarios'),
]
