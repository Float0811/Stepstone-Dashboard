"""
Stepstone Dashboard Scraper
============================
Läuft täglich via GitHub Actions. Scraped die aktiven Stellenanzeigen
und schreibt sie in index.html.

Benötigte GitHub Secrets:
  STEPSTONE_EMAIL    – Stepstone E-Mail-Adresse
  STEPSTONE_PASSWORD – Stepstone Passwort
"""

import json
import os
import re
import sys
import time
from datetime import datetime


def scrape_jobs(email: str, password: str) -> list[dict]:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    JOBS_URL = "https://www.stepstone.de/cmp/de/tatenwerk-frankfurt-gmbh-89389/jobs"
    LOGIN_URL = "https://www.stepstone.de/candidate/#/login"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="de-DE",
            # Automation-Fingerprint verstecken
            extra_http_headers={"Accept-Language": "de-DE,de;q=0.9"}
        )

        # navigator.webdriver auf undefined setzen
        ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = ctx.new_page()

        # ── 1. Login-Seite aufrufen ───────────────────────────
        print("→ Öffne Login-Seite …")
        page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
        time.sleep(3)

        # Cookie-Banner schließen
        for sel in [
            '#onetrust-accept-btn-handler',
            'button[id*="accept"]',
            'button[data-testid*="accept"]',
            '[aria-label*="Accept"]',
        ]:
            try:
                page.click(sel, timeout=3000)
                print("  Cookie-Banner geschlossen")
                time.sleep(1)
                break
            except PlaywrightTimeout:
                pass

        # Aktuelle URL und Seiteninhalt loggen (hilft beim Debuggen)
        print(f"  URL nach Login-Aufruf: {page.url}")

        # ── 2. Login-Formular ausfüllen ───────────────────────
        # Alle möglichen Selektoren für das E-Mail-Feld
        email_selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[id*="email"]',
            'input[autocomplete="email"]',
            'input[autocomplete="username"]',
            'input[placeholder*="E-Mail"]',
            'input[placeholder*="email"]',
            'input[placeholder*="Email"]',
        ]

        email_found = False
        for sel in email_selectors:
            try:
                page.wait_for_selector(sel, timeout=5000, state="visible")
                page.fill(sel, email)
                print(f"  E-Mail-Feld gefunden: {sel}")
                email_found = True
                break
            except PlaywrightTimeout:
                continue

        if not email_found:
            # Seiten-HTML für Debugging ausgeben
            html_snippet = page.content()[:2000]
            print(f"  FEHLER: Kein E-Mail-Feld gefunden. Seiten-Anfang:\n{html_snippet}")
            raise RuntimeError("Login-Formular nicht gefunden. Stepstone hat möglicherweise das Layout geändert.")

        time.sleep(0.5)

        # Passwort
        page.fill('input[type="password"]', password)
        time.sleep(0.5)

        # Absenden
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=25000)
        time.sleep(3)

        print(f"  URL nach Login: {page.url}")

        if "/login" in page.url or "/signin" in page.url:
            raise RuntimeError(
                "Login fehlgeschlagen – nach Submit noch auf Login-Seite. "
                "Bitte E-Mail/Passwort in GitHub Secrets prüfen."
            )

        # ── 3. Jobs-Seite aufrufen ────────────────────────────
        print(f"→ Lade Jobs-Seite …")
        page.goto(JOBS_URL, wait_until="networkidle", timeout=30000)
        time.sleep(4)

        # Warten auf Job-Karten
        try:
            page.wait_for_selector("article", timeout=15000)
        except PlaywrightTimeout:
            print("  Warnung: Keine <article>-Elemente – versuche es trotzdem …")

        # ── 4. Jobs extrahieren ───────────────────────────────
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

        browser.close()

    print(f"  {len(jobs)} Stelle(n) gefunden.")
    return jobs


def update_dashboard(jobs: list[dict], html_path: str = "index.html") -> None:
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    ts = datetime.now().strftime("%d.%m.%Y %H:%M") + " (GitHub Actions)"
    jobs_json = json.dumps(jobs, ensure_ascii=False, indent=2)

    html, n1 = re.subn(r'const JOBS = \[[\s\S]*?\];', f'const JOBS = {jobs_json};', html)
    html, n2 = re.subn(r'const DATA_TS = ".*?"', f'const DATA_TS = "{ts}"', html)

    if n1 == 0 or n2 == 0:
        raise RuntimeError(f"Regex-Ersetzen fehlgeschlagen (JOBS: {n1}, DATA_TS: {n2}).")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ {len(jobs)} Stellen gespeichert – Stand: {ts}")


if __name__ == "__main__":
    email    = os.environ.get("STEPSTONE_EMAIL")
    password = os.environ.get("STEPSTONE_PASSWORD")

    if not email or not password:
        print("❌ STEPSTONE_EMAIL und/oder STEPSTONE_PASSWORD fehlen.")
        sys.exit(1)

    jobs = scrape_jobs(email, password)

    if not jobs:
        print("⚠️  Keine Jobs gefunden – index.html bleibt unverändert.")
        sys.exit(0)

    update_dashboard(jobs)
