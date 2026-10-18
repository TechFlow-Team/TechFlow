"""Browser smoke checks using locally provisioned test accounts; never print passwords."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--credentials', required=True, help='Local JSON: admin/client/staff credentials and UI fixture IDs')
    parser.add_argument('--base-url', default='http://127.0.0.1:8012')
    parser.add_argument('--executable')
    parser.add_argument('--output', default='.git/backlog-ui')
    args = parser.parse_args()
    assert urlparse(args.base_url).hostname in {'127.0.0.1', 'localhost'}, 'Only local test servers are allowed.'
    accounts = json.loads(Path(args.credentials).read_text(encoding='utf-8'))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **({'executable_path': args.executable} if args.executable else {}))
        for width, height in [(1440, 1000), (768, 1024), (390, 844)]:
            for role in ['client', 'staff', 'admin']:
                context = browser.new_context(viewport={'width': width, 'height': height})
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(args.base_url + '/login')
                page.locator('[name=identity]').fill(accounts[role]['username'])
                page.locator('[name=password]').fill(accounts[role]['password'])
                page.locator('button[type=submit]').click()
                page.wait_for_url('**/shop' if role == 'client' else '**/admin/dashboard' if role == 'admin' else '**/staff/dashboard')
                routes = ['/account/favorites', '/account/warranties', '/account/contributions', '/support',
                          '/support/' + str(accounts['thread_id']), '/blog/' + accounts['slug'],
                          '/shop/product/' + str(accounts['product_id']), '/compare'] if role == 'client' else [
                              '/business/low-stock', '/business/reports', '/business/content', '/business/content/new',
                              '/business/moderation', '/support/' + str(accounts['thread_id'])]
                if role == 'admin':
                    routes.append('/admin/staff')
                for route in routes:
                    response = page.goto(args.base_url + route)
                    assert response.status == 200, (role, route, response.status)
                    page.locator('h1').first.wait_for()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (role, route, width, 'horizontal overflow')
                    assert not errors, (role, route, errors)
                    count += 1
                    if route in ['/business/reports', '/business/content/new', '/support/' + str(accounts['thread_id']), '/blog/' + accounts['slug']]:
                        page.screenshot(path=str(output / f'{role}-{width}-{route.rsplit("/", 1)[-1]}.png'))
                if role == 'client':
                    page.goto(args.base_url + '/shop/product/' + str(accounts['product_id']))
                    page.get_by_role('button', name='Chọn/bỏ so sánh', exact=True).click()
                    page.wait_for_url('**/compare')
                    assert page.locator('table').count() == 1
                context.close()
        browser.close()
    print(f'Browser smoke: PASS; {count} pages across desktop/tablet/mobile and three roles; screenshots: {output.resolve()}')


if __name__ == '__main__':
    main()
