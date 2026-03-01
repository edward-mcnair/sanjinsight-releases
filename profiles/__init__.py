"""
profiles/__init__.py

Package init — re-exports the most commonly needed names so that
    from profiles.profiles import MaterialProfile, CATEGORY_ACCENTS
continues to work even if callers only do `import profiles`.
"""
from .profiles import (
    MaterialProfile,
    CATEGORY_SEMICONDUCTOR,
    CATEGORY_PCB,
    CATEGORY_AUTOMOTIVE,
    CATEGORY_METAL,
    CATEGORY_USER,
    CATEGORY_ACCENTS,
)
from .profile_manager import ProfileManager

__all__ = [
    "MaterialProfile",
    "CATEGORY_SEMICONDUCTOR", "CATEGORY_PCB", "CATEGORY_AUTOMOTIVE",
    "CATEGORY_METAL", "CATEGORY_USER", "CATEGORY_ACCENTS",
    "ProfileManager",
]
