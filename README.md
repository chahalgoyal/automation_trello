# AI QA Agent

AI-powered test automation agent that **generates**, **executes**, and **self-repairs** test suites using Google GenAI and Playwright.

## How It Works

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────┐     ┌─────────────────┐
│  config.yaml │────▶│  MCP Snapshot    │────▶│  AI generates  │────▶│  AI generates   │
│  (URL +      │     │  (browser a11y   │     │  test suite    │     │  pytest code    │
│  instructions│     │   tree via Node) │     │  (.md spec)    │     │  from suite     │
└─────────────┘     └──────────────────┘     └────────────────┘     └────────┬────────┘
                                                                             │
                                                                             ▼
                                                                   ┌─────────────────┐
                                                                   │  Run pytest      │
                                                                   │  ┌─────────────┐ │
                                                                   │  │ validate    │ │
                                                                   │  │ collect     │ │
                                                                   │  │ execute     │ │
                                                                   │  └──────┬──────┘ │
                                                                   └────────┬────────┘
                                                                     PASS? │ FAIL?
                                                                      │       │
                                                                 ┌────▼──┐ ┌──▼───────────┐
                                                                 │ Done! │ │ AI repairs    │
                                                                 │ ✓     │ │ code + retry  │
                                                                 └───────┘ │ (up to N)     │
                                                                           └───────────────┘
```

### Key Differentiator

Unlike traditional approaches that use predefined test case files, this agent **generates the test suite specification dynamically**:

1. The AI sees the actual page via a browser accessibility snapshot
2. It creates a structured `.md` test suite grounded in what's really there
3. It then writes executable code from that suite
4. If tests fail, it reads the traceback and fixes the code automatically

## Project Structure

```
automation_flow/
├── config.yaml              # Your configuration (URL, instructions, model)
├── main.py                  # Orchestrator: the Generate → Run → Repair loop
├── ai_engine/               # Google GenAI integration
│   ├── client.py            # LLM calls (generate suite, generate code, repair)
│   └── prompts.py           # System prompt templates (easy to tune)
├── browser/                 # Browser snapshot collection
│   └── mcp_snapshot.py      # Playwright MCP client (Node.js bridge)
├── runner/                  # Test execution
│   ├── executor.py          # Runs pytest, captures results
│   └── validator.py         # Syntax validation, failure classification
├── generated/               # [gitignored] AI output
│   ├── suites/              # Generated test suite .md files
│   ├── tests/               # Generated test .py files
│   └── tests/history/       # Previous versions of failed attempts
├── reports/                 # [gitignored] Test reports
├── package.json             # Node.js dep (@playwright/mcp)
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
└── .gitignore
```

## Setup

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** (for MCP browser snapshots only)
- A **Google Gemini API key**

### Installation

1. **Clone and enter the project:**
   ```bash
   cd automation_flow
   ```

2. **Create and activate a Python virtual environment:**
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/Mac:
   # source .venv/bin/activate
   ```

3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

4. **Install Node.js dependency (for MCP):**
   ```bash
   npm install
   ```

5. **Configure environment variables:**
   ```bash
   copy .env.example .env
   ```
   Edit `.env` with your values:
   ```
   GEMINI_API_KEY=your_gemini_api_key
   TEST_EMAIL=your_test_email
   TEST_PASSWORD=your_test_password
   ```

6. **Edit `config.yaml`** with your target URL and instructions.

## Usage

```bash
python main.py
```

That's it. The agent will:
1. Snapshot your target page
2. Generate a test suite specification
3. Generate executable test code
4. Run the tests
5. Auto-repair and retry if anything fails

## Configuration

Edit `config.yaml`:

```yaml
target_url: "https://your-app.com"
test_type: "ui"              # "ui" or "api"
model: "gemini-2.5-flash"    # Any Gemini model
max_repair_attempts: 3       # How many times AI can fix failing tests

instructions: |
  Describe what you want tested in plain language.
  The AI will analyze the page and create specific test cases.
```

## Output

After a run, you'll find:

| Directory | Contents |
|---|---|
| `generated/suites/` | AI-generated test suite `.md` files — the specification |
| `generated/tests/` | AI-generated pytest code — the executable tests |
| `generated/tests/history/` | Versioned copies of each failed attempt |
| `reports/test_report.json` | Structured JSON report with all attempt data |
| `reports/test-results.xml` | JUnit XML (CI-compatible) |
| `reports/test-report.html` | Visual HTML test report |

## Architecture Notes

- **Python** handles everything except MCP browser communication
- **Node.js** is used ONLY for the Playwright MCP server (`@playwright/mcp`)
- **Google GenAI** is used natively via `google-genai` (not the OpenAI compatibility shim)
- The codebase is modular — adding API testing is a matter of extending prompts and adding a route in `main.py`
