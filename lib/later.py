"""
Later API wrapper.
Docs: https://developer.later.com/
Used by performance_agent to pull last 7 days of post analytics.
"""

import os
import requests
from datetime import datetime, timedelta

LATER_API_KEY = os.getenv("LATER_API_KEY")
BASE_URL = "https://api.later.com/v2"

PLATFORM_MAP = {
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "youtube_shorts": "YouTube Shorts",
    "facebook": "Facebook",
}


def _headers():
    return {
        "Authorization": f"Bearer {LATER_API_KEY}",
        "Content-Type": "application/json",
    }


def get_profiles() -> list:
    """Return all connected social profiles."""
    resp = requests.get(f"{BASE_URL}/profiles", headers=_headers())
    resp.raise_for_status()
    return resp.json().get("data", [])


def get_posts(profile_id: str, since: str, until: str) -> list:
    """
    Pull published posts for a profile within a date range.
    since / until: ISO-8601 date strings (YYYY-MM-DD)
    """
    params = {
        "since": since,
        "until": until,
        "per_page": 100,
    }
    resp = requests.get(
        f"{BASE_URL}/profiles/{profile_id}/posts",
        headers=_headers(),
        params=params,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def get_post_analytics(post_id: str) -> dict:
    """Return analytics for a single post."""
    resp = requests.get(
        f"{BASE_URL}/posts/{post_id}/analytics",
        headers=_headers(),
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def get_last_7_days_performance() -> list:
    """
    Convenience: pull all posts + analytics across all profiles for last 7 days.
    Returns list of dicts with keys: platform, published_at, caption, views,
    link_clicks, post_id.
    """
    until = datetime.utcnow().date()
    since = until - timedelta(days=7)

    profiles = get_profiles()
    results = []

    for profile in profiles:
        profile_id = profile.get("id")
        platform_raw = profile.get("platform_type", "").lower()
        platform = PLATFORM_MAP.get(platform_raw, platform_raw.title())

        posts = get_posts(profile_id, str(since), str(until))
        for post in posts:
            post_id = post.get("id")
            analytics = {}
            try:
                analytics = get_post_analytics(post_id)
            except Exception:
                pass  # analytics may not be available for very recent posts

            results.append(
                {
                    "platform": platform,
                    "published_at": post.get("published_at", ""),
                    "caption": post.get("caption", ""),
                    "views": analytics.get("impressions") or analytics.get("views") or 0,
                    "link_clicks": analytics.get("link_clicks", 0),
                    "post_id": post_id,
                }
            )

    return results
