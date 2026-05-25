from playwright.sync_api import sync_playwright

def test_webapp():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        print("Navigating to http://localhost:3001...")
        page.goto('http://localhost:3001')
        
        print("Waiting for network idle...")
        page.wait_for_load_state('networkidle')
        
        print("Taking screenshot...")
        page.screenshot(path='/tmp/webapp_test.png', full_page=True)
        print(f"Screenshot saved to /tmp/webapp_test.png")
        
        print("Page title:", page.title())
        
        print("Getting page content...")
        content = page.content()
        print(f"Page content length: {len(content)} characters")
        
        print("Finding buttons...")
        buttons = page.locator('button').all()
        print(f"Found {len(buttons)} button(s)")
        
        browser.close()
        print("Test completed successfully!")

if __name__ == "__main__":
    test_webapp()
