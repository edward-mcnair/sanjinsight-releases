"""
tests/test_ai.py

Unit tests for the AI assistant modules.

Covers:
    • build_system_prompt() always embeds Quickstart Guide content
    • build_system_prompt() always appends the out-of-scope instruction
    • build_system_prompt() preserves the persona base string
    • build_system_prompt() includes AI_DOMAIN_KNOWLEDGE
    • SYSTEM_PROMPT convenience constant is non-empty
    • manual_rag._load_sections() returns a list
    • manual_rag.retrieve() returns "" for an empty query
    • manual_rag.retrieve() returns a string for any query
    • manual_rag.retrieve() finds a relevant section when the manual is present
    • manual_rag.retrieve() respects the n_sections=1 cap
    • manual_rag.retrieve() returns "" when min_score is impossibly high

All tests use synthetic data or the real docs/ files — no hardware required.
"""

from __future__ import annotations

import os
import sys
import pytest

# Ensure the project root is on sys.path regardless of where pytest is invoked
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ================================================================== #
#  1. build_system_prompt()                                           #
# ================================================================== #

class TestBuildSystemPrompt:
    """Verify that build_system_prompt() assembles the correct system prompt."""

    def test_includes_quickstart_guide(self):
        """Quickstart Guide section header must appear in every assembled prompt."""
        from ai.prompt_templates import build_system_prompt, QUICKSTART_GUIDE
        if not QUICKSTART_GUIDE:
            pytest.skip("QuickstartGuide.md not found — skipping Quickstart content check")
        prompt = build_system_prompt("You are a test assistant.")
        assert "SanjINSIGHT Quickstart Guide" in prompt

    def test_includes_out_of_scope_instruction(self):
        """Out-of-scope canned response must be present."""
        from ai.prompt_templates import build_system_prompt
        prompt = build_system_prompt("You are a test assistant.")
        # The instruction references the token-limit fallback or the docs URL
        assert "token limit" in prompt.lower() or "quickstart guide" in prompt.lower()

    def test_includes_docs_url(self):
        """User Manual URL (from version.DOCS_URL) must appear in every prompt."""
        from ai.prompt_templates import build_system_prompt
        from version import DOCS_URL
        prompt = build_system_prompt("You are a test assistant.")
        assert DOCS_URL in prompt

    def test_preserves_base_string(self):
        """The persona base string must be present verbatim in the final prompt."""
        from ai.prompt_templates import build_system_prompt
        base = "You are a unique test persona for SanjINSIGHT X9."
        prompt = build_system_prompt(base)
        assert base in prompt

    def test_includes_domain_knowledge(self):
        """AI_DOMAIN_KNOWLEDGE text must be injected into every prompt."""
        from ai.prompt_templates import build_system_prompt
        from ai.instrument_knowledge import AI_DOMAIN_KNOWLEDGE
        prompt = build_system_prompt("Test base.")
        # Check the first 50 chars of the domain knowledge string are present
        assert AI_DOMAIN_KNOWLEDGE[:50] in prompt

    def test_system_prompt_constant_not_empty(self):
        """SYSTEM_PROMPT module constant must be a non-trivial string."""
        from ai.prompt_templates import SYSTEM_PROMPT
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 200

    def test_system_prompt_computed_from_build(self):
        """SYSTEM_PROMPT must equal build_system_prompt(_DEFAULT_BASE)."""
        from ai.prompt_templates import SYSTEM_PROMPT, build_system_prompt, _DEFAULT_BASE
        assert SYSTEM_PROMPT == build_system_prompt(_DEFAULT_BASE)

    def test_no_system_prompt_compact(self):
        """SYSTEM_PROMPT_COMPACT was removed in v1.1.0 — it must not exist."""
        import ai.prompt_templates as tmpl
        assert not hasattr(tmpl, "SYSTEM_PROMPT_COMPACT"), (
            "SYSTEM_PROMPT_COMPACT was supposed to be removed in v1.1.0"
        )


# ================================================================== #
#  2. manual_rag                                                       #
# ================================================================== #

class TestManualRag:
    """Verify the User Manual keyword retrieval module."""

    def test_load_sections_returns_list(self):
        """_load_sections() must always return a list (possibly empty)."""
        from ai.manual_rag import _load_sections
        sections = _load_sections()
        assert isinstance(sections, list)

    def test_load_sections_tuple_structure(self):
        """Each section must be a 3-tuple (heading: str, body: str, tokens: frozenset)."""
        from ai.manual_rag import _load_sections
        sections = _load_sections()
        if not sections:
            pytest.skip("UserManual.md not found")
        for heading, body, tokens in sections:
            assert isinstance(heading, str)
            assert isinstance(body, str)
            assert isinstance(tokens, frozenset)
            assert heading.startswith("## ")

    def test_retrieve_empty_query_returns_empty(self):
        """An empty query must always return an empty string."""
        from ai.manual_rag import retrieve
        assert retrieve("") == ""

    def test_retrieve_whitespace_query_returns_empty(self):
        """A whitespace-only query has no tokens and must return ''."""
        from ai.manual_rag import retrieve
        assert retrieve("   ") == ""

    def test_retrieve_returns_string(self):
        """retrieve() must return a str for any non-empty query."""
        from ai.manual_rag import retrieve
        result = retrieve("camera exposure saturation")
        assert isinstance(result, str)

    def test_retrieve_relevant_section_found(self):
        """A query about 'calibration' must match the Calibration section."""
        from ai.manual_rag import _load_sections, retrieve
        if not _load_sections():
            pytest.skip("UserManual.md not found")
        result = retrieve("calibration temperature C_T coefficient")
        assert result != "", "Expected at least one calibration section to be returned"

    def test_retrieve_limit_n_sections(self):
        """With n_sections=1, the snippet must contain at most one ## heading."""
        from ai.manual_rag import _load_sections, retrieve
        if not _load_sections():
            pytest.skip("UserManual.md not found")
        result = retrieve("camera acquisition scan live", n_sections=1)
        if result:
            assert result.count("## ") <= 1

    def test_retrieve_impossible_min_score_returns_empty(self):
        """A min_score of 1.0 (perfect Jaccard) should never be satisfied."""
        from ai.manual_rag import retrieve
        result = retrieve("camera exposure saturation", min_score=1.0)
        assert result == ""

    def test_retrieve_no_match_gibberish(self):
        """Gibberish tokens with a high min_score must return ''."""
        from ai.manual_rag import retrieve
        result = retrieve("xyzzy frobnicator quuxbaz", min_score=0.5)
        assert result == ""

    def test_retrieve_truncates_long_sections(self):
        """Each section in the snippet must not exceed _MAX_WORDS_PER_SECTION words
        (plus a trailing ellipsis marker if truncated)."""
        from ai.manual_rag import _load_sections, retrieve, _MAX_WORDS_PER_SECTION
        if not _load_sections():
            pytest.skip("UserManual.md not found")
        result = retrieve("acquisition pipeline frames exposure gain")
        if not result:
            pytest.skip("No matching sections returned")
        for section_block in result.split("\n\n"):
            # Word count of the body (skip the heading line)
            lines = section_block.strip().splitlines()
            body  = "\n".join(lines[1:]) if len(lines) > 1 else ""
            words = body.split()
            assert len(words) <= _MAX_WORDS_PER_SECTION + 2, (
                f"Section body exceeds word limit: {len(words)} words"
            )


# ================================================================== #
#  3. Template RAG integration                                         #
# ================================================================== #

class TestTemplateRagIntegration:
    """Verify that manual_context is injected correctly into all three templates."""

    def _ctx(self) -> str:
        return '{"camera": {"connected": true}}'

    def test_free_ask_no_manual_context(self):
        """free_ask without manual_context must not include the Manual header."""
        from ai.prompt_templates import free_ask
        msgs = free_ask("What is the exposure?", self._ctx())
        user_content = msgs[-1]["content"]
        assert "Relevant User Manual sections" not in user_content

    def test_free_ask_with_manual_context(self):
        """free_ask with manual_context must inject the manual snippet."""
        from ai.prompt_templates import free_ask
        snippet = "## Camera\nThe camera tab controls exposure and gain."
        msgs = free_ask("What is the exposure?", self._ctx(), manual_context=snippet)
        user_content = msgs[-1]["content"]
        assert "Relevant User Manual sections" in user_content
        assert snippet in user_content

    def test_explain_tab_no_manual_context(self):
        """explain_tab without manual_context must not include the Manual header."""
        from ai.prompt_templates import explain_tab
        msgs = explain_tab("Camera", self._ctx())
        user_content = msgs[-1]["content"]
        assert "Relevant User Manual sections" not in user_content

    def test_explain_tab_with_manual_context(self):
        """explain_tab with manual_context must inject the manual snippet."""
        from ai.prompt_templates import explain_tab
        snippet = "## Camera\nThe camera tab controls exposure and gain."
        msgs = explain_tab("Camera", self._ctx(), manual_context=snippet)
        user_content = msgs[-1]["content"]
        assert "Relevant User Manual sections" in user_content
        assert snippet in user_content

    def test_diagnose_no_manual_context(self):
        """diagnose without manual_context must not include the Manual header."""
        from ai.prompt_templates import diagnose
        msgs = diagnose(self._ctx())
        user_content = msgs[-1]["content"]
        assert "Relevant User Manual sections" not in user_content

    def test_diagnose_with_manual_context(self):
        """diagnose with manual_context must inject the manual snippet."""
        from ai.prompt_templates import diagnose
        snippet = "## Troubleshooting\nCheck connections if status dot is red."
        msgs = diagnose(self._ctx(), manual_context=snippet)
        user_content = msgs[-1]["content"]
        assert "Relevant User Manual sections" in user_content
        assert snippet in user_content

    def test_out_of_scope_instruction_updated(self):
        """The out-of-scope instruction must mention 'selected sections' (v1.1.0+)."""
        from ai.prompt_templates import SYSTEM_PROMPT
        assert "selected sections" in SYSTEM_PROMPT

    def test_session_report_no_manual_context(self):
        """session_report without manual_context must not include the Manual header."""
        from ai.prompt_templates import session_report
        msgs = session_report({}, self._ctx())
        user_content = msgs[-1]["content"]
        assert "Relevant User Manual sections" not in user_content

    def test_session_report_with_manual_context(self):
        """session_report with manual_context must inject the manual snippet."""
        from ai.prompt_templates import session_report
        snippet = "## Acquisition Quality\nSNR above 20 dB indicates good signal."
        msgs = session_report({}, self._ctx(), manual_context=snippet)
        user_content = msgs[-1]["content"]
        assert "Relevant User Manual sections" in user_content
        assert snippet in user_content
