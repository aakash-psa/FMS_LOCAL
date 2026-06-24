from .admin_apis_urls import urlpatterns as admin_apis_urls
from .addin_apis_urls import urlpatterns as addin_apis_urls

urlpatterns = admin_apis_urls + addin_apis_urls