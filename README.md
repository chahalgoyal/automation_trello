# Automation Testing Agent

This is an LLM-powered agentic tool that generates `pytest` + `playwright` automation tests. It navigates to a URL, explores the page using a headless browser, and writes test files based on your instructions.

## Setup

1. Create a virtual environment and activate it:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/Mac:
   # source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. Set your Gemini API key:
   ```bash
   set GEMINI_API_KEY=your_api_key_here
   # Or on Linux/Mac:
   # export GEMINI_API_KEY=your_api_key_here
   ```

## Usage

Run the `autotester.py` script with the target URL and testing instructions:

```bash
python autotester.py --url "https://demo.playwright.dev/todomvc" --instructions "Verify the page title and add a new todo item. Check if the item is added to the list."
```

## Running the Generated Tests

Once the agent has finished, it will generate a `pytest` file (e.g. `test_flow.py`). You can run it directly:

```bash
pytest test_flow.py -v
```
