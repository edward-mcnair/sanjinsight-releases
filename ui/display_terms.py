"""
ui/display_terms.py  —  Centralised user-facing terminology

Maps internal concept keys to display strings shown in the UI.
All user-visible labels for domain concepts must come from TERMS
rather than being hardcoded as string literals across tabs/widgets.

This eliminates the class of bugs where renaming a concept requires
synchronised changes in 15+ files.

Usage
-----
::
    from ui.display_terms import TERMS

    btn.setText(TERMS["recipe"])            # "Recipe"
    lbl.setText(f"Load {TERMS['recipe']}…")  # "Load Recipe…"
"""

# ── Display term registry ────────────────────────────────────────────
# Key    = stable internal identifier (never rename)
# Value  = current user-facing display string (change freely)

TERMS: dict[str, str] = {
    # Domain concepts
    "recipe":           "Recipe",
    "recipe_plural":    "Recipes",
    "recipe_verb":      "Run Recipe",         # action button
    "profile":          "Material Profile",
    "profile_plural":   "Material Profiles",
    "session":          "Session",
    "session_plural":   "Sessions",

    # Workflow labels
    "lock_recipe":      "Approve && Lock",
    "unlock_recipe":    "Unlock Recipe",

    # Source filter labels (experiment log, sessions list)
    "source_recipe":    "Recipe",
    "source_manual":    "Manual",
}
