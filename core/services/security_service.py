"""
Security Monitoring and Anomaly Detection Service for CampusCare.
Aggregates suspicious claims, chat abuse flags, repeated report velocity anomalies,
and failed OTP lockout alerts for administrative review without automated punitive banning.
"""

import logging
from datetime import timedelta
from django.db.models import Count, Q
from django.utils import timezone
from .audit_service import AuditService

logger = logging.getLogger(__name__)


class SecurityMonitoringService:
    """
    Automated security alert synthesis and moderation workflow.
    """

    @classmethod
    def sync_security_alerts(cls, institution=None):
        """
        Scans across claims, chats, handovers, and item velocity
        to synthesize SecurityAlert records if not already active.
        """
        from core.models import SecurityAlert
        from items.models import Claim, ConversationMessage, Handover, Item

        # 1. Suspicious claims (risk score >= 30)
        claims_qs = Claim.objects.filter(fraud_risk_score__gte=30)
        if institution:
            claims_qs = claims_qs.filter(item__institution=institution)

        for claim in claims_qs.select_related('item', 'claimant', 'item__institution'):
            if not SecurityAlert.objects.filter(claim=claim, alert_type=SecurityAlert.ALERT_SUSPICIOUS_CLAIM).exists():
                severity = SecurityAlert.SEVERITY_HIGH if claim.fraud_risk_score >= 60 else SecurityAlert.SEVERITY_MEDIUM
                reasons = [f['reason'] for f in claim.fraud_risk_flags] if claim.fraud_risk_flags else ["High Velocity / Anomaly Score"]
                SecurityAlert.objects.create(
                    alert_type=SecurityAlert.ALERT_SUSPICIOUS_CLAIM,
                    severity=severity,
                    title=f"Suspicious Claim #{claim.pk} on '{claim.item.title}' (Risk: {claim.fraud_risk_score}/100)",
                    description=f"Flagged ownership claim. Indicators: {'; '.join(reasons)}.",
                    claim=claim,
                    item=claim.item,
                    user=claim.claimant,
                    institution=claim.item.institution,
                    details={'fraud_risk_score': claim.fraud_risk_score, 'flags': claim.fraud_risk_flags}
                )

        # 2. Chat abuse reports
        abuse_msgs = ConversationMessage.objects.filter(is_flagged_for_abuse=True).select_related('conversation__item', 'sender', 'flagged_by')
        for msg in abuse_msgs:
            if not SecurityAlert.objects.filter(message=msg, alert_type=SecurityAlert.ALERT_MESSAGE_ABUSE).exists():
                reporter_name = msg.flagged_by.display_name if msg.flagged_by else "Campus User"
                SecurityAlert.objects.create(
                    alert_type=SecurityAlert.ALERT_MESSAGE_ABUSE,
                    severity=SecurityAlert.SEVERITY_HIGH,
                    title=f"Chat Abuse Flagged on Item '{msg.conversation.item.title}'",
                    description=f"Reported by {reporter_name}. Reason given: {msg.abuse_reason or 'Inappropriate behavior'}.",
                    message=msg,
                    item=msg.conversation.item,
                    user=msg.sender,
                    institution=msg.conversation.item.institution if hasattr(msg.conversation.item, 'institution') else None,
                    details={'message_pk': msg.pk, 'abuse_reason': msg.abuse_reason}
                )

        # 3. Failed OTP handover attempts
        handovers = Handover.objects.filter(Q(status='failed') | Q(attempts_count__gte=3)).select_related('item', 'claimant', 'item__institution')
        for h in handovers:
            if not SecurityAlert.objects.filter(handover=h, alert_type=SecurityAlert.ALERT_FAILED_OTP).exists():
                is_failed = (h.status == Handover.STATUS_FAILED)
                severity = SecurityAlert.SEVERITY_CRITICAL if is_failed else SecurityAlert.SEVERITY_MEDIUM
                SecurityAlert.objects.create(
                    alert_type=SecurityAlert.ALERT_FAILED_OTP,
                    severity=severity,
                    title=f"OTP Verification Anomaly on Handover #{h.pk} ({h.item.title})",
                    description=f"{h.attempts_count} failed OTP verification attempt(s). Status: {h.get_status_display()}.",
                    handover=h,
                    item=h.item,
                    user=h.claimant,
                    institution=h.item.institution,
                    details={'attempts_count': h.attempts_count, 'handover_status': h.status}
                )

        # 4. Repeated report velocity (>= 3 reports in 24 hours)
        since_24h = timezone.now() - timedelta(hours=24)
        active_reporters = (
            Item.objects.filter(created_at__gte=since_24h)
            .values('user')
            .annotate(cnt=Count('id'))
            .filter(cnt__gte=3)
        )
        from django.contrib.auth import get_user_model
        User = get_user_model()

        for entry in active_reporters:
            user_id = entry['user']
            count = entry['cnt']
            u = User.objects.filter(pk=user_id).first()
            if u:
                recent_alert = SecurityAlert.objects.filter(
                    user=u,
                    alert_type=SecurityAlert.ALERT_REPEATED_REPORTS,
                    created_at__gte=since_24h
                ).exists()
                if not recent_alert:
                    SecurityAlert.objects.create(
                        alert_type=SecurityAlert.ALERT_REPEATED_REPORTS,
                        severity=SecurityAlert.SEVERITY_MEDIUM,
                        title=f"High Velocity Activity: {u.display_name} ({count} reports in 24h)",
                        description=f"User has created {count} lost/found reports in the last 24 hours. Verify validity of listings.",
                        user=u,
                        institution=u.institution,
                        details={'reports_count_24h': count}
                    )

    @classmethod
    def get_alerts_summary(cls, institution=None):
        """Returns statistics breakdown of active alerts."""
        from core.models import SecurityAlert
        qs = SecurityAlert.objects.filter(status=SecurityAlert.STATUS_PENDING)
        if institution:
            qs = qs.filter(institution=institution)

        return {
            'total_pending': qs.count(),
            'critical': qs.filter(severity=SecurityAlert.SEVERITY_CRITICAL).count(),
            'high': qs.filter(severity=SecurityAlert.SEVERITY_HIGH).count(),
            'medium': qs.filter(severity=SecurityAlert.SEVERITY_MEDIUM).count(),
            'low': qs.filter(severity=SecurityAlert.SEVERITY_LOW).count(),
        }

    @classmethod
    def review_alert(cls, alert, staff_user, new_status, review_notes="", request=None):
        """
        Records staff review decision on an alert without automated banning.
        Logs to AuditService.
        """
        alert.status = new_status
        alert.reviewed_by = staff_user
        alert.reviewed_at = timezone.now()
        alert.review_notes = review_notes.strip()
        alert.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_notes', 'updated_at'])

        AuditService.log_action(
            action='security_alert',
            actor=staff_user,
            target_obj=alert,
            details={
                'alert_type': alert.alert_type,
                'resolution_status': new_status,
                'notes': review_notes
            },
            request=request
        )
        return alert

