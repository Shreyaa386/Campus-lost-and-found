"""
Django settings for config project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')
load_dotenv()


# Security

SECRET_KEY = os.getenv(
    'SECRET_KEY',
    'django-insecure-development-key-change-before-production'
)

DEBUG = os.getenv('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver,*').split(',') if h.strip()]

# Public Canonical Base URL for item links, receipts and notifications
# Example in production: https://lostandfound.lpu.in
# Example for local network testing: http://192.168.1.15:8000
CAMPUSCARE_BASE_URL = os.getenv('CAMPUSCARE_BASE_URL', '').rstrip('/')


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'core',
    'accounts',
    'items',
]

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'


# Middleware

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.tenant_middleware.TenantMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# URL Configuration

ROOT_URLCONF = 'config.urls'


# Templates

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.institution_context',
            ],
        },
    },
]


# WSGI

WSGI_APPLICATION = 'config.wsgi.application'


# Database Configuration

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'campuscare_db'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}


# Password Validation

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Kolkata'

USE_I18N = True

USE_TZ = True


# Static Files

STATIC_URL = 'static/'

STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

STATIC_ROOT = BASE_DIR / 'staticfiles'


# Media Files

MEDIA_URL = '/media/'

MEDIA_ROOT = BASE_DIR / 'media'


# Email Configuration

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'


# Authentication Redirects

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'


# CampusCare Specific Settings

DEFAULT_ITEM_EXPIRATION_DAYS = 30
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp']

# Step 5: AI & Multi-Institution Configuration
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
PAYMENT_GATEWAY_PROVIDER = os.environ.get('PAYMENT_GATEWAY_PROVIDER', 'razorpay')
PAYMENT_GATEWAY_KEY = os.environ.get('PAYMENT_GATEWAY_KEY', '')
PAYMENT_GATEWAY_SECRET = os.environ.get('PAYMENT_GATEWAY_SECRET', '')
PAYMENT_WEBHOOK_SECRET = os.environ.get('PAYMENT_WEBHOOK_SECRET', '')
SMS_GATEWAY_KEY = os.environ.get('SMS_GATEWAY_KEY', '')
WHATSAPP_API_KEY = os.environ.get('WHATSAPP_API_KEY', '')


# Default Primary Key

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
