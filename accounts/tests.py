from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from core.models import Department, Institution

User = get_user_model()


class AuthenticationAndUserModelTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.institution = Institution.objects.create(
            name="Apex Institute of Technology",
            short_name="AIT"
        )
        self.department = Department.objects.create(
            institution=self.institution,
            name="Computer Science & Engineering",
            code="CSE"
        )
        self.student = User.objects.create_user(
            username="john_student",
            email="john@ait.edu",
            password="StrongPassword123!",
            role=User.ROLE_STUDENT,
            student_id="2024CS01",
            first_name="John",
            last_name="Doe",
            institution=self.institution,
            department=self.department
        )
        self.staff_user = User.objects.create_user(
            username="sarah_staff",
            email="sarah@ait.edu",
            password="StaffPassword123!",
            role=User.ROLE_STAFF,
            first_name="Sarah",
            last_name="Connor",
            institution=self.institution
        )

    def test_user_roles_and_properties(self):
        self.assertTrue(self.student.is_student_user)
        self.assertFalse(self.student.is_staff_member)
        self.assertEqual(self.student.display_name, "John Doe")
        self.assertEqual(self.student.display_department, "Computer Science & Engineering")

        self.assertTrue(self.staff_user.is_staff_member)
        self.assertFalse(self.staff_user.is_student_user)

    def test_student_id_validation_for_student_role(self):
        user_without_id = User(
            username="nostudentid",
            email="no@ait.edu",
            role=User.ROLE_STUDENT
        )
        with self.assertRaises(ValidationError):
            user_without_id.clean()

    def test_student_registration_view(self):
        response = self.client.post(reverse('accounts:register'), {
            'role': User.ROLE_STUDENT,
            'username': 'alex_smith',
            'email': 'alex@ait.edu',
            'first_name': 'Alex',
            'last_name': 'Smith',
            'student_id': '2024CS02',
            'institution': self.institution.pk,
            'department': self.department.pk,
            'password': 'SecurePassWord789!',
            'confirm_password': 'SecurePassWord789!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='alex_smith').exists())

    def test_registration_password_mismatch(self):
        response = self.client.post(reverse('accounts:register'), {
            'role': User.ROLE_STUDENT,
            'username': 'bad_pass',
            'email': 'bad@ait.edu',
            'student_id': '2024CS99',
            'password': 'PasswordOne123!',
            'confirm_password': 'PasswordTwo123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='bad_pass').exists())

    def test_login_with_username(self):
        response = self.client.post(reverse('accounts:login'), {
            'username_or_email': 'john_student',
            'password': 'StrongPassword123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_login_with_email(self):
        response = self.client.post(reverse('accounts:login'), {
            'username_or_email': 'john@ait.edu',
            'password': 'StrongPassword123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_logout(self):
        self.client.login(username='john_student', password='StrongPassword123!')
        response = self.client.post(reverse('accounts:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_profile_view_authenticated(self):
        self.client.login(username='john_student', password='StrongPassword123!')
        response = self.client.get(reverse('accounts:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2024CS01")


class AuthFirstAndDashboardRedesignTest(TestCase):
    """
    Integration tests covering all 12 acceptance criteria for the
    Authentication-First UI and Dashboard Redesign.
    """
    def setUp(self):
        self.client = Client()
        self.institution = Institution.objects.create(
            name="Apex Institute of Technology",
            short_name="AIT"
        )
        self.department = Department.objects.create(
            institution=self.institution,
            name="Computer Science & Engineering",
            code="CSE"
        )
        self.student = User.objects.create_user(
            username="emily_davis",
            email="emily@ait.edu",
            password="StrongPassword456!",
            role=User.ROLE_STUDENT,
            student_id="2024CS55",
            first_name="Emily",
            last_name="Davis",
            institution=self.institution,
            department=self.department
        )

    def test_1_root_url_unauthenticated_redirects_to_login(self):
        """Criterion 1: Opening / without authentication redirects to Login."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_2_login_page_renders_clean_auth_view(self):
        """Criterion 2: Login page is displayed correctly without student nav links."""
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome to CampusCare")
        self.assertContains(response, "Username, Campus Email, or Student ID")
        self.assertContains(response, "password-toggle-btn")
        self.assertContains(response, "Join CampusCare")
        # Ensure student navigation menu is not displayed on login
        self.assertNotContains(response, 'class="nav-links"')

    def test_3_signup_page_renders_student_registration_view(self):
        """Criterion 3: Signup page works and renders clean student form."""
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Join CampusCare")
        self.assertContains(response, "Student ID / Roll No")
        self.assertContains(response, "password-toggle-btn")
        self.assertContains(response, "Sign In here")
        # Ensure student navigation menu is not displayed on signup
        self.assertNotContains(response, 'class="nav-links"')

    def test_4_valid_registration_creates_user_and_auto_logins(self):
        """Criterion 4: Valid registration creates a user and redirects to dashboard."""
        response = self.client.post(reverse('register'), {
            'role': User.ROLE_STUDENT,
            'username': 'ryan_gosling',
            'email': 'ryan@ait.edu',
            'first_name': 'Ryan',
            'last_name': 'Gosling',
            'student_id': '2024CS77',
            'institution': self.institution.pk,
            'department': self.department.pk,
            'password': 'SecurePassword789!',
            'confirm_password': 'SecurePassword789!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('dashboard'), response.url)
        self.assertTrue(User.objects.filter(username='ryan_gosling').exists())
        # Confirms user is automatically logged in
        self.assertIn('_auth_user_id', self.client.session)

    def test_5_login_with_student_id_and_email(self):
        """Criterion 5: Valid login by Student ID or Email redirects to dashboard."""
        # Login via Student ID
        response = self.client.post(reverse('login'), {
            'username_or_email': '2024CS55',
            'password': 'StrongPassword456!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('dashboard'), response.url)
        self.assertIn('_auth_user_id', self.client.session)

        # Logout then login via Email
        self.client.logout()
        response2 = self.client.post(reverse('login'), {
            'username_or_email': 'emily@ait.edu',
            'password': 'StrongPassword456!',
        })
        self.assertEqual(response2.status_code, 302)
        self.assertIn(reverse('dashboard'), response2.url)
        self.assertIn('_auth_user_id', self.client.session)

    def test_6_invalid_login_displays_error(self):
        """Criterion 6: Invalid login displays an appropriate error."""
        response = self.client.post(reverse('login'), {
            'username_or_email': '2024CS55',
            'password': 'WrongPassword999!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid credentials")
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_7_authenticated_users_redirected_from_auth_pages(self):
        """Criterion 7: Authenticated users accessing login, register, or root redirect to dashboard."""
        self.client.login(username='emily_davis', password='StrongPassword456!')

        # Root /
        resp_root = self.client.get('/')
        self.assertEqual(resp_root.status_code, 302)
        self.assertIn(reverse('dashboard'), resp_root.url)

        # Login /login/
        resp_login = self.client.get(reverse('login'))
        self.assertEqual(resp_login.status_code, 302)
        self.assertIn(reverse('dashboard'), resp_login.url)

        # Register /register/
        resp_reg = self.client.get(reverse('register'))
        self.assertEqual(resp_reg.status_code, 302)
        self.assertIn(reverse('dashboard'), resp_reg.url)

    def test_8_unauthenticated_cannot_access_private_pages(self):
        """Criterion 8: Unauthenticated users cannot access private pages."""
        # Dashboard
        resp_dash = self.client.get(reverse('dashboard'))
        self.assertEqual(resp_dash.status_code, 302)
        self.assertIn(reverse('login'), resp_dash.url)

        # Profile
        resp_prof = self.client.get(reverse('profile'))
        self.assertEqual(resp_prof.status_code, 302)
        self.assertIn(reverse('login'), resp_prof.url)

        # Recovery History
        resp_rec = self.client.get(reverse('items:recovery_history'))
        self.assertEqual(resp_rec.status_code, 302)
        self.assertIn(reverse('login'), resp_rec.url)

    def test_9_logout_redirects_to_login(self):
        """Criterion 9: Logout redirects directly to Login."""
        self.client.login(username='emily_davis', password='StrongPassword456!')
        response = self.client.post(reverse('logout'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_10_refreshing_dashboard_preserves_authentication(self):
        """Criterion 10: Refreshing the dashboard preserves authentication."""
        self.client.login(username='emily_davis', password='StrongPassword456!')
        resp1 = self.client.get(reverse('dashboard'))
        self.assertEqual(resp1.status_code, 200)
        self.assertContains(resp1, "Welcome back, Emily Davis!")

        resp2 = self.client.get(reverse('dashboard'))
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "Welcome back, Emily Davis!")
        self.assertIn('_auth_user_id', self.client.session)

    def test_11_dashboard_statistics_use_actual_database_data(self):
        """Criterion 11: Dashboard statistics use actual database data."""
        from items.models import Item
        from core.models import Category, CampusLocation
        from django.utils import timezone

        cat = Category.objects.create(name="Books", slug="books", institution=self.institution)
        loc = CampusLocation.objects.create(name="Library", institution=self.institution)

        # Create 2 lost items and 1 found item
        Item.objects.create(
            user=self.student,
            institution=self.institution,
            report_type='lost',
            title='Calculus Textbook',
            category=cat,
            location=loc,
            date_lost_or_found=timezone.localdate(),
            status='open'
        )
        Item.objects.create(
            user=self.student,
            institution=self.institution,
            report_type='lost',
            title='Physics Notebook',
            category=cat,
            location=loc,
            date_lost_or_found=timezone.localdate(),
            status='open'
        )
        Item.objects.create(
            user=self.student,
            institution=self.institution,
            report_type='found',
            title='Blue Water Bottle',
            category=cat,
            location=loc,
            date_lost_or_found=timezone.localdate(),
            status='open'
        )

        self.client.login(username='emily_davis', password='StrongPassword456!')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

        stats = response.context['stats']
        self.assertEqual(stats['total_lost'], 2)
        self.assertEqual(stats['total_found'], 1)
        self.assertEqual(stats['active_reports'], 3)

    def test_12_navigation_links_functional_for_authenticated_student(self):
        """Criterion 12: Authenticated student navigation menu links are functional."""
        self.client.login(username='emily_davis', password='StrongPassword456!')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

        # Verify key functional navigation targets exist in rendered HTML
        self.assertContains(response, reverse('items:dashboard'))
        self.assertContains(response, reverse('items:lost_items'))
        self.assertContains(response, reverse('items:found_items'))
        self.assertContains(response, reverse('items:report_item', kwargs={'report_type': 'lost'}))
        self.assertContains(response, reverse('items:report_item', kwargs={'report_type': 'found'}))
        self.assertContains(response, reverse('items:my_claims'))
        self.assertContains(response, reverse('items:recovery_history'))
        self.assertContains(response, reverse('items:rewards'))
        self.assertContains(response, reverse('assistant'))
        self.assertContains(response, reverse('accounts:profile'))

    def test_13_split_screen_layout_and_illustrations(self):
        """Test split-screen structure and campus-themed illustrations on Login and Signup."""
        # 1. Login page split layout
        resp_login = self.client.get(reverse('login'))
        self.assertEqual(resp_login.status_code, 200)
        self.assertContains(resp_login, 'auth-split-wrapper')
        self.assertContains(resp_login, 'auth-split-left')
        self.assertContains(resp_login, 'auth-split-right')
        self.assertContains(resp_login, 'Welcome Back')
        self.assertContains(resp_login, 'Sign In')
        # Check campus illustrations on right panel
        self.assertContains(resp_login, 'university-building')
        self.assertContains(resp_login, 'student-id-card')
        self.assertContains(resp_login, 'campus-key')
        self.assertContains(resp_login, 'security-lock')
        self.assertContains(resp_login, 'student-backpack')
        self.assertContains(resp_login, 'lost-and-found-box')

        # 2. Signup page split layout
        resp_signup = self.client.get(reverse('register'))
        self.assertEqual(resp_signup.status_code, 200)
        self.assertContains(resp_signup, 'auth-split-wrapper')
        self.assertContains(resp_signup, 'auth-split-left')
        self.assertContains(resp_signup, 'auth-split-right')
        self.assertContains(resp_signup, 'Join CampusCare')
        self.assertContains(resp_signup, 'Create Account')
        self.assertContains(resp_signup, 'university-building')
        self.assertContains(resp_signup, 'student-id-card')
        self.assertContains(resp_signup, 'campus-key')
        self.assertContains(resp_signup, 'security-lock')
        self.assertContains(resp_signup, 'student-backpack')
        self.assertContains(resp_signup, 'lost-and-found-box')

    def test_14_signup_with_wireframe_fields_only(self):
        """Test that submitting only the wireframe fields successfully creates user and logs in."""
        response = self.client.post(reverse('register'), {
            'first_name': 'Mark',
            'last_name': 'Ruffalo',
            'email': 'mark@ait.edu',
            'student_id': '2024CS88',
            'department': self.department.pk,
            'password': 'SecurePassword999!',
            'confirm_password': 'SecurePassword999!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('dashboard'), response.url)
        user = User.objects.filter(email='mark@ait.edu').first()
        self.assertIsNotNone(user)
        self.assertEqual(user.first_name, 'Mark')
        self.assertEqual(user.student_id, '2024CS88')
        self.assertEqual(user.role, User.ROLE_STUDENT)
        self.assertIn('_auth_user_id', self.client.session)

    def test_15_signup_url_and_auth_base_inheritance(self):
        """Test /signup/ route and verify single content block rendering across pages."""
        # 1. /signup/ GET
        resp_signup = self.client.get('/signup/')
        self.assertEqual(resp_signup.status_code, 200)
        self.assertContains(resp_signup, 'Join CampusCare')
        self.assertContains(resp_signup, 'auth-split-wrapper')
        self.assertContains(resp_signup, 'university-building')

        # 2. /login/ GET
        resp_login = self.client.get('/login/')
        self.assertEqual(resp_login.status_code, 200)
        self.assertContains(resp_login, 'Welcome Back')
        self.assertContains(resp_login, 'auth-split-wrapper')

        # 3. Root / redirects to /login/ when unauthenticated
        resp_root = self.client.get('/')
        self.assertEqual(resp_root.status_code, 302)
        self.assertIn('/login/', resp_root.url)

        # 4. Authenticated dashboard renders base.html without TemplateSyntaxError
        self.client.login(username='emily_davis', password='StrongPassword456!')
        resp_dash = self.client.get('/dashboard/')
        self.assertEqual(resp_dash.status_code, 200)
        self.assertContains(resp_dash, 'Welcome back')
        self.assertContains(resp_dash, 'navbar')
        self.assertContains(resp_dash, 'footer')



