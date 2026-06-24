from django.urls import path
from management.views.admin_apis_views import UserDetailsView
from management.views.admin_apis_views import (
    ProjectCountView,
    ProjectDetailsView,
    CreateProjectView,
    UploadTemplateView,
    EditProjectView,
    ProjectUsersView,
    AssignUserView,
    EditUserPermissionView,
    DeactivateProjectView,
    ListUsersView,
    ListProjectsView,
    SyncUsersView,
    DatabaseCredentialsView,
    ScenariosView,
    ReportView,
    ScenariosDeleteView,
    ScenariosActivateView,
    ExistingScenariosSaveView,
    ProjectAssetsListView,
    ProjectAssetDetailView,
    ToggleAssetStatusView,
    ProjectAssetUploadBaseFileView,
    UploadProjectBaseLandcoDevcoTemplateView,
    UploadAssetBaseFileView,
    NormalisationView
)
from management.views.addin_apis_views import DownloadAssetBaseFileView

urlpatterns = [
    path('user/me/', UserDetailsView.as_view(), name='user-details'),
    path('project-count', ProjectCountView.as_view(), name='project-count'),
    path('project/project-details/<int:project_id>', ProjectDetailsView.as_view(), name='project-details'),
    path('project/create-project', CreateProjectView.as_view(), name='create-project'),
    path('project/<int:project_id>/upload-template', UploadTemplateView.as_view(), name='upload-template'),
    path('project/<int:project_id>/edit', EditProjectView.as_view(), name='edit-project'),
    path('project/<int:project_id>/users', ProjectUsersView.as_view(), name='project-users'),
    path('project/<int:project_id>/assign-user', AssignUserView.as_view(), name='assign-user'),
    path('project/<int:project_id>/<str:user_id>/edit-user', EditUserPermissionView.as_view(), name='edit-user'),
    path('project/<int:project_id>/deactivate-project', DeactivateProjectView.as_view(), name='deactivate-project'),
    path('users-details', ListUsersView.as_view(), name='list-users'),
    path('project/list', ListProjectsView.as_view(), name='list-projects'),
    path('scenarios/', ScenariosView.as_view(), name='project-scenarios'),
    path('report/', ReportView.as_view(), name='report'),
    path('project/scenario_delete', ScenariosDeleteView.as_view(), name='scenario-delete'),
    path('project/scenario_activate', ScenariosActivateView.as_view(), name='scenario-activate'),
    path('project/scenario_save', ExistingScenariosSaveView.as_view(), name='scenario-save'),
    path('users/sync', SyncUsersView.as_view(), name='sync-users'),
    path('db/creds', DatabaseCredentialsView.as_view(), name='db-creds'),
    
    # Asset Management endpoints
    path('project/<int:project_id>/assets/', ProjectAssetsListView.as_view(), name='asset-list'),
    path('project/<int:project_id>/create-asset/', ProjectAssetsListView.as_view(), name='asset-create'),
    path('project/<int:project_id>/edit-asset/<int:asset_id>/', ProjectAssetDetailView.as_view(), name='asset-detail'),
    path('project/<int:project_id>/assets/<int:asset_id>/toggle-status/', ToggleAssetStatusView.as_view(), name='asset-toggle-status'),
    path('project/<int:project_id>/assets/<int:asset_id>/upload-base-file/', ProjectAssetUploadBaseFileView.as_view(), name='asset-upload-base-file-url'),
    path('project/<int:project_id>/assets/<int:asset_id>/download-base-file/', DownloadAssetBaseFileView.as_view(), name='asset-download-base-file'),
    
    # File Upload endpoints
    path('project/<int:project_id>/assets/<int:asset_id>/upload-asset-base-file/', UploadAssetBaseFileView.as_view(), name='upload-asset-base-file'),
    
    # JSON Normalization endpoint
    path('normalisation/', NormalisationView.as_view(), name='normalisation'),
]
