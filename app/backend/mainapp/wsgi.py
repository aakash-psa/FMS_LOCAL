"""
WSGI project for mainapp.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/howto/deployment/wsgi/
"""

import os
from django.core.wsgi import get_wsgi_application

target_env = os.environ.get('TARGET_ENV', 'local').lower()
if target_env == 'uat':
    target_env = 'sit'
if target_env not in ('local', 'dev', 'sit', 'prod'):
    target_env = 'local'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', f'mainapp.settings.{target_env}')

application = get_wsgi_application()
