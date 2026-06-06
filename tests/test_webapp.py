"""Smoke test for the Next.js frontend dev server.

Requires `npm run dev` running on localhost:3001. Skip if unreachable.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # type: ignore[assignment]

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright not installed")


def _port_open(host: str = "localhost", port: int = 3001, timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def test_webapp(tmp_path: Path) -> None:
    if not _port_open():
        pytest.skip("Frontend dev server not running on http://localhost:3001")

    screenshot_path = tmp_path / "webapp_test.png"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Navigating to http://localhost:3001...")
        page.goto("http://localhost:3001")

        print("Waiting for network idle...")
        page.wait_for_load_state("networkidle")

        print(f"Taking screenshot to {screenshot_path}...")
        page.screenshot(path=str(screenshot_path), full_page=True)

        print("Page title:", page.title())

        content = page.content()
        print(f"Page content length: {len(content)} characters")

        buttons = page.locator("button").all()
        print(f"Found {len(buttons)} button(s)")

        browser.close()
        print("Test completed successfully!")

    assert screenshot_path.exists(), f"Screenshot not saved: {screenshot_path}"


if __name__ == "__main__":
    test_webapp(Path("/tmp"))
