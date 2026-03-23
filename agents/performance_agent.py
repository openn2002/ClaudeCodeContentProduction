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
6. Analyses ALL historical live posts with Claude to surface patterns:
   - What topics/pillars are driving above-average views
   - Which hooks/titles are resonating
   - What to do more of, what to avoid
7. Saves performance insights to Research DB (Type = "Performance Analysis")
8. Fires Slack summary to #organic-growth (includes top insight)

The performance insights feed into the Video Idea Agent and Script Agent,
closing the flywheel: post → measure → learn → inform next ideas → repeat.
"""

import os
import re
import sys
from datetime import date, timedelta, datetime
from pathlib import Path

import anthropic
import requests
from typing import Optional
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.notion import (
    DB_CONTENT_CALENDAR,
    DB_RESEARCH,
    DB_WEEKLY_SCORECARD,
    query_database,
    update_page,
    get_or_create_scorecard_row,
    get_all_live_posts,
    create_page,
    append_blocks,
    prop_number,
    prop_title,
    prop_select,
    prop_date,
    prop_checkbox,
)
from lib.later import get_last_7_days_performance
from lib.slack import (
    notify_organic_growth,
    section_block,
    divider_block,
    button_block,
)

load_dotenv(override=True)

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


def match_post_to_calendar(post: dict, calendar_rows: list) -> Optional[dict]:
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
# Performance Analysis — Claude-powered pattern recognition
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT = """
You are a content performance analyst for Digital Wellness — the company that partners with
CSIRO (Australia's national science agency) to deliver the CSIRO Total Wellbeing Diet.

You will receive a list of published social media posts with their performance metrics.
Your job is to identify what is and isn't working, and give specific, actionable
recommendations that will directly inform next week's content ideas and scripts.

Be ruthlessly specific. "Budget/value content performs well" is useful.
"Health content gets views" is not.

Focus on patterns that are REPLICABLE — topics, angles, hooks, and formats that the
team can deliberately repeat or build on.
""".strip()


def format_posts_for_analysis(posts: list) -> str:
    """Format live posts into a structured prompt for Claude."""
    if not posts:
        return "No published posts with metrics found."

    views_list = [p["views"] for p in posts]
    avg_views = sum(views_list) / len(views_list)
    sorted_posts = sorted(posts, key=lambda x: x["views"], reverse=True)

    lines = [
        f"## Published Content Performance — CSIRO Total Wellbeing Diet",
        f"Total posts with metrics: {len(posts)}",
        f"Average views: {avg_views:,.0f}",
        f"Top post views: {sorted_posts[0]['views']:,}",
        f"Bottom post views: {sorted_posts[-1]['views']:,}",
        "",
        "### All Posts (sorted by views, highest first)",
        "| # | Title | Platform | Pillar | Views | Link Clicks | Published | vs Avg |",
        "|---|-------|----------|--------|-------|-------------|-----------|--------|",
    ]

    for i, post in enumerate(sorted_posts, 1):
        platforms = ", ".join(post["platforms"]) if post["platforms"] else "Unknown"
        vs_avg = post["views"] / avg_views if avg_views > 0 else 0
        vs_label = f"{vs_avg:.1f}×"
        lines.append(
            f"| {i} | {post['name'][:60]} | {platforms} | {post['pillar'] or '—'} "
            f"| {post['views']:,} | {post['link_clicks']:,} | {post['published_at'][:10]} | {vs_label} |"
        )

    return "\n".join(lines)


def run_performance_analysis(posts: list) -> str:
    """Pass historical post data to Claude for pattern analysis. Returns markdown report."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    formatted = format_posts_for_analysis(posts)

    user_message = (
        f"Today is {date.today().isoformat()}.\n\n"
        "Below is the full performance history for the CSIRO Total Wellbeing Diet social "
        "media accounts — every published post that has had metrics collected, sorted by views.\n\n"
        "Analyse this data and produce the Performance Insights Report. "
        "Your output will be read by the content team AND injected directly into the "
        "AI agents that generate next week's video ideas and scripts — so be specific "
        "and actionable. What should we do MORE of? What should we STOP doing? "
        "What topics and angles are clearly resonating with our audience?\n\n"
        f"{formatted}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=ANALYSIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    report = ""
    for block in response.content:
        if hasattr(block, "text"):
            report += block.text
    return report


def markdown_to_blocks(text: str) -> list:
    """Convert markdown report to Notion block objects."""
    blocks = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in ("---", "***", "___"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif stripped.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": stripped[4:].strip()[:2000]}}]}})
        elif stripped.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": stripped[3:].strip()[:2000]}}]}})
        elif stripped.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": stripped[2:].strip()[:2000]}}]}})
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": stripped[2:].strip()[:2000]}}]}})
        elif re.match(r"^\d+\.\s", stripped):
            content = re.sub(r"^\d+\.\s", "", stripped).strip()[:2000]
            blocks.append({"object": "block", "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": content}}]}})
        elif stripped.startswith("|"):
            if not stripped.replace("-", "").replace("|", "").replace(" ", ""):
                continue
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            content = " | ".join(cells)[:2000]
            if content:
                blocks.append({"object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]}})
        else:
            blocks.append({"object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": stripped[:2000]}}]}})
    return blocks


def write_insights_to_notion(report: str) -> dict:
    """Save performance insights to Research DB as Type='Performance Analysis'."""
    today = date.today()
    label = f"Performance Analysis — {today.isoformat()}"
    blocks = markdown_to_blocks(report)
    first_batch = blocks[:100]
    remaining = blocks[100:]

    page = create_page(
        DB_RESEARCH,
        {
            "Name": prop_title(label),
            "Content Week": prop_date(str(today)),
            "Market": prop_select("Australia"),
            "Type": prop_select("Performance Analysis"),
            "Status": prop_select("New"),
            "Agent Generated": prop_checkbox(True),
        },
        children=first_batch,
    )
    if remaining:
        append_blocks(page["id"], remaining)
    return page


def extract_top_insight(report: str) -> str:
    """Pull the top recommendation from the report for Slack preview."""
    # Try to find a recommendations section
    match = re.search(
        r"(##.*?recommend.*?\n)(.*?)(?=\n##|\Z)",
        report, re.IGNORECASE | re.DOTALL
    )
    if match:
        return match.group(0)[:400].strip()
    return report[:400].strip()


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

    # 6. Analyse all historical live posts with Claude
    print("Fetching all live posts from Content Calendar for analysis...")
    all_live_posts = get_all_live_posts()
    print(f"  {len(all_live_posts)} posts with metrics found.")

    insights_page = None
    top_insight = ""
    if len(all_live_posts) >= 3:
        print("Running performance analysis with Claude...")
        insights_report = run_performance_analysis(all_live_posts)
        print(f"  Analysis complete ({len(insights_report)} chars).")
        insights_page = write_insights_to_notion(insights_report)
        print(f"  Performance insights saved to Notion: {insights_page.get('url')}")
        top_insight = extract_top_insight(insights_report)
    else:
        print("  Not enough posts yet for meaningful analysis (need ≥ 3). Skipping.")

    # 7. Fire Slack summary to #organic-growth
    slack_blocks = [
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
    ]

    if top_insight:
        slack_blocks += [
            divider_block(),
            section_block(f"*🔁 Performance Insight (feeding into this week's ideas):*\n_{top_insight}_"),
        ]

    insights_url = insights_page.get("url") if insights_page else NOTION_SCORECARD_URL
    slack_blocks += [
        divider_block(),
        button_block("View Scorecard →", NOTION_SCORECARD_URL),
        button_block("View Performance Insights →", insights_url),
    ]

    notify_organic_growth(
        text=f"Weekly performance report for {week_label} is ready.",
        blocks=slack_blocks,
    )
    print("Slack notification sent to #organic-growth.")
    print("=== Performance Agent Done ===")


if __name__ == "__main__":
    main()
