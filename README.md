# AI QA Agent

> An AI-powered test automation pipeline that **generates**, **executes**, and **self-repairs** test suites — for both UI and REST API targets — using Google Gemini and Playwright.

---

## How It Works

The agent runs a four-step pipeline per test mode (UI and/or API). Both modes share the same loop; only the context-collection step differs.

```
┌──────────────┐
│  config.yaml  │  ← URL, instructions, model, max repairs
└──────┬───────┘
       │
       ▼  Step 1 — Collect Context
       ├─ UI  → Playwright MCP captures browser accessibility snapshot
       └─ API → Reads local README / API documentation file

       ▼  Step 2 — AI generates test suite spec (.md)
       │   Gemini reads the context + instructions and writes a
       │   structured Markdown spec (objectives, steps, expected results)

       ▼  Step 3 — AI generates executable pytest code (.py)
       │   Gemini converts the spec into a self-contained pytest file
       │   • UI tests  → playwright sync API, headless Chromium
       │   • API tests → requests, reads base_url from config.yaml

       ▼  Step 4 — Run → Repair loop
       │
       ├─ Syntax check (compile)
       ├─ Collection dry-run (pytest --collect-only)
       ├─ Full test run (pytest)
       │
       ├─ PASS ──▶ Done ✓
       └─ FAIL ──▶ AI reads traceback → repairs code → retry
                   (up to max_repair_attempts times)
```

Each run gets its own timestamped directory under `generated/runs/`:

```
generated/runs/run_YYYYMMDD_HHMMSS/
├── suites/          ← AI-generated test suite spec (.md)
├── tests/           ← AI-generated pytest code (.py)
│   └── history/     ← Versioned snapshots of each failing attempt
└── reports/         ← JSON / JUnit XML / HTML / Allure results
```

---

## Project Structure

```
automation_flow/
│
├── main.py                   # Orchestrator — wires all steps together
│   ├── _collect_context()    # Step 1: browser snapshot or README
│   ├── _generate_suite_and_code()  # Steps 2 & 3: AI generation
│   ├── _run_repair_loop()    # Step 4: execute + repair
│   └── run_pipeline()        # Top-level coordinator per mode
│
├── ai_engine/
│   ├── client.py             # Google GenAI calls (suite, code, repair)
│   │   ├── _classify_model_error()  # Decide: retry vs. switch model
│   │   ├── _try_model()      # Per-model retry with exponential backoff
│   │   └── _request()        # Fallback across FALLBACK_MODELS list
│   └── prompts.py            # System prompt templates (one per phase)
│
├── browser/
│   └── mcp_snapshot.py       # Playwright MCP client — browser → a11y tree
│
├── runner/
│   ├── executor.py           # Runs pytest as subprocess, returns TestResult
│   └── validator.py          # Syntax check, failure classification, JSON report
│
├── generated/                # [gitignored] All AI output lives here
│
├── config.yaml               # ← Edit this to point at your app
├── .env / .env.example       # Secrets (API key, test credentials)
├── requirements.txt          # Python dependencies
├── package.json              # Node.js dep (@playwright/mcp)
├── .pre-commit-config.yaml   # Pre-commit hooks (black, flake8, yaml, etc.)
└── .flake8                   # Flake8 config (88-char limit, prompts.py exempt)
```

---

## Setup

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ (MCP snapshot only) |
| Google Gemini API key | — |

### Installation

```bash
# 1. Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

# 2. Install Python dependencies + Playwright browser
pip install -r requirements.txt
playwright install chromium

# 3. Install Node.js dependency (Playwright MCP)
npm install

# 4. Copy and fill in environment variables
copy .env.example .env   # Windows
# cp .env.example .env   # Linux/macOS

# 5. (Optional) Install pre-commit hooks
pre-commit install
```

### Environment Variables (`.env`)

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | ✅ | Your Google Gemini API key |
| `TEST_EMAIL` | Only if app needs login | Passed to generated UI tests |
| `TEST_PASSWORD` | Only if app needs login | Passed to generated UI tests |

> The API base URL is **not** read from `.env` — it comes from `config.yaml → api.base_url`.

---

## Configuration (`config.yaml`)

```yaml
model: gemini-3.8-flash          # Gemini model to use
max_repair_attempts: 3           # How many times AI may fix failing tests

ui:
  enabled: true
  target_url: https://your-app.com
  instructions: |
    Describe what to test in plain English.
    The AI will analyse the page and create specific test cases.

api:
  enabled: true
  base_url: https://your-api.com
  readme_path: /path/to/your/api/README.md
  instructions: |
    Generate a comprehensive API test suite based on the README.
    Cover CRUD, error handling, edge cases, and status code validation.
```

Both `ui` and `api` can be enabled simultaneously — the pipeline runs them in sequence.

---

## Usage

```bash
python main.py
```

The agent will print progress for each step and attempt, then write all output to `generated/runs/run_<timestamp>/`.

### Pre-commit (manual)

```bash
# Run all hooks against all files (detection + auto-fix)
pre-commit run --all-files

# Run a single hook
pre-commit run flake8 --all-files
pre-commit run check-yaml --all-files
```

---

## Output

| Path | Contents |
|---|---|
| `generated/runs/<run>/suites/` | AI-generated Markdown test suite spec |
| `generated/runs/<run>/tests/` | AI-generated pytest file |
| `generated/runs/<run>/tests/history/` | Versioned copies of each failing attempt |
| `generated/runs/<run>/reports/*.json` | Structured JSON report (all attempts) |
| `generated/runs/<run>/reports/*.xml` | JUnit XML (CI-compatible) |
| `generated/runs/<run>/reports/*.html` | Visual HTML report |
| `generated/runs/<run>/reports/allure-results/` | Allure raw data |

---

## AI Model Fallback

If the configured model is unavailable or quota-exhausted, the agent automatically tries the next model in a fallback list:

```
gemini-3.6-flash → gemini-3.5-flash → gemini-3.7-flash → gemini-3.8-flash → gemini-flash-latest
```

Each model gets up to **5 attempts** with exponential backoff (`1s → 4s → 16s → 64s`) before moving on.

---

## Architecture Notes

- **Python** handles everything except browser snapshot capture
- **Node.js** is used *only* for the `@playwright/mcp` server (browser accessibility tree via MCP protocol)
- **Google GenAI** is called natively via `google-genai` (not the OpenAI shim)
- `api.base_url` is read from `config.yaml` inside generated tests — not from `.env` — so tests stay reproducible without environment setup
- Generated output is fully **gitignored** — only the agent source and config are tracked
