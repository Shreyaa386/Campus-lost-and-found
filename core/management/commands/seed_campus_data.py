from django.core.management.base import BaseCommand
from core.models import Institution, Department, CampusLocation, Category
from items.models import ExpirationRule, RewardRule, Badge, MilestoneReward


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

        # 3. Exactly 62 Campus Locations (Block 1 - Block 56, Central Library, SDMA, DSW, UniMall, Main Gate, Food Court)
        raw_locations_62 = [
            f"Block {i}" for i in range(1, 57)
        ] + [
            "Central Library",
            "SDMA",
            "DSW",
            "UniMall",
            "Main Gate",
            "Food Court",
        ]

        active_location_names = set(raw_locations_62)

        # Handle existing locations gracefully without breaking reports
        for existing_loc in CampusLocation.objects.filter(institution=institution):
            if existing_loc.name == "Main Campus Gate & Security Desk":
                existing_loc.name = "Main Gate"
                existing_loc.building = ""
                existing_loc.sort_order = 61
                existing_loc.is_active = True
                existing_loc.save()
            elif existing_loc.name not in active_location_names:
                existing_loc.is_active = False
                existing_loc.save(update_fields=['is_active'])

        for order, loc_name in enumerate(raw_locations_62, start=1):
            loc, loc_created = CampusLocation.objects.get_or_create(
                institution=institution,
                name=loc_name,
                defaults={
                    'building': '',
                    'floor': '',
                    'sort_order': order,
                    'is_active': True,
                }
            )
            if not loc_created:
                loc.sort_order = order
                loc.is_active = True
                loc.save(update_fields=['sort_order', 'is_active'])
            if loc_created:
                self.stdout.write(f"  + Location: {loc_name} (#{order})")

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

        # 7. Milestone Badges & Academic Duty Leave (DL) Rewards
        badges_data = [
            ('Good Samaritan', 'first-return', 'Safely returned your first found item on campus.', 'fa-handshake', 0, 1, '2 DL'),
            ('Campus Guardian', 'campus-guardian', 'Helped return 5 lost items on campus.', 'fa-shield-halved', 0, 5, '4 DL'),
            ('Campus Legend', 'campus-legend', 'Returned more than 5 items (6+ returns) on campus.', 'fa-crown', 0, 6, '1 Week DL'),
            ('Century Club', 'century-club', 'Accumulated over 100 CampusCare recovery points.', 'fa-trophy', 100, 0, ''),
            ('Master Finder', 'master-finder', 'Elite campus recovery contributor with 10+ returns.', 'fa-medal', 250, 10, ''),
        ]
        for name, slug, desc, icon, pts_th, ret_th, reward in badges_data:
            bdg, bdg_created = Badge.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': name,
                    'description': desc,
                    'icon': icon,
                    'points_threshold': pts_th,
                    'returns_threshold': ret_th,
                    'reward': reward,
                }
            )
            if not bdg_created:
                bdg.name = name
                bdg.description = desc
                bdg.returns_threshold = ret_th
                bdg.reward = reward
                bdg.save()
            if bdg_created:
                self.stdout.write(f"  + Badge: {name}")

        # 7b. Academic Duty Leave (DL) Milestone Rewards
        from items.services.reward_service import RewardService
        RewardService.ensure_default_milestones()
        self.stdout.write(self.style.SUCCESS("  + Seeded 3 DL Milestones: 1 Item (2 DL), 5 Items (4 DL), 6+ Items (1 Week DL)"))

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

