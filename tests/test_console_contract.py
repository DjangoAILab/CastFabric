import json
import re
from pathlib import Path


STATIC = Path(__file__).parents[1] / "miair" / "web" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "console.js").read_text(encoding="utf-8")
CSS = (STATIC / "console.css").read_text(encoding="utf-8")
CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures" / "console_contract.json").read_text(
        encoding="utf-8"
    )
)


def test_production_console_uses_accepted_v6_shell_without_demo_rows_or_review_tools():
    assert "不挑协议，投了就播" in HTML
    assert 'src="/static/console.js"' in HTML
    assert 'href="/static/console.css"' in HTML
    assert 'class="speaker-row' not in HTML
    assert 'class="event-item' not in HTML
    assert 'class="route-row' not in HTML
    assert 'id="reviewToggle"' not in HTML
    assert 'id="scenarioSelect"' not in HTML
    assert not re.search(r"(?:\d{1,3}\.){3}\d{1,3}", HTML)


def test_console_reads_every_v1_collection_and_has_real_failure_states():
    for path in (
        "/api/v1/system",
        "/api/v1/targets",
        "/api/v1/suites",
        "/api/v1/sessions",
        "/api/v1/events?limit=100",
        "/api/v1/settings",
        "/api/v1/targets/scan",
        "/api/v1/diagnostics/export",
    ):
        assert path in JS
    assert "is-loading" in CSS
    assert "is-empty" in CSS
    assert "is-error" in CSS
    assert "is-degraded" in CSS
    assert "data-live-retry" in JS


def test_console_never_guesses_source_app_or_latency():
    combined = JS + HTML
    for forbidden in CONTRACT["forbidden"]:
        if forbidden in {"account", "password", "cookie", "passToken", "mi_did"}:
            continue
        assert forbidden not in combined
    assert "music.126.net" not in combined
    assert "163.com" not in combined
    assert "source?.device_name || tr('sourceUnknown')" in JS


def test_console_has_language_persistence_and_mobile_overflow_rules():
    assert "castfabric.language" in JS
    assert "applyLanguage('en')" in JS
    assert "@media(max-width:980px)" in HTML
    assert "overflow-y:auto" in HTML
    assert "prefers-reduced-motion:reduce" in HTML


def test_ai_access_is_a_bilingual_fourth_page_with_one_origin_mcp_setup():
    assert 'data-page-target="ai"' in HTML
    assert 'id="page-ai"' in HTML
    assert "aiAccess:['AI 接入','AI Access']" in HTML
    assert "samePortTitle:['控制台与 MCP 共用端口','Console and MCP share one port']" in HTML
    assert "`${origin.replace(/\\/$/, '')}/mcp`" in JS
    assert "codex mcp add castfabric --url ${endpoint}" in JS
    assert "claude mcp add --transport http castfabric ${endpoint}" in JS
    assert "MCP 端口" not in HTML
    assert "MCP port" not in HTML


def test_ai_access_exposes_only_implemented_capabilities_and_safe_onboarding():
    for capability in ("list_outputs", "本地文件", "实时 PCM", "播放列表"):
        assert capability in JS
    assert "支持 URL、本地文件与实时 PCM" in HTML
    assert "查询状态、暂停、停止并调整音量" in HTML
    assert "不要播放声音" in JS
    assert "不应把 MCP 地址直接暴露到公网" in HTML
    assert "TTS" not in HTML


def test_ai_access_has_keyboard_tabs_copy_feedback_and_responsive_layout():
    assert 'role="tablist"' in HTML
    assert 'role="tabpanel"' in HTML
    assert "['ArrowLeft', 'ArrowRight', 'Home', 'End']" in JS
    assert "navigator.clipboard.writeText" in JS
    assert 'aria-live="polite"' in HTML
    assert ".ai-layout{height:calc(100% - 94px)" in CSS
    assert "@media(max-width:980px){.ai-page{overflow:auto}" in CSS
