"""
Priority Management and Smart Suggestion Service for CampusCare Lost and Found Items.
Provides heuristic rules to intelligently suggest report priority based on category and title keywords.
"""

import re
from typing import Dict, Any


class PriorityService:
    """
    Analyzes item title and category to offer smart, non-intrusive priority suggestions.
    Guarantees that ordinary electronics are NOT escalated to Critical,
    reserving Critical strictly for life-critical medical, safety, or emergency items.
    """

    CRITICAL = 'critical'
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'

    # Explanations for users
    EXPLANATIONS = {
        CRITICAL: "Immediate urgency: Life-saving medicine, medical equipment, or vital emergency keys.",
        HIGH: "High urgency: Valuable electronics (phone, laptop), wallet/cards, official ID cards, or important documents.",
        MEDIUM: "Standard urgency: Everyday valuables like backpacks, textbooks, clothing, and audio gear.",
        LOW: "Low urgency: Common utility items like water bottles, notebooks, stationery, and small accessories.",
    }

    # Keyword rules for detection (regex compiled for case-insensitive matching)
    CRITICAL_KEYWORDS = [
        r'\binsulin\b', r'\binhaler\b', r'\bprescri(?:ption|pt)\b', r'\bmedic(?:ine|ation|al)\b',
        r'\bepipen\b', r'\bhearing aid\b', r'\bpacemaker\b', r'\bemergency key\b',
    ]

    HIGH_KEYWORDS = [
        # IDs and Official Documents
        r'\bid card\b', r'\bidentity card\b', r'\bstudent id\b', r'\baadhaar\b', r'\bpan card\b',
        r'\bpassport\b', r'\bdriving licen[sc]e\b', r'\blicen[sc]e\b', r'\bvoter id\b',
        r'\bimportant documents?\b', r'\bcertificate\b', r'\bdegree\b', r'\bmarksheet\b',
        r'\bcheque\b', r'\bcheckbook\b',
        # High value electronics
        r'\bmobile\b', r'\bphone\b', r'\bsmartphone\b', r'\biphone\b', r'\bandroid\b',
        r'\blaptop\b', r'\bmacbook\b', r'\bdell\b', r'\bthinkpad\b', r'\bipad\b', r'\btablet\b',
        # Financial / Wallets
        r'\bwallet\b', r'\bpurse\b', r'\bdebit card\b', r'\bcredit card\b', r'\batm card\b',
        r'\bbank card\b', r'\bcash\b',
    ]

    MEDIUM_KEYWORDS = [
        r'\bbook\b', r'\bbooks\b', r'\btextbook\b', r'\bnovel\b',
        r'\bbag\b', r'\bbags\b', r'\bbackpack\b', r'\bhandbag\b', r'\bluggage\b', r'\bduffle\b',
        r'\bheadphones?\b', r'\bearbuds?\b', r'\bairpods?\b', r'\bheadset\b',
        r'\bwatch\b', r'\bsmartwatch\b',
        r'\bjacket\b', r'\bcoat\b', r'\bhoodie\b', r'\bcalculator\b', r'\bscientific calculator\b',
        r'\bglasses\b', r'\bspectacles\b', r'\bsunglasses\b', r'\bcharger\b', r'\bpower bank\b',
        r'\bumbrella\b',
    ]

    LOW_KEYWORDS = [
        r'\bwater bottle\b', r'\bbottle\b', r'\bsipper\b', r'\bflask\b', r'\btumbler\b',
        r'\bstationery\b', r'\bpen\b', r'\bpencil\b', r'\bruler\b', r'\beraser\b',
        r'\bnotebook\b', r'\bregister\b', r'\bfolder\b', r'\bfile\b',
        r'\blunch box\b', r'\btiffin\b', r'\bcap\b', r'\bhat\b', r'\bkeychain\b',
        r'\bcomb\b', r'\bhair clip\b', r'\bscarf\b',
    ]

    @classmethod
    def suggest_priority(cls, title: str, category_name: str = "") -> str:
        """
        Determines the recommended priority based on item text and category.
        Returns one of: 'critical', 'high', 'medium', 'low'.
        Defaults to 'medium' when uncertain.
        """
        text = f"{title or ''} {category_name or ''}".lower()

        # Check Critical keywords
        for pattern in cls.CRITICAL_KEYWORDS:
            if re.search(pattern, text):
                return cls.CRITICAL

        # Check High keywords
        for pattern in cls.HIGH_KEYWORDS:
            if re.search(pattern, text):
                return cls.HIGH

        # Category level checks for High
        cat_lower = (category_name or "").lower()
        if any(w in cat_lower for w in ['id card', 'documents', 'wallet', 'money', 'banking']):
            return cls.HIGH

        # Check Low keywords
        for pattern in cls.LOW_KEYWORDS:
            if re.search(pattern, text):
                return cls.LOW

        # Category level checks for Low
        if any(w in cat_lower for w in ['stationery', 'bottle', 'utensils']):
            return cls.LOW

        # Check Medium keywords
        for pattern in cls.MEDIUM_KEYWORDS:
            if re.search(pattern, text):
                return cls.MEDIUM

        if any(w in cat_lower for w in ['book', 'bag', 'clothing', 'apparel', 'electronics', 'accessories']):
            return cls.MEDIUM

        return cls.MEDIUM

    @classmethod
    def get_priority_meta(cls, priority: str) -> Dict[str, Any]:
        """Returns visual styling metadata and human-readable explanation for a priority level."""
        p = priority.lower() if priority else cls.MEDIUM
        meta = {
            cls.CRITICAL: {
                'code': cls.CRITICAL,
                'label': 'Critical',
                'badge_class': 'badge-priority-critical',
                'color': '#dc2626',
                'bg': '#fef2f2',
                'border': '#fecaca',
                'icon': 'fa-triangle-exclamation',
                'explanation': cls.EXPLANATIONS[cls.CRITICAL],
            },
            cls.HIGH: {
                'code': cls.HIGH,
                'label': 'High',
                'badge_class': 'badge-priority-high',
                'color': '#ea580c',
                'bg': '#fff7ed',
                'border': '#fed7aa',
                'icon': 'fa-circle-exclamation',
                'explanation': cls.EXPLANATIONS[cls.HIGH],
            },
            cls.MEDIUM: {
                'code': cls.MEDIUM,
                'label': 'Medium',
                'badge_class': 'badge-priority-medium',
                'color': '#2563eb',
                'bg': '#eff6ff',
                'border': '#bfdbfe',
                'icon': 'fa-flag',
                'explanation': cls.EXPLANATIONS[cls.MEDIUM],
            },
            cls.LOW: {
                'code': cls.LOW,
                'label': 'Low',
                'badge_class': 'badge-priority-low',
                'color': '#16a34a',
                'bg': '#f0fdf4',
                'border': '#bbf7d0',
                'icon': 'fa-circle-info',
                'explanation': cls.EXPLANATIONS[cls.LOW],
            },
        }
        return meta.get(p, meta[cls.MEDIUM])

