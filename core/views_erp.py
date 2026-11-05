"""
REST API Views for University ERP / Student Information System (SIS) Synchronization.
Authenticates incoming payloads via institutional API keys and executes batch user
roster and campus physical facility updates with transaction safety.
"""

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from core.services.erp_integration_service import ERPIntegrationService


@csrf_exempt
@require_POST
def erp_sync_api_view(request):
    """
    REST API endpoint: /api/v1/erp/sync/
    Headers:
        X-CampusCare-API-Key: <INSTITUTION_API_KEY>
        Content-Type: application/json
    Body:
        {
            "action": "sync_users" | "sync_facilities",
            "users": [...],
            "facilities": [...]
        }
    """
    api_key = request.headers.get('X-CampusCare-API-Key') or request.META.get('HTTP_X_CAMPUSCARE_API_KEY')
    if not api_key:
        return JsonResponse({
            'status': 'error',
            'message': "Missing 'X-CampusCare-API-Key' authentication header."
        }, status=401)

    institution = ERPIntegrationService.authenticate_api_key(api_key)
    if not institution:
        return JsonResponse({
            'status': 'error',
            'message': "Invalid or inactive institutional API key."
        }, status=403)

    try:
        body = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({
            'status': 'error',
            'message': "Invalid JSON payload."
        }, status=400)

    action = body.get('action')

    if action == 'sync_users':
        users_list = body.get('users', [])
        result = ERPIntegrationService.sync_users_directory(
            institution=institution,
            users_data=users_list,
            request=request
        )
        return JsonResponse(result)

    elif action == 'sync_facilities':
        facilities_list = body.get('facilities', [])
        result = ERPIntegrationService.sync_facilities_inventory(
            institution=institution,
            facilities_data=facilities_list,
            request=request
        )
        return JsonResponse(result)

    else:
        return JsonResponse({
            'status': 'error',
            'message': f"Unsupported action '{action}'. Valid actions: 'sync_users', 'sync_facilities'."
        }, status=400)

