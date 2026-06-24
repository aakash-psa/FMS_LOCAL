from django.db import models
from django.contrib.auth.models import User
import uuid

# Create your models here.
class Project(models.Model):
    # id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    template_link = models.URLField(default=None, null=True, blank=True)
    base_landco_devco_template = models.URLField(default=None, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_projects')
    updated_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='updated_projects')
    is_deleted = models.BooleanField(default=False) 

    def __str__(self):
        return self.name

class UserProjectPermission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_assoc = models.ForeignKey(User, on_delete=models.CASCADE)
    project_assoc = models.ForeignKey(Project, on_delete=models.CASCADE)
    read_access = models.BooleanField(default=False)
    write_access = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_user_project_permissions')
    updated_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='updated_user_project_permissions')

    def __str__(self):
        return f"{self.user_assoc.username} - {self.project_assoc.name} - {self.read_access} - {self.write_access}"
    


class ProjectAsset(models.Model):
    project_assoc = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='assets')
    asset_unique_identifier = models.CharField(max_length=100, null=True, blank=True, help_text="Unique identifier like S2-CE-RI-RU-SF-VIL1-0001")
    asset_name = models.CharField(max_length=255)
    asset_base_file_link = models.URLField(default=None, null=True, blank=True)
    is_hospitality = models.BooleanField(default=False, help_text="True if this asset is a hospitality asset")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_project_assets')
    updated_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='updated_project_assets')
    is_deleted = models.BooleanField(default=False)

    class Meta:
        unique_together = [['project_assoc', 'asset_unique_identifier']]
    
    def __str__(self):
        return f"{self.asset_unique_identifier or self.asset_name} - {self.asset_name}"

class ProjectConsolidationAsset(models.Model):
    project_assoc = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='project_consolidation_assets')
    iteration = models.ForeignKey('Iteration', on_delete=models.CASCADE, related_name='project_consolidation_assets', null=True, blank=True)
    asset_unique_identifier = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['iteration', 'asset_unique_identifier']]
        indexes = [
            models.Index(fields=['project_assoc', 'asset_unique_identifier']),
            models.Index(fields=['iteration', 'asset_unique_identifier']),
        ]

    def __str__(self):
        return f"{self.asset_unique_identifier} ({self.project_assoc.name})"

class UnitIteration_Assetco(models.Model):
    iteration = models.ForeignKey('Iteration', on_delete=models.CASCADE, related_name='asset_units', null=True, blank=True)
    project_asset = models.ForeignKey(ProjectAsset, on_delete=models.CASCADE, related_name='units', null=True, blank=True)
    sno = models.PositiveIntegerField(null=True, blank=True)
    asset_name = models.CharField(max_length=255, null=True, blank=True)
    asset_id = models.CharField(max_length=150, null=True, blank=True)
    asset_address = models.CharField(max_length=255, null=True, blank=True)
    unit_id = models.CharField(max_length=150, null=True, blank=True)
    unit_type = models.CharField(max_length=255, null=True, blank=True)
    sub_unit_type = models.CharField(max_length=255, null=True, blank=True)
    gross_leasable_area = models.FloatField(null=True, blank=True)
    tenant_id = models.CharField(max_length=150, null=True, blank=True)
    tenant_name = models.CharField(max_length=255, null=True, blank=True)
    lease_start_date = models.DateField(null=True, blank=True)
    lease_tenure = models.FloatField(null=True, blank=True)
    rent_free_duration = models.FloatField(null=True, blank=True)
    cash_collection_start_date = models.DateField(null=True, blank=True)
    lease_expiration_date = models.DateField(null=True, blank=True)
    break_option_exercised = models.CharField(max_length=50, null=True, blank=True)
    break_option_date = models.DateField(null=True, blank=True)
    sales_density = models.FloatField(null=True, blank=True)
    second_tenant = models.CharField(max_length=255, null=True, blank=True)
    void_period_months = models.CharField(max_length=50, null=True, blank=True)
    renewal_probability = models.CharField(max_length=50, null=True, blank=True)
    forecast_base_rent = models.FloatField(null=True, blank=True)
    tenant_2_id = models.CharField(max_length=150, null=True, blank=True)
    tenant_2_name = models.CharField(max_length=255, null=True, blank=True)
    tenant_2_lease_start_date = models.DateField(null=True, blank=True)
    tenant_2_lease_tenure = models.FloatField(null=True, blank=True)
    tenant_2_rent_free_duration = models.FloatField(null=True, blank=True)
    tenant_2_cash_collection_start_date = models.DateField(null=True, blank=True)
    tenant_2_lease_expiration_date = models.DateField(null=True, blank=True)
    tenant_2_break_option_exercised = models.CharField(max_length=50, null=True, blank=True)
    tenant_2_break_option_date = models.DateField(null=True, blank=True)
    tenant_2_sales_density = models.FloatField(null=True, blank=True)
    tenant_2_forecast_base_rent = models.FloatField(null=True, blank=True)
    market_rent = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['iteration', 'unit_id']]

    def __str__(self):
        return f"{self.unit_id} ({self.tenant_name or 'no tenant'})"

class Iteration(models.Model):
    ITERATION_TYPE_CHOICES = [
        ('landco_devco', 'LandCo & DevCo'),
        ('assetco', 'AssetCo'),
        ('assetco_consolidated', 'AssetCo Consolidated'),
        ('consolidation', 'Project Consolidation'),
    ]
    
    project_assoc = models.ForeignKey(Project, on_delete=models.CASCADE)
    user_assoc = models.ForeignKey(User, on_delete=models.CASCADE)
    asset_assoc = models.ForeignKey(ProjectAsset, on_delete=models.CASCADE, null=True, blank=True, related_name='iterations')
    name = models.CharField(max_length=255)
    iteration_type = models.CharField(max_length=32, choices=ITERATION_TYPE_CHOICES, null=True, blank=True)
    input_json = models.JSONField()
    output_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False) 

    def __str__(self):
        return self.name

class UserIterationPermission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_assoc = models.ForeignKey(User, on_delete=models.CASCADE, related_name='iteration_permissions')
    iteration_assoc = models.ForeignKey(Iteration, on_delete=models.CASCADE, related_name='user_permissions')
    read_access = models.BooleanField(default=True)
    write_access = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_user_iteration_permissions')
    updated_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='updated_user_iteration_permissions')

    class Meta:
        unique_together = ('user_assoc', 'iteration_assoc')

    def __str__(self):
        return f"{self.user_assoc.username} - {self.iteration_assoc.name} - Read: {self.read_access} - Write: {self.write_access}"

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    azure_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_profile'
    
    def __str__(self):
        return f"{self.user.username} - Profile"

class JvIteration(models.Model):
    iteration_assoc = models.OneToOneField(
        Iteration,
        on_delete=models.CASCADE,
        related_name="jv_iteration",
    )
    name = models.CharField(max_length=255, default="")
    iteration_type = models.CharField(max_length=32, null=True, blank=True)
    output_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ConsolidatedIteration(models.Model):
    iteration_assoc = models.OneToOneField(
        Iteration,
        on_delete=models.CASCADE,
        related_name="consolidated_iteration",
    )
    name = models.CharField(max_length=255, default="")
    iteration_type = models.CharField(max_length=32, null=True, blank=True)
    output_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ConsolidationSourceCombination(models.Model):
    CONSOLIDATION_TYPE_CHOICES = [
        ('assetco_consolidation', 'AssetCo Consolidation'),
        ('jv_consolidation', 'JV Consolidation'),
        ('project_consolidation', 'Project Consolidation'),
    ]

    target_iteration = models.ForeignKey(
        Iteration,
        on_delete=models.CASCADE,
        related_name='source_combinations',
    )
    project_assoc = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='consolidation_source_combinations',
    )
    user_assoc = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='consolidation_source_combinations',
    )
    consolidation_type = models.CharField(max_length=32, choices=CONSOLIDATION_TYPE_CHOICES)
    source_iteration_ids = models.BigIntegerField(null=True, blank=True)
    source_iteration_type = models.CharField(max_length=64, null=True, blank=True)
    source_reference_id = models.BigIntegerField(null=True, blank=True)
    scenario_name = models.CharField(max_length=255, null=True, blank=True)   # ← new
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __init__(self, *args, **kwargs):
        # Backward compatibility for callers still sending legacy keys.
        legacy_reference_id = kwargs.pop('source_reference_ids', None)
        kwargs.pop('source_reference_type', None)
        super().__init__(*args, **kwargs)
        if self.source_reference_id is None and legacy_reference_id is not None:
            try:
                self.source_reference_id = int(legacy_reference_id)
            except (TypeError, ValueError):
                self.source_reference_id = None

    class Meta:
        indexes = [
            models.Index(fields=['target_iteration', 'consolidation_type']),
            models.Index(fields=['project_assoc', 'consolidation_type']),
            models.Index(fields=['user_assoc']),
        ]

    def __str__(self):
        return f"{self.consolidation_type} -> iteration {self.target_iteration_id}"


class DimPeriod(models.Model):
    period_start = models.DateField()
    period_end = models.DateField()
    period_type = models.CharField(max_length=50)

    class Meta:
        db_table = 'dim_period'
        constraints = [
            models.UniqueConstraint(
                fields=["period_start", "period_end", "period_type"],
                name="uq_dim_period_start_end_type",
            ),
        ]

    def __str__(self):
        return f"{self.period_type}: {self.period_start} to {self.period_end}"


class DimDataItem(models.Model):
    module = models.CharField(max_length=100)
    category = models.CharField(max_length=255)
    item = models.CharField(max_length=255)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
        db_column='parent_id',
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'dim_dataitem'
        ordering = ['parent_id', 'display_order', 'id']

    def __str__(self):
        return f"{self.module} | {self.category} | {self.item}"


class DimGlobalDataItem(models.Model):
    category = models.CharField(max_length=255)
    item = models.CharField(max_length=255)

    class Meta:
        db_table = 'dim_globaldataitem'

    def __str__(self):
        return f"{self.category} | {self.item}"


class GlobalInputsIteration(models.Model):
    global_data_item = models.ForeignKey(
        DimGlobalDataItem,
        on_delete=models.PROTECT,
        db_column='globaldataitemid',
        related_name='global_input_iterations'
    )
    value = models.TextField(null=True, blank=True)
    iteration = models.ForeignKey(
        Iteration,
        on_delete=models.CASCADE,
        db_column='iterationid',
        related_name='global_input_iterations'
    )
    module = models.CharField(max_length=100)

    class Meta:
        # db_table = 'globalinputsiterations'
        indexes = [
            models.Index(fields=['iteration']),
            models.Index(fields=['global_data_item']),
            models.Index(fields=['module']),
        ]
    
    
class AssetIteration_Landco(models.Model):
    iteration = models.ForeignKey(
        Iteration,
        on_delete=models.CASCADE,
        related_name="asset_iterations_landco",
    )

    region = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    asset_class = models.CharField(max_length=100)
    sub_category = models.CharField(max_length=100)
    typology = models.CharField(max_length=100)
    construction_phase = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    asset_unique_id = models.CharField(max_length=150)
    asset_name = models.CharField(max_length=255, null=True, blank=True)
    business_model = models.CharField(max_length=100, null=True, blank=True)
    exit_counterparty = models.CharField(max_length=100, null=True, blank=True)
    units = models.FloatField(null=True, blank=True)
    developable_land_area = models.FloatField(null=True, blank=True)
    master_plan_efficiency = models.FloatField(null=True, blank=True)
    gross_land_area = models.FloatField(null=True, blank=True)
    site_coverage_ratio = models.FloatField(null=True, blank=True)
    site_coverage_area = models.FloatField(null=True, blank=True)
    gross_floor_area = models.FloatField(null=True, blank=True)
    built_up_area = models.FloatField(null=True, blank=True)
    floor_plan_efficiency = models.FloatField(null=True, blank=True)
    total_nsa_gla = models.FloatField(null=True, blank=True)
    floor_area_ratio = models.FloatField(null=True, blank=True)
    parking_bays = models.FloatField(null=True, blank=True)

    jvjda_inclusion = models.CharField(max_length=20, null=True, blank=True)
    landco_inclusion = models.CharField(max_length=20, null=True, blank=True)
    venture_type = models.CharField(max_length=100, null=True, blank=True)
    land_bank_override = models.CharField(max_length=20, null=True, blank=True)
    holding_period = models.CharField(max_length=20, null=True, blank=True)
    land_sales_price = models.FloatField(null=True, blank=True)
    land_sales_override = models.CharField(max_length=20, null=True, blank=True)
    land_development = models.CharField(max_length=20, null=True, blank=True)
    vertical_development = models.CharField(max_length=20, null=True, blank=True)
    asset_operations = models.CharField(max_length=20, null=True, blank=True)
    secondary_infrastructure_override = models.CharField(max_length=20, null=True, blank=True)
    secondary_infrastructure_module_construction_start_date = models.DateField(null=True, blank=True)
    primary_infrastructure_module_override = models.CharField(max_length=20, null=True, blank=True)
    primary_infrastructure_module_construction_start_date = models.DateField(null=True, blank=True)
    asset_landco_inclusion = models.CharField(max_length=20, null=True, blank=True)
    asset_order = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ("iteration", "asset_unique_id","region", "city", "asset_class", "sub_category", "typology", "asset_order")
        indexes = [
            models.Index(fields=["iteration"]),
            models.Index(fields=["asset_unique_id"]),
            models.Index(fields=["region", "city"]),
        ]

class AssetIteration_Devco(models.Model):
    iteration = models.ForeignKey(
        Iteration,
        on_delete=models.CASCADE,
        related_name="asset_iterations_devco",
    )

    region = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    asset_class = models.CharField(max_length=100)
    sub_category = models.CharField(max_length=100)
    typology = models.CharField(max_length=100)
    construction_phase = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    asset_unique_id = models.CharField(max_length=150)
    asset_name = models.CharField(max_length=255, null=True, blank=True)
    business_model = models.CharField(max_length=100, null=True, blank=True)
    exit_counterparty = models.CharField(max_length=100, null=True, blank=True)
   
    units = models.FloatField(null=True, blank=True)
    developable_land_area = models.FloatField(null=True, blank=True)
    master_plan_efficiency = models.FloatField(null=True, blank=True)
    gross_land_area = models.FloatField(null=True, blank=True)
    site_coverage_ratio = models.FloatField(null=True, blank=True)
    site_coverage_area = models.FloatField(null=True, blank=True)
    gross_floor_area = models.FloatField(null=True, blank=True)
    built_up_area = models.FloatField(null=True, blank=True)
    floor_plan_efficiency = models.FloatField(null=True, blank=True)
    total_nsa_gla = models.FloatField(null=True, blank=True)
    floor_area_ratio = models.FloatField(null=True, blank=True)
    parking_bays = models.FloatField(null=True, blank=True)

    devco_inclusion = models.CharField(max_length=20, null=True, blank=True)
    jvjda_inclusion = models.CharField(max_length=20, null=True, blank=True)
    venture_type = models.CharField(max_length=100, null=True, blank=True)
    land_bank_override = models.CharField(max_length=20, null=True, blank=True)
    holding_period = models.CharField(max_length=20, null=True, blank=True)
    asset_devco_inclusion = models.CharField(max_length=20, null=True, blank=True)
    sales_override = models.CharField(max_length=20, null=True, blank=True)
    sales_value = models.FloatField(null=True, blank=True)
    asset_order = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ("iteration", "asset_unique_id","region", "city", "asset_class", "sub_category", "typology", "asset_order")
        indexes = [
            models.Index(fields=["iteration"]),
            models.Index(fields=["asset_unique_id"]),
            models.Index(fields=["region", "city"]),
        ]


class NormalisedIteration(models.Model):
    period = models.ForeignKey(
        DimPeriod,
        on_delete=models.PROTECT,
        related_name='normalised_iterations'
    )
    data_item = models.ForeignKey(
        DimDataItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='normalised_iterations'
    )
    value = models.FloatField()
    iteration = models.ForeignKey(
        Iteration,
        on_delete=models.CASCADE,
        related_name='normalised_iterations'
    )
    asset_landco = models.ForeignKey(
        AssetIteration_Landco,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='asset_landco_id',
        related_name='normalised_iterations'
    )
    asset_devco = models.ForeignKey(
        AssetIteration_Devco,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='asset_devco_id',
        related_name='normalised_iterations'
    )
    asset_unit = models.ForeignKey(
        UnitIteration_Assetco,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='asset_unit_id',
        related_name='normalised_iterations'
    )
    asset_project_consolidation = models.ForeignKey(
        'ProjectConsolidationAsset',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='asset_project_consolidation_id',
        related_name='normalised_iterations'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_jv = models.BooleanField(default=False)

    @property
    def asset(self):
        """Compatibility accessor for code paths that expect a single asset reference."""
        return self.asset_landco or self.asset_devco

    class Meta:
        # db_table = 'normalised_iteration'
        indexes = [
            models.Index(fields=['iteration', 'period']),
            models.Index(fields=['data_item']),
            models.Index(fields=['asset_landco']),
            models.Index(fields=['asset_devco']),
            models.Index(fields=['asset_unit']),
            models.Index(fields=['asset_project_consolidation']),
        ]

class InflationProfile(models.Model):
    iteration = models.ForeignKey('Iteration', on_delete=models.CASCADE, related_name='inflation_profiles')
    profile_name = models.CharField(max_length=255)
    year = models.IntegerField()
    value = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('iteration', 'profile_name', 'year')
        indexes = [
            models.Index(fields=['iteration', 'profile_name', 'year']),
        ]

    def __str__(self):
        return f"{self.profile_name} ({self.year}): {self.value}"


class IrrDecomposition(models.Model):
    iteration = models.ForeignKey('Iteration', on_delete=models.CASCADE, related_name='irr_decomposition_rows')
    metric_name = models.CharField(max_length=255)
    value = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('iteration', 'metric_name')
        indexes = [
            models.Index(fields=['iteration', 'metric_name']),
        ]

    def __str__(self):
        return f"{self.metric_name}: {self.value}"


class SensitivityScenario(models.Model):
    """Unique scenario definitions per iteration+module — referenced by SensitivityIteration rows."""
    iteration = models.ForeignKey(
        'Iteration',
        on_delete=models.CASCADE,
        related_name='sensitivity_scenarios',
    )
    module = models.CharField(max_length=50)  # 'landco', 'devco', 'assetco'
    scenario_label = models.CharField(max_length=500)
    scenario_code = models.CharField(max_length=10, blank=True, default='')
    param1 = models.CharField(max_length=255, blank=True, default='')
    param1_pct = models.CharField(max_length=20, blank=True, default='')
    param2 = models.CharField(max_length=255, blank=True, default='')
    param2_pct = models.CharField(max_length=20, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('iteration', 'module', 'scenario_code')
        indexes = [
            models.Index(fields=['iteration', 'module']),
            models.Index(fields=['iteration', 'module', 'scenario_code']),
        ]

    def __str__(self):
        return f"{self.module} | {self.scenario_code} | {self.scenario_label}"


class SensitivityIteration(models.Model):
    iteration = models.ForeignKey(
        'Iteration',
        on_delete=models.CASCADE,
        related_name='sensitivity_iterations',
    )
    module = models.CharField(max_length=50)  # 'landco', 'devco', 'assetco'
    scenario = models.ForeignKey(
        SensitivityScenario,
        on_delete=models.CASCADE,
        related_name='sensitivity_rows',
    )
    asset_landco = models.ForeignKey(
        AssetIteration_Landco,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sensitivity_rows',
    )
    asset_devco = models.ForeignKey(
        AssetIteration_Devco,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sensitivity_rows',
    )
    asset_unit = models.ForeignKey(
        UnitIteration_Assetco,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sensitivity_rows',
    )
    asset_project = models.ForeignKey(
        ProjectAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sensitivity_rows',
    )
    period = models.ForeignKey(
        DimPeriod,
        on_delete=models.PROTECT,
        related_name='sensitivity_iterations',
    )
    value = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['iteration', 'module']),
            models.Index(fields=['scenario']),
            models.Index(fields=['asset_landco']),
            models.Index(fields=['asset_devco']),
            models.Index(fields=['asset_unit']),
            models.Index(fields=['asset_project']),
        ]

    def __str__(self):
        return f"{self.module} | {self.scenario.scenario_code}"


class GoalSeekIteration(models.Model):
    iteration = models.ForeignKey(
        'Iteration',
        on_delete=models.CASCADE,
        related_name='goal_seek_iterations',
    )
    module = models.CharField(max_length=50)  # 'landco', 'devco', 'assetco'
    variable = models.CharField(max_length=255, blank=True, default='')
    target_metric = models.CharField(max_length=255, blank=True, default='')
    target_value = models.FloatField(null=True, blank=True)
    base_metric_value = models.FloatField(null=True, blank=True)
    pct_change_required = models.FloatField(null=True, blank=True)
    achieved_metric_value = models.FloatField(null=True, blank=True)
    metric_error = models.FloatField(null=True, blank=True)
    model_evaluations = models.IntegerField(null=True, blank=True)
    linear_pct_change = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('iteration', 'module')
        indexes = [
            models.Index(fields=['iteration', 'module']),
        ]

    def __str__(self):
        return f"{self.module} | {self.variable} -> {self.target_metric}"

