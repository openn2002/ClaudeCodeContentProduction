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
    get_page_text,
    query_database,
    prop_title,
    prop_select,
    prop_multi_select,
    prop_rich_text,
    prop_checkbox,
    prop_date,
)
from lib.slack import notify_content_pipeline, section_block, divider_block, button_block
from lib.notion import get_latest_performance_insights
from agents.competitor_agent import get_latest_analysis

load_dotenv(override=True)

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
    """Fetch the full research report from the page body blocks."""
    return get_page_text(research_page["id"])


def run_idea_generation(
    research_text: str,
    competitor_analysis: str,
    recent_titles: list = None,
    performance_insights: str = None,
) -> str:
    """Run video-idea-agent with research, competitor analysis, and performance insights."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    system_prompt = load_system_prompt()

    competitor_section = (
        f"\n\n---\n\n## COMPETITOR INTELLIGENCE REPORT\n\n{competitor_analysis}"
        if competitor_analysis
        else "\n\n(No competitor analysis available for this run.)"
    )

    performance_section = (
        f"\n\n---\n\n## OUR PERFORMANCE INSIGHTS — What's Working For Us\n\n"
        f"{performance_insights[:3000]}\n\n"
        "_Use this to build on what's already resonating with our audience. "
        "If a topic, format, or angle has proven to perform well, generate ideas "
        "that deliberately expand on it._"
        if performance_insights
        else "\n\n(No performance insights yet — will populate once posts go live.)"
    )

    recent_section = ""
    if recent_titles:
        titles_list = "\n".join(f"- {t}" for t in recent_titles)
        recent_section = (
            f"\n\n---\n\n**PREVIOUSLY GENERATED IDEAS (do not repeat these or close variations):**\n\n"
            f"{titles_list}"
        )

    user_message = (
        f"Today is {date.today().isoformat()}.\n\n"
        "You have THREE intelligence inputs this week:\n\n"
        "**1. Industry Research Report** (trends, keywords, platform signals, GLP-1 landscape):\n\n"
        f"{research_text}"
        f"{competitor_section}"
        f"{performance_section}"
        f"{recent_section}\n\n"
        "---\n\n"
        "Using ALL THREE inputs, generate your full ranked video concept list (10–15 concepts) "
        "and full production briefs for the top 3.\n\n"
        "Prioritise ideas that:\n"
        "- Build on topics/formats that have already proven to perform well FOR US (performance insights)\n"
        "- Exploit gaps competitors are NOT filling well (competitor report)\n"
        "- Address audience frustrations surfaced in the research data\n"
        "- Ride trends where CSIRO credibility gives us an unfair advantage\n\n"
        "IMPORTANT — only generate ideas that are directly grounded in the data provided above. "
        "Do NOT invent facts, announcements, product updates, or claims that are not present in "
        "the research, competitor, or performance inputs. If you cannot point to a specific signal "
        "in the data that supports an idea, do not include it.\n\n"
        "For each concept in the ranked list, include a JSON metadata block:\n"
        "```json\n"
        '{"title": "...", "platform": ["TikTok"], "pillar": "Science & Credibility", '
        '"market": "Australia", "priority": "High", '
        '"source": "1-sentence description of which specific data signal, competitor insight, or performance pattern informed this idea"}\n'
        "```\n"
        "Valid platforms: Instagram, Facebook, Facebook Group, TikTok, YouTube Shorts, YouTube\n"
        "Valid pillars: Science & Credibility, Weight Loss Results, Nutrition & Meal Planning, "
        "Habit & Behaviour Change, GLP-1 & Medication Support, Exercise & Movement, "
        "Promotion & Offers, People & Community\n"
        "Valid markets: Australia\n"
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

            market = data.get("market", "Australia")
            if market not in VALID_MARKETS:
                market = "Australia"

            priority = data.get("priority", "Medium")
            if priority not in VALID_PRIORITIES:
                priority = "Medium"

            source = data.get("source", "").strip()[:500]

            ideas.append(
                {
                    "title": title,
                    "platforms": platforms,
                    "pillar": pillar,
                    "market": market,
                    "priority": priority,
                    "source": source,
                }
            )
        except json.JSONDecodeError:
            continue

    return ideas


def get_recent_idea_titles() -> list:
    """Return idea titles from the last 4 weeks to avoid repeating them."""
    pages = query_database(DB_IDEAS)
    titles = []
    for page in pages:
        title_blocks = page.get("properties", {}).get("Name", {}).get("title", [])
        title = "".join(b.get("text", {}).get("content", "") for b in title_blocks)
        if title:
            titles.append(title)
    return titles


def week_range() -> tuple[str, str]:
    """Returns next week's Monday–Sunday — the content week these ideas are planned for."""
    today = date.today()
    next_monday = today + timedelta(days=(7 - today.weekday()))
    next_sunday = next_monday + timedelta(days=6)
    return str(next_monday), str(next_sunday)


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
        if idea.get("source"):
            props["Source"] = prop_rich_text(idea["source"])

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

    competitor_analysis = get_latest_analysis()
    if competitor_analysis:
        print(f"Competitor analysis loaded ({len(competitor_analysis)} chars).")
    else:
        print("No competitor analysis found — run competitor_agent.py first for best results.")

    performance_insights = get_latest_performance_insights()
    if performance_insights:
        print(f"Performance insights loaded ({len(performance_insights)} chars).")
    else:
        print("No performance insights yet — ideas will be generated without performance context.")

    recent_titles = get_recent_idea_titles()
    if recent_titles:
        print(f"Loaded {len(recent_titles)} recent idea titles to avoid repeating.")

    output = run_idea_generation(research_text, competitor_analysis, recent_titles, performance_insights)
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
