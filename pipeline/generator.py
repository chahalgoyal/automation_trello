"""
Suite and code generation — Steps 2 & 3 of the pipeline.

Calls the AI engine to produce:
  - a structured Markdown test suite specification (.md)
  - executable pytest code from that specification (.py)
"""

from pathlib import Path

from ai_engine.client import (
    generate_api_test_suite,
    generate_test_code,
    generate_ui_test_suite,
)

from ._paths import ROOT


def generate_suite_and_code(
    test_type: str,
    target_url: str,
    snapshot: str,
    readme_content: str,
    instructions: str,
    suite_path: Path,
    generated_test: Path,
) -> str:
    """
    Run steps 2 and 3 of the pipeline:
      - AI generates a Markdown test suite specification
      - AI generates executable pytest code from that spec
    Returns the suite markdown string.
    """
    tag = test_type.upper()

    print(f"\n[{tag}] [2/4] AI is generating a test suite specification...")
    if test_type == "ui":
        suite_md = generate_ui_test_suite(target_url, snapshot, instructions)
    else:
        suite_md = generate_api_test_suite(target_url, readme_content, instructions)
    suite_path.write_text(suite_md, encoding="utf-8")
    print(f"  [OK] Suite specification saved: {suite_path.relative_to(ROOT)}")

    print(f"\n[{tag}] [3/4] AI is generating executable pytest code...")
    generated_code = generate_test_code(suite_md, snapshot, test_type)
    generated_test.write_text(generated_code, encoding="utf-8")
    print(f"  [OK] Test code saved: {generated_test.relative_to(ROOT)}")

    return suite_md
