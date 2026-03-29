"""
ui/guidance/tutor.py  —  Tier 3: AI-driven adaptive tutorial manager

NOT YET IMPLEMENTED.  This module defines the interface for an
AI-powered tutorial system that adapts to the user's context,
hardware, and questions.

When implemented, the tutor will:
  - Use the AI service (Cloud, Ollama, or local) to generate
    contextual explanations anchored to specific workflow steps
  - Adapt language and depth based on workspace mode
  - Reference the same content database (ui.guidance.content)
    as Tier 1 cards, using step_ids as conversation anchors
  - Provide a "Still confused? Ask AI" button on GuidanceCards
  - Optionally drive Tier 2 overlay spotlights based on AI
    recommendations

The GuidanceCard.step_id field is the bridge: each card's step_id
maps to a content entry that provides the AI with domain context.

Dependencies (when implemented):
  - ai.ai_service.AIService — inference engine
  - ui.guidance.content     — domain knowledge context
  - ui.guidance.overlay     — optional visual highlighting
"""
from __future__ import annotations

import logging
from typing import Optional, Callable

log = logging.getLogger(__name__)


class TutorSession:
    """Manages an AI-guided tutorial conversation.

    Tier 3 stub — interface only, no AI calls yet.
    """

    def __init__(self) -> None:
        self._step_id: str | None = None
        self._history: list[dict] = []  # {"role": ..., "content": ...}
        self._active = False
        self._on_response: Callable[[str], None] | None = None

    def start(self, step_id: str) -> None:
        """Begin a tutorial conversation anchored to a workflow step.

        The step_id maps to content in ui.guidance.content, which is
        injected into the system prompt as domain context.
        """
        self._step_id = step_id
        self._active = True
        self._history.clear()
        log.info("Tutor session started for step: %s", step_id)
        # TODO: build system prompt from content.get_help() + content.get_section_cards()
        # TODO: send initial greeting via AIService

    def ask(self, question: str) -> None:
        """Send a user question to the AI tutor.

        The response is delivered asynchronously via the on_response callback.
        """
        if not self._active:
            log.warning("TutorSession.ask() called on inactive session")
            return
        self._history.append({"role": "user", "content": question})
        log.info("Tutor question: %s", question[:80])
        # TODO: send to AIService with step context
        # TODO: on response, call self._on_response(text)

    def set_response_callback(self, callback: Callable[[str], None]) -> None:
        """Set the callback for receiving AI responses."""
        self._on_response = callback

    def stop(self) -> None:
        """End the tutorial session."""
        self._active = False
        self._step_id = None
        log.info("Tutor session stopped")

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def current_step_id(self) -> str | None:
        return self._step_id
