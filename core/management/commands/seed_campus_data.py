from django.core.management.base import BaseCommand
from core.models import Institution, Department, CampusLocation, Category
from items.models import ExpirationRule, RewardRule, Badge


class Command(BaseCommand):
    help = 'Seeds initial campus institution, departments, locations, categories, and expiration rules.'

    def handle(self, *args, **options):
        # 1. Create or get default institution
        institution = Institution.objects.first()
        if not institution:
            institution = Institution.objects.create(
                slug='lpu-phagwara-punjab',
                name='Lovely Professional University (LPU), Phagwara, Punjab',
                short_name='LPU',
                domain='lpu.in',
                city='Phagwara',
                state='Punjab',
                address='Jalandhar - Delhi, Grand Trunk Rd, Phagwara, Punjab 144411',
                contact_email='lostandfound@lpu.in',
                contact_phone='+91 1824 517000',
                is_active=True,
            )
            self.stdout.write(self.style.SUCCESS(f"Created institution: {institution.name}"))
        else:
            institution.name = 'Lovely Professional University (LPU), Phagwara, Punjab'
            institution.short_name = 'LPU'
            institution.domain = 'lpu.in'
            institution.city = 'Phagwara'
            institution.state = 'Punjab'
            institution.address = 'Jalandhar - Delhi, Grand Trunk Rd, Phagwara, Punjab 144411'
            institution.contact_email = 'lostandfound@lpu.in'
            institution.save()
            self.stdout.write(f"Updated institution: {institution.name}")

        # 2. Departments
        departments_data = [
            ('Computer Science & Engineering', 'CSE'),
            ('Information Technology', 'IT'),
            ('Electronics & Communication Engineering', 'ECE'),
            ('Electrical & Electronics Engineering', 'EEE'),
            ('Mechanical Engineering', 'ME'),
            ('Civil Engineering', 'CE'),
            ('Management Studies', 'MBA'),
            ('Basic Sciences & Humanities', 'BSH'),
        ]
        for name, code in departments_data:
            dept, dept_created = Department.objects.get_or_create(
                institution=institution,
                code=code,
                defaults={'name': name, 'is_active': True}
            )
            if dept_created:
                self.stdout.write(f"  + Department: {name} ({code})")

        # 3. Campus Locations (with GPS coordinates for campus heatmap)
        locations_data = [
            ('Central Library - Ground Floor Reading Room', 'Library Building', 'Ground Floor', 12.9719, 77.5942),
            ('Central Library - 2nd Floor Digital Lab', 'Library Building', '2nd Floor', 12.9720, 77.5943),
            ('Main Student Cafeteria', 'Student Activity Center', 'Ground Floor', 12.9712, 77.5950),
            ('Academic Block A - CSE Lab 3', 'Academic Block A', '3rd Floor', 12.9725, 77.5938),
            ('Academic Block B - Lecture Hall 101', 'Academic Block B', '1st Floor', 12.9728, 77.5945),
            ('Sports Complex & Gymnasium', 'Sports Complex', 'Ground Floor', 12.9705, 77.5955),
            ('Campus Auditorium', 'Admin Complex', 'Ground Floor', 12.9715, 77.5935),
            ('Main Campus Gate & Security Desk', 'Main Gate', 'Ground Floor', 12.9700, 77.5940),
            ('Student Parking Lot B', 'Parking Zone', 'Open Ground', 12.9702, 77.5948),
        ]
        for name, building, floor, lat, lng in locations_data:
            loc, loc_created = CampusLocation.objects.get_or_create(
                institution=institution,
                name=name,
                defaults={'building': building, 'floor': floor, 'latitude': lat, 'longitude': lng, 'is_active': True}
            )
            if not loc_created:
                # Update lat/lng if not set
                if loc.latitude is None or loc.longitude is None:
                    loc.latitude = lat
                    loc.longitude = lng
                    loc.save(update_fields=['latitude', 'longitude'])
            if loc_created:
                self.stdout.write(f"  + Location: {name}")

        # 4. Item Categories
        categories_data = [
            ('Electronics & Gadgets', 'electronics-gadgets', 'fa-laptop', 'Laptops, phones, headphones, chargers, power banks'),
            ('IDs & Access Cards', 'ids-access-cards', 'fa-id-card', 'Student IDs, driver licenses, ATM cards, library cards'),
            ('Keys & Keychains', 'keys-keychains', 'fa-key', 'Room keys, bike/car keys, locker keys'),
            ('Bags, Wallets & Purses', 'bags-wallets', 'fa-wallet', 'Backpacks, purses, wallets, pouches'),
            ('Books & Stationery', 'books-stationery', 'fa-book', 'Notebooks, textbooks, calculators, pencil pouches'),
            ('Bottles & Daily Essentials', 'bottles-essentials', 'fa-flask', 'Water bottles, umbrella, lunch boxes'),
            ('Clothing & Accessories', 'clothing-accessories', 'fa-tshirt', 'Jackets, spectacles, wristwatches, jewelry'),
            ('Other Belongings', 'other', 'fa-box', 'Miscellaneous items not classified above'),
        ]
        for name, slug, icon, desc in categories_data:
            cat, cat_created = Category.objects.get_or_create(
                slug=slug,
                defaults={
                    'institution': institution,
                    'name': name,
                    'icon': icon,
                    'description': desc,
                    'is_active': True,
                }
            )
            if cat_created:
                self.stdout.write(f"  + Category: {name}")

        # 5. Default Expiration Rule
        rule, rule_created = ExpirationRule.objects.get_or_create(
            institution=institution,
            category=None,
            report_type='all',
            defaults={'days_to_expire': 30, 'is_active': True}
        )
        if rule_created:
            self.stdout.write(self.style.SUCCESS(f"Created default 30-day expiration rule."))

        # 6. Default Reward Rules
        reward_rules = [
            ('item_returned', 50, 'Awarded for safely returning a found item via verified OTP handover.'),
            ('handover_confirmed', 25, 'Awarded for confirming item handover at campus desk.'),
            ('report_submitted', 10, 'Awarded for lodging an accurate lost/found report.'),
        ]
        for action_type, points, desc in reward_rules:
            rr, rr_created = RewardRule.objects.get_or_create(
                action_type=action_type,
                defaults={'points': points, 'description': desc, 'is_active': True}
            )
            if rr_created:
                self.stdout.write(f"  + Reward Rule: {action_type} ({points} pts)")

        # 7. Milestone Badges
        badges_data = [
            ('Good Samaritan', 'first-return', 'Safely returned your first found item on campus.', 'fa-handshake', 0, 1),
            ('Campus Guardian', 'campus-guardian', 'Helped return 5 lost items on campus.', 'fa-shield-halved', 0, 5),
            ('Century Club', 'century-club', 'Accumulated over 100 CampusCare recovery points.', 'fa-trophy', 100, 0),
            ('Master Finder', 'master-finder', 'Elite campus recovery contributor with 10+ returns.', 'fa-crown', 250, 10),
        ]
        for name, slug, desc, icon, pts_th, ret_th in badges_data:
            bdg, bdg_created = Badge.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'description': desc,
                    'icon': icon,
                    'points_threshold': pts_th,
                    'returns_threshold': ret_th,
                }
            )
            if bdg_created:
                self.stdout.write(f"  + Badge: {name}")

        # 8. Subscription Plans & Institutional Subscription
        from core.models import SubscriptionPlan, InstitutionSubscription
        from django.utils import timezone
        from datetime import timedelta

        plans_data = [
            (
                'Campus Starter (Free)', 'free',
                'Essential lost & found tools for small campus communities.',
                0.00, 0.00, 50, 2, True, False, False, False, False
            ),
            (
                'College Professional', 'pro',
                'Advanced smart matching, AI Assistant, custom domain, and predictive trend analytics.',
                1499.00, 14990.00, 500, 10, True, True, True, False, True
            ),
            (
                'University Enterprise', 'enterprise',
                'Unlimited campus items, full college ERP sync, multi-facility governance, and dedicated support.',
                4999.00, 49990.00, 10000, 50, True, True, True, True, True
            ),
        ]

        for p_name, p_code, p_desc, p_mo, p_yr, max_it, max_st, ai_en, pred_en, dom_en, erp_en, notif_en in plans_data:
            plan, p_created = SubscriptionPlan.objects.get_or_create(
                code=p_code,
                defaults={
                    'name': p_name,
                    'description': p_desc,
                    'price_monthly': p_mo,
                    'price_annual': p_yr,
                    'max_active_items': max_it,
                    'max_staff_accounts': max_st,
                    'ai_chatbot_enabled': ai_en,
                    'predictive_analytics_enabled': pred_en,
                    'custom_domain_enabled': dom_en,
                    'erp_integration_enabled': erp_en,
                    'sms_whatsapp_notifications_enabled': notif_en,
                    'is_active': True
                }
            )
            if p_created:
                self.stdout.write(f"  + Subscription Plan: {p_name}")

        # Set default ERP API key for AIT if unset
        if not institution.erp_api_key:
            institution.erp_api_key = 'ait_erp_secret_key_2026'
            institution.save(update_fields=['erp_api_key'])

        # Assign Pro subscription to AIT for testing
        pro_plan = SubscriptionPlan.objects.get(code='pro')
        sub, sub_created = InstitutionSubscription.objects.get_or_create(
            institution=institution,
            defaults={
                'plan': pro_plan,
                'status': InstitutionSubscription.STATUS_ACTIVE,
                'billing_cycle': InstitutionSubscription.CYCLE_ANNUAL,
                'current_period_start': timezone.now(),
                'current_period_end': timezone.now() + timedelta(days=365)
            }
        )

        self.stdout.write(self.style.SUCCESS("Initial campus data seeding completed!"))

