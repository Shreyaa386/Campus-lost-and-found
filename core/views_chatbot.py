"""
AI Chatbot Views and Real-Time Interaction API for CampusCare.
Provides a dedicated conversational assistant portal and asynchronous JSON endpoint
for instant reporting guidance, item searching, and recovery workflow answers.
"""

import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from core.services.ai_chatbot_service import AIChatbotService


@ensure_csrf_cookie
def assistant_view(request):
    """
    Dedicated AI Campus Assistant web page.
    """
    institution = getattr(request, 'institution', None)
    initial_actions = AIChatbotService.get_default_actions()

    return render(request, 'chatbot/assistant.html', {
        'initial_actions': initial_actions,
        'institution': institution,
    })


@require_POST
def api_assistant_chat(request):
    """
    Asynchronous JSON chat endpoint.
    Processes user query and returns structured AI reply, source, and item matches.
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON request.'}, status=400)

    message = data.get('message', '').strip()
    if not message:
        return JsonResponse({'status': 'error', 'message': 'Message cannot be empty.'}, status=400)

    institution = getattr(request, 'institution', None)
    user = request.user if request.user.is_authenticated else None

    # Retrieve recent conversation turns from session for context
    history = request.session.get('ai_chat_history', [])

    response_data = AIChatbotService.process_message(
        message=message,
        user=user,
        institution=institution,
        conversation_history=history
    )

    # Update session history (store up to last 6 turns)
    history.append({'role': 'user', 'content': message})
    history.append({'role': 'assistant', 'content': response_data['reply']})
    request.session['ai_chat_history'] = history[-6:]

    return JsonResponse({
        'status': 'success',
        'reply': response_data['reply'],
        'source': response_data['source'],
        'suggested_actions': response_data['suggested_actions'],
        'matched_items': response_data['matched_items']
    })

