"""
Context collection — Step 1 of the pipeline.

- UI:  captures a browser accessibility snapshot via Playwright MCP
- API: loads the local README / API documentation file
"""

from pathlib import Path

from browser.mcp_snapshot import get_page_snapshot


def _collect_ui_context(target_url: str) -> str:
    """Collect browser accessibility snapshot for UI testing."""
    print("\n[UI] [1/4] Collecting browser snapshot via MCP...")
    try:
        snapshot = get_page_snapshot(target_url)
        print(f"  [OK] Snapshot collected ({len(snapshot)} chars)")
        return snapshot
    except Exception as e:
        print(f"  [WARN] Snapshot collection failed: {e}")
        print("  Continuing without snapshot - AI will have less context")
        return ""


def _collect_api_context(config_section: dict) -> str:
    """Load README / API documentation for API testing."""
    print("\n[API] [1/4] Collecting API documentation...")
    readme_path_str = config_section.get("readme_path")
    if not readme_path_str:
        print("  [WARN] No readme_path configured for API mode")
        return ""
    readme_path = Path(readme_path_str)
    if not readme_path.exists():
        print(f"  [WARN] README not found at {readme_path}")
        return ""
    content = readme_path.read_text(encoding="utf-8")
    print(f"  [OK] Loaded README ({len(content)} chars)")
    return content


def collect_context(
    test_type: str, config_section: dict, target_url: str
) -> tuple[str, str]:
    """Return (snapshot, readme_content) for the given test type."""
    if test_type == "ui":
        return _collect_ui_context(target_url), ""
    return "", _collect_api_context(config_section)
