import jwt
from jwt import PyJWKClient
from typing import Optional, Dict, Any
from django.conf import settings
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.models import AnonymousUser, User


class MSALTokenValidator:
    _jwks_client = None

    @classmethod
    def get_jwks_client(cls):
        if cls._jwks_client is None:
            tenant = settings.AZURE_TENANT_ID
            jwks_uri = f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"
            cls._jwks_client = PyJWKClient(jwks_uri)
        return cls._jwks_client

    @staticmethod
    def validate_token(token: str) -> Dict[str, Any]:
        try:
            jwks_client = MSALTokenValidator.get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            tenant = settings.AZURE_TENANT_ID
            # Allow override via env
            configured_issuer = getattr(settings, 'AZURE_ISSUER', None)
            v2_issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
            v1_issuer = f"https://sts.windows.net/{tenant}/"
            allowed_issuers = {configured_issuer} if configured_issuer else {v2_issuer, v1_issuer}

            audience = getattr(settings, 'AZURE_AUDIENCE', None) or settings.AZURE_CLIENT_ID
            if hasattr(settings, 'AZURE_ALLOWED_AUDIENCES') and settings.AZURE_ALLOWED_AUDIENCES:
                # Comma-separated audiences in settings
                allowed_auds = {a.strip() for a in settings.AZURE_ALLOWED_AUDIENCES.split(',') if a.strip()}
            else:
                allowed_auds = {audience}

            # Verify signature/exp/aud; verify_iss manually after decode to support multiple issuers
            decoded = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=list(allowed_auds),
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
            

            token_iss = decoded.get('iss')
            if token_iss not in allowed_issuers:
                return {'valid': False, 'error': f'Invalid token issuer: {token_iss}', 'error_code': 'INVALID_ISSUER'}

            user_info = {
                'user_id': decoded.get('oid') or decoded.get('sub'),
                'email': decoded.get('preferred_username') or decoded.get('email') or decoded.get('upn'),
                'name': decoded.get('name'),
                'roles': decoded.get('roles', []),
                'tenant_id': decoded.get('tid'),
                'app_id': decoded.get('appid') or decoded.get('azp'),
                'exp': decoded.get('exp'),
                'iat': decoded.get('iat'),
            }

            return {'valid': True, 'payload': user_info, 'raw_token': decoded}

        except jwt.ExpiredSignatureError:
            return {'valid': False, 'error': 'Token has expired', 'error_code': 'TOKEN_EXPIRED'}
        except jwt.InvalidAudienceError:
            return {'valid': False, 'error': 'Invalid token audience', 'error_code': 'INVALID_AUDIENCE'}
        except jwt.InvalidIssuerError:
            return {'valid': False, 'error': 'Invalid token issuer', 'error_code': 'INVALID_ISSUER'}
        except jwt.InvalidSignatureError:
            return {'valid': False, 'error': 'Invalid token signature', 'error_code': 'INVALID_SIGNATURE'}
        except jwt.DecodeError:
            return {'valid': False, 'error': 'Token decode error', 'error_code': 'DECODE_ERROR'}
        except Exception as e:
            return {'valid': False, 'error': f'Token validation failed: {str(e)}', 'error_code': 'VALIDATION_ERROR'}


def _extract_bearer_token(request) -> Optional[str]:
    auth_header = request.META.get('HTTP_AUTHORIZATION') or request.headers.get('Authorization')
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        return None
    return parts[1]


def _get_or_create_user_from_msal(msal_payload: Dict[str, Any]) -> Optional[User]:
    """
    Get or create a Django User from MSAL token payload.
    Uses oid (Object ID) as the primary identifier stored in username.
    """
    oid = msal_payload.get('user_id')  # This is the oid from token
    email = msal_payload.get('email')
    name = msal_payload.get('name', '')
    
    if not oid:
        return None
    
    # Use oid as username (it's a UUID string, should be valid for username)
    # Try to find by username first (where username = oid)
    try:
        user = User.objects.get(username=oid)
        # Update email and name if they've changed
        if email and user.email != email:
            user.email = email
        if name:
            name_parts = name.split(' ', 1)
            if len(name_parts) >= 1:
                user.first_name = name_parts[0]
            if len(name_parts) >= 2:
                user.last_name = name_parts[1]
            user.save()
        return user
    except User.DoesNotExist:
        pass
    
    # If not found by username, try by email
    if email:
        try:
            user = User.objects.get(email=email)
            # Update username to oid if it's different
            if user.username != oid:
                user.username = oid
                user.save()
            # Update name if provided
            if name:
                name_parts = name.split(' ', 1)
                if len(name_parts) >= 1:
                    user.first_name = name_parts[0]
                if len(name_parts) >= 2:
                    user.last_name = name_parts[1]
                user.save()
            return user
        except User.DoesNotExist:
            pass
    
    # Create new user with oid as username
    name_parts = name.split(' ', 1) if name else []
    user = User.objects.create_user(
        username=oid,
        email=email or '',
        first_name=name_parts[0] if len(name_parts) >= 1 else '',
        last_name=name_parts[1] if len(name_parts) >= 2 else '',
    )
    return user


class AzureJWTAuthenticationMiddleware(MiddlewareMixin):
    def process_request(self, request):
        token = _extract_bearer_token(request)
        
        if not token:
            request.msal_user = None
            return None

        result = MSALTokenValidator.validate_token(token)
        if not result.get('valid'):
            request.msal_user = None
            request.msal_error = result
            return None

        payload = result['payload']
        request.msal_user = payload
        request.msal_raw_token = result.get('raw_token')
        
        # Create or get Django User from MSAL payload
        django_user = _get_or_create_user_from_msal(payload)
        if django_user:
            request.user = django_user
        
        return None

