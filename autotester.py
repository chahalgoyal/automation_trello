import argparse
import os
import sys
import json
from playwright.sync_api import sync_playwright
from google import genai
from google.genai import types

browser = None
context = None
page = None
playwright_instance = None
tests_saved = False

def init_browser():
    global browser, context, page, playwright_instance
    playwright_instance = sync_playwright().start()
    browser = playwright_instance.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

def close_browser():
    global browser, context, page, playwright_instance
    if context:
        context.close()
    if browser:
        browser.close()
    if playwright_instance:
        playwright_instance.stop()

def goto_url(url: str) -> str:
    """Navigates the browser to the specified URL. Use this to visit the page you need to test."""
    print(f"  [Agent Tool] Navigating to {url}...")
    try:
        page.goto(url)
        page.wait_for_load_state('networkidle', timeout=10000)
        return f"Successfully navigated to {url}. Page title: '{page.title()}'"
    except Exception as e:
        return f"Failed to navigate: {str(e)}"

def get_page_summary() -> str:
    """Returns a simplified summary of the page structure (buttons, inputs, links) and inner text. Use this to understand what elements are on the page."""
    print("  [Agent Tool] Extracting page summary...")
    try:
        script = """
        () => {
            const elements = Array.from(document.querySelectorAll('button, input, a, select, textarea'));
            const interactive = elements.map(e => {
                return {
                    tag: e.tagName.toLowerCase(),
                    type: e.type || undefined,
                    id: e.id || undefined,
                    name: e.name || undefined,
                    placeholder: e.placeholder || undefined,
                    text: (e.innerText || e.value || '').substring(0, 100).trim(),
                    href: e.href || undefined
                };
            }).filter(e => e.id || e.name || e.text || e.placeholder);
            
            return {
                title: document.title,
                url: window.location.href,
                text: document.body.innerText.substring(0, 3000),
                interactiveElements: interactive.slice(0, 100)
            };
        }
        """
        data = page.evaluate(script)
        return json.dumps(data, indent=2)
    except Exception as e:
        return f"Failed to get page source: {str(e)}"

def save_test_files(files: list[dict]) -> str:
    """
    Saves the generated Pytest + Playwright test files to disk.
    Expected format: [{'path': 'test_example.py', 'content': 'import pytest\n...'}]
    Call this tool ONLY when you are completely ready to finalize the test script.
    """
    global tests_saved
    print("  [Agent Tool] Generating and saving test files...")
    try:
        for file_obj in files:
            path = file_obj.get("path", "test_file.py")
            content = file_obj.get("content", "")
            
            # Ensure safe path writing relative to current dir
            safe_path = os.path.basename(path)
            
            with open(safe_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  [+] Saved test file: {safe_path}")
        tests_saved = True
        return "Files saved successfully. Stop calling tools and let the user know you are done."
    except Exception as e:
        return f"Failed to save files: {str(e)}"

def run_agent(url: str, instructions: str):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        print("Please set it using: set GEMINI_API_KEY=your_key")
        sys.exit(1)
        
    client = genai.Client(api_key=api_key)
    
    print("[*] Initializing Playwright browser...")
    init_browser()
    
    print("[*] Starting Agent Loop...")
    
    system_instruction = (
        "You are an expert Automation Testing Agent. "
        "Your goal is to generate Pytest + Playwright automated test scripts based on user instructions.\n"
        "STEPS:\n"
        "1. Use `goto_url` to visit the target URL.\n"
        "2. Use `get_page_summary` to understand the page structure, interactive elements, and text.\n"
        "3. Once you have enough context, use `save_test_files` to generate the test code.\n"
        "4. Your test code should use `pytest` and `playwright` (e.g., using `page` fixture).\n"
        "5. ONLY generate the final files when you are completely ready. After saving, stop calling tools."
    )
    
    prompt = f"Target URL: {url}\nInstructions: {instructions}\nPlease begin by navigating to the URL."
    
    tools = [goto_url, get_page_summary, save_test_files]
    
    # Enable automatic tool calling
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.2,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
    )
    
    chat = client.chats.create(model='gemini-3.6-flash', config=config)
    
    try:
        print("Agent thinking and exploring (this may take a minute depending on iterations)...")
        response = chat.send_message(prompt)
        print("\nAgent Final Output:")
        print(response.text)
        print("\n[*] Process completed!")
    except Exception as e:
        print(f"\n[-] Error during agent execution: {e}")
    finally:
        close_browser()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-Powered Automation Testing Agent")
    parser.add_argument("--url", required=True, help="Target URL to test")
    parser.add_argument("--instructions", required=True, help="Testing instructions and flows")
    args = parser.parse_args()
    
    run_agent(args.url, args.instructions)


