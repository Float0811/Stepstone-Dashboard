"""
Stepstone Dashboard Scraper
============================
Läuft täglich via GitHub Actions. Logged sich in Stepstone ein,
scraped die aktiven Stellenanzeigen und schreibt sie in index.html.

Benötigte GitHub Secrets:
  STEPSTONE_EMAIL    – deine Stepstone-E-Mail-Adresse
  STEPSTONE_PASSWORD – dein Stepstone-Passwort
"""

import json
import os
import re
import sys
import time
from datetime import datetime


def scrape_jobs(email: str, password: str) -> list[dict]:
    """Loggt in Stepstone ein und scraped aktive Stellenanzeigen."""
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
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
        )
        page = ctx.new_page()

        # ── 1. Login ──────────────────────────────────────────
        print("→ Öffne Login-Seite …")
        page.goto("https://www.stepstone.de/candidate/#/login", wait_until="domcontentloaded")
        time.sleep(2)

        # Cookie-Banner akzeptieren, falls vorhanden
        for sel in ['button[id*="accept"]', 'button[data-testid*="accept"]', '#onetrust-accept-btn-handler']:
            try:
                page.click(sel, timeout=3000)
                print("  Cookie-Banner geschlossen")
                break
            except PlaywrightTimeout:
                pass

        # E-Mail eingeben
        page.wait_for_selector('input[type="email"], input[name="email"], input[id*="email"]', timeout=15000)
        page.fill('input[type="email"], input[name="email"], input[id*="email"]', email)
        time.sleep(0.5)

        # Passwort eingeben
        page.fill('input[type="password"]', password)
        time.sleep(0.5)

        # Absenden
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=20000)
        time.sleep(2)

        # Login-Prüfung
        if "/login" in page.url or "/signin" in page.url:
            raise RuntimeError(
                "Login fehlgeschlagen – URL nach Submit: " + page.url +
                ". Bitte Zugangsdaten in den GitHub Secrets prüfen."
            )
        print(f"  Eingeloggt. Aktuelle URL: {page.url}")

        # ── 2. Jobs-Seite aufrufen ────────────────────────────
        print(f"→ Lade Jobs-Seite: {JOBS_URL}")
        page.goto(JOBS_URL, wait_until="networkidle", timeout=30000)
        time.sleep(3)

        # Warten bis mindestens ein article-Element sichtbar ist
        try:
            page.wait_for_selector("article", timeout=15000)
        except PlaywrightTimeout:
            print("  Warnung: Keine <article>-Elemente gefunden – möglicherweise leere Seite.")

        # ── 3. Jobs extrahieren ───────────────────────────────
        print("→ Extrahiere Stellenanzeigen …")
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

        browser.close()

    print(f"  {len(jobs)} Stelle(n) gefunden.")
    return jobs


def update_dashboard(jobs: list[dict], html_path: str = "index.html") -> None:
    """Ersetzt JOBS und DATA_TS in der index.html."""
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    ts = datetime.now().strftime("%d.%m.%Y %H:%M") + " (GitHub Actions)"
    jobs_json = json.dumps(jobs, ensure_ascii=False, indent=2)

    # JOBS-Array ersetzen
    html, n1 = re.subn(
        r'const JOBS = \[[\s\S]*?\];',
        f'const JOBS = {jobs_json};',
        html,
    )
    # Timestamp ersetzen
    html, n2 = re.subn(
        r'const DATA_TS = ".*?"',
        f'const DATA_TS = "{ts}"',
        html,
    )

    if n1 == 0 or n2 == 0:
        raise RuntimeError(
            f"Ersetzen fehlgeschlagen (JOBS gefunden: {n1}, DATA_TS gefunden: {n2}). "
            "Bitte HTML-Struktur prüfen."
        )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ index.html aktualisiert – {len(jobs)} Stellen, Stand: {ts}")


if __name__ == "__main__":
    email    = os.environ.get("STEPSTONE_EMAIL")
    password = os.environ.get("STEPSTONE_PASSWORD")

    if not email or not password:
        print("❌ STEPSTONE_EMAIL und/oder STEPSTONE_PASSWORD nicht gesetzt.")
        sys.exit(1)

    jobs = scrape_jobs(email, password)

    if not jobs:
        print("⚠️  Keine Stellen gefunden – index.html wird NICHT überschrieben.")
        sys.exit(0)  # kein Fehler, nur keine Änderung

    update_dashboard(jobs)
