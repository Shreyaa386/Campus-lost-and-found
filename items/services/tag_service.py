"""
Item Tag Service for CampusCare Lost and Found Items.
Generates printable identification tag and asset metadata.
Encodes strictly public/safe item URLs and item reference codes without leaking private personal information.
Does not generate or rely on QR code matrices or scanner libraries.
"""

import logging
import os
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


class TagService:
    """
    Handles generation of printable item identification tags linking directly
    to the safe public item view with official university asset reference code.
    """

    @classmethod
    def get_safe_item_url(cls, item, request=None):
        """
        Returns the canonical public URL for an item.
        Prefers configured CAMPUSCARE_BASE_URL so that item links
        work reliably across devices on the network or after production deployment.
        """
        path = reverse('items:item_detail', kwargs={'pk': item.pk})
        base_url = getattr(settings, 'CAMPUSCARE_BASE_URL', '') or os.environ.get('CAMPUSCARE_BASE_URL', '').strip()
        if base_url:
            return f"{base_url.rstrip('/')}{path}"
        if request is not None:
            return request.build_absolute_uri(path)
        return path

    @classmethod
    def generate_tag_context(cls, item, request=None) -> dict:
        """
        Builds the complete template context for rendering or printing
        the item identification tag. Does NOT contain private contact numbers or emails.
        """
        safe_url = cls.get_safe_item_url(item, request=request)
        item_code = item.item_code or f"CC-{item.created_at.year}-{item.pk:05d}"
        inst_name = item.institution.name if item.institution else "Lovely Professional University (LPU), Phagwara, Punjab"

        return {
            'item': item,
            'item_code': item_code,
            'safe_url': safe_url,
            'institution_name': inst_name,
            'category_name': item.category.name if item.category else "General Belonging",
            'instructions': "Found this item on campus? Please return it to Campus Security (Block 34 Helpdesk) or the Central Lost & Found Counter quoting this Item Code.",
        }


# Compatibility alias for existing callers
QRService = TagService

