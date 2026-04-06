"""
ui/widgets/empty_state.py

Factory for "empty state" placeholder widgets shown when a device is not
connected or no data is available.

Usage
-----
Hardware tabs (device not connected)::

    from ui.widgets.empty_state import build_empty_state

    page = build_empty_state(
        title="Temperature",
        description="Connect the TEC controller in Device Manager to enable controls.",
        on_action=self.open_device_manager,
    )

Analysis tabs (no data loaded)::

    page = build_empty_state(
        icon_text="\U0001f50d",       # unicode emoji instead of MDI icon
        title="No Sessions Selected",
        description="Select two sessions in the Sessions tab to compare them.",
        btn_text="Go to Sessions",
        on_action=lambda: self.navigate_requested.emit("Sessions"),
        use_mdi_icon=False,
    )

The returned ``EmptyStatePage`` is a plain ``QWidget`` with public
attributes for sub-widgets so callers can restyle on theme switch::

    page.icon_lbl    # QLabel — the icon
    page.title_lbl   # QLabel — the heading
    page.desc_lbl    # QLabel — the description
    page.action_btn  # QPushButton | None — the action button
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton

from ui.theme import FONT, PALETTE
from ui.icons import IC, make_icon_label


class EmptyStatePage(QWidget):
    """Lightweight container returned by :func:`build_empty_state`.

    Sub-widgets are stored as public attributes so ``_apply_styles()``
    methods can re-theme them without rebuilding the page.
    """

    icon_lbl: QLabel
    title_lbl: QLabel
    desc_lbl: QLabel
    action_btn: QPushButton | None

    def _apply_styles(self) -> None:
        """Re-apply palette colours after a theme switch."""
        P, F = PALETTE, FONT
        if getattr(self, "_use_mdi", False):
            # Rebuild the MDI icon with the new palette colour
            new_icon = make_icon_label(
                self._mdi_icon, color=P["textSub"],
                size=self._mdi_size)
            new_icon.setAlignment(Qt.AlignCenter)
            old = self.icon_lbl
            lay = self.layout()
            idx = lay.indexOf(old)
            lay.removeWidget(old)
            old.deleteLater()
            lay.insertWidget(idx, new_icon)
            self.icon_lbl = new_icon
        else:
            self.icon_lbl.setStyleSheet(
                f"font-size: 52pt; color: {P['border']};")

        self.title_lbl.setStyleSheet(
            f"font-size: {F['readoutSm']}pt; font-weight: bold; "
            f"color: {P['textDim']};")
        self.desc_lbl.setStyleSheet(
            f"font-size: {F['label']}pt; color: {P['textSub']};")

        if self.action_btn is not None:
            self.action_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {P['surface']}; color: {P['accent']};
                    border: 1px solid {P['accent']}66; border-radius: 5px;
                    font-size: {F['label']}pt; font-weight: 600;
                }}
                QPushButton:hover {{ background: {P['surface2']}; }}
            """)


def build_empty_state(
    *,
    title: str,
    description: str,
    icon: str = IC.LINK_OFF,
    icon_size: int = 64,
    btn_text: str = "Open Device Manager",
    on_action=None,
    use_mdi_icon: bool = True,
    icon_text: str = "",
    max_desc_width: int = 400,
) -> EmptyStatePage:
    """Create a centred empty-state placeholder page.

    Parameters
    ----------
    title
        Heading text (e.g. ``"Temperature Not Connected"``).
    description
        Explanatory body text shown below the title.
    icon
        MDI icon constant from :class:`ui.icons.IC` (used when
        *use_mdi_icon* is True).
    icon_size
        Pixel size of the MDI icon.
    btn_text
        Label for the action button.  Pass ``""`` to omit the button.
    on_action
        Callable connected to the button's ``clicked`` signal.
    use_mdi_icon
        If False, *icon_text* is rendered as a plain text label
        (e.g. a unicode emoji) instead of an MDI pixmap.
    icon_text
        Unicode string used as the icon when *use_mdi_icon* is False.
    max_desc_width
        Maximum pixel width of the description label.

    Returns
    -------
    EmptyStatePage
        A QWidget with ``.icon_lbl``, ``.title_lbl``, ``.desc_lbl``,
        and ``.action_btn`` attributes for downstream re-theming.
    """
    P, F = PALETTE, FONT
    page = EmptyStatePage()

    lay = QVBoxLayout(page)
    lay.setAlignment(Qt.AlignCenter)
    lay.setSpacing(16)

    # ── Icon ──────────────────────────────────────────────────────────
    if use_mdi_icon:
        icon_lbl = make_icon_label(icon, color=P["textSub"], size=icon_size)
        icon_lbl.setAlignment(Qt.AlignCenter)
        page._use_mdi = True
        page._mdi_icon = icon
        page._mdi_size = icon_size
    else:
        icon_lbl = QLabel(icon_text)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(
            f"font-size: 52pt; color: {P['border']};")
        page._use_mdi = False

    # ── Title ─────────────────────────────────────────────────────────
    title_lbl = QLabel(title)
    title_lbl.setAlignment(Qt.AlignCenter)
    title_lbl.setStyleSheet(
        f"font-size: {F['readoutSm']}pt; font-weight: bold; "
        f"color: {P['textDim']};")

    # ── Description ───────────────────────────────────────────────────
    desc_lbl = QLabel(description)
    desc_lbl.setAlignment(Qt.AlignCenter)
    desc_lbl.setWordWrap(True)
    desc_lbl.setStyleSheet(
        f"font-size: {F['label']}pt; color: {P['textSub']};")
    desc_lbl.setMaximumWidth(max_desc_width)

    # ── Action button (optional) ──────────────────────────────────────
    action_btn = None
    if btn_text and on_action is not None:
        action_btn = QPushButton(btn_text)
        action_btn.setFixedWidth(200)
        action_btn.setFixedHeight(36)
        action_btn.setStyleSheet(f"""
            QPushButton {{
                background: {P['surface']}; color: {P['accent']};
                border: 1px solid {P['accent']}66; border-radius: 5px;
                font-size: {F['label']}pt; font-weight: 600;
            }}
            QPushButton:hover {{ background: {P['surface2']}; }}
        """)
        action_btn.clicked.connect(on_action)

    # ── Layout ────────────────────────────────────────────────────────
    lay.addStretch()
    lay.addWidget(icon_lbl)
    lay.addWidget(title_lbl)
    lay.addWidget(desc_lbl)
    if action_btn is not None:
        lay.addSpacing(8)
        lay.addWidget(action_btn, 0, Qt.AlignCenter)
    lay.addStretch()

    # Store refs for theme switching
    page.icon_lbl = icon_lbl
    page.title_lbl = title_lbl
    page.desc_lbl = desc_lbl
    page.action_btn = action_btn

    return page
