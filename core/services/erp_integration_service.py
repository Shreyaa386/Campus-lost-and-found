"""
Modular Campus ERP / Student Information System (SIS) Integration Service.
Provides secure REST synchronization for student/faculty directories and campus
facility inventories with Ellucian Banner, SAP SLCM, or custom university portals.
Enforces API key authentication, strict payload validation, and tenant isolation.
"""

import logging
import secrets
from django.contrib.auth import get_user_model
from django.db import transaction
from core.models import CampusLocation, Department, Institution
from core.services.audit_service import AuditService

User = get_user_model()
logger = logging.getLogger(__name__)


class ERPIntegrationService:
    """
    Handles bidirectional synchronization between CampusCare and university ERP systems.
    """

    @classmethod
    def authenticate_api_key(cls, api_key: str) -> Institution:
        """
        Validates the ERP API key and returns the associated Institution, or None.
        """
        if not api_key:
            return None
        return Institution.objects.filter(erp_api_key=api_key, is_active=True).first()

    @classmethod
    def sync_users_directory(cls, institution: Institution, users_data: list, request=None) -> dict:
        """
        Synchronizes student, faculty, and staff rosters from university ERP.
        Payload format per user:
        {
            "student_id": "S10023",
            "username": "s10023",
            "email": "student@institution.edu",
            "first_name": "Alice",
            "last_name": "Smith",
            "role": "student",  # 'student', 'faculty', 'staff'
            "department_code": "CSE",
            "is_active": true
        }
        """
        if not isinstance(users_data, list):
            return {'status': 'error', 'message': "Payload 'users' must be a JSON array.", 'created': 0, 'updated': 0, 'errors': []}

        created_count = 0
        updated_count = 0
        errors = []

        with transaction.atomic():
            for idx, item in enumerate(users_data):
                username = str(item.get('username') or item.get('student_id') or '').strip()
                email = str(item.get('email') or '').strip().lower()
                first_name = str(item.get('first_name') or '').strip()
                last_name = str(item.get('last_name') or '').strip()
                student_id = str(item.get('student_id') or '').strip()
                role_val = str(item.get('role') or 'student').lower()
                dept_code = str(item.get('department_code') or '').strip()
                is_active = bool(item.get('is_active', True))

                if not username or not email:
                    errors.append(f"Row {idx}: 'username' and 'email' are required.")
                    continue

                # Department link
                dept = None
                if dept_code:
                    dept = Department.objects.filter(institution=institution, code__iexact=dept_code).first()

                role_mapped = User.ROLE_STUDENT
                if role_val in ['faculty', 'professor']:
                    role_mapped = User.ROLE_FACULTY
                elif role_val in ['staff', 'security', 'admin']:
                    role_mapped = User.ROLE_STAFF

                user = User.objects.filter(email=email).first() or User.objects.filter(username=username).first()

                if user:
                    # Update existing record
                    user.first_name = first_name or user.first_name
                    user.last_name = last_name or user.last_name
                    user.student_id = student_id or user.student_id
                    user.role = role_mapped
                    user.institution = institution
                    user.department = dept or user.department
                    user.is_active = is_active
                    user.save()
                    updated_count += 1
                else:
                    # Create new user
                    new_user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=secrets.token_urlsafe(12),
                        first_name=first_name,
                        last_name=last_name,
                        role=role_mapped,
                        institution=institution,
                        is_active=is_active
                    )
                    new_user.student_id = student_id
                    new_user.department = dept
                    new_user.save()
                    created_count += 1

        # Audit sync event
        AuditService.log_action(
            action='user_role',
            actor=None,
            target_obj=institution,
            details={
                'source': 'erp_sync_directory',
                'created_count': created_count,
                'updated_count': updated_count,
                'error_count': len(errors)
            },
            request=request
        )

        return {
            'status': 'success',
            'created': created_count,
            'updated': updated_count,
            'errors': errors
        }

    @classmethod
    def sync_facilities_inventory(cls, institution: Institution, facilities_data: list, request=None) -> dict:
        """
        Synchronizes campus buildings and facility rooms from campus physical asset ERP.
        Payload format per facility:
        {
            "name": "Central Library Reading Room",
            "building": "Library Complex",
            "floor": "Ground Floor",
            "latitude": 12.9719,
            "longitude": 77.5942,
            "is_active": true
        }
        """
        if not isinstance(facilities_data, list):
            return {'status': 'error', 'message': "Payload 'facilities' must be a JSON array.", 'created': 0, 'updated': 0, 'errors': []}

        created_count = 0
        updated_count = 0
        errors = []

        with transaction.atomic():
            for idx, f in enumerate(facilities_data):
                name = str(f.get('name') or '').strip()
                building = str(f.get('building') or '').strip()
                floor = str(f.get('floor') or '').strip()
                lat = f.get('latitude')
                lng = f.get('longitude')
                is_active = bool(f.get('is_active', True))

                if not name:
                    errors.append(f"Row {idx}: Facility 'name' is required.")
                    continue

                loc, created = CampusLocation.objects.get_or_create(
                    institution=institution,
                    name=name,
                    defaults={
                        'building': building,
                        'floor': floor,
                        'latitude': lat,
                        'longitude': lng,
                        'is_active': is_active
                    }
                )

                if not created:
                    loc.building = building or loc.building
                    loc.floor = floor or loc.floor
                    if lat is not None:
                        loc.latitude = lat
                    if lng is not None:
                        loc.longitude = lng
                    loc.is_active = is_active
                    loc.save()
                    updated_count += 1
                else:
                    created_count += 1

        AuditService.log_action(
            action='location_modify',
            actor=None,
            target_obj=institution,
            details={
                'source': 'erp_sync_facilities',
                'created_count': created_count,
                'updated_count': updated_count,
                'error_count': len(errors)
            },
            request=request
        )

        return {
            'status': 'success',
            'created': created_count,
            'updated': updated_count,
            'errors': errors
        }

