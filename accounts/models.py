from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    ROLE_STUDENT = 'student'
    ROLE_FACULTY = 'faculty'
    ROLE_STAFF = 'staff'
    ROLE_ADMIN = 'admin'

    ROLE_CHOICES = [
        (ROLE_STUDENT, 'Student'),
        (ROLE_FACULTY, 'Faculty Member'),
        (ROLE_STAFF, 'Campus Staff / Security'),
        (ROLE_ADMIN, 'Administrator'),
    ]

    email = models.EmailField(unique=True)
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_STUDENT,
        help_text="Designates the user's campus role."
    )
    student_id = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
        help_text="Student Roll Number / Faculty or Staff ID"
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="Contact phone number (kept private based on contact preferences)"
    )
    institution = models.ForeignKey(
        'core.Institution',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        help_text="Institution this user belongs to"
    )
    department = models.ForeignKey(
        'core.Department',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users',
        help_text="Academic or administrative department"
    )
    department_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Fallback department text"
    )
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        null=True
    )
    reward_points = models.PositiveIntegerField(
        default=0,
        help_text="Points awarded for returning lost items to owners"
    )

    @property
    def is_student_user(self):
        return self.role == self.ROLE_STUDENT

    @property
    def is_faculty_user(self):
        return self.role == self.ROLE_FACULTY

    @property
    def is_staff_member(self):
        return self.role in (self.ROLE_STAFF, self.ROLE_ADMIN) or self.is_staff or self.is_superuser

    @property
    def is_admin_user(self):
        return self.role == self.ROLE_ADMIN or self.is_superuser

    @property
    def display_name(self):
        full = f"{self.first_name} {self.last_name}".strip()
        return full if full else self.username

    @property
    def display_department(self):
        if self.department:
            return self.department.name
        return self.department_name or "General Campus"

    def clean(self):
        super().clean()
        if self.role == self.ROLE_STUDENT and not self.student_id:
            raise ValidationError({'student_id': 'Student ID / Roll No is required for students.'})

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
