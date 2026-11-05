from django.contrib import admin
from .models import (
    Badge,
    Claim,
    ClaimStatusHistory,
    ConversationMessage,
    ExpirationRule,
    Handover,
    Item,
    ItemConversation,
    ItemMatch,
    ItemStatusHistory,
    Notification,
    NotificationPreference,
    RecoveryReceipt,
    RewardRule,
    RewardTransaction,
    UserBadge,
)


class ItemStatusHistoryInline(admin.TabularInline):
    model = ItemStatusHistory
    extra = 0
    readonly_fields = ('changed_by', 'old_status', 'new_status', 'remarks', 'created_at')
    can_delete = False


class ClaimInline(admin.TabularInline):
    model = Claim
    extra = 0
    fields = ('claimant', 'status', 'fraud_risk_score', 'created_at')
    readonly_fields = ('claimant', 'status', 'fraud_risk_score', 'created_at')
    show_change_link = True
    can_delete = False


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        'title', 'report_type', 'category', 'location',
        'user', 'status', 'date_lost_or_found', 'expires_at', 'created_at'
    )
    list_filter = ('report_type', 'status', 'category', 'institution', 'date_lost_or_found')
    search_fields = ('title', 'description', 'location_details', 'user__username', 'user__email')
    inlines = [ItemStatusHistoryInline, ClaimInline]
    date_hierarchy = 'created_at'


@admin.register(ItemMatch)
class ItemMatchAdmin(admin.ModelAdmin):
    list_display = ('source_item', 'matched_item', 'score', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('source_item__title', 'matched_item__title')
    ordering = ('-score',)


class ClaimStatusHistoryInline(admin.TabularInline):
    model = ClaimStatusHistory
    extra = 0
    readonly_fields = ('changed_by', 'old_status', 'new_status', 'reason', 'created_at')
    can_delete = False


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'item', 'claimant', 'status', 'fraud_risk_score',
        'reviewed_by', 'reviewed_at', 'created_at'
    )
    list_filter = ('status', 'created_at')
    search_fields = ('item__title', 'claimant__username', 'claimant__student_id', 'identifying_details')
    inlines = [ClaimStatusHistoryInline]
    readonly_fields = ('fraud_risk_score', 'fraud_risk_flags')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'title', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('recipient__username', 'title', 'message')


@admin.register(ExpirationRule)
class ExpirationRuleAdmin(admin.ModelAdmin):
    list_display = ('institution', 'category', 'report_type', 'days_to_expire', 'is_active', 'created_at')
    list_filter = ('report_type', 'is_active', 'institution')


@admin.register(Handover)
class HandoverAdmin(admin.ModelAdmin):
    list_display = ('id', 'item', 'claimant', 'held_by', 'status', 'attempts_count', 'otp_expires_at', 'verified_at')
    list_filter = ('status', 'initiated_at')
    search_fields = ('item__title', 'claimant__username', 'held_by__username', 'handover_location')
    readonly_fields = ('otp_hash', 'otp_salt', 'attempts_count')


@admin.register(RecoveryReceipt)
class RecoveryReceiptAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'item_title', 'claimant_name', 'holder_name', 'handover_date', 'is_finalized')
    list_filter = ('is_finalized', 'handover_date')
    search_fields = ('receipt_number', 'item_title', 'claimant_name', 'holder_name', 'digital_signature')
    readonly_fields = ('receipt_number', 'digital_signature', 'created_at')


class ConversationMessageInline(admin.TabularInline):
    model = ConversationMessage
    extra = 0
    fields = ('sender', 'message_text', 'is_flagged_for_abuse', 'abuse_reason', 'flagged_by', 'created_at')
    readonly_fields = ('sender', 'created_at')


@admin.register(ItemConversation)
class ItemConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'item', 'participant_1', 'participant_2', 'updated_at', 'created_at')
    search_fields = ('item__title', 'participant_1__username', 'participant_2__username')
    inlines = [ConversationMessageInline]


@admin.register(ConversationMessage)
class ConversationMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'sender', 'is_flagged_for_abuse', 'flagged_by', 'created_at')
    list_filter = ('is_flagged_for_abuse', 'created_at')
    search_fields = ('sender__username', 'message_text', 'abuse_reason')


@admin.register(RewardTransaction)
class RewardTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'points', 'transaction_type', 'item', 'created_at')
    list_filter = ('transaction_type', 'created_at')
    search_fields = ('user__username', 'description')
    readonly_fields = ('created_at',)


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'points_threshold', 'returns_threshold', 'icon')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(UserBadge)
class UserBadgeAdmin(admin.ModelAdmin):
    list_display = ('user', 'badge', 'awarded_at')
    list_filter = ('badge', 'awarded_at')
    search_fields = ('user__username', 'badge__name')


@admin.register(RewardRule)
class RewardRuleAdmin(admin.ModelAdmin):
    list_display = ('action_type', 'points', 'is_active', 'description')
    list_editable = ('points', 'is_active')


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'notify_on_matches', 'notify_on_claims', 'notify_on_handover', 'notify_on_rewards', 'email_notifications')

