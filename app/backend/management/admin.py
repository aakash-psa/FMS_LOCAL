from django.contrib import admin
from management.models import Project, UserProjectPermission, Iteration

# Register your models here.
admin.site.register(Project)    
admin.site.register(UserProjectPermission)
admin.site.register(Iteration)