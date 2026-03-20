"""
Video Idea Agent — runs Saturday morning (after research_agent).

Workflow:
1. Reads the latest row from 🔍 Research DB
2. Runs Claude with the video-idea-agent prompt + research as context
3. Parses 10–15 ranked video concepts from the output
4. Writes each concept as a row to 💡 Ideas DB
5. Fires Slack notification to #content-pipeline
"""

import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.notion import (
    DB_IDEAS,
    create_page,
    get_latest_research_row,
    prop_title,
    prop_select,
    prop_multi_select,
    prop_checkbox,
    prop_date,
)
from lib.slack import notify_content_pipeline, section_block, divider_block, button_block

load_dotenv()

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8096

# Valid values per Notion schema
VALID_PILLARS = [
    "Science & Credibility",
    "Weight Loss Results",
    "Nutrition & Meal Planning",
    "Habit & Behaviour Change",
    "GLP-1 & Medication Support",
    "Exercise & Movement",
    "Promotion & Offers",
    "People & Community",
]
VALID_PLATFORMS = ["Instagram", "Facebook", "Facebook Group", "TikTok", "YouTube Shorts", "YouTube"]
VALID_PRIORITIES = ["Highest", "High", "Medium", "Low"]
VALID_MARKETS = ["Australia", "US", "Both"]


def load_system_prompt() -> str:
    return (PROMPTS_DIR / "video_idea_agent.md").read_text()


def extract_research_text(research_page: dict) -> str:
    """Pull all text fields from a Research Notion page into one string."""
    props = research_page.get("properties", {})
    parts = []
    for field in ["Trending Topics", "Keyword Opportunities", "Platform Signals", "GLP-1 Landscape", "Strategic Summary"]:
        rt = props.get(field, {}).get("rich_text", [])
        text = "".join(block.get("text", {}).get("content", "") for block in rt)
        if text:
            parts.append(f"## {field}\n{text}")
    return "\n\n".join(parts)


def run_idea_generation(research_text: str) -> str:
    """Run video-idea-agent and return the full output."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    system_prompt = load_system_prompt()

    user_message = (
        f"Today is {date.today().isoformat()}.\n\n"
        "Here is the latest research report:\n\n"
        f"{research_text}\n\n"
        "Please generate your full ranked video concept list (10–15 concepts) "
        "and full production briefs for the top 3. "
        "For each concept in the ranked list, include a JSON metadata block in this format:\n"
        "```json\n"
        '{"title": "...", "platform": ["TikTok"], "pillar": "Science & Credibility", '
        '"market": "Both", "priority": "High"}\n'
        "```\n"
        "Valid platforms: Instagram, Facebook, Facebook Group, TikTok, YouTube Shorts, YouTube\n"
        "Valid pillars: Science & Credibility, Weight Loss Results, Nutrition & Meal Planning, "
        "Habit & Behaviour Change, GLP-1 & Medication Support, Exercise & Movement, "
        "Promotion & Offers, People & Community\n"
        "Valid markets: Australia, US, Both\n"
        "Valid priorities: Highest, High, Medium, Low"
    )

    print("Running video idea agent...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    output = ""
    for block in response.content:
        if hasattr(block, "text"):
            output += block.text
    return output


def parse_ideas(output: str) -> list:
    """
    Extract structured idea metadata from JSON blocks embedded in the output.
    Each idea must have: title, platform (list), pillar, market, priority.
    """
    ideas = []
    json_pattern = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

    for match in json_pattern.finditer(output):
        try:
            data = json.loads(match.group(1))
            # Validate and normalise
            title = data.get("title", "").strip()
            if not title:
                continue

            platforms = data.get("platform", [])
            if isinstance(platforms, str):
                platforms = [platforms]
            platforms = [p for p in platforms if p in VALID_PLATFORMS]

            pillar = data.get("pillar", "")
            if pillar not in VALID_PILLARS:
                pillar = "Science & Credibility"

            market = data.get("market", "Both")
            if market not in VALID_MARKETS:
                market = "Both"

            priority = data.get("priority", "Medium")
            if priority not in VALID_PRIORITIES:
                priority = "Medium"

            ideas.append(
                {
                    "title": title,
                    "platforms": platforms,
                    "pillar": pillar,
                    "market": market,
                    "priority": priority,
                }
            )
        except json.JSONDecodeError:
            continue

    return ideas


def week_range() -> tuple[str, str]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return str(monday), str(sunday)


def write_ideas_to_notion(ideas: list) -> list:
    week_start, week_end = week_range()
    created_pages = []

    for idea in ideas:
        props = {
            "Name": prop_title(idea["title"]),
            "Pillar": prop_select(idea["pillar"]),
            "Market": prop_select(idea["market"]),
            "Priority": prop_select(idea["priority"]),
            "Status": prop_select("New"),
            "Agent Generated": prop_checkbox(True),
            "Week": prop_date(week_start, week_end),
        }
        if idea["platforms"]:
            props["Platform"] = prop_multi_select(idea["platforms"])

        page = create_page(DB_IDEAS, props)
        created_pages.append(page)
        print(f"  Created idea: {idea['title']}")

    return created_pages


def fire_slack(ideas: list, created_pages: list):
    count = len(ideas)
    # Link to first created page as entry point
    notion_url = created_pages[0].get("url", "https://notion.so") if created_pages else "https://notion.so"

    idea_lines = "\n".join(
        f"• *{idea['title']}* ({idea['priority']} | {', '.join(idea['platforms']) or 'TBD'})"
        for idea in ideas[:10]
    )
    if len(ideas) > 10:
        idea_lines += f"\n_...and {len(ideas) - 10} more_"

    blocks = [
        section_block(f"*💡 {count} new video ideas are ready for review*"),
        divider_block(),
        section_block(idea_lines),
        divider_block(),
        button_block("Review Ideas in Notion →", notion_url),
    ]
    notify_content_pipeline(
        text=f"{count} new video ideas ready for review in Notion.",
        blocks=blocks,
    )
    print("Slack notification sent to #content-pipeline.")


def main():
    print("=== Video Idea Agent Starting ===")

    research_page = get_latest_research_row()
    if not research_page:
        print("No research row found in Notion. Run research_agent first.")
        sys.exit(1)

    research_text = extract_research_text(research_page)
    print(f"Research loaded ({len(research_text)} chars).")

    output = run_idea_generation(research_text)
    print(f"Output generated ({len(output)} chars).")

    ideas = parse_ideas(output)
    print(f"Parsed {len(ideas)} ideas.")

    if not ideas:
        print("WARNING: No structured ideas parsed. Check agent output format.")
        sys.exit(1)

    created_pages = write_ideas_to_notion(ideas)
    print(f"{len(created_pages)} rows written to 💡 Ideas DB.")

    fire_slack(ideas, created_pages)
    print("=== Video Idea Agent Done ===")


if __name__ == "__main__":
    main()
