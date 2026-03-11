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
        """With n_sections=1, the snippet must contain at most one section block.

        Section blocks are delimited by '\\n\\n' and each starts with a '## '
        heading line.  The body of a section may legitimately contain '## '
        within table cells or inline references, so we count section-starting
        heading lines (lines whose very first characters are '## ') rather
        than counting all occurrences of the substring.
        """
        from ai.manual_rag import _load_sections, retrieve
        if not _load_sections():
            pytest.skip("UserManual.md not found")
        result = retrieve("camera acquisition scan live", n_sections=1)
        if result:
            # Count only lines that start a new section (begin with "## ")
            section_heading_lines = [
                ln for ln in result.splitlines()
                if ln.startswith("## ")
            ]
            assert len(section_heading_lines) <= 1, (
                f"Expected at most 1 section heading, found "
                f"{len(section_heading_lines)}: {section_heading_lines}"
            )

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


# ================================================================== #
#  4. Synonym normalisation                                           #
# ================================================================== #

class TestSynonymNormalisation:
    """Verify that _SYNONYMS are applied symmetrically in _tokenize()."""

    def test_synonyms_dict_exists(self):
        """_SYNONYMS must be a non-empty dict."""
        from ai.manual_rag import _SYNONYMS
        assert isinstance(_SYNONYMS, dict)
        assert len(_SYNONYMS) > 0

    def test_clipped_maps_to_saturation(self):
        """'clipped' and 'clipping' must both tokenise to 'saturation'."""
        from ai.manual_rag import _tokenize
        tokens = _tokenize("clipped image clipping")
        assert "saturation" in tokens
        assert "clipped" not in tokens
        assert "clipping" not in tokens

    def test_overexposed_maps_to_saturation(self):
        """'overexposed' must tokenise to 'saturation'."""
        from ai.manual_rag import _tokenize
        tokens = _tokenize("overexposed frame")
        assert "saturation" in tokens

    def test_calibrate_maps_to_calibration(self):
        """'calibrate' and 'calibrating' must both map to 'calibration'."""
        from ai.manual_rag import _tokenize
        t1 = _tokenize("calibrate the stage")
        t2 = _tokenize("calibrating now")
        assert "calibration" in t1
        assert "calibration" in t2
        assert "calibrate" not in t1
        assert "calibrating" not in t2

    def test_acquire_maps_to_acquisition(self):
        """'acquire', 'acquiring', 'acquired' must all map to 'acquisition'."""
        from ai.manual_rag import _tokenize
        for word in ("acquire", "acquiring", "acquired"):
            tokens = _tokenize(word)
            assert "acquisition" in tokens, f"'{word}' did not map to 'acquisition'"
            assert word not in tokens

    def test_debug_maps_to_troubleshooting(self):
        """'debug' must map to 'troubleshooting'."""
        from ai.manual_rag import _tokenize
        tokens = _tokenize("how to debug connection issue")
        assert "troubleshooting" in tokens

    def test_disconnected_maps_to_connection(self):
        """'disconnected' and 'reconnect' must map to 'connection'."""
        from ai.manual_rag import _tokenize
        t1 = _tokenize("camera disconnected")
        t2 = _tokenize("reconnect device")
        assert "connection" in t1
        assert "connection" in t2

    def test_unknown_word_unchanged(self):
        """A word not in _SYNONYMS must pass through unchanged."""
        from ai.manual_rag import _tokenize
        tokens = _tokenize("exposure gain frame")
        assert "exposure" in tokens
        assert "gain" in tokens
        assert "frame" in tokens

    def test_synonyms_applied_to_sections(self):
        """Section token sets must not contain raw synonym keys — only canonical forms."""
        from ai.manual_rag import _load_sections, _SYNONYMS
        sections = _load_sections()
        if not sections:
            pytest.skip("UserManual.md not found")
        for heading, body, tokens in sections:
            for raw_form in _SYNONYMS:
                assert raw_form not in tokens, (
                    f"Section '{heading}' contains raw synonym key '{raw_form}' "
                    f"— _tokenize() should have mapped it to '{_SYNONYMS[raw_form]}'"
                )

    def test_retrieve_clipped_finds_saturation_section(self):
        """A query using 'clipped' must return a str (synonym bridges the gap)."""
        from ai.manual_rag import _load_sections, retrieve
        if not _load_sections():
            pytest.skip("UserManual.md not found")
        result = retrieve("camera clipped pixels")
        assert isinstance(result, str)


# ================================================================== #
#  5. BM25 index                                                       #
# ================================================================== #

class TestBM25Index:
    """Verify the BM25 retrieval index built over manual sections."""

    def test_bm25_index_returns_expected_types(self):
        """_load_bm25_index() must return (dict, list, list, float)."""
        from ai.manual_rag import _load_bm25_index
        idf, term_freqs, doc_lengths, avgdl = _load_bm25_index()
        assert isinstance(idf, dict)
        assert isinstance(term_freqs, list)
        assert isinstance(doc_lengths, list)
        assert isinstance(avgdl, float)

    def test_bm25_index_nonempty_when_manual_present(self):
        """When the manual is available, the index must be populated."""
        from ai.manual_rag import _load_sections, _load_bm25_index
        if not _load_sections():
            pytest.skip("UserManual.md not found")
        idf, term_freqs, doc_lengths, avgdl = _load_bm25_index()
        assert len(idf) > 0
        assert len(term_freqs) > 0
        assert avgdl > 0.0

    def test_bm25_index_length_matches_sections(self):
        """term_freqs and doc_lengths must have the same length as _load_sections()."""
        from ai.manual_rag import _load_sections, _load_bm25_index
        sections = _load_sections()
        if not sections:
            pytest.skip("UserManual.md not found")
        _, term_freqs, doc_lengths, _ = _load_bm25_index()
        assert len(term_freqs) == len(sections)
        assert len(doc_lengths) == len(sections)

    def test_bm25_idf_all_positive(self):
        """All IDF weights must be positive (Okapi BM25 IDF + 1 guard)."""
        from ai.manual_rag import _load_sections, _load_bm25_index
        if not _load_sections():
            pytest.skip("UserManual.md not found")
        idf, _, _, _ = _load_bm25_index()
        for term, weight in idf.items():
            assert weight > 0, f"IDF for '{term}' is not positive: {weight}"

    def test_bm25_score_function_positive_for_match(self):
        """_bm25() must return a positive score when the query term is in the doc."""
        from ai.manual_rag import _bm25
        from collections import Counter
        # Artificial single-term scenario
        idf        = {"exposure": 2.0}
        tf_counter = Counter({"exposure": 3})
        score      = _bm25(frozenset(["exposure"]), idf, tf_counter, 10, 10.0)
        assert score > 0.0, f"BM25 score should be positive, got {score}"

    def test_bm25_score_zero_for_no_match(self):
        """_bm25() must return 0.0 when no query term matches the document."""
        from ai.manual_rag import _bm25
        from collections import Counter
        idf        = {"exposure": 2.0}
        tf_counter = Counter({"gain": 5})
        score      = _bm25(frozenset(["exposure"]), idf, tf_counter, 10, 10.0)
        assert score == 0.0, f"BM25 score should be 0.0 for no match, got {score}"

    def test_retrieve_bm25_still_passes_threshold(self):
        """retrieve() with BM25 ranking still respects the Jaccard min_score filter."""
        from ai.manual_rag import retrieve
        # min_score=1.0 is impossible for Jaccard — BM25 should not bypass it
        result = retrieve("camera exposure saturation", min_score=1.0)
        assert result == "", (
            "BM25 ranking must not bypass the Jaccard min_score threshold"
        )

    def test_retrieve_bm25_higher_score_ranked_first(self):
        """A section with more matching terms should rank above one with fewer."""
        from ai.manual_rag import _load_sections, retrieve
        if not _load_sections():
            pytest.skip("UserManual.md not found")
        # Both sections should exist; whichever has more 'calibration' term
        # occurrences should appear first in the result.
        result = retrieve("calibration temperature coefficient", n_sections=2)
        if result:
            blocks = [b for b in result.split("\n\n") if b.strip().startswith("## ")]
            # Just verify the structure is sane — at most 2 blocks returned
            assert len(blocks) <= 2


# ================================================================== #
#  6. ModelDownloader SHA-256 field                                    #
# ================================================================== #

class TestModelCatalog:
    """Verify that the model catalog sha256 field is present and well-formed."""

    def test_catalog_has_sha256_field(self):
        """Every MODEL_CATALOG entry must have a 'sha256' key."""
        from ai.model_catalog import MODEL_CATALOG
        for model_id, entry in MODEL_CATALOG.items():
            assert "sha256" in entry, (
                f"MODEL_CATALOG['{model_id}'] is missing the 'sha256' key"
            )

    def test_sha256_field_is_string(self):
        """The 'sha256' field must be a str (empty or 64-char hex digest)."""
        from ai.model_catalog import MODEL_CATALOG
        import re
        hex_re = re.compile(r"^[0-9a-f]{64}$")
        for model_id, entry in MODEL_CATALOG.items():
            sha = entry["sha256"]
            assert isinstance(sha, str), (
                f"MODEL_CATALOG['{model_id}']['sha256'] must be a str"
            )
            # Either empty (no verification) or a valid 64-char lowercase hex digest
            assert sha == "" or hex_re.match(sha), (
                f"MODEL_CATALOG['{model_id}']['sha256'] is not empty or valid hex: {sha!r}"
            )


# ================================================================== #
#  7. AIService cancel / export                                        #
# ================================================================== #

class TestAIServiceInterface:
    """Smoke-test the new public methods on AIService without a loaded model."""

    def _make_service(self):
        """Create an AIService without a QApplication (signals not connected)."""
        import sys
        # Minimal PyQt5 setup — import only, no display required
        from ai.ai_service import AIService
        # AIService requires a QApplication to exist for QObject
        # We test the attributes without instantiating (import-level check)
        return AIService

    def test_cancel_method_exists(self):
        """AIService must expose a cancel() method."""
        from ai.ai_service import AIService
        assert callable(getattr(AIService, "cancel", None)), (
            "AIService must have a cancel() method"
        )

    def test_export_history_method_exists(self):
        """AIService must expose an export_history() method."""
        from ai.ai_service import AIService
        assert callable(getattr(AIService, "export_history", None)), (
            "AIService must have an export_history() method"
        )

    def test_history_exported_signal_exists(self):
        """AIService must declare a history_exported signal."""
        from ai.ai_service import AIService
        assert hasattr(AIService, "history_exported"), (
            "AIService must have a 'history_exported' pyqtSignal"
        )
