"""
scraper.py — Build the local support corpus
=============================================

Run ONCE from the repo root before running main.py:

    python code/scraper.py

Crawls the three support sites and saves each article as a .txt file:
    data/hackerrank/
    data/claude/
    data/visa/

Uses polite delays (1.2 s between requests).
"""

import re
import sys
import time
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR  = REPO_ROOT / "data"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SupportCorpusBuilder/1.0 HackerRank-Orchestrate)"
    )
}
DELAY = 1.2   # seconds between requests

# ── seed URLs ─────────────────────────────────────────────────────────────────

HACKERRANK_COLLECTIONS = [
    "https://support.hackerrank.com/collections/1453467047-hackerrank-screen",
    "https://support.hackerrank.com/collections/3896660124-interviews",
    "https://support.hackerrank.com/collections/4294572050-account-settings",
    "https://support.hackerrank.com/collections/9278577162-general-help",
    "https://support.hackerrank.com/collections/4054400338-engage-",
    "https://support.hackerrank.com/collections/6175643472-skillup",
    "https://support.hackerrank.com/collections/9271153455-library",
    "https://support.hackerrank.com/collections/7654924072-integrations-1",
    "https://support.hackerrank.com/collections/9492939711-chakra",
]

CLAUDE_COLLECTIONS = [
    "https://support.claude.com/en/collections/4078531-claude",
    "https://support.claude.com/en/collections/5953830-pro-and-max-plans",
    "https://support.claude.com/en/collections/9387370-team-and-enterprise-plans",
    "https://support.claude.com/en/collections/5370014-claude-api-and-console",
    "https://support.claude.com/en/collections/4078534-privacy-and-legal",
    "https://support.claude.com/en/collections/4078535-safeguards",
    "https://support.claude.com/en/collections/4078537-amazon-bedrock",
    "https://support.claude.com/en/collections/12630177-claude-for-education",
    "https://support.claude.com/en/collections/9387080-claude-mobile-apps",
    "https://support.claude.com/en/collections/17270717-identity-management-sso-jit-scim",
]

VISA_SEEDS = [
    "https://www.visa.co.in/support.html",
    "https://www.visa.co.in/support/consumer/card-benefits.html",
    "https://www.visa.co.in/support/consumer/lost-stolen-cards.html",
    "https://www.visa.co.in/support/consumer/travel-support.html",
    "https://www.visa.co.in/support/consumer/security.html",
    "https://www.visa.co.in/support/consumer/dispute-resolution.html",
    "https://www.visa.co.in/support/consumer/protect-yourself.html",
    "https://www.visa.co.in/support/small-business/security-and-disputes.html",
    "https://www.visa.co.in/support/small-business/card-management.html",
    "https://www.visa.co.in/support/consumer/travel-support/lost-stolen-card.html",
    "https://www.visa.co.in/support/consumer/travel-support/emergency-cash.html",
    "https://www.visa.co.in/support/consumer/travel-support/travellers-cheques.html",
    "https://www.visa.co.in/support/consumer/visa-card-faq.html",
    "https://www.visa.co.in/support/consumer/minimum-spend.html",
]

# Content selectors (tried in order, first match wins)
_HR_SELECTORS   = ["article", ".article-body", ".article__body", "main", ".content"]
_CL_SELECTORS   = ["article", ".intercom-interblocks-article-body", ".article-body", "main"]
_VISA_SELECTORS = [".support-content", ".page-content", "article", "main", "#main-content"]


# ── helpers ───────────────────────────────────────────────────────────────────

def _get(url: str, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
            print(f"    HTTP {r.status_code}: {url}")
            return None
        except Exception as e:
            if attempt == retries - 1:
                print(f"    FAIL {url}: {e}")
            else:
                time.sleep(2)
    return None


def _extract(soup: BeautifulSoup, selectors: list[str]) -> str:
    for sel in selectors:
        tag = soup.select_one(sel)
        if tag:
            for noise in tag.select("nav, footer, script, style, .nav, .footer, .sidebar"):
                noise.decompose()
            text = tag.get_text(separator="\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()
    body = soup.find("body")
    return body.get_text(separator="\n", strip=True) if body else ""


def _title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else ""


def _slug(url: str) -> str:
    path = urlparse(url).path.strip("/").replace("/", "_")
    return (path or hashlib.md5(url.encode()).hexdigest()[:12])[:90]


def _save(company: str, slug: str, title: str, body: str):
    if not body or len(body) < 80:
        return False
    out = DATA_DIR / company
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-]", "_", slug)
    fpath = out / f"{safe}.txt"
    content = f"# {title}\n\n{body}" if title else body
    fpath.write_text(content, encoding="utf-8")
    return True


# ── scrapers ──────────────────────────────────────────────────────────────────

def scrape_hackerrank():
    print("\n[HackerRank] Discovering articles...")
    urls: set[str] = set()

    for coll in HACKERRANK_COLLECTIONS:
        r = _get(coll)
        if not r:
            time.sleep(DELAY)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href*='/articles/']"):
            href = a.get("href", "")
            urls.add(urljoin("https://support.hackerrank.com", href).split("?")[0])
        time.sleep(DELAY)

    print(f"  {len(urls)} articles found. Downloading...")
    count = 0
    for url in sorted(urls):
        r = _get(url)
        if not r:
            time.sleep(DELAY)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        if _save("hackerrank", _slug(url), _title(soup), _extract(soup, _HR_SELECTORS)):
            count += 1
        time.sleep(DELAY)

    print(f"  ✓ Saved {count} HackerRank articles")


def scrape_claude():
    print("\n[Claude] Discovering articles...")
    urls: set[str] = set()

    for coll in CLAUDE_COLLECTIONS:
        r = _get(coll)
        if not r:
            time.sleep(DELAY)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href*='/articles/']"):
            href = a.get("href", "")
            urls.add(urljoin("https://support.claude.com", href).split("?")[0])
        time.sleep(DELAY)

    print(f"  {len(urls)} articles found. Downloading...")
    count = 0
    for url in sorted(urls):
        r = _get(url)
        if not r:
            time.sleep(DELAY)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        if _save("claude", _slug(url), _title(soup), _extract(soup, _CL_SELECTORS)):
            count += 1
        time.sleep(DELAY)

    print(f"  ✓ Saved {count} Claude articles")


def scrape_visa():
    print("\n[Visa] Crawling support pages...")
    visited: set[str] = set()
    queue = list(VISA_SEEDS)
    count = 0

    while queue and count < 60:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        r = _get(url)
        if not r:
            time.sleep(DELAY)
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        body = _extract(soup, _VISA_SELECTORS)

        if _save("visa", _slug(url), _title(soup), body):
            count += 1

        # follow internal Visa support links one level deep
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            full = urljoin("https://www.visa.co.in", href)
            if (full.startswith("https://www.visa.co.in/support")
                    and full not in visited
                    and full not in queue):
                queue.append(full)

        time.sleep(DELAY)

    print(f"  ✓ Saved {count} Visa pages")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    print("=" * 58)
    print("  Support Corpus Builder  —  HackerRank Orchestrate 2026")
    print("=" * 58)
    print(f"  Output: {DATA_DIR}\n")
    print("  This takes ~15-20 minutes (polite 1.2 s delay per request).")
    print("  Run once; results are cached in data/\n")

    scrape_hackerrank()
    scrape_claude()
    scrape_visa()

    print("\n" + "=" * 58)
    print("Corpus summary:")
    total_kb = 0
    for company in ["hackerrank", "claude", "visa"]:
        d = DATA_DIR / company
        if d.exists():
            files = list(d.glob("*.txt"))
            kb    = sum(f.stat().st_size for f in files) // 1024
            total_kb += kb
            print(f"  {company:12s}  {len(files):3d} files  {kb:5d} KB")
        else:
            print(f"  {company:12s}  (no data — check network/selectors)")

    print(f"\n  Total: {total_kb} KB")
    print("\nNext step:  python code/main.py")


if __name__ == "__main__":
    main()
