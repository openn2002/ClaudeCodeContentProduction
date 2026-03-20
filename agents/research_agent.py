"""
Research Agent — runs weekly (Friday night cron).

Workflow:
1. Loads system prompt from prompts/research_agent.md
2. Runs Claude with web_search tool to surface trends, keywords,
   platform signals, and GLP-1 landscape
3. Writes one new row to the 🔍 Research Notion DB
4. Fires Slack notification to #content-pipeline
"""

import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.notion import (
    DB_RESEARCH,
    create_page,
    prop_title,
    prop_rich_text,
    prop_select,
    prop_checkbox,
    prop_date,
)
from lib.slack import notify_content_pipeline, section_block, divider_block, button_block

load_dotenv()

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8096


def load_system_prompt() -> str:
    return (PROMPTS_DIR / "research_agent.md").read_text()


def week_range() -> tuple[str, str]:
    """Return (start, end) for the current Mon–Sun week as ISO strings."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return str(monday), str(sunday)


def run_research() -> str:
    """Run the research agent and return the full markdown report."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    system_prompt = load_system_prompt()

    week_start, week_end = week_range()
    user_message = (
        f"Today is {date.today().isoformat()}. "
        f"Current week: {week_start} to {week_end}. "
        "Please run your full research workflow for both the AU and US markets. "
        "Produce the complete structured report."
    )

    print("Running research agent with web search...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": user_message}],
    )

    # Extract the final text response
    report = ""
    for block in response.content:
        if hasattr(block, "text"):
            report += block.text

    return report


def parse_sections(report: str) -> dict:
    """
    Extract the five key sections from the report markdown.
    Returns dict with keys matching Notion property names.
    Falls back to full report for any section not found.
    """

    def extract_section(text: str, heading: str, next_headings: list) -> str:
        pattern = rf"##\s*\d*\.?\s*{re.escape(heading)}.*?(?=\n##\s*(?:{'|'.join(next_headings)})|$)"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return match.group(0).strip() if match else ""

    sections = {
        "Trending Topics": extract_section(
            report, "Trending Topics", ["Keyword", "Platform", "GLP", "Strategic"]
        ),
        "Keyword Opportunities": extract_section(
            report, "Keyword", ["Platform", "GLP", "Strategic", "Trending"]
        ),
        "Platform Signals": extract_section(
            report, "Platform", ["GLP", "Strategic", "Trending", "Keyword"]
        ),
        "GLP-1 Landscape": extract_section(
            report, "GLP", ["Strategic", "Trending", "Keyword", "Platform"]
        ),
        "Strategic Summary": extract_section(
            report, "Strategic", ["Trending", "Keyword", "Platform", "GLP"]
        ),
    }

    # Fall back: if a section is empty, use the full report for that slot
    for key in sections:
        if not sections[key]:
            sections[key] = report[:2000]

    return sections


def write_to_notion(report: str, sections: dict) -> dict:
    week_start, week_end = week_range()
    week_label = f"Research — {week_start}"

    page = create_page(
        DB_RESEARCH,
        {
            "Name": prop_title(week_label),
            "Week": prop_date(week_start, week_end),
            "Market": prop_select("Both"),
            "Agent Generated": prop_checkbox(True),
            "Trending Topics": prop_rich_text(sections["Trending Topics"]),
            "Keyword Opportunities": prop_rich_text(sections["Keyword Opportunities"]),
            "Platform Signals": prop_rich_text(sections["Platform Signals"]),
            "GLP-1 Landscape": prop_rich_text(sections["GLP-1 Landscape"]),
            "Strategic Summary": prop_rich_text(sections["Strategic Summary"]),
        },
    )
    return page


def fire_slack(page: dict, sections: dict):
    week_start, week_end = week_range()
    page_url = page.get("url", "https://notion.so")

    # Pull a brief summary from Strategic Summary (first 300 chars)
    summary_preview = sections["Strategic Summary"][:300].strip()
    if len(sections["Strategic Summary"]) > 300:
        summary_preview += "..."

    blocks = [
        section_block(f"*🔍 Weekly Research Report is ready*\n_{week_start} → {week_end}_"),
        divider_block(),
        section_block(f"*Strategic Summary Preview:*\n{summary_preview}"),
        divider_block(),
        button_block("View in Notion →", page_url),
    ]
    notify_content_pipeline(
        text=f"Research report for {week_start}–{week_end} is ready in Notion.",
        blocks=blocks,
    )
    print("Slack notification sent to #content-pipeline.")


def main():
    print("=== Research Agent Starting ===")
    report = run_research()
    print(f"Report generated ({len(report)} chars).")

    sections = parse_sections(report)
    page = write_to_notion(report, sections)
    print(f"Notion row created: {page.get('url')}")

    fire_slack(page, sections)
    print("=== Research Agent Done ===")


if __name__ == "__main__":
    main()
