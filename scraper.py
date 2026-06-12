"""
Stepstone Dashboard Scraper (ohne Login)
=========================================
Läuft täglich via GitHub Actions.
Öffnet die öffentliche Stepstone-Unternehmensseite mit Playwright
(vollständiges JS-Rendering) und aktualisiert index.html.

Keine GitHub Secrets erforderlich.
"""

import json
import re
import sys
import time
from datetime import datetime


def scrape_jobs() -> list[dict]:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    JOBS_URL = "https://www.stepstone.de/cmp/de/tatenwerk-frankfurt-gmbh-89389/jobs"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
        )
        page = ctx.new_page()

        # ── Seite laden ───────────────────────────────────────
        print(f"→ Lade {JOBS_URL} …")
        page.goto(JOBS_URL, wait_until="networkidle", timeout=30000)
        time.sleep(3)

        # Cookie-Banner schließen (falls vorhanden)
        for sel in [
            '#onetrust-accept-btn-handler',
            'button[id*="accept"]',
            'button[data-testid*="accept"]',
        ]:
            try:
                page.click(sel, timeout=3000)
                print("  Cookie-Banner geschlossen")
                time.sleep(1)
                break
            except PlaywrightTimeout:
                pass

        # Warten bis Job-Karten geladen sind
        try:
            page.wait_for_selector("article", timeout=15000)
            print("  Job-Karten gefunden.")
        except PlaywrightTimeout:
            print("  Warnung: Keine <article>-Elemente sichtbar.")

        # ── Jobs extrahieren ──────────────────────────────────
        print("→ Extrahiere Jobs …")
        jobs = page.evaluate("""
            () => [...document.querySelectorAll('article')].map(a => {
                const titleEl = a.querySelector('a[href*="stellenangebote"]');
                const txt = a.innerText || '';
                const loc = txt.match(/Tatenwerk Frankfurt GmbH\\s*\\n([^\\n]+)/)?.[1]?.trim()
                          || txt.match(/Frankfurt[^\\n]*/)?.[0]?.trim()
                          || '';
                const date = txt.match(/vor \\d+ \\w+/)?.[0] || 'Aktuell';
                return {
                    title:    titleEl?.textContent?.trim() || null,
                    url:      titleEl?.href               || null,
                    location: loc,
                    date:     date,
                };
            }).filter(j => j.title && j.url)
        """)

        # Anzahl der Artikel auf der Seite (zum Debugging)
        total_articles = page.evaluate("() => document.querySelectorAll('article').length")
        print(f"  Artikel auf Seite gesamt: {total_articles}, davon mit Stellentitel: {len(jobs)}")

        browser.close()

    return jobs


def update_dashboard(jobs: list[dict], html_path: str = "index.html") -> None:
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    ts = datetime.now().strftime("%d.%m.%Y %H:%M") + " (GitHub Actions)"
    jobs_json = json.dumps(jobs, ensure_ascii=False, indent=2)

    html, n1 = re.subn(r'const JOBS = \[[\s\S]*?\];', f'const JOBS = {jobs_json};', html)
    html, n2 = re.subn(r'const DATA_TS = ".*?"', f'const DATA_TS = "{ts}"', html)

    if n1 == 0 or n2 == 0:
        raise RuntimeError(f"Regex fehlgeschlagen (JOBS: {n1}, DATA_TS: {n2}).")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ index.html aktualisiert – {len(jobs)} Stellen, Stand: {ts}")


if __name__ == "__main__":
    jobs = scrape_jobs()

    if not jobs:
        print("⚠️  Keine Jobs gefunden – index.html bleibt unverändert.")
        sys.exit(0)

    update_dashboard(jobs)
