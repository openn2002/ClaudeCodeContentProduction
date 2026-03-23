"""
Web trend fetcher — scrapes curated trend-reporting websites for platform content trends.
No Apify required: standard HTTP requests + BeautifulSoup.

Runs as part of the research agent every Friday night to surface trending
TikTok/Instagram/YouTube formats that can be adapted for CSIRO TWD content.
"""

import re
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Curated trend-reporting sources ──────────────────────────────────────────
# Each entry: human-readable label → URL
TREND_SOURCES = {
    "Later — TikTok Trends This Week":
        "https://later.com/blog/tiktok-trends/",
    "Influencer Marketing Hub — TikTok Trends":
        "https://influencermarketinghub.com/tiktok-trends/",
    "Later — Instagram Trends":
        "https://later.com/blog/instagram-trends/",
    "Buffer — Social Media Trends":
        "https://buffer.com/resources/social-media-trends/",
    "Social Media Today — TikTok":
        "https://www.socialmediatoday.com/topic/tiktok/",
    "HubSpot — Social Media Trends":
        "https://blog.hubspot.com/marketing/social-media-trends",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-AU,en;q=0.9",
}

# Max characters to extract per source (keeps Claude context manageable)
MAX_CHARS_PER_SOURCE = 2500


def _extract_text(html: str) -> str:
    """Parse HTML and return clean plain text from the main content area."""
    soup = BeautifulSoup(html, "html.parser")

    # Strip noise
    for tag in soup(["script", "style", "nav", "header", "footer",
                      "aside", "form", "iframe", "noscript", "svg"]):
        tag.decompose()

    # Prefer semantic content containers
    content = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_=re.compile(r"(content|post|article|blog|entry)", re.I))
        or soup.find("body")
    )

    raw = content.get_text(separator=" ", strip=True) if content else ""
    # Collapse whitespace
    return re.sub(r"\s{2,}", " ", raw).strip()


def fetch_page(url: str, max_chars: int = MAX_CHARS_PER_SOURCE) -> str:
    """Fetch a URL and return trimmed plain text. Returns error string on failure."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        text = _extract_text(resp.text)
        return text[:max_chars] if text else "[No content extracted]"
    except requests.exceptions.Timeout:
        return "[Timed out]"
    except requests.exceptions.HTTPError as e:
        return f"[HTTP {e.response.status_code}]"
    except Exception as e:
        return f"[Error: {e}]"


def fetch_all_trend_articles(verbose: bool = True) -> str:
    """
    Fetch all trend-reporting sources and return a single formatted string
    ready to be injected into the research agent's Claude prompt.

    Covers: trending TikTok/Instagram/YouTube formats, viral content styles,
    platform-specific tactics, and format ideas that can be adapted for health/wellness brands.
    """
    lines = [
        "## PLATFORM TREND INTELLIGENCE — Curated Industry Sources",
        (
            "The following is scraped from leading social media trend-reporting websites. "
            "Use this to identify trending video formats, viral hooks, and content styles "
            "that are working right now — and consider how they could be adapted for the "
            "CSIRO Total Wellbeing Diet audience in Australia.\n"
            "Pay particular attention to:\n"
            "- Trending video formats (POV, 'day in my life', myth-bust, reaction, duet, challenge)\n"
            "- Hook styles and opening lines that are driving views\n"
            "- Format ideas that suit the People & Community pillar "
            "(e.g. staff/member challenges, behind-the-scenes, team content)\n"
            "- Any health/wellness-adjacent trends that TWD could authentically join\n"
        ),
    ]

    fetched = 0
    for label, url in TREND_SOURCES.items():
        if verbose:
            print(f"  Fetching trend article: {label}...")
        text = fetch_page(url)

        # Skip sources that outright failed
        if text.startswith("["):
            if verbose:
                print(f"  → Skipped ({text})")
            continue

        lines.append(f"### {label}")
        lines.append(f"Source: {url}")
        lines.append(text)
        lines.append("")
        fetched += 1

    if verbose:
        print(f"  → {fetched}/{len(TREND_SOURCES)} trend sources fetched successfully")

    return "\n".join(lines)
