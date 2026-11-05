from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Institution(models.Model):
    """
    Educational institution / university / college campus.
    Enables future multi-college support.
    """
    name = models.CharField(max_length=200, unique=True)
    short_name = models.CharField(max_length=50, blank=True)
    slug = models.SlugField(max_length=100, unique=True)
    domain = models.CharField(
        max_length=100,
        blank=True,
        help_text="Campus email domain, e.g., 'campus.edu'"
    )
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    custom_domain = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
        help_text="Custom institution domain, e.g., 'lostfound.ait.edu'"
    )
    logo = models.ImageField(upload_to='institution_logos/', blank=True, null=True)
    logo_url = models.URLField(blank=True, help_text="External or fallback logo URL")
    primary_color = models.CharField(max_length=20, default="#1e3a8a", help_text="Primary branding color (Hex)")
    secondary_color = models.CharField(max_length=20, default="#3b82f6", help_text="Secondary branding color (Hex)")
    welcome_message = models.TextField(blank=True, default="Welcome to CampusCare Lost & Found")
    allowed_email_domains = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Comma-separated allowed student/staff email domains, e.g. 'ait.edu,alumni.ait.edu'"
    )
    erp_api_key = models.CharField(max_length=64, blank=True, null=True, unique=True)
    erp_webhook_url = models.URLField(blank=True)
    is_federated_search_enabled = models.BooleanField(
        default=True,
        help_text="Allow students to participate in cross-campus search"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.short_name or self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.short_name})" if self.short_name else self.name

    def active_subscription(self):
        """Returns the active subscription or None."""
        if hasattr(self, 'subscription') and self.subscription.is_valid:
            return self.subscription
        return None

    def has_feature(self, feature_code: str) -> bool:
        """Checks if the institution's plan grants the requested feature."""
        sub = self.active_subscription()
        if sub and sub.plan:
            return getattr(sub.plan, f"{feature_code}_enabled", False)
        # Fallback to default Free plan capabilities
        default_plan = SubscriptionPlan.get_default_plan()
        return getattr(default_plan, f"{feature_code}_enabled", False)

    def can_add_item(self) -> bool:
        """Checks if active item count is within plan limits."""
        sub = self.active_subscription()
        max_items = sub.plan.max_active_items if sub and sub.plan else 50
        active_count = self.items.filter(status__in=['open', 'pending_verification', 'claimed']).count()
        return active_count < max_items


class Department(models.Model):
    """
    Academic or administrative department within an institution.
    """
    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name='departments'
    )
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        unique_together = ('institution', 'code')

    def __str__(self):
        return f"{self.name} ({self.code})"


class CampusLocation(models.Model):
    """
    Specific campus physical location (e.g., Library, Cafeteria, Sports Complex).
    """
    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name='locations'
    )
    name = models.CharField(max_length=150)
    building = models.CharField(max_length=100)
    floor = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    latitude = models.FloatField(
        null=True,
        blank=True,
        help_text="Approved campus GPS latitude for heatmap visualization"
    )
    longitude = models.FloatField(
        null=True,
        blank=True,
        help_text="Approved campus GPS longitude for heatmap visualization"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['building', 'name']

    def __str__(self):
        parts = [self.name]
        if self.building:
            parts.append(f"[{self.building}]")
        if self.floor:
            parts.append(f"({self.floor})")
        return " ".join(parts)


class Category(models.Model):
    """
    Categories for lost and found items (e.g., Electronics, Documents, Keys).
    Allows institution-specific or global (institution=null) categories.
    """
    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='categories',
        help_text="Leave blank for global categories available to all institutions."
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    icon = models.CharField(
        max_length=50,
        default='fa-box',
        help_text="FontAwesome or Lucide icon name, e.g. fa-laptop, fa-id-card, fa-key"
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# --------------------------------------------------------------------------
# STEP 4: AUDIT LOGGING & SECURITY ALERTS
# --------------------------------------------------------------------------

class AuditLog(models.Model):
    """
    Immutable audit trail recording significant administrative, moderation,
    security, and data change events.
    Enforces that logs cannot be edited or deleted once written.
    Protects privacy: never stores passwords, OTPs, or private answers.
    """
    ACTION_CLAIM_DECISION = 'claim_decision'
    ACTION_ITEM_STATUS = 'item_status'
    ACTION_ITEM_ARCHIVE = 'item_archive'
    ACTION_REWARD_ADJUST = 'reward_adjust'
    ACTION_USER_STATUS = 'user_status'
    ACTION_USER_ROLE = 'user_role'
    ACTION_LOCATION_MODIFY = 'location_modify'
    ACTION_CATEGORY_MODIFY = 'category_modify'
    ACTION_SECURITY_ALERT = 'security_alert'
    ACTION_EXPORT_DATA = 'export_data'

    ACTION_CHOICES = [
        (ACTION_CLAIM_DECISION, 'Claim Moderation Decision'),
        (ACTION_ITEM_STATUS, 'Item Status Transition'),
        (ACTION_ITEM_ARCHIVE, 'Item Report Archived'),
        (ACTION_REWARD_ADJUST, 'Reward Points Adjustment'),
        (ACTION_USER_STATUS, 'User Activation/Deactivation'),
        (ACTION_USER_ROLE, 'User Role Update'),
        (ACTION_LOCATION_MODIFY, 'Campus Location Modification'),
        (ACTION_CATEGORY_MODIFY, 'Category Modification'),
        (ACTION_SECURITY_ALERT, 'Security Alert Resolution'),
        (ACTION_EXPORT_DATA, 'Report / Data Export'),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    target_model = models.CharField(max_length=50, blank=True)
    target_object_id = models.CharField(max_length=50, blank=True)
    target_repr = models.CharField(max_length=200, blank=True)
    institution = models.ForeignKey(
        Institution,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Safe metadata. Passwords, OTPs, and private verification answers are forbidden."
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['target_model', 'target_object_id']),
            models.Index(fields=['timestamp']),
        ]

    def __str__(self):
        actor_name = self.actor.username if self.actor else "System"
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] {actor_name} -> {self.get_action_display()} on {self.target_repr}"

    def clean(self):
        if self.pk is not None:
            raise ValidationError("Audit log records are immutable and cannot be updated.")

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Audit log records are immutable and cannot be updated.")

        # Sanitization: Ensure sensitive data is never persisted
        forbidden_substrings = {'password', 'otp', 'salt', 'token', 'secret', 'verification_answers'}
        if isinstance(self.details, dict):
            clean_details = {}
            for k, v in self.details.items():
                if any(f in k.lower() for f in forbidden_substrings):
                    clean_details[k] = "[REDACTED_SECURITY_DATA]"
                else:
                    clean_details[k] = v
            self.details = clean_details

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit log records are protected and cannot be deleted.")


class SecurityAlert(models.Model):
    """
    Centralized security monitoring alerts for suspicious claims, repeated report velocities,
    abusive messages, failed OTP handover lockouts, and unauthorized privilege escalation.
    Allows campus staff to review alerts without automatically banning students.
    """
    ALERT_SUSPICIOUS_CLAIM = 'suspicious_claim'
    ALERT_REPEATED_REPORTS = 'repeated_reports'
    ALERT_MESSAGE_ABUSE = 'message_abuse'
    ALERT_FAILED_OTP = 'failed_otp'
    ALERT_ACCESS_ANOMALY = 'access_anomaly'

    ALERT_TYPE_CHOICES = [
        (ALERT_SUSPICIOUS_CLAIM, 'Suspicious Ownership Claim'),
        (ALERT_REPEATED_REPORTS, 'Repeated Report Velocity / Anomaly'),
        (ALERT_MESSAGE_ABUSE, 'Abuse Report in Anonymous Chat'),
        (ALERT_FAILED_OTP, 'Failed OTP Handover Lockout'),
        (ALERT_ACCESS_ANOMALY, 'Unauthorized Access / Escalation Attempt'),
    ]

    SEVERITY_LOW = 'low'
    SEVERITY_MEDIUM = 'medium'
    SEVERITY_HIGH = 'high'
    SEVERITY_CRITICAL = 'critical'

    SEVERITY_CHOICES = [
        (SEVERITY_LOW, 'Low Severity'),
        (SEVERITY_MEDIUM, 'Medium Severity'),
        (SEVERITY_HIGH, 'High Severity'),
        (SEVERITY_CRITICAL, 'Critical Risk'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_REVIEWED = 'reviewed'
    STATUS_DISMISSED = 'dismissed'
    STATUS_RESOLVED = 'resolved'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Review'),
        (STATUS_REVIEWED, 'Under Active Investigation'),
        (STATUS_DISMISSED, 'Dismissed (False Positive)'),
        (STATUS_RESOLVED, 'Resolved / Action Taken'),
    ]

    alert_type = models.CharField(max_length=30, choices=ALERT_TYPE_CHOICES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default=SEVERITY_MEDIUM)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    title = models.CharField(max_length=200)
    description = models.TextField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_alerts'
    )
    institution = models.ForeignKey(
        Institution,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_alerts'
    )
    item = models.ForeignKey(
        'items.Item',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_alerts'
    )
    claim = models.ForeignKey(
        'items.Claim',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_alerts'
    )
    handover = models.ForeignKey(
        'items.Handover',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_alerts'
    )
    message = models.ForeignKey(
        'items.ConversationMessage',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_alerts'
    )
    details = models.JSONField(default=dict, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_security_alerts'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['alert_type', 'status']),
            models.Index(fields=['severity', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.title} ({self.get_status_display()})"


# --------------------------------------------------------------------------
# STEP 5: SUBSCRIPTIONS, PAYMENTS, NOTIFICATION PACKAGES & ERP
# --------------------------------------------------------------------------

class SubscriptionPlan(models.Model):
    """
    Tiered subscription plan for institutions (Free, Pro, Enterprise).
    Controls feature gating, active item limits, and staff seat allocations.
    """
    PLAN_FREE = 'free'
    PLAN_PRO = 'pro'
    PLAN_ENTERPRISE = 'enterprise'

    PLAN_CHOICES = [
        (PLAN_FREE, 'Campus Starter (Free)'),
        (PLAN_PRO, 'College Professional'),
        (PLAN_ENTERPRISE, 'University Enterprise'),
    ]

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=30, choices=PLAN_CHOICES, unique=True)
    description = models.TextField(blank=True)
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    price_annual = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    max_active_items = models.PositiveIntegerField(default=50, help_text="Maximum simultaneous active lost/found items")
    max_staff_accounts = models.PositiveIntegerField(default=2, help_text="Maximum staff/security seats")

    # Feature Toggles
    ai_chatbot_enabled = models.BooleanField(default=True)
    predictive_analytics_enabled = models.BooleanField(default=False)
    custom_domain_enabled = models.BooleanField(default=False)
    erp_integration_enabled = models.BooleanField(default=False)
    sms_whatsapp_notifications_enabled = models.BooleanField(default=False)
    priority_support = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['price_monthly']

    def __str__(self):
        return f"{self.name} (₹{self.price_monthly}/mo)"

    @classmethod
    def get_default_plan(cls):
        """Returns or creates the default Free tier plan."""
        plan, _ = cls.objects.get_or_create(
            code=cls.PLAN_FREE,
            defaults={
                'name': 'Campus Starter (Free)',
                'description': 'Essential Lost & Found capabilities for campus communities.',
                'price_monthly': 0.00,
                'price_annual': 0.00,
                'max_active_items': 50,
                'max_staff_accounts': 2,
                'ai_chatbot_enabled': True,
                'predictive_analytics_enabled': False,
                'custom_domain_enabled': False,
                'erp_integration_enabled': False,
                'sms_whatsapp_notifications_enabled': False,
                'priority_support': False,
                'is_active': True,
            }
        )
        return plan


class InstitutionSubscription(models.Model):
    """
    Active subscription record linking an institution to its purchased tier.
    """
    STATUS_ACTIVE = 'active'
    STATUS_TRIALING = 'trialing'
    STATUS_PAST_DUE = 'past_due'
    STATUS_CANCELED = 'canceled'
    STATUS_EXPIRED = 'expired'

    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_TRIALING, 'Trial Period'),
        (STATUS_PAST_DUE, 'Past Due / Payment Required'),
        (STATUS_CANCELED, 'Canceled'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    CYCLE_MONTHLY = 'monthly'
    CYCLE_ANNUAL = 'annual'
    CYCLE_CHOICES = [
        (CYCLE_MONTHLY, 'Monthly'),
        (CYCLE_ANNUAL, 'Annual'),
    ]

    institution = models.OneToOneField(
        Institution,
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name='subscriptions'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    billing_cycle = models.CharField(max_length=20, choices=CYCLE_CHOICES, default=CYCLE_MONTHLY)
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField()
    auto_renew = models.BooleanField(default=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.institution.name} — {self.plan.name} ({self.get_status_display()})"

    @property
    def is_valid(self):
        return self.status in [self.STATUS_ACTIVE, self.STATUS_TRIALING] and (
            self.current_period_end is None or self.current_period_end >= timezone.now()
        )


class PaymentTransaction(models.Model):
    """
    Financial ledger recording gateway transactions with HMAC validation and idempotency.
    Strictly forbids storing raw credit card details or CVVs.
    """
    STATUS_PENDING = 'pending'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_REFUNDED = 'refunded'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_REFUNDED, 'Refunded'),
    ]

    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    subscription = models.ForeignKey(
        InstitutionSubscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions'
    )
    transaction_id = models.CharField(max_length=100, unique=True, db_index=True)
    gateway = models.CharField(max_length=30, default='razorpay')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default='INR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    idempotency_key = models.CharField(max_length=120, blank=True, db_index=True)
    invoice_number = models.CharField(max_length=50, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.gateway.upper()}] {self.transaction_id} — {self.currency} {self.amount} ({self.status})"


class NotificationPackage(models.Model):
    """
    Prepaid SMS and WhatsApp dispatch credits for high-volume campus notification bursts.
    """
    TYPE_SMS = 'sms'
    TYPE_WHATSAPP = 'whatsapp'
    TYPE_CHOICES = [
        (TYPE_SMS, 'SMS Notification Pack'),
        (TYPE_WHATSAPP, 'WhatsApp Cloud Pack'),
    ]

    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name='notification_packages'
    )
    package_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_SMS)
    credits_purchased = models.PositiveIntegerField(default=500)
    credits_remaining = models.PositiveIntegerField(default=500)
    cost = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    purchased_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.institution.short_name or self.institution.name} — {self.get_package_type_display()} ({self.credits_remaining}/{self.credits_purchased} left)"


class NotificationUsageLog(models.Model):
    """
    Audit ledger tracking dispatched notifications, ensuring consent compliance
    and quota accounting without storing unmasked personal numbers.
    """
    institution = models.ForeignKey(
        Institution,
        on_delete=models.CASCADE,
        related_name='notification_usage_logs'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notification_logs'
    )
    notification_type = models.CharField(max_length=20, choices=NotificationPackage.TYPE_CHOICES)
    recipient_masked = models.CharField(max_length=60, help_text="Masked phone or contact endpoint, e.g. +91 98*** **321")
    purpose = models.CharField(max_length=100, help_text="e.g. claim_approval, handover_otp, security_alert")
    consent_verified = models.BooleanField(default=True)
    status = models.CharField(max_length=20, default='sent')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.notification_type.upper()}] To {self.recipient_masked} ({self.purpose})"


