"""
Browser snapshot collection via the Playwright MCP server.

This is the ONLY Node.js dependency in the project. It launches
`npx @playwright/mcp@latest --headless` as a subprocess and communicates
with it over the MCP (Model Context Protocol) to:
  1. Navigate to the target URL
  2. Capture an accessibility snapshot of the page

The snapshot gives the AI accurate knowledge of what's on the page —
element roles, names, text, structure — so it can generate correct locators.
"""

import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _extract_snapshot_text(result) -> str:
    """Extract text content from an MCP tool result."""
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) or str(result)


async def _collect_snapshot(url: str) -> str:
    """
    Connect to the Playwright MCP server, navigate to the URL,
    and capture an accessibility snapshot.
    """
    server_params = StdioServerParameters(
        command="npx",
        args=["@playwright/mcp@latest", "--headless"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("  [MCP] Connected to Playwright MCP server")

            # Navigate to the target URL
            await session.call_tool("browser_navigate", {"url": url})
            print(f"  [MCP] Navigated to {url}")

            # Wait a moment for any client-side rendering
            await asyncio.sleep(2)

            # Capture the accessibility snapshot
            result = await session.call_tool("browser_snapshot", {})
            snapshot = _extract_snapshot_text(result)
            print(f"  [MCP] Captured snapshot ({len(snapshot)} chars)")

            return snapshot


def get_page_snapshot(url: str) -> str:
    """
    Synchronous wrapper to collect a browser accessibility snapshot via MCP.

    This launches a headless Chromium instance through the Playwright MCP
    server, navigates to the URL, and returns the page's accessibility tree
    as text — perfect for LLM consumption.
    """
    return asyncio.run(_collect_snapshot(url))
