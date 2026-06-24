from functools import wraps
from typing import Optional
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth.models import User
from management.models import UserProjectPermission


def _resolve_acting_user(request) -> Optional[User]:
    if hasattr(request, 'user') and isinstance(request.user, User) and request.user.is_authenticated:
        return request.user
    msal_user = getattr(request, 'msal_user', None)
    if msal_user:
        email = msal_user.get('email')
        if email:
            try:
                return User.objects.get(email=email)
            except User.DoesNotExist:
                return None
    return None


def require_project_permission(read: bool = False, write: bool = False):
    """
    Decorator for APIView methods that require project-level permissions.
    Expects URL kwarg `project_id` to be present.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(self, request, *args, **kwargs):
            project_id = kwargs.get('project_id')
            if not project_id:
                return Response({"detail": "project_id is required in URL"}, status=status.HTTP_400_BAD_REQUEST)

            acting_user = _resolve_acting_user(request)
            if not acting_user:
                return Response({"detail": "Authenticated user not found"}, status=status.HTTP_403_FORBIDDEN)

            try:
                perm = UserProjectPermission.objects.get(user_assoc=acting_user, project_assoc_id=project_id)
            except UserProjectPermission.DoesNotExist:
                return Response({"detail": "No permissions for this project"}, status=status.HTTP_403_FORBIDDEN)

            if write and not perm.write_access:
                return Response({"detail": "Write access required"}, status=status.HTTP_403_FORBIDDEN)
            if read and not (perm.read_access or perm.write_access):
                # write implies read; allow if either is present for read
                return Response({"detail": "Read access required"}, status=status.HTTP_403_FORBIDDEN)

            return view_func(self, request, *args, **kwargs)

        return _wrapped
    return decorator


