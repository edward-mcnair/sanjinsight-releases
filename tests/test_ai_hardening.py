"""
tests/test_ai_hardening.py

Targeted tests for the AI subsystem hardening modules:
  - token_budget: estimation, allocation, trimming, truncation
  - request_lifecycle: stale suppression, cancellation, supersession
  - task_context: digest caching, task-specific filtering, compact summary
  - output_parser: JSON extraction, repair, tier-aware schemas
  - prompt_templates: tier-specific instructions
  - manual_rag: retrieval ranking, query normalisation, synonyms
  - advisor: parse_advice with output_parser integration
"""

import json
import threading
import time
import pytest


# ─── token_budget ────────────────────────────────────────────────────────────

class TestTokenEstimation:
    def test_empty_string(self):
        from ai.token_budget import estimate_tokens
        assert estimate_tokens("") == 0

    def test_short_string(self):
        from ai.token_budget import estimate_tokens
        # 4 chars → ~1 token
        assert estimate_tokens("test") >= 1

    def test_longer_string(self):
        from ai.token_budget import estimate_tokens
        text = "a" * 400  # ~100 tokens
        result = estimate_tokens(text)
        assert 80 <= result <= 120

    def test_messages_tokens(self):
        from ai.token_budget import estimate_messages_tokens
        msgs = [
            {"role": "user", "content": "hello world"},
            {"role": "assistant", "content": "hi there"},
        ]
        total = estimate_messages_tokens(msgs)
        # 2 messages × ~4 overhead + content tokens
        assert total > 8


class TestBudgetAllocation:
    def test_basic_allocation(self):
        from ai.token_budget import allocate_budget, TaskType
        budget = allocate_budget(TaskType.CHAT, n_ctx=8192, tier=2)
        assert budget.n_ctx == 8192
        # All slots should be positive
        assert budget.system_prompt > 0
        assert budget.history > 0
        assert budget.response > 0
        # Sum should not exceed n_ctx
        total = (budget.system_prompt + budget.task_prompt +
                 budget.instrument_ctx + budget.rag_snippets +
                 budget.history + budget.response)
        assert total <= budget.n_ctx

    def test_cloud_tier_caps(self):
        from ai.token_budget import allocate_budget, TaskType
        # FULL tier caps at 32K even if n_ctx is higher
        budget = allocate_budget(TaskType.CHAT, n_ctx=128_000, tier=3)
        assert budget.n_ctx == 32_000

    def test_basic_tier_uses_small_ctx(self):
        from ai.token_budget import allocate_budget, TaskType
        budget = allocate_budget(TaskType.CHAT, n_ctx=8192, tier=1)
        assert budget.n_ctx == 4096

    def test_session_report_favours_response(self):
        from ai.token_budget import allocate_budget, TaskType
        chat = allocate_budget(TaskType.CHAT, n_ctx=8192, tier=2)
        report = allocate_budget(TaskType.SESSION_REPORT, n_ctx=8192, tier=2)
        assert report.response > chat.response

    def test_advisor_minimal_history(self):
        from ai.token_budget import allocate_budget, TaskType
        budget = allocate_budget(TaskType.ADVISOR, n_ctx=8192, tier=2)
        # Advisor needs very little history
        assert budget.history < budget.response


class TestHistoryTrimming:
    def test_empty_history(self):
        from ai.token_budget import trim_history
        assert trim_history([], 1000) == []

    def test_zero_budget(self):
        from ai.token_budget import trim_history
        msgs = [{"role": "user", "content": "hello"}]
        assert trim_history(msgs, 0) == []

    def test_fits_without_trimming(self):
        from ai.token_budget import trim_history
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hey"},
        ]
        result = trim_history(msgs, 10000)
        assert len(result) == 2

    def test_drops_oldest_first(self):
        from ai.token_budget import trim_history
        msgs = [
            {"role": "user", "content": "x" * 200},      # ~50 tok + overhead
            {"role": "assistant", "content": "x" * 200},  # ~50 tok + overhead
            {"role": "user", "content": "recent"},
            {"role": "assistant", "content": "latest"},
        ]
        # Very tight budget — should keep only the newest messages
        result = trim_history(msgs, 30)
        assert len(result) < len(msgs)
        # Last message should be preserved
        assert result[-1]["content"] == "latest"

    def test_turn_count_cap(self):
        from ai.token_budget import trim_history
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(100)]
        result = trim_history(msgs, 100000, max_turns=5)
        assert len(result) <= 10  # 5 turns × 2 msgs


class TestTruncateText:
    def test_short_text_unchanged(self):
        from ai.token_budget import truncate_text
        assert truncate_text("hello world", 1000) == "hello world"

    def test_long_text_truncated(self):
        from ai.token_budget import truncate_text
        text = "word " * 500  # ~2500 chars
        result = truncate_text(text, 50)
        assert result.endswith("[truncated]")
        assert len(result) < len(text)

    def test_zero_budget(self):
        from ai.token_budget import truncate_text
        assert truncate_text("hello", 0) == ""


# ─── request_lifecycle ───────────────────────────────────────────────────────

class TestRequestManager:
    def test_new_request_returns_id(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        rid = mgr.new_request(FlowType.CHAT, "test")
        assert isinstance(rid, int)
        assert rid > 0

    def test_monotonic_ids(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        r1 = mgr.new_request(FlowType.CHAT)
        r2 = mgr.new_request(FlowType.CHAT)
        assert r2 > r1

    def test_is_current_for_active_request(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        rid = mgr.new_request(FlowType.CHAT)
        assert mgr.is_current(rid)

    def test_supersession_cancels_previous(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        r1 = mgr.new_request(FlowType.CHAT, "first")
        r2 = mgr.new_request(FlowType.CHAT, "second")
        assert not mgr.is_current(r1)  # superseded
        assert mgr.is_current(r2)

    def test_different_flows_independent(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        r_chat = mgr.new_request(FlowType.CHAT, "chat")
        r_report = mgr.new_request(FlowType.REPORT, "report")
        # Both should still be current
        assert mgr.is_current(r_chat)
        assert mgr.is_current(r_report)

    def test_cancel_returns_id(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        rid = mgr.new_request(FlowType.CHAT)
        cancelled = mgr.cancel(FlowType.CHAT)
        assert cancelled == rid
        assert not mgr.is_current(rid)

    def test_cancel_nonexistent_returns_none(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        assert mgr.cancel(FlowType.CHAT) is None

    def test_cancel_all(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        r1 = mgr.new_request(FlowType.CHAT)
        r2 = mgr.new_request(FlowType.REPORT)
        cancelled = mgr.cancel_all()
        assert r1 in cancelled
        assert r2 in cancelled
        assert not mgr.is_current(r1)
        assert not mgr.is_current(r2)

    def test_complete_returns_true_for_current(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        rid = mgr.new_request(FlowType.CHAT)
        assert mgr.complete(rid) is True
        # After completion, no longer "current"
        assert not mgr.is_current(rid)

    def test_complete_returns_false_for_cancelled(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        rid = mgr.new_request(FlowType.CHAT)
        mgr.cancel(FlowType.CHAT)
        assert mgr.complete(rid) is False

    def test_complete_returns_false_for_superseded(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        r1 = mgr.new_request(FlowType.CHAT)
        r2 = mgr.new_request(FlowType.CHAT)
        assert mgr.complete(r1) is False

    def test_reset_clears_state(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        rid = mgr.new_request(FlowType.CHAT)
        mgr.reset()
        assert not mgr.is_current(rid)
        # Counter should still be monotonic after reset
        r2 = mgr.new_request(FlowType.CHAT)
        assert r2 > rid

    def test_thread_safety(self):
        from ai.request_lifecycle import RequestManager, FlowType
        mgr = RequestManager()
        results = []

        def worker():
            for _ in range(50):
                rid = mgr.new_request(FlowType.CHAT)
                results.append(rid)
                mgr.is_current(rid)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # All IDs should be unique
        assert len(set(results)) == len(results)


# ─── task_context ────────────────────────────────────────────────────────────

class TestBuildTaskContext:
    SAMPLE_STATE = json.dumps({
        "tab": "Camera",
        "workspace_mode": "Manual",
        "cam": {"connected": True, "exposure_us": 500, "gain_db": 6},
        "fpga": {"connected": True, "running": True, "freq_hz": 1000},
        "tecs": [{"idx": 0, "enabled": True, "actual_c": 25.0}],
        "stage": {"connected": False},
        "bias": {"connected": False},
        "ldd": {"connected": False},
        "metrics": {"snr_db": 12.5},
        "rules": [],
        "modality": "tr",
        "profile": {"name": "GaAs"},
    })

    def test_chat_context_includes_tab(self):
        from ai.task_context import build_task_context
        from ai.token_budget import TaskType
        result = build_task_context(TaskType.CHAT, self.SAMPLE_STATE)
        data = json.loads(result)
        assert "tab" in data
        assert data["tab"] == "Camera"

    def test_disconnected_device_compact(self):
        from ai.task_context import build_task_context
        from ai.token_budget import TaskType
        result = build_task_context(TaskType.CHAT, self.SAMPLE_STATE)
        data = json.loads(result)
        # Disconnected devices should be "off"
        assert data.get("stage") == "off" or data.get("bias") == "off"

    def test_session_report_excludes_stage(self):
        from ai.task_context import build_task_context
        from ai.token_budget import TaskType
        result = build_task_context(TaskType.SESSION_REPORT, self.SAMPLE_STATE)
        data = json.loads(result)
        assert "stage" not in data

    def test_invalid_json_passthrough(self):
        from ai.task_context import build_task_context
        from ai.token_budget import TaskType
        result = build_task_context(TaskType.CHAT, "not json")
        assert result == "not json"


class TestCompactStateSummary:
    def test_basic_summary(self):
        from ai.task_context import compact_state_summary
        state = json.dumps({
            "cam": {"connected": True, "exposure_us": 500, "gain_db": 6.0},
            "fpga": {"connected": True, "running": True, "freq_hz": 1000, "duty_pct": 50},
            "tecs": [{"idx": 0, "enabled": True, "actual_c": 25.0, "setpoint_c": 25.0}],
            "stage": {"connected": True, "homed": True},
            "tab": "Camera",
        })
        result = compact_state_summary(state)
        assert "Camera" in result
        assert "connected" in result
        assert "500" in result
        assert "FPGA" in result

    def test_disconnected_camera(self):
        from ai.task_context import compact_state_summary
        state = json.dumps({"cam": {"connected": False}})
        result = compact_state_summary(state)
        assert "disconnected" in result

    def test_invalid_json(self):
        from ai.task_context import compact_state_summary
        result = compact_state_summary("bad")
        assert "unavailable" in result


class TestDigestCache:
    def test_initial_state_is_stale(self):
        from ai.task_context import DigestCache
        cache = DigestCache()
        assert cache._digest.stale

    def test_invalidate_marks_stale(self):
        from ai.task_context import DigestCache
        cache = DigestCache()
        cache._digest.stale = False
        cache.invalidate()
        assert cache._digest.stale


# ─── output_parser ───────────────────────────────────────────────────────────

class TestOutputParser:
    def test_clean_json(self):
        from ai.output_parser import parse_json_response
        raw = '{"ready": true, "fix": "lower exposure"}'
        result = parse_json_response(raw)
        assert result.parse_ok
        assert result.data["ready"] is True
        assert not result.repaired

    def test_fenced_json(self):
        from ai.output_parser import parse_json_response
        raw = 'Here is my analysis:\n```json\n{"ready": false, "fix": "increase gain"}\n```'
        result = parse_json_response(raw)
        assert result.parse_ok
        assert result.data["ready"] is False

    def test_trailing_comma_repair(self):
        from ai.output_parser import parse_json_response
        raw = '{"ready": true, "fix": "ok",}'
        result = parse_json_response(raw)
        assert result.parse_ok
        assert result.repaired

    def test_unclosed_brace_repair(self):
        from ai.output_parser import parse_json_response
        raw = '{"ready": true, "fix": "ok"'
        result = parse_json_response(raw)
        assert result.parse_ok
        assert result.repaired

    def test_prose_preamble_then_json(self):
        from ai.output_parser import parse_json_response
        raw = 'Based on the analysis, I recommend:\n{"ready": true, "fix": "all good"}'
        result = parse_json_response(raw)
        assert result.parse_ok
        assert result.data["fix"] == "all good"

    def test_empty_response(self):
        from ai.output_parser import parse_json_response
        result = parse_json_response("")
        assert not result.parse_ok
        assert result.error == "empty response"

    def test_no_json_at_all(self):
        from ai.output_parser import parse_json_response
        result = parse_json_response("Everything looks fine, no changes needed.")
        assert not result.parse_ok

    def test_required_keys_present(self):
        from ai.output_parser import parse_json_response
        raw = '{"ready": true, "conflicts": []}'
        result = parse_json_response(raw, required_keys=("ready", "conflicts"))
        assert result.parse_ok

    def test_required_keys_missing(self):
        from ai.output_parser import parse_json_response
        raw = '{"ready": true}'
        result = parse_json_response(raw, required_keys=("ready", "conflicts"))
        assert not result.parse_ok
        assert "missing" in result.error


class TestTierSchemas:
    def test_basic_schema_is_simple(self):
        from ai.output_parser import advisor_schema_prompt
        schema = advisor_schema_prompt(1)
        assert "ready" in schema
        assert "fix" in schema
        # Should NOT have conflicts array
        assert "physics" not in schema.lower()

    def test_full_schema_has_physics(self):
        from ai.output_parser import advisor_schema_prompt
        schema = advisor_schema_prompt(3)
        assert "physics" in schema.lower()
        assert "summary" in schema


# ─── prompt_templates ────────────────────────────────────────────────────────

class TestTierInstructions:
    def test_chat_tiers(self):
        from ai.prompt_templates import get_tier_instruction
        basic = get_tier_instruction("chat", 1)
        full = get_tier_instruction("chat", 3)
        assert "1-2" in basic
        assert "3-6" in full
        assert len(full) > len(basic)

    def test_diagnose_tiers(self):
        from ai.prompt_templates import get_tier_instruction
        basic = get_tier_instruction("diagnose", 1)
        assert "single" in basic.lower()

    def test_report_tiers(self):
        from ai.prompt_templates import get_tier_instruction
        basic = get_tier_instruction("session_report", 1)
        full = get_tier_instruction("session_report", 3)
        assert "2 sentences" in basic
        assert "4-6" in full

    def test_unknown_task_falls_back(self):
        from ai.prompt_templates import get_tier_instruction
        result = get_tier_instruction("nonexistent", 2)
        # Should fall back to chat instruction
        assert result != ""


# ─── manual_rag ──────────────────────────────────────────────────────────────

class TestQueryNormalisation:
    def test_strips_how_do_i(self):
        from ai.manual_rag import _normalize_query
        assert _normalize_query("how do I calibrate the camera") == "calibrate the camera"

    def test_strips_where_is(self):
        from ai.manual_rag import _normalize_query
        assert _normalize_query("Where is the export button") == "the export button"

    def test_preserves_plain_query(self):
        from ai.manual_rag import _normalize_query
        assert _normalize_query("calibration procedure") == "calibration procedure"


class TestSynonymNormalisation:
    def test_clipping_maps_to_saturation(self):
        from ai.manual_rag import _tokenize
        tokens = _tokenize("camera clipping issue")
        assert "saturation" in tokens

    def test_calibrate_maps_to_calibration(self):
        from ai.manual_rag import _tokenize
        tokens = _tokenize("calibrate temperature")
        assert "calibration" in tokens

    def test_led_maps_to_illumination(self):
        from ai.manual_rag import _tokenize
        tokens = _tokenize("LED wavelength")
        assert "illumination" in tokens

    def test_short_words_excluded(self):
        from ai.manual_rag import _tokenize
        tokens = _tokenize("a is to by in")
        assert len(tokens) == 0  # all < 3 chars


class TestRetrieval:
    def test_empty_query_returns_empty(self):
        from ai.manual_rag import retrieve
        assert retrieve("") == ""

    def test_nonsense_query_returns_empty_or_low(self):
        from ai.manual_rag import retrieve
        # Very high threshold should filter out weak matches
        result = retrieve("xyzzy zork plugh", min_score=0.5)
        assert result == ""


# ─── advisor (output_parser integration) ─────────────────────────────────────

class TestAdvisorParseAdvice:
    def test_clean_json_parsed(self):
        from ai.advisor import parse_advice
        raw = json.dumps({
            "conflicts": [{"issue": "exposure too high", "param": "exposure_us",
                           "value": 200, "unit": "µs"}],
            "suggestions": [],
            "ready": False,
        })
        result = parse_advice(raw)
        assert result.parse_ok
        assert not result.ready
        assert len(result.conflicts) == 1
        assert result.conflicts[0].param == "exposure_us"

    def test_fenced_json_parsed(self):
        from ai.advisor import parse_advice
        raw = (
            "Here is my analysis:\n"
            "```json\n"
            '{"conflicts": [], "suggestions": [{"param": "gain_db", '
            '"value": 12, "unit": "dB", "reason": "improve SNR"}], "ready": true}\n'
            "```"
        )
        result = parse_advice(raw)
        assert result.parse_ok
        assert result.ready
        assert len(result.suggestions) == 1

    def test_malformed_json_repaired(self):
        from ai.advisor import parse_advice
        # Trailing comma — output_parser should fix it
        raw = '{"conflicts": [], "suggestions": [], "ready": true,}'
        result = parse_advice(raw)
        assert result.parse_ok
        assert result.ready

    def test_prose_fallback(self):
        from ai.advisor import parse_advice
        raw = "Everything looks fine. No changes needed."
        result = parse_advice(raw)
        assert not result.parse_ok
        assert result.raw_text == raw

    def test_summary_extracted_for_cloud(self):
        from ai.advisor import parse_advice
        raw = json.dumps({
            "summary": "Profile looks good for GaAs measurement.",
            "conflicts": [],
            "suggestions": [],
            "ready": True,
        })
        result = parse_advice(raw)
        assert result.parse_ok
        assert "GaAs" in result.summary


# ─── ai_metrics ──────────────────────────────────────────────────────────────

class TestAIMetricsCollector:
    def test_initial_snapshot_zeroed(self):
        from ai.ai_metrics import AIMetricsCollector
        m = AIMetricsCollector()
        s = m.snapshot()
        assert s["requests_started"] == 0
        assert s["requests_completed"] == 0
        assert s["stale_tokens_dropped"] == 0
        assert s["parse_success"] == 0

    def test_request_lifecycle_counters(self):
        from ai.ai_metrics import AIMetricsCollector
        m = AIMetricsCollector()
        m.on_request_started()
        m.on_request_started()
        m.on_request_completed(elapsed_s=1.5, tokens=50)
        m.on_request_cancelled()
        s = m.snapshot()
        assert s["requests_started"] == 2
        assert s["requests_completed"] == 1
        assert s["requests_cancelled"] == 1
        assert s["total_tokens_generated"] == 50
        assert s["avg_response_s"] == 1.5

    def test_stale_counters(self):
        from ai.ai_metrics import AIMetricsCollector
        m = AIMetricsCollector()
        m.on_stale_token()
        m.on_stale_token()
        m.on_stale_token()
        m.on_stale_completion()
        s = m.snapshot()
        assert s["stale_tokens_dropped"] == 3
        assert s["stale_completions_dropped"] == 1

    def test_parse_counters(self):
        from ai.ai_metrics import AIMetricsCollector
        m = AIMetricsCollector()
        m.on_parse_success(repaired=False)
        m.on_parse_success(repaired=False)
        m.on_parse_success(repaired=True)
        m.on_parse_failed()
        s = m.snapshot()
        assert s["parse_success"] == 2
        assert s["parse_repaired"] == 1
        assert s["parse_failed"] == 1
        assert s["parse_repair_rate"] == 0.25  # 1 repaired / 4 total

    def test_history_trim_counters(self):
        from ai.ai_metrics import AIMetricsCollector
        m = AIMetricsCollector()
        m.on_history_trimmed(messages_dropped=3)
        m.on_history_trimmed(messages_dropped=2)
        s = m.snapshot()
        assert s["history_trim_events"] == 2
        assert s["history_messages_dropped"] == 5

    def test_rag_counters(self):
        from ai.ai_metrics import AIMetricsCollector
        m = AIMetricsCollector()
        m.on_rag_query(hit=True)
        m.on_rag_query(hit=True)
        m.on_rag_query(hit=False)
        s = m.snapshot()
        assert s["rag_queries"] == 3
        assert s["rag_hits"] == 2
        assert s["rag_misses"] == 1
        assert s["rag_hit_rate"] == round(2/3, 3)

    def test_reset_clears_all(self):
        from ai.ai_metrics import AIMetricsCollector
        m = AIMetricsCollector()
        m.on_request_started()
        m.on_parse_success()
        m.on_rag_query(hit=True)
        m.reset()
        s = m.snapshot()
        assert s["requests_started"] == 0
        assert s["parse_success"] == 0
        assert s["rag_queries"] == 0

    def test_derived_stale_rate(self):
        from ai.ai_metrics import AIMetricsCollector
        m = AIMetricsCollector()
        m.on_request_started()
        m.on_request_started()
        m.on_request_started()
        m.on_request_started()
        m.on_request_cancelled()
        m.on_stale_completion()
        s = m.snapshot()
        # stale_rate = (1 cancelled + 1 stale completion) / 4 started = 0.5
        assert s["stale_rate"] == 0.5

    def test_thread_safety(self):
        from ai.ai_metrics import AIMetricsCollector
        m = AIMetricsCollector()

        def worker():
            for _ in range(100):
                m.on_request_started()
                m.on_stale_token()
                m.on_rag_query(hit=True)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        s = m.snapshot()
        assert s["requests_started"] == 400
        assert s["stale_tokens_dropped"] == 400
        assert s["rag_queries"] == 400

    def test_uptime_positive(self):
        from ai.ai_metrics import AIMetricsCollector
        m = AIMetricsCollector()
        s = m.snapshot()
        assert s["uptime_s"] >= 0.0


class TestAdvisorSafeParams:
    """Verify the safe-param set used for quick-apply buttons."""

    def test_safe_params_match_main_app_allowlist(self):
        """The advisor dialog's _SAFE_PARAMS should be a superset of the
        params handled in _on_advisor_proceed."""
        # These are the params from main_app._on_advisor_proceed
        main_app_params = {
            "exposure", "exposure_us", "gain", "gain_db",
            "stimulus_freq", "stimulus_freq_hz", "stimulus_duty",
            "tec_setpoint", "tec_setpoint_c", "n_frames",
        }
        from ui.widgets.advisor_dialog import AdvisorDialog
        assert main_app_params == AdvisorDialog._SAFE_PARAMS
