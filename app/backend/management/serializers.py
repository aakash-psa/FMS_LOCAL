from rest_framework import serializers
from django.contrib.auth.models import User
from management.models import Project, UserProjectPermission, Iteration, ProjectAsset


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = [
            'id', 'name', 'template_link', 'base_landco_devco_template', 'created_at', 'updated_at',
            'created_by', 'updated_by', 'is_deleted'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by', 'updated_by']


class ProjectCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['name', 'template_link']


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']


class UserProjectPermissionSerializer(serializers.ModelSerializer):
    user = UserSerializer(source='user_assoc', read_only=True)

    class Meta:
        model = UserProjectPermission
        fields = ['id', 'user', 'read_access', 'write_access', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class AssignUserPermissionSerializer(serializers.Serializer):
    user_id = serializers.CharField(max_length=255)
    read_access = serializers.BooleanField(default=True)
    write_access = serializers.BooleanField(default=False)


class UserSyncItemSerializer(serializers.Serializer):
    user_id = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    display_name = serializers.CharField(max_length=255, required=False, allow_blank=True)


class UserSyncRequestSerializer(serializers.Serializer):
    users = UserSyncItemSerializer(many=True)
    group_id = serializers.CharField(max_length=255, required=False, allow_blank=True)


class ScenarioSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()

    class Meta:
        model = Iteration
        fields = [
            'id',
            'name',
            'project_assoc',
            'project_name',
            'user_assoc',
            'user_name',
            'user_email',
            'input_json',
            'output_json',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_user_name(self, obj):
        if obj.user_assoc:
            return f"{obj.user_assoc.first_name} {obj.user_assoc.last_name}".strip() or obj.user_assoc.username
        return None

    def get_user_email(self, obj):
        return obj.user_assoc.email if obj.user_assoc else None

    def get_project_name(self, obj):
        return obj.project_assoc.name if obj.project_assoc else None


class ProjectAssetSerializer(serializers.ModelSerializer):
    project_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ProjectAsset
        fields = [
            'id',
            'asset_unique_identifier',
            'asset_name',
            'asset_base_file_link',
            'is_hospitality',
            'project_assoc',
            'project_name',
            'is_deleted',
            'created_at',
            'updated_at',
            'created_by',
            'created_by_name',
            'updated_by',
            'updated_by_name'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by', 'updated_by']

    def get_project_name(self, obj):
        return obj.project_assoc.name if obj.project_assoc else None

    def get_created_by_name(self, obj):
        return obj.created_by.username if obj.created_by else None

    def get_updated_by_name(self, obj):
        return obj.updated_by.username if obj.updated_by else None


class ProjectAssetCreateSerializer(serializers.ModelSerializer):
    asset_unique_identifier = serializers.CharField(required=True, max_length=100)
    
    class Meta:
        model = ProjectAsset
        fields = ['asset_unique_identifier', 'asset_name', 'asset_base_file_link', 'is_hospitality']
    
    def validate_asset_unique_identifier(self, value):
        """
        Check that the asset_unique_identifier is unique within the project for non-deleted assets.
        """
        # Get project from context (passed by the view)
        project = self.context.get('project')
        if not project:
            return value
        
        # Check if asset with this identifier exists in this project
        if ProjectAsset.objects.filter(
            project_assoc=project,
            asset_unique_identifier=value,
            is_deleted=False
        ).exists():
            raise serializers.ValidationError(
                f"Asset with identifier '{value}' already exists in this project. Cannot add again."
            )
        return value


class ProjectAssetUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectAsset
        fields = ['asset_unique_identifier', 'asset_name', 'asset_base_file_link', 'is_hospitality', 'is_deleted']
    
    def validate_asset_unique_identifier(self, value):
        """
        Check that the asset_unique_identifier is unique within the project for non-deleted assets,
        excluding the current instance being updated.
        """
        # Get the instance being updated
        instance = self.instance
        if not instance:
            return value
        
        # Get project from the instance
        project = instance.project_assoc
        
        # Check if another asset with this identifier exists in this project (excluding current instance)
        exists = ProjectAsset.objects.filter(
            project_assoc=project,
            asset_unique_identifier=value,
            is_deleted=False
        ).exclude(id=instance.id).exists()
        
        if exists:
            raise serializers.ValidationError(
                f"Asset with identifier '{value}' already exists in this project. Cannot use this identifier."
            )
        return value


# Keep IterationSerializer as alias for backward compatibility (optional)
IterationSerializer = ScenarioSerializer


