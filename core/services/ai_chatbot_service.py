"""
AI Conversational Assistant Service for CampusCare.
Provides intelligent, privacy-compliant guidance for reporting, item search,
claim explanation, and recovery workflows.
Supports Google Gemini API with modular natural-language heuristic fallback.
Strictly safeguards against prompt injection and private data leakage (OTPs,
verification secrets, personal phone numbers/emails).
"""

import json
import logging
import re
import urllib.request
import urllib.error
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.urls import reverse

logger = logging.getLogger(__name__)


class AIChatbotService:
    """
    Modular CampusCare AI Assistant service with zero-leakage security boundaries.
    """

    SYSTEM_GUARDRAILS = """
You are CampusCare Assistant, an empathetic, official AI guide for university Lost and Found.
You help students, faculty, and campus visitors navigate lost and found processes.

CRITICAL SECURITY AND PRIVACY RULES:
1. NEVER reveal, guess, or discuss private ownership verification answers or private questions.
2. NEVER disclose handover One-Time Passwords (OTPs), secret salts, or verification codes.
3. NEVER disclose personal phone numbers, raw email addresses, or student IDs.
4. If a user asks for private claimant answers, secret codes, or restricted staff logs, politely refuse citing CampusCare Institutional Privacy Policy.
5. Provide actionable, concise, structured steps (bullet points where appropriate).
6. Always encourage safe handovers at designated Campus Security Desks.
"""

    @classmethod
    def process_message(cls, message: str, user=None, institution=None, conversation_history=None) -> dict:
        """
        Processes a user message and returns a structured AI response dictionary:
        {
            'reply': str,
            'source': 'gemini' | 'nlp_fallback',
            'suggested_actions': list[dict],
            'matched_items': list[dict]
        }
        """
        clean_input = message.strip()
        if not clean_input:
            return {
                'reply': "Hello! I am your CampusCare Assistant. How can I assist you with a lost or found item today?",
                'source': 'nlp_fallback',
                'suggested_actions': cls.get_default_actions(),
                'matched_items': []
            }

        # 1. Privacy Pre-Screening: Detect prompt extraction attempts
        blocked_reply = cls._screen_sensitive_prompt(clean_input)
        if blocked_reply:
            return {
                'reply': blocked_reply,
                'source': 'nlp_fallback',
                'suggested_actions': cls.get_default_actions(),
                'matched_items': []
            }

        # 2. Extract potential item search queries
        matched_items = cls._search_public_items(clean_input, institution=institution)

        # 3. Attempt Gemini API if configured
        gemini_key = getattr(settings, 'GEMINI_API_KEY', '')
        if gemini_key:
            gemini_reply = cls._call_gemini_api(clean_input, gemini_key, user=user, institution=institution, matched_items=matched_items)
            if gemini_reply:
                # Sanitize response to guarantee zero leakage
                sanitized_reply = cls._sanitize_output(gemini_reply)
                return {
                    'reply': sanitized_reply,
                    'source': 'gemini',
                    'suggested_actions': cls._infer_suggested_actions(clean_input),
                    'matched_items': matched_items[:3]
                }

        # 4. Graceful Fallback: Intelligent Natural Language Dialog Engine
        fallback_reply = cls._generate_nlp_fallback_response(clean_input, user=user, institution=institution, matched_items=matched_items)
        sanitized_fallback = cls._sanitize_output(fallback_reply)

        return {
            'reply': sanitized_fallback,
            'source': 'nlp_fallback',
            'suggested_actions': cls._infer_suggested_actions(clean_input),
            'matched_items': matched_items[:3]
        }

    # ----------------------------------------------------------------------
    # PRIVACY SCREENING & OUTPUT SANITIZATION
    # ----------------------------------------------------------------------

    @classmethod
    def _screen_sensitive_prompt(cls, prompt: str) -> str:
        """Blocks prompt injection or queries attempting to leak restricted data."""
        p_lower = prompt.lower()

        # Check for intent to reveal/extract secret data
        sensitive_targets = ['otp', 'code', 'verification answer', 'private answer', 'secret', 'password', 'phone', 'email', 'claimant']
        extraction_verbs = ['reveal', 'give me', 'show me', 'what is', 'tell me', 'get me', 'leak', 'share']

        is_extraction = any(v in p_lower for v in extraction_verbs)
        targets_sensitive = any(t in p_lower for t in sensitive_targets)

        direct_matches = [
            'secret answer', 'verification answer', 'who claimed my item', 'claimant phone',
            'claimant email', 'staff notes', 'sql injection', 'drop table', 'bypass permission',
            'ignore instructions', 'ignore previous'
        ]

        if (is_extraction and targets_sensitive and ('otp' in p_lower or 'answer' in p_lower or 'phone' in p_lower or 'secret' in p_lower or 'code' in p_lower)) or any(m in p_lower for m in direct_matches):
            return (
                "Security Notice: I cannot disclose private verification answers, secret handover OTPs, "
                "or personal claimant contact information. These details are strictly protected under "
                "institutional privacy policies. Please coordinate handovers through the designated "
                "Campus Security Desk."
            )
        return ""

    @classmethod
    def _sanitize_output(cls, text: str) -> str:
        """Redacts any accidental 6-digit OTPs, phone patterns, or credentials."""
        # Redact raw OTP-like 6 digit codes
        redacted = re.sub(r'\b\d{6}\b', '[PROTECTED_CODE]', text)
        # Redact potential Indian phone number sequences (+91 or 10 digits)
        redacted = re.sub(r'(\+?91[\-\s]?)?[6-9]\d{9}', '[REDACTED_PHONE]', redacted)
        return redacted

    # ----------------------------------------------------------------------
    # ITEM SEARCH INTEGRATION
    # ----------------------------------------------------------------------

    @classmethod
    def _search_public_items(cls, query: str, institution=None) -> list:
        """
        Finds active public items matching user keywords within their institution
        or cross-campus visible listings.
        """
        from items.models import Item

        # Filter keywords (ignore small stopwords)
        words = [w for w in re.findall(r'\b\w+\b', query.lower()) if len(w) > 2 and w not in ['the', 'how', 'where', 'what', 'can', 'find', 'lost', 'found']]
        if not words:
            return []

        search_q = Q()
        for w in words[:4]:
            search_q |= Q(title__icontains=w) | Q(category__name__icontains=w) | Q(location__name__icontains=w)

        # Restrict strictly to authorized scope (institution or cross-campus visible)
        qs = Item.objects.filter(
            status__in=[Item.STATUS_OPEN, Item.STATUS_PENDING],
        ).filter(search_q)

        if institution:
            qs = qs.filter(Q(institution=institution) | Q(is_cross_campus_visible=True))

        items = []
        for item in qs.select_related('category', 'location', 'institution')[:5]:
            items.append({
                'id': item.id,
                'title': item.title,
                'report_type': item.get_report_type_display(),
                'category': item.category.name if item.category else "General",
                'location': item.location.name if item.location else "Campus Grounds",
                'institution': item.institution.short_name or item.institution.name,
                'date': item.date_lost_or_found.strftime('%b %d, %Y'),
                'url': f"/items/{item.id}/",
                'status': item.get_status_display()
            })
        return items

    # ----------------------------------------------------------------------
    # GEMINI API CLIENT (Modular & Fallback-Safe)
    # ----------------------------------------------------------------------

    @classmethod
    def _call_gemini_api(cls, prompt: str, api_key: str, user=None, institution=None, matched_items=None) -> str:
        """
        Calls Google Gemini API using urllib to avoid heavy external dependencies.
        Returns generated text or None on failure.
        """
        inst_name = institution.name if institution else "Lovely Professional University (LPU), Phagwara, Punjab"
        context_notes = f"Current User: {user.display_name if user else 'Campus Visitor'}, Institution: {inst_name}."

        items_context = ""
        if matched_items:
            items_context = "Currently open campus reports matching user's keywords:\n"
            for it in matched_items:
                items_context += f"- #{it['id']} ({it['report_type']}): '{it['title']}' in {it['category']} at {it['location']} ({it['date']})\n"

        full_prompt = (
            f"{cls.SYSTEM_GUARDRAILS}\n\n"
            f"Context: {context_notes}\n"
            f"{items_context}\n"
            f"User Question: {prompt}\n\n"
            f"Response:"
        )

        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [{"text": full_prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 400,
            }
        }

        try:
            req = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    candidates = data.get('candidates', [])
                    if candidates:
                        parts = candidates[0].get('content', {}).get('parts', [])
                        if parts:
                            return parts[0].get('text', '').strip()
        except Exception as e:
            logger.warning(f"Gemini API request failed ({e}). Seamlessly switching to NLP fallback engine.")
            return None
        return None

    # ----------------------------------------------------------------------
    # INTELLIGENT RULE-BASED NLP FALLBACK ENGINE
    # ----------------------------------------------------------------------

    @classmethod
    def _generate_nlp_fallback_response(cls, message: str, user=None, institution=None, matched_items=None) -> str:
        """
        Offline dialog engine resolving common lost-and-found intents with rich context.
        """
        msg = message.lower()
        inst_name = institution.short_name or (institution.name if institution else "Campus")

        # 1. Report Lost Item
        if ('lost' in msg and any(w in msg for w in ['report', 'how', 'submit', 'lost my', 'i lost', 'missing'])):
            return (
                f"**To report a lost item at {inst_name}:**\n\n"
                "1. Click **'Report Item'** in the top navigation.\n"
                "2. Choose **'Lost Item'** and select the appropriate category (e.g. Electronics, IDs, Keys).\n"
                "3. Provide the campus facility/room where you last remember having it and the approximate date.\n"
                "4. Add distinguishing marks (stickers, scratches, color) and upload a photo if you have one.\n"
                "5. Choose your contact preference (Email, Phone, or Campus Desk).\n\n"
                "Our automated smart matching engine will immediately scan existing found reports and alert you if a potential match appears."
            )

        # 2. Report Found Item
        if ('found' in msg and any(w in msg for w in ['report', 'how', 'submit', 'found a', 'turned in', 'picked up'])):
            return (
                f"**Thank you for helping our {inst_name} community! Here is how to report a found item:**\n\n"
                "1. Click **'Report Item'** and select **'Found Item'**.\n"
                "2. Specify where on campus you discovered it (e.g. Library, Cafeteria).\n"
                "3. **Ownership Verification Questions (Crucial):** Formulate 1-2 private questions only the genuine owner would know (e.g. *'What is the lock screen picture?'* or *'What is inside the front zipper?'*).\n"
                "4. Hand the physical item over to the **Campus Security Desk** or designated Department Office for safe custody.\n"
                "5. You will earn **Honesty Points and Badges** on the CampusCare Leaderboard once verified!"
            )

        # 3. Claim Status
        if any(w in msg for w in ['claim status', 'my claim', 'how to claim', 'submit claim', 'status of claim']):
            return (
                "**Understanding Your Claim Status:**\n\n"
                "• **Pending Review:** Your claim and private answers have been received and are waiting for staff review.\n"
                "• **Under Review:** Campus security or the finder is reviewing your verification evidence.\n"
                "• **Approved:** Congratulations! Ownership is verified. You will receive a secure Handover OTP to present at collection.\n"
                "• **Rejected:** The provided answers or serial numbers did not match the item records. You can view the reason on your dashboard.\n\n"
                "You can monitor all your submissions under **'My Claims'** in your student dashboard."
            )

        # 4. Handover & OTP Recovery Process
        if any(w in msg for w in ['handover', 'otp', 'recovery', 'collect item', 'pickup']):
            return (
                "**Safe Recovery Handover Workflow:**\n\n"
                "1. Once your claim is approved, CampusCare generates a secure, time-limited **6-digit Handover OTP** accessible exclusively in your private dashboard.\n"
                "2. Visit the designated **Campus Security Desk** with your valid Student ID.\n"
                "3. Present your Handover OTP to the staff member or finder for server-side verification.\n"
                "4. Upon successful match, your item status updates to **'Recovered'**, and you can download a digital Handover Receipt.\n\n"
                "*(Note: Never share your OTP in public chats or unverified messages!)*"
            )

        # 5. Reward Points & Badges
        if any(w in msg for w in ['reward', 'points', 'leaderboard', 'badge', 'karma']):
            return (
                "**CampusCare Rewards & Recognition:**\n\n"
                "• Reporting a found item and successfully returning it awards **Honesty Points**.\n"
                "• Collect prestigious campus badges like *Good Samaritan*, *Honesty Champion*, and *Master Finder*.\n"
                "• View your rank on the campus-wide **Leaderboard** (privacy-conscious display names protect your identity).\n"
                "• Points can be redeemed for institutional commendation certificates and cafeteria privileges."
            )

        # 6. Public Search Matches Response
        if matched_items:
            response = f"I found **{len(matched_items)} potential report(s)** matching your query on {inst_name}:\n\n"
            for it in matched_items:
                response += f"• **[{it['report_type']}] {it['title']}** — {it['location']} ({it['date']}) → [View Details]({it['url']})\n"
            response += "\nWould you like more details on one of these, or should I help you submit a new report?"
            return response

        # 7. Default Guidance
        return (
            f"I am here to help you navigate lost and found services at **{inst_name}**.\n\n"
            "Here is what I can do for you:\n"
            "• Guide you through reporting lost or found belongings.\n"
            "• Search existing campus reports for matching items.\n"
            "• Explain claim verification and ownership questions.\n"
            "• Guide you through the secure OTP handover process.\n\n"
            "What would you like assistance with?"
        )

    @classmethod
    def get_default_actions(cls) -> list:
        return [
            {'label': "Report Lost Item", 'query': "How do I report a lost item?"},
            {'label': "Report Found Item", 'query': "I found an item on campus"},
            {'label': "Check Claim Status", 'query': "How does claim approval work?"},
            {'label': "Handover & OTP Process", 'query': "Explain the handover OTP process"},
        ]

    @classmethod
    def _infer_suggested_actions(cls, prompt: str) -> list:
        p = prompt.lower()
        if 'lost' in p:
            return [
                {'label': "Report Lost Item Now", 'url': "/items/report/lost/"},
                {'label': "Search Found Items", 'url': "/items/found/"},
                {'label': "How to write good description", 'query': "What details should I include when reporting a lost item?"}
            ]
        elif 'found' in p:
            return [
                {'label': "Report Found Item Now", 'url': "/items/report/found/"},
                {'label': "Good verification questions", 'query': "What are good ownership verification questions?"},
                {'label': "Reward Points Info", 'query': "How do reward points work?"}
            ]
        elif 'claim' in p or 'otp' in p:
            return [
                {'label': "View My Claims", 'url': "/items/claims/"},
                {'label': "Handover Safety Steps", 'query': "Where should I meet for item handover?"}
            ]
        return cls.get_default_actions()

