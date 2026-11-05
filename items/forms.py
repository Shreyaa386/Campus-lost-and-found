from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from PIL import Image
from core.models import CampusLocation, Category
from .models import Claim, Item, ItemMatch


class ItemReportForm(forms.ModelForm):
    # Optional verification prompts when reporting a found item
    verification_q1 = forms.CharField(
        label="Ownership Question 1 (Optional)",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. What is the lockscreen wallpaper / case color?'
        }),
        help_text="Ask private details only the true owner would know."
    )
    verification_q2 = forms.CharField(
        label="Ownership Question 2 (Optional)",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. What items are inside the front zipped pocket?'
        })
    )

    class Meta:
        model = Item
        fields = [
            'title',
            'category',
            'location',
            'location_details',
            'date_lost_or_found',
            'description',
            'image',
            'contact_preference',
            'contact_phone',
            'contact_email',
            'is_cross_campus_visible',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Blue Dell Laptop with stickers, Silver Keychain, Casio Watch'
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'location': forms.Select(attrs={'class': 'form-select'}),
            'location_details': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'e.g. Reading table #5 near windows, 2nd floor elevator lobby'
            }),
            'date_lost_or_found': forms.DateInput(attrs={
                'class': 'form-input',
                'type': 'date'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 4,
                'placeholder': 'Provide detailed descriptions, unique scratches, model numbers, contents, brand, color...'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-file-input',
                'accept': 'image/*'
            }),
            'contact_preference': forms.Select(attrs={'class': 'form-select'}),
            'contact_phone': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': '+91 98765 43210 (Optional if using profile phone)'
            }),
            'contact_email': forms.EmailInput(attrs={
                'class': 'form-input',
                'placeholder': 'your-email@campus.edu (Optional if using profile email)'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.report_type = kwargs.pop('report_type', Item.REPORT_TYPE_LOST)
        super().__init__(*args, **kwargs)

        if self.user and hasattr(self.user, 'institution') and self.user.institution:
            self.fields['location'].queryset = CampusLocation.objects.filter(
                institution=self.user.institution,
                is_active=True
            )
            self.fields['category'].queryset = Category.objects.filter(
                Q(institution=self.user.institution) | Q(institution__isnull=True),
                is_active=True
            )
        else:
            self.fields['category'].queryset = Category.objects.filter(is_active=True)
            self.fields['location'].queryset = CampusLocation.objects.filter(is_active=True)

        if not self.initial.get('date_lost_or_found'):
            self.fields['date_lost_or_found'].initial = timezone.localdate()

        if self.report_type == Item.REPORT_TYPE_LOST:
            self.fields['date_lost_or_found'].label = "Date Lost"
            self.fields['location'].label = "Last Seen Location"
            self.fields['title'].label = "Lost Item Title"
            # Remove verification questions for lost items
            self.fields.pop('verification_q1', None)
            self.fields.pop('verification_q2', None)
        else:
            self.fields['date_lost_or_found'].label = "Date Found"
            self.fields['location'].label = "Found Location"
            self.fields['title'].label = "Found Item Title"
            if self.instance.pk and self.instance.verification_questions:
                qs = self.instance.verification_questions
                if len(qs) > 0:
                    self.fields['verification_q1'].initial = qs[0]
                if len(qs) > 1:
                    self.fields['verification_q2'].initial = qs[1]

        if self.user and not self.instance.pk:
            if not self.initial.get('contact_email') and self.user.email:
                self.fields['contact_email'].initial = self.user.email
            if not self.initial.get('contact_phone') and hasattr(self.user, 'phone_number') and self.user.phone_number:
                self.fields['contact_phone'].initial = self.user.phone_number

    def clean_date_lost_or_found(self):
        item_date = self.cleaned_data.get('date_lost_or_found')
        if item_date and item_date > timezone.localdate():
            raise ValidationError("The date cannot be in the future.")
        return item_date

    def clean_image(self):
        img_file = self.cleaned_data.get('image')
        if img_file and hasattr(img_file, 'size'):
            if img_file.size > 5 * 1024 * 1024:
                raise ValidationError("Image file size exceeds 5MB limit.")
            ext = img_file.name.lower().split('.')[-1]
            if ext not in ['jpg', 'jpeg', 'png', 'webp']:
                raise ValidationError("Allowed image formats are JPG, JPEG, PNG, and WEBP.")
            try:
                img = Image.open(img_file)
                img.verify()
            except Exception:
                raise ValidationError("Uploaded file is not a valid or readable image.")
        return img_file

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.report_type == Item.REPORT_TYPE_FOUND:
            questions = []
            q1 = self.cleaned_data.get('verification_q1', '').strip()
            q2 = self.cleaned_data.get('verification_q2', '').strip()
            if q1:
                questions.append(q1)
            if q2:
                questions.append(q2)
            instance.verification_questions = questions

        if commit:
            instance.save()
            self.save_m2m()
        return instance


class ItemStatusUpdateForm(forms.Form):
    status = forms.ChoiceField(
        choices=Item.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 3,
            'placeholder': 'Add optional notes about this status change...'
        })
    )

    def __init__(self, *args, **kwargs):
        is_staff = kwargs.pop('is_staff', False)
        current_status = kwargs.pop('current_status', Item.STATUS_OPEN)
        super().__init__(*args, **kwargs)

        if not is_staff:
            allowed = [
                (Item.STATUS_OPEN, 'Open / Active'),
                (Item.STATUS_CLAIMED, 'Claimed / Matched'),
                (Item.STATUS_RETURNED, 'Returned to Owner'),
                (Item.STATUS_CLOSED, 'Closed / Cancelled'),
            ]
            self.fields['status'].choices = allowed

        self.fields['status'].initial = current_status


class ClaimSubmissionForm(forms.ModelForm):
    """
    Form for claimants to submit an ownership verification claim.
    Supports dynamic private ownership questions.
    """
    class Meta:
        model = Claim
        fields = [
            'identifying_details',
            'proof_image',
        ]
        widgets = {
            'identifying_details': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 4,
                'placeholder': (
                    "Provide specific hidden details only the true owner would know:\n"
                    "- Lock screen wallpaper / passcode hint\n"
                    "- Contents inside pockets/compartments\n"
                    "- Serial number, engraving, or unique scratches\n"
                    "- Purchase date, brand, or model specifics"
                )
            }),
            'proof_image': forms.FileInput(attrs={
                'class': 'form-file-input',
                'accept': 'image/*'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.item = kwargs.pop('item', None)
        self.claimant = kwargs.pop('claimant', None)
        super().__init__(*args, **kwargs)

        # Build dynamic fields for verification questions set on the item
        if self.item and self.item.verification_questions:
            for idx, q_text in enumerate(self.item.verification_questions):
                field_name = f"question_{idx}"
                self.fields[field_name] = forms.CharField(
                    label=f"Verification Prompt #{idx + 1}: {q_text}",
                    required=True,
                    widget=forms.TextInput(attrs={
                        'class': 'form-input',
                        'placeholder': f"Your private answer to: '{q_text}'"
                    }),
                    help_text="This answer is kept strictly private and visible only to campus reviewers."
                )

    def clean_proof_image(self):
        img_file = self.cleaned_data.get('proof_image')
        if img_file and hasattr(img_file, 'size'):
            if img_file.size > 5 * 1024 * 1024:
                raise ValidationError("Proof photo size exceeds 5MB limit.")
            ext = img_file.name.lower().split('.')[-1]
            if ext not in ['jpg', 'jpeg', 'png', 'webp']:
                raise ValidationError("Allowed image formats are JPG, JPEG, PNG, and WEBP.")
            try:
                img = Image.open(img_file)
                img.verify()
            except Exception:
                raise ValidationError("Uploaded proof file is not a valid image.")
        return img_file

    def clean(self):
        cleaned_data = super().clean()
        details = cleaned_data.get('identifying_details', '').strip()
        if len(details.split()) < 3:
            self.add_error('identifying_details', "Please provide at least 3 descriptive words verifying your ownership.")
        return cleaned_data

    def save_with_answers(self, commit=True):
        claim = super().save(commit=False)
        claim.item = self.item
        claim.claimant = self.claimant

        # Extract structured answers for dynamic questions
        answers = {}
        if self.item and self.item.verification_questions:
            for idx, q_text in enumerate(self.item.verification_questions):
                field_name = f"question_{idx}"
                answers[q_text] = self.cleaned_data.get(field_name, '')
        claim.verification_answers = answers

        if commit:
            claim.save()
        return claim


class ClaimReviewForm(forms.ModelForm):
    """
    Form for campus staff / administrators to review and decide on a claim.
    """
    class Meta:
        model = Claim
        fields = [
            'status',
            'decision_reason',
            'admin_notes',
        ]
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'decision_reason': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 3,
                'placeholder': 'Explain the decision to the claimant (e.g. details match item photo; approved for counter pickup at Central Desk)...'
            }),
            'admin_notes': forms.Textarea(attrs={
                'class': 'form-textarea',
                'rows': 2,
                'placeholder': 'Internal notes (e.g. student ID verified at front desk, serial matched)...'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit review choices to review states
        self.fields['status'].choices = [
            (Claim.STATUS_UNDER_REVIEW, 'Under Active Review'),
            (Claim.STATUS_APPROVED, 'Approve (Confirm Ownership)'),
            (Claim.STATUS_REJECTED, 'Reject Claim'),
        ]

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        reason = cleaned_data.get('decision_reason', '').strip()

        if status in [Claim.STATUS_APPROVED, Claim.STATUS_REJECTED] and not reason:
            self.add_error('decision_reason', "A clear reason must be provided when approving or rejecting a claim.")
        return cleaned_data


class DismissMatchForm(forms.Form):
    """Form to dismiss an inaccurate suggested match."""
    dismissed_reason = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Optional reason (e.g., Color is different, brand mismatch)'
        })
    )


class HandoverInitiateForm(forms.Form):
    """Form to schedule and initiate a physical recovery exchange."""
    handover_location = forms.CharField(
        label="Designated Handover Location",
        max_length=150,
        initial="Campus Lost & Found Desk - Student Affairs",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. Central Library Front Counter, Security Office North Gate'
        }),
        help_text="Choose a public, safe, campus-monitored location for exchange."
    )
    handover_notes = forms.CharField(
        label="Logistics & Meeting Notes (Optional)",
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 3,
            'placeholder': 'e.g. Please bring your student ID card. Available Mon-Fri 10:00 AM - 4:00 PM.'
        })
    )


class OTPVerificationForm(forms.Form):
    """Form for item holder to verify the 6-digit recovery OTP."""
    otp_code = forms.CharField(
        label="6-Digit Verification OTP",
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-input tracking-widest text-2xl text-center font-mono font-bold',
            'placeholder': '123456',
            'autocomplete': 'off',
            'pattern': '[0-9]{6}',
            'maxlength': '6',
        }),
        help_text="Ask the claimant for the 6-digit code displayed on their CampusCare recovery screen."
    )

    def clean_otp_code(self):
        otp = self.cleaned_data.get('otp_code', '').strip()
        if not otp.isdigit() or len(otp) != 6:
            raise ValidationError("Please enter a valid 6-digit numerical OTP.")
        return otp


class AnonymousMessageForm(forms.Form):
    """Form for sending privacy-safe coordination messages."""
    message_text = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={
            'class': 'form-textarea',
            'rows': 3,
            'placeholder': 'Type your message (your phone number and email will remain private)...'
        })
    )

    def clean_message_text(self):
        text = self.cleaned_data.get('message_text', '').strip()
        if not text:
            raise ValidationError("Message cannot be blank.")
        return text


class ReportAbuseForm(forms.Form):
    """Form to flag an abusive or harassing conversation message."""
    abuse_reason = forms.CharField(
        label="Reason for Report",
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'e.g. Harassment, spam, asking for money, inappropriate language'
        })
    )


class NotificationPreferenceForm(forms.ModelForm):
    """User preferences for in-app and external alerts."""
    class Meta:
        from .models import NotificationPreference
        model = NotificationPreference
        fields = [
            'notify_on_matches',
            'notify_on_claims',
            'notify_on_handover',
            'notify_on_rewards',
            'email_notifications',
        ]
        widgets = {
            'notify_on_matches': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'notify_on_claims': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'notify_on_handover': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'notify_on_rewards': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'email_notifications': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }

