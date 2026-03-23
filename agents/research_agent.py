"""
Research Agent — runs weekly (Friday night cron).

Workflow:
1. Fetches curated trend-reporting websites (Later, IMH, Buffer, etc.) via lib/web.py
2. Runs Apify scrapers to gather live social data:
   - TikTok trending videos (health/wellness keywords)
   - Instagram top posts (health/wellness hashtags)
   - YouTube trending videos (health/wellness search)
   - Google Search results (health/wellness keywords)
3. Passes all data + system prompt to Claude for analysis
4. Creates a new row in the 🔍 Research Notion DB with the full report as page content
5. Fires Slack notification to #content-pipeline
"""

import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.notion import (
    DB_RESEARCH,
    create_page,
    append_blocks,
    query_database,
    prop_title,
    prop_select,
    prop_checkbox,
    prop_date,
)
from lib.slack import notify_content_pipeline, section_block, divider_block, button_block
from lib.apify import gather_all
from lib.web import fetch_all_trend_articles

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8096


def load_system_prompt() -> str:
    return (PROMPTS_DIR / "research_agent.md").read_text()


def week_range() -> tuple:
    """Returns the Monday–Sunday of NEXT week — the content week this research informs."""
    today = date.today()
    next_monday = today + timedelta(days=(7 - today.weekday()))
    next_sunday = next_monday + timedelta(days=6)
    return str(next_monday), str(next_sunday)


def run_research(scraped_data: str, trend_articles: str) -> str:
    """Pass scraped live data + trend articles to Claude for analysis. Returns full markdown report."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    system_prompt = load_system_prompt()

    week_start, week_end = week_range()
    user_message = (
        f"Today is {date.today().isoformat()}. "
        f"Content week: {week_start} to {week_end}.\n\n"
        "You have two data sources below:\n\n"
        "**Source 1 — Industry Trend Articles:** Scraped from leading social media "
        "trend-reporting websites (Later, Influencer Marketing Hub, Buffer, etc.). "
        "Use this to surface trending video formats, viral hooks, and content styles "
        "working right now — and how they could be adapted for the CSIRO TWD audience.\n\n"
        "**Source 2 — Live Social Data:** Real scraped data from TikTok, Instagram, "
        "YouTube, and Google Search. Use this to identify what's actually performing, "
        "what hooks are working, and what topics are trending in health/wellness.\n\n"
        "Ground your analysis in both sources. Supplement with your own knowledge where "
        "needed, but do not invent trends not evidenced by the data.\n\n"
        "Produce the complete structured research report for the AU market.\n\n"
        "---\n\n"
        f"{trend_articles}\n\n"
        "---\n\n"
        f"{scraped_data}"
    )

    print("Analysing scraped data with Claude...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    report = ""
    for block in response.content:
        if hasattr(block, "text"):
            report += block.text

    return report


def markdown_to_blocks(text: str) -> list:
    """Convert a markdown report to Notion block objects."""
    blocks = []
    lines = text.split("\n")

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        if stripped in ("---", "***", "___"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})

        elif stripped.startswith("### "):
            content = stripped[4:].strip()[:2000]
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": content}}]},
            })

        elif stripped.startswith("## "):
            content = stripped[3:].strip()[:2000]
            blocks.append({
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": content}}]},
            })

        elif stripped.startswith("# "):
            content = stripped[2:].strip()[:2000]
            blocks.append({
                "object": "block", "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": content}}]},
            })

        elif stripped.startswith("- ") or stripped.startswith("* "):
            content = stripped[2:].strip()[:2000]
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": content}}]},
            })

        elif re.match(r"^\d+\.\s", stripped):
            content = re.sub(r"^\d+\.\s", "", stripped).strip()[:2000]
            blocks.append({
                "object": "block", "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": content}}]},
            })

        elif stripped.startswith("|"):
            # Skip markdown table separator rows
            if not stripped.replace("-", "").replace("|", "").replace(" ", ""):
                continue
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            content = " | ".join(cells)[:2000]
            if content:
                blocks.append({
                    "object": "block", "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
                })

        else:
            content = stripped[:2000]
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
            })

    return blocks


def extract_strategic_summary(report: str) -> str:
    """Pull the Strategic Summary section for Slack preview."""
    match = re.search(r"##\s*\d*\.?\s*Strategic Summary.*", report, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0)[:500].strip()
    return report[:500].strip()


def write_to_notion(report: str) -> dict:
    week_start, week_end = week_range()
    week_label = f"Research — {week_start}"

    blocks = markdown_to_blocks(report)
    first_batch = blocks[:100]
    remaining = blocks[100:]

    page = create_page(
        DB_RESEARCH,
        {
            "Name": prop_title(week_label),
            "Content Week": prop_date(week_start, week_end),
            "Market": prop_select("Both"),
            "Type": prop_select("Research"),
            "Status": prop_select("New"),
            "Agent Generated": prop_checkbox(True),
        },
        children=first_batch,
    )

    if remaining:
        append_blocks(page["id"], remaining)

    return page


def fire_slack(page: dict, report: str):
    week_start, week_end = week_range()
    page_url = page.get("url", "https://notion.so")
    summary = extract_strategic_summary(report)
    if len(summary) >= 500:
        summary += "..."

    blocks = [
        section_block(f"*🔍 Weekly Research Report is ready*\n_{week_start} → {week_end}_"),
        divider_block(),
        section_block(f"*Strategic Summary:*\n{summary}"),
        divider_block(),
        button_block("View in Notion →", page_url),
    ]
    notify_content_pipeline(
        text=f"Research report for {week_start}–{week_end} is ready in Notion.",
        blocks=blocks,
    )
    print("Slack notification sent to #content-pipeline.")


def already_ran_this_week() -> bool:
    """Return True if a Research row already exists for next week's content week."""
    week_start, _ = week_range()
    pages = query_database(
        DB_RESEARCH,
        filter_obj={"property": "Type", "select": {"equals": "Research"}},
    )
    for page in pages:
        date_prop = page["properties"].get("Content Week", {}).get("date")
        if date_prop and date_prop.get("start") == week_start:
            return True
    return False


def main():
    print("=== Research Agent Starting ===")

    if already_ran_this_week():
        print("Research report already exists for this content week. Skipping.")
        return

    print("Fetching trend articles from industry websites...")
    trend_articles = fetch_all_trend_articles(verbose=True)
    print(f"Trend articles ready ({len(trend_articles)} chars).")

    print("Gathering live data via Apify...")
    scraped_data = gather_all(verbose=True)
    print(f"Scraped data ready ({len(scraped_data)} chars).")

    report = run_research(scraped_data, trend_articles)
    print(f"Research report generated ({len(report)} chars).")

    page = write_to_notion(report)
    print(f"Notion row created: {page.get('url')}")

    fire_slack(page, report)
    print("=== Research Agent Done ===")


if __name__ == "__main__":
    main()
