"""
Tag Service Compatibility Shim for CampusCare Lost and Found Items.
Redirects legacy QRService imports to the modernized TagService without QR matrices.
"""

from .tag_service import TagService, QRService

__all__ = ['TagService', 'QRService']
