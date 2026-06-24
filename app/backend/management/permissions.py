from rest_framework.authentication import BaseAuthentication
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import AuthenticationFailed


class MSALAuthentication(BaseAuthentication):
    """
    DRF authentication class that recognizes MSAL token authentication
    validated by the middleware.
    """
    def authenticate(self, request):
        msal_user = getattr(request, 'msal_user', None)
        if msal_user:
            # Return a tuple (user, None) where user is the payload dict
            # This tells DRF the request is authenticated
            return (msal_user, None)
        return None

    def authenticate_header(self, request):
        return 'Bearer'


class IsMSALAuthenticated(BasePermission):
    def has_permission(self, request, view) -> bool:
        return bool(getattr(request, 'msal_user', None))


