import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Item(models.Model):
    REPORT_TYPE_LOST = 'lost'
    REPORT_TYPE_FOUND = 'found'
    REPORT_TYPE_CHOICES = [
        (REPORT_TYPE_LOST, 'Lost Item'),
        (REPORT_TYPE_FOUND, 'Found Item'),
    ]

    STATUS_OPEN = 'open'
    STATUS_PENDING = 'pending_verification'
    STATUS_CLAIMED = 'claimed'
    STATUS_RETURNED = 'returned'
    STATUS_EXPIRED = 'expired'
    STATUS_CLOSED = 'closed'
    STATUS_ARCHIVED = 'archived'

    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open / Active'),
        (STATUS_PENDING, 'Under Review / Verification'),
        (STATUS_CLAIMED, 'Claimed'),
        (STATUS_RETURNED, 'Returned to Owner'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_CLOSED, 'Closed / Cancelled'),
        (STATUS_ARCHIVED, 'Archived'),
    ]

    CONTACT_EMAIL = 'email'
    CONTACT_PHONE = 'phone'
    CONTACT_BOTH = 'both'
    CONTACT_CAMPUS_DESK = 'campus_desk'

    CONTACT_PREFERENCE_CHOICES = [
        (CONTACT_EMAIL, 'Email Only'),
        (CONTACT_PHONE, 'Phone Only'),
        (CONTACT_BOTH, 'Both Email & Phone'),
        (CONTACT_CAMPUS_DESK, 'Campus Lost & Found Desk (Private - No Personal Info Shown)'),
    ]

    PRIORITY_CRITICAL = 'critical'
    PRIORITY_HIGH = 'high'
    PRIORITY_MEDIUM = 'medium'
    PRIORITY_LOW = 'low'

    PRIORITY_CHOICES = [
        (PRIORITY_CRITICAL, 'Critical'),
        (PRIORITY_HIGH, 'High'),
        (PRIORITY_MEDIUM, 'Medium'),
        (PRIORITY_LOW, 'Low'),
    ]

    PRIORITY_EXPLANATIONS = {
        PRIORITY_CRITICAL: 'Emergency or life-critical item (e.g. prescription medicines, medical device, primary home/vehicle emergency keys). Requires immediate campus broadcast.',
        PRIORITY_HIGH: 'Urgent high-value item or sensitive ID (e.g. mobile phone, laptop, wallet, government ID card, passport). High risk of loss or unauthorized misuse.',
        PRIORITY_MEDIUM: 'Standard valuable personal belonging (e.g. backpacks, textbooks, branded jackets, calculators, watches). Standard campus recovery process.',
        PRIORITY_LOW: 'Common everyday utility item (e.g. water bottles, stationery, umbrellas, notebooks). Non-urgent item.',
    }

    item_code = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
        help_text="Unique item tracking code for item tag identification (e.g. CC-2026-A1B2C3)"
    )
    institution = models.ForeignKey(
        'core.Institution',
        on_delete=models.CASCADE,
        related_name='items'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reported_items'
    )
    report_type = models.CharField(
        max_length=10,
        choices=REPORT_TYPE_CHOICES,
        default=REPORT_TYPE_LOST
    )
    title = models.CharField(max_length=200)
    description = models.TextField(
        help_text="Detailed description of the item including brand, color, distinguishing marks."
    )
    category = models.ForeignKey(
        'core.Category',
        on_delete=models.PROTECT,
        related_name='items'
    )
    location = models.ForeignKey(
        'core.CampusLocation',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='items'
    )
    location_details = models.CharField(
        max_length=255,
        blank=True,
        help_text="Specific spot, bench, classroom number, etc."
    )
    date_lost_or_found = models.DateField(
        help_text="Date when the item was lost or found"
    )
    image = models.ImageField(
        upload_to='item_images/%Y/%m/',
        blank=True,
        null=True,
        help_text="Clear photo of the item (max 5MB, JPG/PNG/WEBP)"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN
    )
    priority = models.CharField(
        max_length=15,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_MEDIUM,
        help_text="Set the priority according to the importance and urgency of this item."
    )
    contact_preference = models.CharField(
        max_length=20,
        choices=CONTACT_PREFERENCE_CHOICES,
        default=CONTACT_EMAIL
    )
    contact_phone = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional custom contact phone number"
    )
    contact_email = models.EmailField(
        blank=True,
        help_text="Optional custom contact email address"
    )
    verification_questions = models.JSONField(
        default=list,
        blank=True,
        help_text="List of private questions for ownership verification (e.g. ['What color is the inside pouch?'])"
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Date after which this report automatically expires if unresolved"
    )
    is_cross_campus_visible = models.BooleanField(
        default=False,
        help_text="Allow students from participating campuses to search this item in federated search"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['report_type', 'status']),
            models.Index(fields=['institution', 'status']),
            models.Index(fields=['category', 'status']),
            models.Index(fields=['item_code']),
            models.Index(fields=['priority']),
            models.Index(fields=['report_type', 'priority']),
        ]

    def __str__(self):
        return f"[{self.get_report_type_display()}] {self.title} ({self.get_status_display()})"

    @property
    def priority_meta(self):
        """Returns visual styling metadata and human-readable explanation."""
        from .services.priority_service import PriorityService
        return PriorityService.get_priority_meta(self.priority)

    @classmethod
    def suggest_priority(cls, title: str, category_name: str = "") -> str:
        """Heuristic smart priority suggestion without forcing."""
        from .services.priority_service import PriorityService
        return PriorityService.suggest_priority(title, category_name)

    @property
    def is_active(self):
        if self.status != self.STATUS_OPEN:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True

    def calculate_expiration_days(self):
        """Determine expiration days from ExpirationRule or settings."""
        rule = ExpirationRule.objects.filter(
            is_active=True,
            institution=self.institution,
            category=self.category,
            report_type__in=[self.report_type, 'all']
        ).first()

        if not rule:
            rule = ExpirationRule.objects.filter(
                is_active=True,
                institution=self.institution,
                category__isnull=True,
                report_type__in=[self.report_type, 'all']
            ).first()

        if not rule:
            rule = ExpirationRule.objects.filter(
                is_active=True,
                institution__isnull=True,
                category__isnull=True,
                report_type__in=[self.report_type, 'all']
            ).first()

        if rule:
            return rule.days_to_expire

        return getattr(settings, 'DEFAULT_ITEM_EXPIRATION_DAYS', 30)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_status = None
        if not is_new:
            try:
                old_status = Item.objects.get(pk=self.pk).status
            except Item.DoesNotExist:
                pass

        # Populate unique item tracking code if not set
        if not self.item_code:
            year = timezone.now().year
            rand_code = uuid.uuid4().hex[:6].upper()
            self.item_code = f"CC-{year}-{rand_code}"

        if not self.contact_email and self.user and self.user.email:
            self.contact_email = self.user.email
        if not self.contact_phone and self.user and hasattr(self.user, 'phone_number') and self.user.phone_number:
            self.contact_phone = self.user.phone_number

        if not self.expires_at:
            days = self.calculate_expiration_days()
            self.expires_at = timezone.now() + timedelta(days=days)

        super().save(*args, **kwargs)

        if is_new:
            ItemStatusHistory.objects.create(
                item=self,
                changed_by=self.user,
                old_status='',
                new_status=self.status,
                remarks=f"Report created as '{self.get_report_type_display()}'"
            )
        elif old_status and old_status != self.status:
            pass

    def can_edit(self, user):
        if not user or not user.is_authenticated:
            return False
        if user == self.user:
            return True
        return getattr(user, 'is_staff_member', False)

    def can_delete(self, user):
        if not user or not user.is_authenticated:
            return False
        if user == self.user:
            return True
        return getattr(user, 'is_staff_member', False)

    def can_view_contact(self, user):
        """Never expose private contact details publicly."""
        if self.contact_preference == self.CONTACT_CAMPUS_DESK:
            return False
        if not user or not user.is_authenticated:
            return False
        return True


class ItemStatusHistory(models.Model):
    """Maintains an audit trail / history of item status transitions."""
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='history'
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='status_changes'
    )
    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.item.title}: {self.old_status or 'New'} -> {self.new_status}"


class ExpirationRule(models.Model):
    """Configurable rules to automatically expire items."""
    institution = models.ForeignKey(
        'core.Institution',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='expiration_rules',
        help_text="Leave blank to apply rule globally to all institutions"
    )
    category = models.ForeignKey(
        'core.Category',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expiration_rules',
        help_text="Leave blank to apply rule to all categories"
    )
    report_type = models.CharField(
        max_length=10,
        choices=[('all', 'All Reports'), ('lost', 'Lost Items'), ('found', 'Found Items')],
        default='all'
    )
    days_to_expire = models.PositiveIntegerField(
        default=30,
        help_text="Number of days before an unresolved item transitions to expired"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        inst_label = self.institution.short_name if self.institution else "Global"
        cat_label = self.category.name if self.category else "All Categories"
        return f"[{inst_label}] {cat_label} ({self.get_report_type_display()}): {self.days_to_expire} days"


class ItemMatch(models.Model):
    """
    Suggested match between a lost report and a found report with
    explainable weighted scores.
    """
    STATUS_SUGGESTED = 'suggested'
    STATUS_DISMISSED = 'dismissed'
    STATUS_CONFIRMED = 'confirmed'

    STATUS_CHOICES = [
        (STATUS_SUGGESTED, 'Suggested Match'),
        (STATUS_DISMISSED, 'Dismissed by User'),
        (STATUS_CONFIRMED, 'Confirmed Match'),
    ]

    source_item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='source_matches'
    )
    matched_item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='target_matches'
    )
    score = models.FloatField(help_text="Composite similarity score (0.0 - 100.0)")
    category_score = models.FloatField(default=0.0)
    text_score = models.FloatField(default=0.0)
    location_score = models.FloatField(default=0.0)
    date_score = models.FloatField(default=0.0)
    image_score = models.FloatField(default=0.0)
    reasons = models.JSONField(
        default=list,
        blank=True,
        help_text="Explainable breakdown bullets for users and administrators"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_SUGGESTED
    )
    dismissed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dismissed_matches'
    )
    dismissed_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-score', '-created_at']
        unique_together = ('source_item', 'matched_item')
        indexes = [
            models.Index(fields=['source_item', 'status']),
            models.Index(fields=['matched_item', 'status']),
        ]

    def __str__(self):
        return f"Match ({self.score:.1f}%): #{self.source_item_id} <-> #{self.matched_item_id}"


class Claim(models.Model):
    """
    Ownership verification claim for a found item with private identifying
    details and fraud risk indicators.
    """
    STATUS_PENDING = 'pending'
    STATUS_UNDER_REVIEW = 'under_review'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_WITHDRAWN = 'withdrawn'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending Review'),
        (STATUS_UNDER_REVIEW, 'Under Active Review'),
        (STATUS_APPROVED, 'Approved (Ownership Verified)'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_WITHDRAWN, 'Withdrawn by Claimant'),
    ]

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='claims'
    )
    claimant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='claims'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING
    )
    identifying_details = models.TextField(
        help_text="Private details only the true owner would know (contents, unique marks, lockscreen, etc.)"
    )
    verification_answers = models.JSONField(
        default=dict,
        blank=True,
        help_text="Private answers to item-specific verification questions"
    )
    proof_image = models.ImageField(
        upload_to='claim_proofs/%Y/%m/',
        blank=True,
        null=True,
        help_text="Optional proof photo, receipt, or original photo with the item"
    )
    admin_notes = models.TextField(
        blank=True,
        help_text="Internal notes for campus staff/administrators reviewing this claim"
    )
    decision_reason = models.TextField(
        blank=True,
        help_text="Explanation provided to claimant upon approval or rejection"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_claims'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    fraud_risk_score = models.IntegerField(
        default=0,
        help_text="Calculated risk score 0-100 based on claim velocity, duplicate text, and history"
    )
    fraud_risk_flags = models.JSONField(
        default=list,
        blank=True,
        help_text="Explainable risk indicator tags and reasons"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['item', 'status']),
            models.Index(fields=['claimant', 'status']),
        ]

    def clean(self):
        super().clean()

        if hasattr(self, 'item') and hasattr(self, 'claimant'):
            if self.item.user == self.claimant:
                raise ValidationError("You cannot submit an ownership claim for an item you reported yourself.")

            if self.claimant.institution and self.item.institution:
                if self.claimant.institution != self.item.institution:
                    raise ValidationError("You cannot claim an item belonging to a different campus institution.")

        if not self.pk and hasattr(self, 'item') and hasattr(self, 'claimant'):
            active_claims = Claim.objects.filter(
                item=self.item,
                claimant=self.claimant,
                status__in=[self.STATUS_PENDING, self.STATUS_UNDER_REVIEW]
            )
            if active_claims.exists():
                raise ValidationError("You already have an active pending claim for this item.")

        if self.status == self.STATUS_APPROVED and hasattr(self, 'item'):
            conflicting = Claim.objects.filter(
                item=self.item,
                status=self.STATUS_APPROVED
            )
            if self.pk:
                conflicting = conflicting.exclude(pk=self.pk)
            if conflicting.exists():
                raise ValidationError(
                    f"Conflict: Claim #{conflicting.first().pk} is already approved for this item. "
                    "Only one approved owner claim is permitted. Revoke or reject the other claim first."
                )

    def save(self, *args, **kwargs):
        self.clean()
        is_new = self.pk is None
        old_status = None
        if not is_new:
            try:
                old_status = Claim.objects.get(pk=self.pk).status
            except Claim.DoesNotExist:
                pass

        super().save(*args, **kwargs)

        if is_new:
            ClaimStatusHistory.objects.create(
                claim=self,
                changed_by=self.claimant,
                old_status='',
                new_status=self.status,
                reason="Ownership claim submitted by claimant."
            )
        elif old_status and old_status != self.status:
            ClaimStatusHistory.objects.create(
                claim=self,
                changed_by=self.reviewed_by,
                old_status=old_status,
                new_status=self.status,
                reason=self.decision_reason or f"Status changed to {self.get_status_display()}"
            )

    def can_view_private_answers(self, user):
        """Never display verification answers publicly."""
        if not user or not user.is_authenticated:
            return False
        if user == self.claimant:
            return True
        return getattr(user, 'is_staff_member', False)

    def can_review(self, user):
        if not user or not user.is_authenticated:
            return False
        return getattr(user, 'is_staff_member', False)

    def can_withdraw(self, user):
        if not user or not user.is_authenticated:
            return False
        if user == self.claimant and self.status in [self.STATUS_PENDING, self.STATUS_UNDER_REVIEW]:
            return True
        return False


class ClaimStatusHistory(models.Model):
    """Maintains an audit trail of ownership claim status transitions."""
    claim = models.ForeignKey(
        Claim,
        on_delete=models.CASCADE,
        related_name='history'
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='claim_status_changes'
    )
    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Claim #{self.claim.pk}: {self.old_status or 'New'} -> {self.new_status}"


# --------------------------------------------------------------------------
# STEP 3: RECOVERY, HANDOVER, RECEIPTS, MESSAGING & REWARDS
# --------------------------------------------------------------------------

class Handover(models.Model):
    """
    Represents the secure physical recovery handover between claimant and item holder.
    Uses salted hashing for OTP storage and limits verification attempts.
    """
    STATUS_INITIATED = 'initiated'
    STATUS_VERIFIED = 'verified'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_INITIATED, 'Handover Initiated (OTP Active)'),
        (STATUS_VERIFIED, 'Verified & Recovered'),
        (STATUS_FAILED, 'Failed (Max Attempts Exceeded)'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    claim = models.OneToOneField(
        Claim,
        on_delete=models.CASCADE,
        related_name='handover'
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='handovers'
    )
    claimant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_handovers'
    )
    held_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='released_handovers'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_INITIATED
    )
    otp_hash = models.CharField(max_length=128, help_text="Salted SHA-256 hash of the 6-digit OTP")
    otp_salt = models.CharField(max_length=32)
    otp_expires_at = models.DateTimeField()
    attempts_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    verified_at = models.DateTimeField(null=True, blank=True)
    handover_location = models.CharField(
        max_length=150,
        default="Campus Lost & Found Desk - Student Affairs",
        help_text="Designated safe campus location for physical exchange"
    )
    handover_notes = models.TextField(blank=True)
    initiated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-initiated_at']

    def __str__(self):
        return f"Handover for Claim #{self.claim_id} ({self.get_status_display()})"

    @classmethod
    def _hash_otp(cls, raw_otp, salt):
        return hashlib.sha256(f"{salt}{raw_otp}".encode()).hexdigest()

    def generate_otp(self, expiry_minutes=30):
        """
        Generates a secure cryptographically random 6-digit OTP,
        salts & hashes it, and returns the raw OTP to be shown to claimant.
        """
        raw_otp = f"{secrets.randbelow(900000) + 100000}"
        self.otp_salt = secrets.token_hex(16)
        self.otp_hash = self._hash_otp(raw_otp, self.otp_salt)
        self.otp_expires_at = timezone.now() + timedelta(minutes=expiry_minutes)
        self.attempts_count = 0
        self.status = self.STATUS_INITIATED
        return raw_otp

    def verify_otp(self, entered_otp):
        """
        Server-side OTP verification with strict attempt limits and expiration checks.
        Returns: (success: bool, message: str)
        """
        if self.status != self.STATUS_INITIATED:
            return False, f"Handover is already {self.get_status_display()}."

        if self.attempts_count >= self.max_attempts:
            self.status = self.STATUS_FAILED
            self.save(update_fields=['status', 'updated_at'])
            return False, "Maximum verification attempts exceeded. Handover locked."

        if timezone.now() > self.otp_expires_at:
            self.status = self.STATUS_FAILED
            self.save(update_fields=['status', 'updated_at'])
            return False, "Handover OTP has expired. Please initiate a new handover."

        self.attempts_count += 1
        computed_hash = self._hash_otp(str(entered_otp).strip(), self.otp_salt)

        if hmac.compare_digest(computed_hash, self.otp_hash):
            self.status = self.STATUS_VERIFIED
            self.verified_at = timezone.now()
            self.save(update_fields=['status', 'verified_at', 'attempts_count', 'updated_at'])

            # Transition item status to returned
            self.item.status = Item.STATUS_RETURNED
            self.item.save(update_fields=['status', 'updated_at'])

            ItemStatusHistory.objects.create(
                item=self.item,
                changed_by=self.held_by,
                old_status=Item.STATUS_CLAIMED,
                new_status=Item.STATUS_RETURNED,
                remarks=f"Item physically handed over to verified owner ({self.claimant.display_name}) via OTP verification."
            )

            # Generate digital handover receipt
            RecoveryReceipt.create_from_handover(self)

            return True, "OTP verified successfully! Item recovery complete."
        else:
            remaining = self.max_attempts - self.attempts_count
            if remaining <= 0:
                self.status = self.STATUS_FAILED
            self.save(update_fields=['status', 'attempts_count', 'updated_at'])

            if remaining > 0:
                return False, f"Invalid OTP code. {remaining} attempt(s) remaining."
            else:
                return False, "Invalid OTP code. Maximum verification attempts exceeded. Handover failed."


class RecoveryReceipt(models.Model):
    """
    Digital immutable handover proof generated upon successful OTP verification.
    Includes cryptographic digital signature and masked participant names.
    """
    handover = models.OneToOneField(
        Handover,
        on_delete=models.CASCADE,
        related_name='receipt'
    )
    receipt_number = models.CharField(max_length=50, unique=True)
    item_title = models.CharField(max_length=200)
    item_category = models.CharField(max_length=100)
    item_code = models.CharField(max_length=30, blank=True)
    claimant_name = models.CharField(max_length=150)
    holder_name = models.CharField(max_length=150)
    institution_name = models.CharField(max_length=200)
    handover_date = models.DateTimeField()
    handover_location = models.CharField(max_length=150)
    digital_signature = models.CharField(
        max_length=64,
        help_text="SHA-256 cryptographic verification signature"
    )
    is_finalized = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Receipt #{self.receipt_number} ({self.item_title})"

    def clean(self):
        # Prevent users from modifying completed receipts
        if self.pk is not None:
            original = RecoveryReceipt.objects.get(pk=self.pk)
            if original.is_finalized:
                raise ValidationError("Finalized recovery receipts are immutable and cannot be altered.")

    def save(self, *args, **kwargs):
        self.clean()
        if not self.receipt_number:
            year_month = timezone.now().strftime('%Y%m')
            code = uuid.uuid4().hex[:8].upper()
            self.receipt_number = f"REC-{year_month}-{code}"

        if not self.digital_signature:
            raw_data = f"{self.receipt_number}:{self.item_title}:{self.claimant_name}:{self.handover_date.isoformat()}"
            self.digital_signature = hashlib.sha256(raw_data.encode()).hexdigest()

        super().save(*args, **kwargs)

    @classmethod
    def create_from_handover(cls, handover):
        """Factory method to generate immutable receipt from verified handover."""
        inst_name = handover.item.institution.name if handover.item.institution else "CampusCare"
        return cls.objects.create(
            handover=handover,
            item_title=handover.item.title,
            item_category=handover.item.category.name,
            item_code=handover.item.item_code or f"CC-{handover.item.pk}",
            claimant_name=handover.claimant.display_name,
            holder_name=handover.held_by.display_name,
            institution_name=inst_name,
            handover_date=handover.verified_at or timezone.now(),
            handover_location=handover.handover_location,
            is_finalized=True
        )


class NotificationPreference(models.Model):
    """User-configurable notification channel preferences."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    notify_on_matches = models.BooleanField(default=True)
    notify_on_claims = models.BooleanField(default=True)
    notify_on_handover = models.BooleanField(default=True)
    notify_on_rewards = models.BooleanField(default=True)
    email_notifications = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification Preferences for {self.user.username}"


class ItemConversation(models.Model):
    """
    Anonymous, secure coordination channel between claimant and finder/staff.
    Keeps private contact info hidden while enabling recovery logistics.
    """
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='conversations'
    )
    claim = models.ForeignKey(
        Claim,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversations'
    )
    participant_1 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations_as_p1'
    )
    participant_2 = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='conversations_as_p2'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ('item', 'participant_1', 'participant_2')

    def __str__(self):
        return f"Conversation on Item #{self.item_id}: {self.participant_1.username} & {self.participant_2.username}"

    def can_access(self, user):
        if not user or not user.is_authenticated:
            return False
        if user in [self.participant_1, self.participant_2]:
            return True
        return getattr(user, 'is_staff_member', False)


class ConversationMessage(models.Model):
    """Individual message in an anonymous item conversation with abuse reporting."""
    conversation = models.ForeignKey(
        ItemConversation,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_messages'
    )
    message_text = models.TextField()
    is_flagged_for_abuse = models.BooleanField(default=False)
    abuse_reason = models.CharField(max_length=255, blank=True)
    flagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='flagged_messages'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Msg from {self.sender.username} at {self.created_at}"


class RewardTransaction(models.Model):
    """
    Maintains an audit ledger of reward points awarded for legitimate recoveries.
    Prevents duplicate reward payouts for the same item/recovery.
    """
    TYPE_ITEM_RETURNED = 'item_returned'
    TYPE_HANDOVER_CONFIRMED = 'handover_confirmed'
    TYPE_REPORT_SUBMITTED = 'report_submitted'
    TYPE_ADMIN_ADJUSTMENT = 'admin_adjustment'

    TYPE_CHOICES = [
        (TYPE_ITEM_RETURNED, 'Found Item Returned to Owner'),
        (TYPE_HANDOVER_CONFIRMED, 'Handover Verified via OTP'),
        (TYPE_REPORT_SUBMITTED, 'Helpful Lost/Found Report Logged'),
        (TYPE_ADMIN_ADJUSTMENT, 'Administrative Adjustment'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reward_transactions'
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reward_transactions'
    )
    handover = models.ForeignKey(
        Handover,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reward_transactions'
    )
    points = models.IntegerField()
    transaction_type = models.CharField(
        max_length=30,
        choices=TYPE_CHOICES
    )
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'item', 'transaction_type')

    def __str__(self):
        return f"{self.user.username}: +{self.points} pts ({self.get_transaction_type_display()})"


class Badge(models.Model):
    """Milestone achievements awarded for campus lost & found citizenship."""
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField()
    icon = models.CharField(max_length=50, default='fa-medal')
    points_threshold = models.PositiveIntegerField(default=0)
    returns_threshold = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['points_threshold']

    def __str__(self):
        return self.name


class UserBadge(models.Model):
    """Awarded badge mapping."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='badges'
    )
    badge = models.ForeignKey(
        Badge,
        on_delete=models.CASCADE,
        related_name='recipients'
    )
    awarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-awarded_at']
        unique_together = ('user', 'badge')

    def __str__(self):
        return f"{self.user.username} earned '{self.badge.name}'"


class RewardRule(models.Model):
    """Configurable reward points rules managed by administrators."""
    action_type = models.CharField(max_length=50, unique=True)
    points = models.IntegerField(default=50)
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.action_type}: {self.points} points"


class Notification(models.Model):
    """In-app notifications for claim status changes, matches, and recovery events."""
    TYPE_CLAIM_SUBMITTED = 'claim_submitted'
    TYPE_CLAIM_STATUS = 'claim_status_changed'
    TYPE_MATCH_FOUND = 'match_found'
    TYPE_HANDOVER_INITIATED = 'handover_initiated'
    TYPE_HANDOVER_COMPLETED = 'handover_completed'
    TYPE_REWARD_EARNED = 'reward_earned'
    TYPE_SYSTEM = 'system'

    TYPE_CHOICES = [
        (TYPE_CLAIM_SUBMITTED, 'Claim Submitted'),
        (TYPE_CLAIM_STATUS, 'Claim Status Update'),
        (TYPE_MATCH_FOUND, 'Suggested Match Found'),
        (TYPE_HANDOVER_INITIATED, 'Handover Initiated'),
        (TYPE_HANDOVER_COMPLETED, 'Handover Completed'),
        (TYPE_REWARD_EARNED, 'Reward Points Earned'),
        (TYPE_SYSTEM, 'System Notification'),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=30,
        choices=TYPE_CHOICES,
        default=TYPE_SYSTEM
    )
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification to {self.recipient.username}: {self.title}"
