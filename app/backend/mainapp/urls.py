
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('super-admin/', admin.site.urls),
    path('api/admin/', include('management.urls.admin_apis_urls')),
    path('api/addins/', include('management.urls.addin_apis_urls')),
]
