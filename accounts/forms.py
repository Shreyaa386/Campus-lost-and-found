from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from PIL import Image
from core.models import Department, Institution

User = get_user_model()


class UserRegistrationForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Create a strong password',
            'autocomplete': 'new-password'
        }),
        help_text="Must contain at least 8 characters, avoiding common sequences."
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Confirm your password',
            'autocomplete': 'new-password'
        })
    )

    class Meta:
        model = User
        fields = [
            'role',
            'first_name',
            'last_name',
            'username',
            'email',
            'student_id',
            'institution',
            'department',
            'phone_number',
            'profile_picture',
        ]
        widgets = {
            'role': forms.Select(attrs={'class': 'form-select', 'id': 'id_role'}),
            'first_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. John'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Doe'}),
            'username': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Choose unique username'}),
            'email': forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'e.g. student@ait.edu'}),
            'student_id': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Roll No / Student ID / Staff ID'}),
            'institution': forms.Select(attrs={'class': 'form-select'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '+91 98765 43210'}),
            'profile_picture': forms.FileInput(attrs={'class': 'form-file-input', 'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['institution'].queryset = Institution.objects.filter(is_active=True)
        self.fields['department'].queryset = Department.objects.filter(is_active=True)
        # Select first active institution by default if available
        if not self.initial.get('institution'):
            first_inst = Institution.objects.filter(is_active=True).first()
            if first_inst:
                self.fields['institution'].initial = first_inst
        if not self.initial.get('role'):
            self.fields['role'].initial = User.ROLE_STUDENT
        # Make username, role, and institution optional in UI so wireframe fields work cleanly
        self.fields['username'].required = False
        self.fields['role'].required = False
        self.fields['institution'].required = False

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account with this email address already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if not username:
            email = self.cleaned_data.get('email', '').strip()
            if email:
                base_username = email.split('@')[0].lower()
                username = base_username
                counter = 1
                while User.objects.filter(username__iexact=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1
            else:
                username = f"user_{User.objects.count() + 1}"
        elif User.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already taken. Please choose another.")
        return username

    def clean_student_id(self):
        role = self.cleaned_data.get('role') or User.ROLE_STUDENT
        student_id = self.cleaned_data.get('student_id', '').strip()
        if role == User.ROLE_STUDENT and not student_id:
            raise ValidationError("Student Roll Number / Student ID is required for student registration.")
        if student_id and User.objects.filter(student_id__iexact=student_id).exists():
            raise ValidationError("This Student ID / Staff ID is already registered.")
        return student_id or None

    def clean_profile_picture(self):
        picture = self.cleaned_data.get('profile_picture')
        if picture:
            # File size limit (5MB)
            if picture.size > 5 * 1024 * 1024:
                raise ValidationError("Profile picture file size must not exceed 5MB.")
            # File extension check
            ext = picture.name.lower().split('.')[-1]
            if ext not in ['jpg', 'jpeg', 'png', 'webp']:
                raise ValidationError("Allowed image formats are JPG, JPEG, PNG, and WEBP.")
            # Image integrity validation using Pillow
            try:
                img = Image.open(picture)
                img.verify()
            except Exception:
                raise ValidationError("Uploaded file is not a valid or readable image.")
        return picture

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password:
            if password != confirm_password:
                self.add_error('confirm_password', "Passwords do not match.")
            else:
                # Validate against Django password validators
                try:
                    validate_password(password)
                except ValidationError as e:
                    self.add_error('password', e)

        if not cleaned_data.get('role'):
            cleaned_data['role'] = User.ROLE_STUDENT
        if not cleaned_data.get('institution'):
            first_inst = Institution.objects.filter(is_active=True).first()
            if first_inst:
                cleaned_data['institution'] = first_inst

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class UserLoginForm(forms.Form):
    username_or_email = forms.CharField(
        label="Username, Campus Email, or Student ID",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Enter username, email, or Student ID',
            'autofocus': True,
        })
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Enter password',
            'autocomplete': 'current-password',
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'})
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        username_or_email = self.cleaned_data.get('username_or_email', '').strip()
        password = self.cleaned_data.get('password')

        if username_or_email and password:
            # 1. Try authenticating directly by username
            self.user_cache = authenticate(self.request, username=username_or_email, password=password)

            # 2. If failed, look up user by email
            if self.user_cache is None:
                try:
                    user_obj = User.objects.get(email__iexact=username_or_email)
                    self.user_cache = authenticate(self.request, username=user_obj.username, password=password)
                except (User.DoesNotExist, User.MultipleObjectsReturned):
                    pass

            # 3. If failed, look up user by student_id
            if self.user_cache is None:
                try:
                    user_obj = User.objects.get(student_id__iexact=username_or_email)
                    self.user_cache = authenticate(self.request, username=user_obj.username, password=password)
                except (User.DoesNotExist, User.MultipleObjectsReturned):
                    pass

            if self.user_cache is None:
                raise ValidationError("Invalid username, email, student ID, or password. Please try again.")
            elif not self.user_cache.is_active:
                raise ValidationError("This account is currently inactive. Please contact administration.")

        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class UserProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            'first_name',
            'last_name',
            'phone_number',
            'department',
            'profile_picture',
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-input'}),
            'last_name': forms.TextInput(attrs={'class': 'form-input'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-input', 'placeholder': '+91 98765 43210'}),
            'department': forms.Select(attrs={'class': 'form-select'}),
            'profile_picture': forms.FileInput(attrs={'class': 'form-file-input', 'accept': 'image/*'}),
        }

    def clean_profile_picture(self):
        picture = self.cleaned_data.get('profile_picture')
        if picture and hasattr(picture, 'size'):
            if picture.size > 5 * 1024 * 1024:
                raise ValidationError("Profile picture file size must not exceed 5MB.")
            ext = picture.name.lower().split('.')[-1]
            if ext not in ['jpg', 'jpeg', 'png', 'webp']:
                raise ValidationError("Allowed formats: JPG, JPEG, PNG, WEBP.")
            try:
                img = Image.open(picture)
                img.verify()
            except Exception:
                raise ValidationError("Uploaded file is not a valid image.")
        return picture

