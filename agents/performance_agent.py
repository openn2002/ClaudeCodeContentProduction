"""
Performance Agent — runs Monday 8am AEST cron.

Workflow:
1. Later API — pulls last 7 days of post performance (TikTok, Instagram, YouTube)
2. Meta API — pulls Facebook page reach for the same period
3. Matches posts to Content Calendar rows by Publish Date + Platform
4. Updates each matched Content Calendar row: Views, Link Clicks
5. Rolls up to the current week's Weekly Scorecard row:
   - TikTok Views, Instagram Reach, YouTube Views, Facebook Reach, Link Clicks
   - Running: Views and Running: Link Clicks (cumulative)
6. Fires Slack summary to #organic-growth
"""

import os
import sys
from datetime import date, timedelta, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.notion import (
    DB_CONTENT_CALENDAR,
    DB_WEEKLY_SCORECARD,
    query_database,
    update_page,
    get_or_create_scorecard_row,
    prop_number,
)
from lib.later import get_last_7_days_performance
from lib.slack import (
    notify_organic_growth,
    section_block,
    divider_block,
    button_block,
)

load_dotenv()

META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_PAGE_ID = os.getenv("META_PAGE_ID")

NOTION_SCORECARD_URL = "https://www.notion.so/73cc62471de24c16987b661fb05e32e1"


# ---------------------------------------------------------------------------
# Meta API — Facebook page reach
# ---------------------------------------------------------------------------

def get_facebook_reach(since: date, until: date) -> int:
    """Pull total Facebook page reach for the period via Meta Graph API."""
    url = f"https://graph.facebook.com/v20.0/{META_PAGE_ID}/insights"
    params = {
        "metric": "page_impressions_unique",
        "period": "day",
        "since": str(since),
        "until": str(until),
        "access_token": META_ACCESS_TOKEN,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()

    total_reach = 0
    for item in data.get("data", []):
        for val in item.get("values", []):
            total_reach += val.get("value", 0)
    return total_reach


# ---------------------------------------------------------------------------
# Match Later posts to Content Calendar
# ---------------------------------------------------------------------------

def get_calendar_rows_for_period(since: date, until: date) -> list:
    """Query Content Calendar rows with Publish Date in range."""
    return query_database(
        DB_CONTENT_CALENDAR,
        filter_obj={
            "and": [
                {
                    "property": "Publish Date",
                    "date": {"on_or_after": str(since)},
                },
                {
                    "property": "Publish Date",
                    "date": {"on_or_before": str(until)},
                },
            ]
        },
    )


def match_post_to_calendar(post: dict, calendar_rows: list) -> dict | None:
    """
    Match a Later post to a Content Calendar row.
    Match criteria: same Publish Date (date portion) + overlapping platform.
    """
    post_date_str = post.get("published_at", "")[:10]  # YYYY-MM-DD
    post_platform = post.get("platform", "")

    for row in calendar_rows:
        props = row.get("properties", {})
        cal_date = props.get("Publish Date", {}).get("date", {})
        cal_date_str = (cal_date or {}).get("start", "")[:10]

        if cal_date_str != post_date_str:
            continue

        cal_platforms = props.get("Platform", {}).get("multi_select", [])
        cal_platform_names = [p.get("name", "") for p in cal_platforms]

        if post_platform in cal_platform_names:
            return row

    return None


# ---------------------------------------------------------------------------
# Rollup helpers
# ---------------------------------------------------------------------------

def aggregate_by_platform(posts: list) -> dict:
    """Sum views and link_clicks by platform."""
    totals = {
        "TikTok": {"views": 0, "link_clicks": 0},
        "Instagram": {"views": 0, "link_clicks": 0},
        "YouTube": {"views": 0, "link_clicks": 0},
        "YouTube Shorts": {"views": 0, "link_clicks": 0},
        "Facebook": {"views": 0, "link_clicks": 0},
    }
    for post in posts:
        platform = post.get("platform", "")
        if platform in totals:
            totals[platform]["views"] += post.get("views", 0)
            totals[platform]["link_clicks"] += post.get("link_clicks", 0)
    return totals


def week_label_and_range() -> tuple[str, str, str]:
    """Return (label, start_iso, end_iso) for the week ending last Sunday."""
    today = date.today()
    # Last Monday → last Sunday
    last_sunday = today - timedelta(days=today.weekday() + 1)
    last_monday = last_sunday - timedelta(days=6)
    label = f"Week of {last_monday.strftime('%d %b %Y')}"
    return label, str(last_monday), str(last_sunday)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Performance Agent Starting ===")

    until = date.today() - timedelta(days=1)  # yesterday
    since = until - timedelta(days=6)          # 7 days back

    # 1. Pull Later post performance
    print(f"Fetching Later posts from {since} to {until}...")
    later_posts = get_last_7_days_performance()
    print(f"  {len(later_posts)} posts retrieved from Later.")

    # 2. Pull Facebook reach from Meta API
    print("Fetching Facebook reach from Meta API...")
    facebook_reach = 0
    try:
        facebook_reach = get_facebook_reach(since, until)
        print(f"  Facebook reach: {facebook_reach:,}")
    except Exception as e:
        print(f"  WARNING: Meta API error — {e}. Facebook reach set to 0.")

    # 3. Match posts to Content Calendar and update rows
    print("Matching posts to Content Calendar...")
    calendar_rows = get_calendar_rows_for_period(since, until)
    print(f"  {len(calendar_rows)} calendar rows found for period.")

    matched_count = 0
    for post in later_posts:
        row = match_post_to_calendar(post, calendar_rows)
        if row:
            existing_views = row["properties"].get("Views", {}).get("number") or 0
            existing_clicks = row["properties"].get("Link Clicks", {}).get("number") or 0
            update_page(
                row["id"],
                {
                    "Views": prop_number(existing_views + post.get("views", 0)),
                    "Link Clicks": prop_number(existing_clicks + post.get("link_clicks", 0)),
                },
            )
            matched_count += 1

    print(f"  Updated {matched_count} Content Calendar rows.")

    # 4. Aggregate by platform for Scorecard
    platform_totals = aggregate_by_platform(later_posts)

    tiktok_views = platform_totals["TikTok"]["views"]
    instagram_reach = platform_totals["Instagram"]["views"]
    youtube_views = (
        platform_totals["YouTube"]["views"] + platform_totals["YouTube Shorts"]["views"]
    )
    total_link_clicks = sum(v["link_clicks"] for v in platform_totals.values())
    total_views = tiktok_views + instagram_reach + youtube_views + facebook_reach

    # 5. Update Weekly Scorecard
    week_label, week_start, week_end = week_label_and_range()
    scorecard_row = get_or_create_scorecard_row(week_start, week_end, week_label)
    scorecard_props = scorecard_row.get("properties", {})

    prev_running_views = scorecard_props.get("Running: Views", {}).get("number") or 0
    prev_running_clicks = scorecard_props.get("Running: Link Clicks", {}).get("number") or 0

    update_page(
        scorecard_row["id"],
        {
            "TikTok Views": prop_number(tiktok_views),
            "Instagram Reach": prop_number(instagram_reach),
            "YouTube Views": prop_number(youtube_views),
            "Facebook Reach": prop_number(facebook_reach),
            "Link Clicks": prop_number(total_link_clicks),
            "Running: Views": prop_number(prev_running_views + total_views),
            "Running: Link Clicks": prop_number(prev_running_clicks + total_link_clicks),
        },
    )
    print(f"Weekly Scorecard updated: {week_label}")

    # 6. Fire Slack summary to #organic-growth
    blocks = [
        section_block(f"*📊 Weekly Performance Report — {week_label}*"),
        divider_block(),
        section_block(
            f"*Platform Breakdown:*\n"
            f"• TikTok Views: *{tiktok_views:,}*\n"
            f"• Instagram Reach: *{instagram_reach:,}*\n"
            f"• YouTube Views: *{youtube_views:,}*\n"
            f"• Facebook Reach: *{facebook_reach:,}*\n"
            f"• Link Clicks: *{total_link_clicks:,}*"
        ),
        divider_block(),
        section_block(
            f"*Running Totals:*\n"
            f"• Views (all time): *{prev_running_views + total_views:,}*\n"
            f"• Link Clicks (all time): *{prev_running_clicks + total_link_clicks:,}*"
        ),
        divider_block(),
        button_block("View Scorecard in Notion →", NOTION_SCORECARD_URL),
    ]
    notify_organic_growth(
        text=f"Weekly performance report for {week_label} is ready.",
        blocks=blocks,
    )
    print("Slack notification sent to #organic-growth.")
    print("=== Performance Agent Done ===")


if __name__ == "__main__":
    main()
