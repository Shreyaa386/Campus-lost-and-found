from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import CampusLocation, Category, Institution
from items.models import (
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
from items.services import (
    CommunicationService,
    FraudDetector,
    ImageSimilarityService,
    MatchingService,
    NotificationService,
    TagService,
    QRService,
    RewardService,
)

User = get_user_model()


class ItemReportingAndManagementTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.institution = Institution.objects.create(
            name="Apex Institute of Technology",
            short_name="AIT"
        )
        self.category = Category.objects.create(
            name="Electronics",
            slug="electronics",
            institution=self.institution
        )
        self.location = CampusLocation.objects.create(
            institution=self.institution,
            name="Central Library"
        )
        self.user1 = User.objects.create_user(
            username="student1",
            email="student1@ait.edu",
            password="Password123!",
            student_id="2024CS11",
            institution=self.institution,
            phone_number="+919876543210"
        )
        self.user2 = User.objects.create_user(
            username="student2",
            email="student2@ait.edu",
            password="Password123!",
            student_id="2024CS22",
            institution=self.institution
        )
        self.staff_user = User.objects.create_user(
            username="security_admin",
            email="security@ait.edu",
            password="Password123!",
            role=User.ROLE_STAFF,
            institution=self.institution
        )

    def test_report_lost_item_creation(self):
        self.client.login(username="student1", password="Password123!")
        response = self.client.post(reverse('items:report_item', kwargs={'report_type': 'lost'}), {
            'title': 'Blue Dell XPS 15',
            'category': self.category.pk,
            'location': self.location.pk,
            'location_details': 'Table 14 near window',
            'date_lost_or_found': timezone.localdate(),
            'description': 'Has a green sticker on top cover.',
            'contact_preference': Item.CONTACT_EMAIL,
            'contact_email': 'student1@ait.edu',
        })
        self.assertEqual(response.status_code, 302)
        item = Item.objects.filter(title='Blue Dell XPS 15').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.report_type, Item.REPORT_TYPE_LOST)
        self.assertEqual(item.status, Item.STATUS_OPEN)
        self.assertEqual(item.user, self.user1)

        history = item.history.first()
        self.assertIsNotNone(history)
        self.assertEqual(history.new_status, Item.STATUS_OPEN)

    def test_report_future_date_rejected(self):
        self.client.login(username="student1", password="Password123!")
        tomorrow = timezone.localdate() + timedelta(days=1)
        response = self.client.post(reverse('items:report_item', kwargs={'report_type': 'lost'}), {
            'title': 'Future Item',
            'category': self.category.pk,
            'location': self.location.pk,
            'date_lost_or_found': tomorrow,
            'description': 'Lost tomorrow?',
            'contact_preference': Item.CONTACT_EMAIL,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(title='Future Item').exists())

    def test_edit_permissions_owner_vs_stranger(self):
        item = Item.objects.create(
            institution=self.institution,
            user=self.user1,
            report_type=Item.REPORT_TYPE_LOST,
            title="Lost Keys",
            description="Silver ring with 2 keys",
            category=self.category,
            location=self.location,
            date_lost_or_found=timezone.localdate()
        )

        self.client.login(username="student2", password="Password123!")
        response = self.client.post(reverse('items:item_edit', kwargs={'pk': item.pk}), {
            'title': 'Hacked Keys',
            'category': self.category.pk,
            'location': self.location.pk,
            'date_lost_or_found': timezone.localdate(),
            'description': 'Changed description',
            'contact_preference': Item.CONTACT_EMAIL,
        })
        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.title, "Lost Keys")

        self.client.login(username="security_admin", password="Password123!")
        response = self.client.post(reverse('items:item_edit', kwargs={'pk': item.pk}), {
            'title': 'Lost Keys (Verified by Security)',
            'category': self.category.pk,
            'location': self.location.pk,
            'date_lost_or_found': timezone.localdate(),
            'description': 'Verified by security staff',
            'contact_preference': Item.CONTACT_EMAIL,
        })
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.title, "Lost Keys (Verified by Security)")

    def test_delete_permissions(self):
        item = Item.objects.create(
            institution=self.institution,
            user=self.user1,
            report_type=Item.REPORT_TYPE_LOST,
            title="Lost Umbrella",
            description="Black umbrella",
            category=self.category,
            date_lost_or_found=timezone.localdate()
        )

        self.client.login(username="student2", password="Password123!")
        response = self.client.post(reverse('items:item_delete', kwargs={'pk': item.pk}))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Item.objects.filter(pk=item.pk).exists())

        self.client.login(username="student1", password="Password123!")
        response = self.client.post(reverse('items:item_delete', kwargs={'pk': item.pk}))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Item.objects.filter(pk=item.pk).exists())

    def test_contact_privacy_protection(self):
        item = Item.objects.create(
            institution=self.institution,
            user=self.user1,
            report_type=Item.REPORT_TYPE_LOST,
            title="Lost Wallet",
            description="Brown leather wallet",
            category=self.category,
            date_lost_or_found=timezone.localdate(),
            contact_preference=Item.CONTACT_BOTH,
            contact_phone="+919876543210",
            contact_email="student1@ait.edu"
        )

        self.client.logout()
        response = self.client.get(reverse('items:item_detail', kwargs={'pk': item.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(item.can_view_contact(None))
        self.assertNotContains(response, "+919876543210")
        self.assertContains(response, "Sign In to View Contact")

        self.client.login(username="student2", password="Password123!")
        response = self.client.get(reverse('items:item_detail', kwargs={'pk': item.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "+919876543210")

        item.contact_preference = Item.CONTACT_CAMPUS_DESK
        item.save()
        self.assertFalse(item.can_view_contact(self.user2))
        response = self.client.get(reverse('items:item_detail', kwargs={'pk': item.pk}))
        self.assertContains(response, "Campus Lost & Found Desk")
        self.assertNotContains(response, "+919876543210")

    def test_status_update_and_reward_points(self):
        found_item = Item.objects.create(
            institution=self.institution,
            user=self.user1,
            report_type=Item.REPORT_TYPE_FOUND,
            title="Found Calculator",
            description="Casio Scientific fx-991EX",
            category=self.category,
            date_lost_or_found=timezone.localdate(),
            status=Item.STATUS_OPEN
        )

        initial_points = self.user1.reward_points

        self.client.login(username="student1", password="Password123!")
        response = self.client.post(reverse('items:item_update_status', kwargs={'pk': found_item.pk}), {
            'status': Item.STATUS_RETURNED,
            'remarks': 'Handed back to classmate after ID check'
        })
        self.assertEqual(response.status_code, 302)

        found_item.refresh_from_db()
        self.assertEqual(found_item.status, Item.STATUS_RETURNED)

        self.user1.refresh_from_db()
        self.assertEqual(self.user1.reward_points, initial_points + 50)

        history_item = found_item.history.filter(new_status=Item.STATUS_RETURNED).first()
        self.assertIsNotNone(history_item)
        self.assertEqual(history_item.remarks, 'Handed back to classmate after ID check')

    def test_auto_expire_items_management_command(self):
        past_item = Item.objects.create(
            institution=self.institution,
            user=self.user1,
            report_type=Item.REPORT_TYPE_LOST,
            title="Old Missing Notebook",
            description="Left in library long ago",
            category=self.category,
            date_lost_or_found=timezone.localdate() - timedelta(days=60),
            status=Item.STATUS_OPEN
        )
        Item.objects.filter(pk=past_item.pk).update(
            expires_at=timezone.now() - timedelta(days=10)
        )

        call_command('expire_items')

        past_item.refresh_from_db()
        self.assertEqual(past_item.status, Item.STATUS_EXPIRED)

        history = past_item.history.filter(new_status=Item.STATUS_EXPIRED).first()
        self.assertIsNotNone(history)
        self.assertIn("Automatically expired", history.remarks)


# --------------------------------------------------------------------------
# STEP 2 TESTS: SMART MATCHING & OWNERSHIP VERIFICATION
# --------------------------------------------------------------------------

class SmartMatchingAndVerificationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.institution = Institution.objects.create(
            name="Apex Institute of Technology",
            short_name="AIT"
        )
        self.other_institution = Institution.objects.create(
            name="Other Tech University",
            short_name="OTU"
        )
        self.cat_electronics = Category.objects.create(
            name="Electronics",
            slug="electronics",
            institution=self.institution
        )
        self.cat_keys = Category.objects.create(
            name="Keys",
            slug="keys",
            institution=self.institution
        )
        self.loc_library = CampusLocation.objects.create(
            institution=self.institution,
            name="Central Library - 2nd Floor",
            building="Library Block"
        )
        self.loc_cafeteria = CampusLocation.objects.create(
            institution=self.institution,
            name="Main Cafeteria",
            building="SAC Block"
        )

        self.student_lost = User.objects.create_user(
            username="student_lost",
            email="lost@ait.edu",
            password="Password123!",
            student_id="2024CS91",
            institution=self.institution
        )
        self.student_finder = User.objects.create_user(
            username="student_finder",
            email="finder@ait.edu",
            password="Password123!",
            student_id="2024CS92",
            institution=self.institution
        )
        self.student_claimant2 = User.objects.create_user(
            username="student_claimant2",
            email="claimant2@ait.edu",
            password="Password123!",
            student_id="2024CS93",
            institution=self.institution
        )
        self.staff_reviewer = User.objects.create_user(
            username="staff_reviewer",
            email="staff@ait.edu",
            password="Password123!",
            role=User.ROLE_STAFF,
            institution=self.institution
        )

        # 1. Lost Laptop
        self.lost_laptop = Item.objects.create(
            institution=self.institution,
            user=self.student_lost,
            report_type=Item.REPORT_TYPE_LOST,
            title="Dell Inspiron 15 Blue Laptop",
            description="Dark blue laptop with an anime sticker on top lid and scratches near trackpad.",
            category=self.cat_electronics,
            location=self.loc_library,
            date_lost_or_found=timezone.localdate()
        )

        # 2. Found Laptop (High Compatibility Match)
        self.found_laptop = Item.objects.create(
            institution=self.institution,
            user=self.student_finder,
            report_type=Item.REPORT_TYPE_FOUND,
            title="Found Blue Dell Laptop",
            description="Discovered a blue Dell laptop left on study desk. Has stickers on lid.",
            category=self.cat_electronics,
            location=self.loc_library,
            date_lost_or_found=timezone.localdate(),
            verification_questions=["What specific anime character is on the top lid sticker?"]
        )

        # 3. Found Keys (Incompatible item)
        self.found_keys = Item.objects.create(
            institution=self.institution,
            user=self.student_finder,
            report_type=Item.REPORT_TYPE_FOUND,
            title="Silver Key with Red Lanyard",
            description="Room key found on cafeteria floor.",
            category=self.cat_keys,
            location=self.loc_cafeteria,
            date_lost_or_found=timezone.localdate() - timedelta(days=20)
        )

    def test_matching_score_high_compatibility(self):
        """Test that compatible lost and found reports yield a high score with explainable reasons."""
        analysis = MatchingService.compute_similarity(self.lost_laptop, self.found_laptop)
        score = analysis['score']
        reasons = analysis['reasons']

        # Expected score: category 25 + location 20 + date 15 + text ~15-25 = >65%
        self.assertGreaterEqual(score, 60.0)
        self.assertEqual(analysis['category_score'], 25.0)
        self.assertGreaterEqual(analysis['location_score'], 20.0)
        self.assertEqual(analysis['date_score'], 15.0)

        # Check explainable reason bullets
        reasons_text = " ".join(reasons)
        self.assertIn("Category Match", reasons_text)
        self.assertIn("Exact Location Match", reasons_text)
        self.assertIn("dell", reasons_text.lower())

    def test_matching_score_low_compatibility(self):
        """Test that incompatible items (different category, date, location) produce a low score."""
        analysis = MatchingService.compute_similarity(self.lost_laptop, self.found_keys)
        score = analysis['score']

        self.assertLess(score, 35.0)
        self.assertEqual(analysis['category_score'], 0.0)

    def test_find_matches_service_and_dismissal(self):
        """Test discovering matches and dismissing false suggestions."""
        matches = MatchingService.find_matches_for_item(self.lost_laptop, min_score=40.0)
        self.assertGreaterEqual(len(matches), 1)
        top_match = matches[0]
        self.assertEqual(top_match.matched_item, self.found_laptop)
        self.assertEqual(top_match.status, ItemMatch.STATUS_SUGGESTED)

        # User dismisses the match
        self.client.login(username="student_lost", password="Password123!")
        dismiss_url = reverse('items:item_dismiss_match', kwargs={
            'pk': self.lost_laptop.pk,
            'match_pk': top_match.pk
        })
        response = self.client.post(dismiss_url, {'dismissed_reason': 'Not my model'})
        self.assertEqual(response.status_code, 302)

        top_match.refresh_from_db()
        self.assertEqual(top_match.status, ItemMatch.STATUS_DISMISSED)
        self.assertEqual(top_match.dismissed_reason, 'Not my model')

        # Next call to find_matches_for_item must exclude dismissed match
        subsequent_matches = MatchingService.find_matches_for_item(self.lost_laptop, min_score=40.0)
        self.assertEqual(len(subsequent_matches), 0)

    def test_claim_submission_with_verification_questions(self):
        """Test submitting an ownership claim and storing private verification answers securely."""
        self.client.login(username="student_lost", password="Password123!")
        claim_url = reverse('items:item_claim', kwargs={'pk': self.found_laptop.pk})

        response = self.client.post(claim_url, {
            'question_0': 'Naruto sticker with orange background',
            'identifying_details': 'Serial number is DL-99882. Inner battery has my roll number 2024CS91 scratched.',
        })
        self.assertEqual(response.status_code, 302)

        claim = Claim.objects.filter(item=self.found_laptop, claimant=self.student_lost).first()
        self.assertIsNotNone(claim)
        self.assertEqual(claim.status, Claim.STATUS_PENDING)
        self.assertEqual(
            claim.verification_answers.get('What specific anime character is on the top lid sticker?'),
            'Naruto sticker with orange background'
        )

        # Verify in-app notifications dispatched
        claimant_note = Notification.objects.filter(
            recipient=self.student_lost,
            notification_type=Notification.TYPE_CLAIM_SUBMITTED
        ).first()
        self.assertIsNotNone(claimant_note)

        finder_note = Notification.objects.filter(
            recipient=self.student_finder,
            notification_type=Notification.TYPE_CLAIM_SUBMITTED
        ).first()
        self.assertIsNotNone(finder_note)

    def test_claimant_privacy_and_access_restrictions(self):
        """Test that private verification details are never exposed to unauthorized users."""
        claim = Claim.objects.create(
            item=self.found_laptop,
            claimant=self.student_lost,
            identifying_details="Secret Serial Number: 12345-XYZ",
            verification_answers={"Prompt": "Secret Passcode"}
        )

        # 1. Model permission check
        self.assertTrue(claim.can_view_private_answers(self.student_lost))
        self.assertTrue(claim.can_view_private_answers(self.staff_reviewer))
        self.assertFalse(claim.can_view_private_answers(self.student_claimant2))
        self.assertFalse(claim.can_view_private_answers(None))

        # 2. View access restriction (other student cannot access claim detail)
        self.client.login(username="student_claimant2", password="Password123!")
        response = self.client.get(reverse('items:claim_detail', kwargs={'pk': claim.pk}))
        self.assertEqual(response.status_code, 403)

        # 3. Staff can view claim detail and private answers
        self.client.login(username="staff_reviewer", password="Password123!")
        response = self.client.get(reverse('items:claim_detail', kwargs={'pk': claim.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secret Serial Number: 12345-XYZ")
        self.assertContains(response, "Secret Passcode")

    def test_multiple_claimants_supported(self):
        """Test that multiple users can independently submit claims for the same found item."""
        claim1 = Claim.objects.create(
            item=self.found_laptop,
            claimant=self.student_lost,
            identifying_details="Claimant 1 private proof details"
        )
        claim2 = Claim.objects.create(
            item=self.found_laptop,
            claimant=self.student_claimant2,
            identifying_details="Claimant 2 private proof details"
        )

        all_claims = self.found_laptop.claims.all()
        self.assertEqual(all_claims.count(), 2)
        self.assertIn(claim1, all_claims)
        self.assertIn(claim2, all_claims)

    def test_conflict_prevention_on_final_approval(self):
        """Test that only one claim can be approved, blocking conflicting final decisions."""
        claim1 = Claim.objects.create(
            item=self.found_laptop,
            claimant=self.student_lost,
            identifying_details="Proof A"
        )
        claim2 = Claim.objects.create(
            item=self.found_laptop,
            claimant=self.student_claimant2,
            identifying_details="Proof B"
        )

        # Approve claim 1
        claim1.status = Claim.STATUS_APPROVED
        claim1.decision_reason = "Serial number matched official record."
        claim1.reviewed_by = self.staff_reviewer
        claim1.save()
        self.assertEqual(claim1.status, Claim.STATUS_APPROVED)

        # Attempting to approve claim 2 while claim 1 is approved MUST raise a ValidationError
        claim2.status = Claim.STATUS_APPROVED
        claim2.decision_reason = "Approving competing claim"
        with self.assertRaises(ValidationError):
            claim2.clean()

    def test_cannot_claim_own_reported_item(self):
        """Test that a user cannot submit a claim for an item they reported."""
        claim = Claim(
            item=self.found_laptop,
            claimant=self.student_finder,  # Reported this item
            identifying_details="I am claiming what I found"
        )
        with self.assertRaises(ValidationError):
            claim.clean()

    def test_claim_withdrawal_by_claimant(self):
        """Test that a claimant can withdraw their pending claim."""
        claim = Claim.objects.create(
            item=self.found_laptop,
            claimant=self.student_lost,
            identifying_details="Withdrawing this soon"
        )
        self.assertTrue(claim.can_withdraw(self.student_lost))

        self.client.login(username="student_lost", password="Password123!")
        withdraw_url = reverse('items:claim_withdraw', kwargs={'pk': claim.pk})
        response = self.client.post(withdraw_url)
        self.assertEqual(response.status_code, 302)

        claim.refresh_from_db()
        self.assertEqual(claim.status, Claim.STATUS_WITHDRAWN)
        self.assertFalse(claim.can_withdraw(self.student_lost))

    def test_fraud_detector_high_claim_velocity(self):
        """Test that submitting multiple claims in a 24-hour window flags explainable risk indicators."""
        # Create 4 dummy claims in past hour
        for i in range(4):
            dummy_item = Item.objects.create(
                institution=self.institution,
                user=self.student_finder,
                report_type=Item.REPORT_TYPE_FOUND,
                title=f"Item {i}",
                description="Sample",
                category=self.cat_electronics,
                date_lost_or_found=timezone.localdate()
            )
            Claim.objects.create(
                item=dummy_item,
                claimant=self.student_lost,
                identifying_details=f"Sample details {i}"
            )

        # Analyze risk on a 5th claim
        risk_score, risk_flags = FraudDetector.analyze_claim_risk(
            self.student_lost,
            self.found_laptop,
            "Legitimate proof with enough words"
        )

        self.assertGreaterEqual(risk_score, 35)
        flag_rules = [f['rule'] for f in risk_flags]
        self.assertIn('high_24h_velocity', flag_rules)

    def test_fraud_detector_text_mirroring(self):
        """Test that pasting the exact public description as private proof triggers text mirroring flag."""
        # Exact duplicate text
        risk_score, risk_flags = FraudDetector.analyze_claim_risk(
            self.student_claimant2,
            self.found_laptop,
            self.found_laptop.description
        )

        self.assertGreaterEqual(risk_score, 30)
        flag_rules = [f['rule'] for f in risk_flags]
        self.assertIn('public_text_mirroring', flag_rules)


class RecoveryAndRewardsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.institution = Institution.objects.create(
            name="Apex Institute of Technology",
            short_name="AIT"
        )
        self.category = Category.objects.create(
            name="Electronics",
            slug="electronics",
            institution=self.institution
        )
        self.location = CampusLocation.objects.create(
            institution=self.institution,
            name="Central Library"
        )
        self.finder = User.objects.create_user(
            username="finder_sam",
            email="sam@ait.edu",
            password="Password123!",
            student_id="2024CS01",
            role=User.ROLE_STUDENT,
            institution=self.institution,
            phone_number="+919876543210"
        )
        self.claimant = User.objects.create_user(
            username="owner_alice",
            email="alice@ait.edu",
            password="Password123!",
            student_id="2024CS02",
            role=User.ROLE_STUDENT,
            institution=self.institution,
            phone_number="+919876543211"
        )
        self.stranger = User.objects.create_user(
            username="stranger_bob",
            email="bob@ait.edu",
            password="Password123!",
            student_id="2024CS03",
            role=User.ROLE_STUDENT,
            institution=self.institution
        )
        self.staff_admin = User.objects.create_user(
            username="officer_carol",
            email="carol@ait.edu",
            password="Password123!",
            role=User.ROLE_STAFF,
            institution=self.institution
        )

        self.found_item = Item.objects.create(
            institution=self.institution,
            user=self.finder,
            report_type=Item.REPORT_TYPE_FOUND,
            title="Graphing Calculator TI-84",
            description="Found on desk 4 with sticker",
            category=self.category,
            location=self.location,
            date_lost_or_found=timezone.localdate(),
            item_code="CC-2026-0001",
            status=Item.STATUS_OPEN
        )

        self.approved_claim = Claim.objects.create(
            item=self.found_item,
            claimant=self.claimant,
            status=Claim.STATUS_APPROVED,
            identifying_details="Has name written in battery compartment",
            reviewed_by=self.staff_admin,
            reviewed_at=timezone.now()
        )

    def test_otp_generation_and_hashing(self):
        """Test secure OTP generation, salted SHA-256 hashing, and non-storage of raw OTP."""
        handover = Handover(
            claim=self.approved_claim,
            item=self.found_item,
            claimant=self.claimant,
            held_by=self.finder
        )
        raw_otp = handover.generate_otp(expiry_minutes=30)
        handover.save()

        self.assertEqual(len(raw_otp), 6)
        self.assertTrue(raw_otp.isdigit())

        # Salt and hash stored
        self.assertEqual(len(handover.otp_hash), 64)
        self.assertEqual(len(handover.otp_salt), 32)
        self.assertNotEqual(handover.otp_hash, raw_otp)
        self.assertGreater(handover.otp_expires_at, timezone.now())

    def test_otp_verification_success_and_item_status(self):
        """Test successful OTP verification completes handover and creates immutable receipt."""
        handover = Handover(
            claim=self.approved_claim,
            item=self.found_item,
            claimant=self.claimant,
            held_by=self.finder
        )
        raw_otp = handover.generate_otp(expiry_minutes=30)
        handover.save()

        success, msg = handover.verify_otp(raw_otp)
        self.assertTrue(success)
        self.assertEqual(handover.status, Handover.STATUS_VERIFIED)

        # Item status updated to returned
        self.found_item.refresh_from_db()
        self.assertEqual(self.found_item.status, Item.STATUS_RETURNED)

        # Receipt automatically created
        receipt = RecoveryReceipt.objects.filter(handover=handover).first()
        self.assertIsNotNone(receipt)
        self.assertTrue(receipt.receipt_number.startswith("REC-"))
        self.assertEqual(len(receipt.digital_signature), 64)

    def test_otp_failed_attempts_lockout(self):
        """Test that exceeding maximum OTP verification attempts locks the handover."""
        handover = Handover(
            claim=self.approved_claim,
            item=self.found_item,
            claimant=self.claimant,
            held_by=self.finder
        )
        raw_otp = handover.generate_otp(expiry_minutes=30)
        handover.save()

        # Try 5 wrong OTPs
        for _ in range(5):
            success, msg = handover.verify_otp("000000")
            self.assertFalse(success)

        self.assertEqual(handover.status, Handover.STATUS_FAILED)

        # 6th attempt should be blocked
        success, msg = handover.verify_otp(raw_otp)
        self.assertFalse(success)
        self.assertIn("already", msg.lower())

    def test_otp_expiration(self):
        """Test that an expired OTP is rejected."""
        handover = Handover(
            claim=self.approved_claim,
            item=self.found_item,
            claimant=self.claimant,
            held_by=self.finder
        )
        raw_otp = handover.generate_otp(expiry_minutes=30)
        # Manually backdate expiration
        handover.otp_expires_at = timezone.now() - timedelta(minutes=10)
        handover.save()

        success, msg = handover.verify_otp(raw_otp)
        self.assertFalse(success)
        self.assertIn("expired", msg.lower())
        self.assertEqual(handover.status, Handover.STATUS_FAILED)

    def test_handover_access_permissions(self):
        """Test that only claimant, holder, and staff can access handover."""
        handover = Handover(
            claim=self.approved_claim,
            item=self.found_item,
            claimant=self.claimant,
            held_by=self.finder
        )
        raw_otp = handover.generate_otp(expiry_minutes=30)
        handover.save()

        # 1. Claimant can access
        self.client.login(username="owner_alice", password="Password123!")
        res = self.client.get(reverse('items:handover_detail', kwargs={'pk': handover.pk}))
        self.assertEqual(res.status_code, 200)

        # 2. Holder can access
        self.client.login(username="finder_sam", password="Password123!")
        res = self.client.get(reverse('items:handover_detail', kwargs={'pk': handover.pk}))
        self.assertEqual(res.status_code, 200)

        # 3. Staff can access
        self.client.login(username="officer_carol", password="Password123!")
        res = self.client.get(reverse('items:handover_detail', kwargs={'pk': handover.pk}))
        self.assertEqual(res.status_code, 200)

        # 4. Unrelated stranger is forbidden (403)
        self.client.login(username="stranger_bob", password="Password123!")
        res = self.client.get(reverse('items:handover_detail', kwargs={'pk': handover.pk}))
        self.assertEqual(res.status_code, 403)

    def test_otp_never_exposed_on_public_item_page(self):
        """Test that confidential OTP code is never leaked on public item pages."""
        handover = Handover(
            claim=self.approved_claim,
            item=self.found_item,
            claimant=self.claimant,
            held_by=self.finder
        )
        raw_otp = handover.generate_otp(expiry_minutes=30)
        handover.save()

        # Anonymous visitor
        self.client.logout()
        res = self.client.get(reverse('items:item_detail', kwargs={'pk': self.found_item.pk}))
        self.assertNotContains(res, raw_otp)

        # Logged in stranger
        self.client.login(username="stranger_bob", password="Password123!")
        res = self.client.get(reverse('items:item_detail', kwargs={'pk': self.found_item.pk}))
        self.assertNotContains(res, raw_otp)

    def test_recovery_receipt_immutability(self):
        """Test that finalized recovery receipts cannot be altered by users."""
        handover = Handover(
            claim=self.approved_claim,
            item=self.found_item,
            claimant=self.claimant,
            held_by=self.finder
        )
        raw_otp = handover.generate_otp()
        handover.save()
        handover.verify_otp(raw_otp)

        receipt = RecoveryReceipt.objects.get(handover=handover)
        self.assertTrue(receipt.is_finalized)

        receipt.claimant_name = "Hacker Name"
        with self.assertRaises(ValidationError):
            receipt.clean()

    def test_qr_code_tag_generation(self):
        """Test printable item tag generation contains canonical item URL without private secrets or QR images."""
        tag_context = TagService.generate_tag_context(self.found_item)
        self.assertIn('safe_url', tag_context)
        self.assertIn(f"/{self.found_item.pk}/", tag_context['safe_url'])
        self.assertNotIn(self.finder.email, tag_context['safe_url'])
        self.assertNotIn(self.finder.phone_number, tag_context['safe_url'])

        # Printable item tag page accessible via both 'item_tag' and backward-compatible 'qr_tag' routes
        res_tag = self.client.get(reverse('items:item_tag', kwargs={'pk': self.found_item.pk}))
        self.assertEqual(res_tag.status_code, 200)
        self.assertContains(res_tag, self.found_item.item_code)
        self.assertNotContains(res_tag, 'data:image/png;base64')
        self.assertNotContains(res_tag, 'qr-matrix-box')

        res_qr = self.client.get(reverse('items:qr_tag', kwargs={'pk': self.found_item.pk}))
        self.assertEqual(res_qr.status_code, 200)
        self.assertContains(res_qr, self.found_item.item_code)

    def test_anonymous_messaging_and_abuse_reporting(self):
        """Test anonymous communication and abuse flagging."""
        conv = CommunicationService.get_or_create_conversation(
            self.found_item,
            self.claimant,
            self.finder,
            claim=self.approved_claim
        )
        self.assertTrue(CommunicationService.can_access(conv, self.claimant))
        self.assertTrue(CommunicationService.can_access(conv, self.finder))
        self.assertFalse(CommunicationService.can_access(conv, self.stranger))

        # Send message
        msg = CommunicationService.send_message(conv, self.claimant, "Where can we meet at library?")
        self.assertEqual(conv.messages.count(), 1)

        # Flag for abuse
        CommunicationService.report_abuse(msg, self.finder, "Inappropriate content")
        msg.refresh_from_db()
        self.assertTrue(msg.is_flagged_for_abuse)
        self.assertEqual(msg.flagged_by, self.finder)

    def test_reward_award_and_duplicate_prevention(self):
        """Test that reward points are awarded and duplicate payouts are prevented."""
        RewardRule.objects.get_or_create(action_type='item_returned', defaults={'points': 50, 'is_active': True})

        handover = Handover(
            claim=self.approved_claim,
            item=self.found_item,
            claimant=self.claimant,
            held_by=self.finder
        )
        raw_otp = handover.generate_otp()
        handover.save()
        handover.verify_otp(raw_otp)

        initial_points = self.finder.reward_points or 0
        tx, badges = RewardService.award_handover_reward(handover)
        self.assertIsNotNone(tx)

        self.finder.refresh_from_db()
        self.assertEqual(self.finder.reward_points, initial_points + 50)

        # Attempt duplicate reward payout for same handover
        tx_duplicate, _ = RewardService.award_handover_reward(handover)
        self.assertEqual(tx_duplicate.pk, tx.pk)

        self.finder.refresh_from_db()
        # Points should NOT have doubled
        self.assertEqual(self.finder.reward_points, initial_points + 50)

    def test_notification_preferences_respected(self):
        """Test that turning off notifications in preferences prevents alerts."""
        pref, _ = NotificationPreference.objects.get_or_create(user=self.claimant)
        pref.notify_on_handover = False
        pref.save()

        handover = Handover(
            claim=self.approved_claim,
            item=self.found_item,
            claimant=self.claimant,
            held_by=self.finder
        )
        handover.generate_otp()
        handover.save()

        NotificationService.notify_handover_initiated(handover)

        # Claimant opted out, so no notification should exist for claimant
        claimant_notes = Notification.objects.filter(
            recipient=self.claimant,
            notification_type=Notification.TYPE_HANDOVER_INITIATED
        )
        self.assertEqual(claimant_notes.count(), 0)

        # Holder opted in by default, so notification should exist for holder
        holder_notes = Notification.objects.filter(
            recipient=self.finder,
            notification_type=Notification.TYPE_HANDOVER_INITIATED
        )
        self.assertEqual(holder_notes.count(), 1)

    def test_recovery_history_view_and_permissions(self):
        """
        Comprehensive test for /recovery-history/:
        1. Accessing without ValueError.
        2. Empty state when no records exist.
        3. Authenticated student can see their own recovery records.
        4. Other students cannot access private records of another student.
        5. Filtering by search query, category, status, and date.
        6. Sorting options work.
        7. Real CSV export returns formatted data.
        8. Summary KPI metrics match actual database records.
        """
        recovery_url = reverse('items:recovery_history')

        # 1. Unauthenticated redirect to login
        res = self.client.get(recovery_url)
        self.assertEqual(res.status_code, 302)

        # 2. Authenticated user with no records sees professional empty state
        self.client.force_login(self.stranger)
        res = self.client.get(recovery_url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "No Recovery History Yet")
        self.assertContains(res, "Browse Found Items")
        self.assertEqual(res.context['total_recovered'], 0)
        self.assertEqual(res.context['total_handovers'], 0)

        # 3. Create verified handover for claimant and finder
        handover = Handover(
            claim=self.approved_claim,
            item=self.found_item,
            claimant=self.claimant,
            held_by=self.finder,
            handover_location="Block 34 Helpdesk"
        )
        raw_otp = handover.generate_otp()
        handover.save()
        success, _ = handover.verify_otp(raw_otp)
        self.assertTrue(success)
        self.assertEqual(handover.status, Handover.STATUS_VERIFIED)

        # Award points to finder
        RewardService.award_handover_reward(handover)

        # 4. Claimant sees their own recovery record
        self.client.force_login(self.claimant)
        res_claimant = self.client.get(recovery_url)
        self.assertEqual(res_claimant.status_code, 200)
        self.assertContains(res_claimant, self.found_item.title)
        self.assertContains(res_claimant, self.found_item.item_code)
        self.assertContains(res_claimant, "Verified &amp; Recovered")
        self.assertEqual(res_claimant.context['total_recovered'], 1)
        self.assertEqual(res_claimant.context['total_handovers'], 1)

        # 5. Finder sees their own recovery record with points
        self.client.force_login(self.finder)
        res_finder = self.client.get(recovery_url)
        self.assertEqual(res_finder.status_code, 200)
        self.assertContains(res_finder, self.found_item.title)
        self.assertGreaterEqual(res_finder.context['total_reward_points'], 50)

        # 6. Third unrelated student CANNOT see claimant's/finder's recovery record
        self.client.force_login(self.stranger)
        res_stranger = self.client.get(recovery_url)
        self.assertEqual(res_stranger.status_code, 200)
        self.assertNotContains(res_stranger, self.found_item.item_code)
        self.assertEqual(res_stranger.context['total_recovered'], 0)

        # 7. Search filtering
        self.client.force_login(self.claimant)
        res_search_hit = self.client.get(f"{recovery_url}?q={self.found_item.title[:6]}")
        self.assertEqual(len(res_search_hit.context['page_obj']), 1)

        res_search_miss = self.client.get(f"{recovery_url}?q=NonExistentQueryXYZ")
        self.assertEqual(len(res_search_miss.context['page_obj']), 0)

        # 8. Category & Status & Date filtering
        res_cat = self.client.get(f"{recovery_url}?category={self.category.id}")
        self.assertEqual(len(res_cat.context['page_obj']), 1)

        res_status_verified = self.client.get(f"{recovery_url}?status=verified")
        self.assertEqual(len(res_status_verified.context['page_obj']), 1)

        res_status_failed = self.client.get(f"{recovery_url}?status=failed")
        self.assertEqual(len(res_status_failed.context['page_obj']), 0)

        res_date = self.client.get(f"{recovery_url}?date=today")
        self.assertEqual(len(res_date.context['page_obj']), 1)

        # 9. Sorting
        res_sort_newest = self.client.get(f"{recovery_url}?sort=newest")
        self.assertEqual(res_sort_newest.status_code, 200)

        res_sort_oldest = self.client.get(f"{recovery_url}?sort=oldest")
        self.assertEqual(res_sort_oldest.status_code, 200)

        res_sort_title = self.client.get(f"{recovery_url}?sort=title")
        self.assertEqual(res_sort_title.status_code, 200)

        # 10. Real CSV export
        res_csv = self.client.get(f"{recovery_url}?export=csv")
        self.assertEqual(res_csv.status_code, 200)
        self.assertEqual(res_csv['Content-Type'], 'text/csv; charset=utf-8')
        content = res_csv.content.decode('utf-8')
        self.assertIn("Item Title", content)
        self.assertIn(self.found_item.title, content)
        self.assertIn(self.found_item.item_code, content)

        # 11. Handover Detail opens without error and displays item & claim info
        res_detail = self.client.get(reverse('items:handover_detail', kwargs={'pk': handover.pk}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, self.found_item.title)
        self.assertContains(res_detail, self.found_item.item_code)
        self.assertContains(res_detail, f"Claim #{self.approved_claim.pk}")


