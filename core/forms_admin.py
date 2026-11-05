"""
Forms for the CampusCare Administrator and Security Dashboard.
Includes role management, location GPS coordinates, category management,
alert moderation, and report export filters.
"""

from django import forms
from django.contrib.auth import get_user_model
from core.models import CampusLocation, Category, SecurityAlert
from items.models import Item

User = get_user_model()


class UserRoleUpdateForm(forms.ModelForm):
    """Enforces strict role assignment and prevents unauthorized privilege escalation."""
    class Meta:
        model = User
        fields = ['role', 'is_active']
        widgets = {
            'role': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        self.actor = kwargs.pop('actor', None)
        self.target_user = kwargs.get('instance', None)
        super().__init__(*args, **kwargs)

        # Non-superusers cannot assign superuser-level capabilities
        if not getattr(self.actor, 'is_superuser', False):
            # Remove admin choice if actor is not an admin
            if getattr(self.actor, 'role', '') != User.ROLE_ADMIN:
                self.fields['role'].choices = [
                    (c, l) for c, l in self.fields['role'].choices if c != User.ROLE_ADMIN
                ]


class CampusLocationForm(forms.ModelForm):
    """Form to manage campus locations and approved GPS coordinates for heatmap."""
    class Meta:
        model = CampusLocation
        fields = ['name', 'building', 'floor', 'description', 'latitude', 'longitude', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Central Library 2nd Floor'}),
            'building': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Library Building'}),
            'floor': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. 2nd Floor'}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 2, 'placeholder': 'Brief description'}),
            'latitude': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.000001', 'placeholder': 'e.g. 12.971598'}),
            'longitude': forms.NumberInput(attrs={'class': 'form-input', 'step': '0.000001', 'placeholder': 'e.g. 77.594562'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class CategoryForm(forms.ModelForm):
    """Form to manage item categories and icons."""
    class Meta:
        model = Category
        fields = ['name', 'icon', 'description', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. Electronics & Gadgets'}),
            'icon': forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'e.g. fa-laptop, fa-key, fa-wallet'}),
            'description': forms.Textarea(attrs={'class': 'form-textarea', 'rows': 2, 'placeholder': 'Category scope description'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }


class SecurityAlertReviewForm(forms.Form):
    """Form to moderate security alerts without auto-banning users."""
    status = forms.ChoiceField(
        choices=SecurityAlert.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    review_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 3,
            'placeholder': 'Add administrative findings or notes on resolution...'
        })
    )


class ReportExportFilterForm(forms.Form):
    """Filters for generating downloadable Excel/PDF activity reports."""
    FORMAT_CHOICES = [
        ('xlsx', 'Excel Spreadsheet (.xlsx)'),
        ('pdf', 'Portable Document Format (.pdf)'),
    ]

    export_format = forms.ChoiceField(
        choices=FORMAT_CHOICES,
        initial='xlsx',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    report_type = forms.ChoiceField(
        choices=[('all', 'All Reports'), ('lost', 'Lost Items Only'), ('found', 'Found Items Only')],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    status = forms.ChoiceField(
        choices=[('all', 'All Statuses')] + Item.STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label="All Categories",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    location = forms.ModelChoiceField(
        queryset=CampusLocation.objects.filter(is_active=True),
        required=False,
        empty_label="All Locations",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'})
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'})
    )

