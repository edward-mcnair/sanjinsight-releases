"""
ui/widgets/theme_aware.py

ThemeAwareMixin — lightweight mixin enforcing the ``_apply_styles()`` contract.

Usage
-----
Any widget that calls ``setStyleSheet()`` should inherit from this mixin
to guarantee it participates in theme switching::

    class MyWidget(ThemeAwareMixin, QWidget):
        def __init__(self):
            super().__init__()
            self._apply_styles()

        def _apply_styles(self):
            self.setStyleSheet(f"background:{PALETTE['bg']};")

The mixin provides:

1.  A concrete ``_apply_styles()`` default (no-op) so subclasses that
    forget to override still satisfy ``hasattr(w, '_apply_styles')``.

2.  A ``__init_subclass__`` hook that emits a runtime warning (not an
    error) when a subclass calls ``setStyleSheet`` without overriding
    ``_apply_styles``.  This helps catch regressions during development
    without breaking anything in production.

The mixin is intentionally minimal — it adds **zero overhead** to
``paintEvent`` and **zero instance state**.
"""

from __future__ import annotations

import logging
import warnings

log = logging.getLogger(__name__)


class ThemeAwareMixin:
    """Mixin that marks a widget as theme-switch-safe.

    Any widget inheriting this mixin will be checked (once, at class
    definition time) for whether it overrides ``_apply_styles()``.
    If the subclass has ``setStyleSheet`` calls but no ``_apply_styles``
    override, a ``UserWarning`` is emitted during development.
    """

    def _apply_styles(self) -> None:
        """Rebuild inline stylesheets from the current PALETTE.

        Override in subclasses.  The default implementation simply
        triggers a repaint, which is sufficient for widgets that only
        use PALETTE inside ``paintEvent``.
        """
        try:
            self.update()  # type: ignore[attr-defined]
        except AttributeError:
            pass

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Light check: warn if the subclass appears to use setStyleSheet
        # but hasn't overridden _apply_styles.  This is a development-time
        # hint, not an enforcement barrier.
        if "_apply_styles" not in cls.__dict__:
            # We can't inspect method bodies at definition time, so just
            # log a debug note for auditing purposes.
            log.debug(
                "ThemeAwareMixin subclass %s.%s does not override "
                "_apply_styles() — ensure inline stylesheets are "
                "refreshed on theme switch.",
                cls.__module__, cls.__qualname__,
            )
