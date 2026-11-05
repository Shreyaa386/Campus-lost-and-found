from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import get_object_or_404, redirect, render
from .forms import UserLoginForm, UserProfileUpdateForm, UserRegistrationForm


def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = UserRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(
                request,
                f"Registration successful! Welcome to CampusCare, {user.first_name or user.username}."
            )
            return redirect('dashboard')
        else:
            messages.error(request, "Please correct the errors in the form below.")
    else:
        initial_role = request.GET.get('role', 'student')
        form = UserRegistrationForm(initial={'role': initial_role})

    return render(request, 'accounts/register.html', {
        'form': form,
        'is_auth_page': True,
    })


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    redirect_to = request.GET.get('next', 'dashboard')
    if redirect_to in ['home', 'login', 'register', 'signup', '/home/', '/login/', '/register/', '/signup/']:
        redirect_to = 'dashboard'

    if request.method == 'POST':
        form = UserLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)

            # Remember me logic
            remember_me = form.cleaned_data.get('remember_me', True)
            if not remember_me:
                request.session.set_expiry(0)  # Session expires on browser close
            else:
                request.session.set_expiry(1209600)  # 2 weeks default

            messages.success(request, f"Welcome back, {user.display_name}!")
            return redirect(redirect_to)
        else:
            messages.error(request, "Invalid credentials or inactive account.")
    else:
        form = UserLoginForm(request)

    return render(request, 'accounts/login.html', {
        'form': form,
        'next': redirect_to,
        'is_auth_page': True,
    })


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out securely.")
    return redirect('login')


@login_required
def profile_view(request):
    user = request.user
    recent_reports = user.reported_items.all().select_related('category', 'location')[:5]
    total_reported = user.reported_items.count()
    lost_count = user.reported_items.filter(report_type='lost').count()
    found_count = user.reported_items.filter(report_type='found').count()
    resolved_count = user.reported_items.filter(status__in=['claimed', 'returned']).count()

    return render(request, 'accounts/profile.html', {
        'user_profile': user,
        'recent_reports': recent_reports,
        'total_reported': total_reported,
        'lost_count': lost_count,
        'found_count': found_count,
        'resolved_count': resolved_count,
    })


@login_required
def profile_edit_view(request):
    if request.method == 'POST':
        form = UserProfileUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile has been updated successfully.")
            return redirect('profile')
        else:
            messages.error(request, "Please fix the errors below.")
    else:
        form = UserProfileUpdateForm(instance=request.user)

    return render(request, 'accounts/profile_edit.html', {'form': form})


@login_required
def password_change_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Keep user logged in
            messages.success(request, "Your password was changed successfully.")
            return redirect('profile')
        else:
            messages.error(request, "Please correct the password errors below.")
    else:
        form = PasswordChangeForm(user=request.user)

    return render(request, 'accounts/password_change.html', {'form': form})
