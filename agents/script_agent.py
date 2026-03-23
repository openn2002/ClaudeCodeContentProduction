"""
Script Agent — polls every hour for approved ideas.

Workflow:
1. Queries 💡 Ideas DB for rows where Status = "Approved"
2. Checks a local state file to skip already-processed idea IDs
3. For each new approved idea, generates a full script via Claude
4. Writes to 📝 Script Library DB with all fields populated
5. Fires Slack notification to #content-pipeline tagging Ollie + Nicole
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.notion import (
    DB_SCRIPT_LIBRARY,
    create_page,
    append_blocks,
    markdown_to_blocks,
    get_approved_ideas,
    get_page,
    get_latest_research_row,
    get_latest_performance_insights,
    get_page_text,
    prop_title,
    prop_rich_text,
    prop_checkbox,
)
from lib.slack import notify_content_pipeline, section_block, divider_block, button_block
from agents.competitor_agent import get_latest_analysis

load_dotenv(override=True)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8096

# Persist processed idea IDs to avoid re-processing on each poll
STATE_FILE = Path(__file__).parent.parent / ".processed_ideas.json"

SLACK_USER_ID_OLLIE = os.getenv("SLACK_USER_ID_OLLIE", "")
SLACK_USER_ID_NICOLE = os.getenv("SLACK_USER_ID_NICOLE", "")

SCRIPT_SYSTEM_PROMPT = """
You are a video content scriptwriter for Digital Wellness — the company behind the CSIRO Total Wellbeing Diet (Australia).

Your job is to write production-ready short-form video scripts for the Australian market.

**Our content philosophy:**
We lead with value, not with selling. The goal is to be the most credible, trustworthy voice in the Australian health and nutrition space. Most videos should leave the viewer genuinely better informed — the brand affinity and product interest follows naturally from that. Avoid scripts that feel like ads. Avoid scripts that end with a hard product push. If someone watches our content and thinks "that was actually useful", we've won.

CSIRO is our credibility signal, not our sales pitch. Reference it to back up a claim or add authority — not as a closing argument to buy something.

Every script must be:
- Warm, direct, and genuinely useful — like advice from a knowledgeable friend
- Free from shame, fear-mongering, or miracle-cure framing
- Structured for short-form video (TikTok, Reels, YouTube Shorts) unless otherwise specified
- Grounded in real science — cite CSIRO research where it adds genuine credibility, not decoration
- Natural with naming — default to "the program", "our plan", "our approach", or "we" when referring to the product. Use the full name "CSIRO Total Wellbeing Diet" at most once per script, and only where it's contextually earned (e.g. the caption, or a hook where the program itself is the subject). Repeating the full name feels like an ad; dropping it in naturally feels like a brand people trust.
- Informed by what hooks, formats, and caption styles are actually working right now (see context below)

You will be given:
1. The approved video idea (title, pillar, platform, source signal)
2. This week's research report — what topics are trending, what keywords matter, what platform formats are performing
3. Competitor analysis — what hooks competitors are using, what formats are winning, what gaps exist

Use inputs 2 and 3 to shape the hook style, script format, and caption — not just the idea itself.

For each idea, produce a script with these exact six sections in order:

## Creative Direction
2–4 sentences covering: overall tone and energy, who the talent is (member-led, presenter-to-camera, voiceover, etc.), setting and aesthetic (home kitchen, natural light, unpolished vs. styled), and any important filming notes. This is the brief for the person filming — not a shot list, just enough direction to set the right vibe.

## Hook
Three complete hook options to choose from or A/B test. For each, write:
- **Option [A/B/C]:** One sentence description of the hook style
- **Spoken line:** The exact words said in the opening 3–5 seconds

Keep hooks punchy. No visual directions here — that's covered by Creative Direction and the On-Screen Text section.

## Script Outline
Scene-by-scene breakdown with rough timing (e.g. 0:00–0:10). For each scene, write the spoken content only — what the talent actually says. Do not include visual directions or on-screen text notes inside this section; those belong in Creative Direction and Key On-Screen Text respectively.

## Key On-Screen Text
Bullet list of every text overlay that appears throughout the video, in order. Keep each one short — these are the words that flash on screen to reinforce or punctuate what's being said.

## CTA
One to three sentences for the closing moment. Match the energy of the content — most videos should end with a soft, community-building action (save this, follow for more, comment below, share with someone who needs this). Reserve product CTAs (visit the site, start your free trial) for videos that are explicitly product-focused. When in doubt, go soft.

## Caption
The social media caption for this post. Include relevant Australian hashtags. Keep it punchy and platform-appropriate. The caption should feel native — not like a press release.
"""


def load_state() -> set:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        return set(data.get("processed", []))
    return set()


def save_state(processed_ids: set):
    STATE_FILE.write_text(json.dumps({"processed": list(processed_ids)}))


def extract_idea_context(idea_page: dict) -> str:
    """Pull title and available fields from the idea page."""
    props = idea_page.get("properties", {})

    title_blocks = props.get("Name", {}).get("title", [])
    title = "".join(b.get("text", {}).get("content", "") for b in title_blocks)

    pillar = props.get("Pillar", {}).get("select", {})
    pillar_name = pillar.get("name", "") if pillar else ""

    platform_items = props.get("Platform", {}).get("multi_select", [])
    platforms = ", ".join(p.get("name", "") for p in platform_items)

    market = props.get("Market", {}).get("select", {})
    market_name = market.get("name", "") if market else "Both"

    priority = props.get("Priority", {}).get("select", {})
    priority_name = priority.get("name", "") if priority else ""

    return (
        f"**Video Idea:** {title}\n"
        f"**Content Pillar:** {pillar_name}\n"
        f"**Platform(s):** {platforms}\n"
        f"**Market:** {market_name}\n"
        f"**Priority:** {priority_name}"
    )


def generate_script(
    idea_context: str,
    research_text: str = "",
    competitor_analysis: str = "",
    performance_insights: str = "",
) -> str:
    """Run Claude to generate the full script."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    context_section = ""
    if research_text:
        context_section += f"\n\n---\n\n**THIS WEEK'S RESEARCH REPORT** (use to inform hook style, format, and topics):\n\n{research_text[:4000]}"
    if competitor_analysis:
        context_section += f"\n\n---\n\n**COMPETITOR ANALYSIS** (use to inform hook style, caption approach, and format choices):\n\n{competitor_analysis[:3000]}"
    if performance_insights:
        context_section += (
            f"\n\n---\n\n**OUR PERFORMANCE INSIGHTS** (use to shape the hook and angle — "
            f"topics and formats that have already proven to work for this brand):\n\n{performance_insights[:2000]}"
        )

    user_message = (
        f"Today is {date.today().isoformat()}.\n\n"
        "Please write a full production script for the following approved video idea:\n\n"
        f"{idea_context}"
        f"{context_section}\n\n"
        "---\n\n"
        "Follow the exact output structure defined in your system instructions. "
        "Use the research, competitor, and performance context to shape the hook, format, "
        "and caption — not just the idea title. If performance insights show a certain "
        "angle or hook style works particularly well for this audience, lean into it."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SCRIPT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    output = ""
    for block in response.content:
        if hasattr(block, "text"):
            output += block.text
    return output


def parse_script_sections(script: str) -> dict:
    """Extract the six script sections from the generated text."""
    import re

    def extract(text: str, heading: str, next_headings: list) -> str:
        pattern = rf"##\s*{re.escape(heading)}.*?(?=\n##\s*(?:{'|'.join(next_headings)})|$)"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        return match.group(0).strip() if match else ""

    all_headings = ["Creative Direction", "Hook", "Script Outline", "Key On-Screen", "CTA", "Caption"]

    return {
        "Creative Direction": extract(script, "Creative Direction", ["Hook", "Script Outline", "Key On-Screen", "CTA", "Caption"]),
        "Hook": extract(script, "Hook", ["Script Outline", "Key On-Screen", "CTA", "Caption", "Creative"]),
        "Script Outline": extract(script, "Script Outline", ["Key On-Screen", "CTA", "Caption", "Hook", "Creative"]),
        "Key On-Screen Text": extract(script, "Key On-Screen", ["CTA", "Caption", "Hook", "Script", "Creative"]),
        "CTA": extract(script, "CTA", ["Caption", "Hook", "Script", "Key", "Creative"]),
        "Caption": extract(script, "Caption", ["Hook", "Script", "Key", "CTA", "Creative"]),
    }


def write_to_notion(idea_page: dict, sections: dict) -> dict:
    """
    Create the Script Library page with metadata in properties and
    the full script written as formatted page body blocks.

    Properties hold only short, scannable fields (Caption, CTA) plus checkboxes.
    The script body (Creative Direction → Caption) is written as Notion blocks
    so bold/italic/headings render correctly when the page is opened.
    """
    props = idea_page.get("properties", {})
    title_blocks = props.get("Name", {}).get("title", [])
    title = "".join(b.get("text", {}).get("content", "") for b in title_blocks)

    # Create the page — keep Caption and CTA as properties for quick DB-view scanning
    page = create_page(
        DB_SCRIPT_LIBRARY,
        {
            "Name": prop_title(title),
            "Agent Generated": prop_checkbox(True),
            "Science Approved": prop_checkbox(False),
            "Approved for filming": prop_checkbox(False),
            "Caption": prop_rich_text(sections.get("Caption", "")[:2000]),
            "CTA": prop_rich_text(sections.get("CTA", "")[:500]),
        },
    )

    # Build the full script as page body blocks for proper formatting
    section_order = [
        "Creative Direction",
        "Hook",
        "Script Outline",
        "Key On-Screen Text",
        "CTA",
        "Caption",
    ]
    body_md = "\n\n".join(
        sections[s] for s in section_order if sections.get(s)
    )
    if body_md:
        blocks = markdown_to_blocks(body_md)
        if blocks:
            append_blocks(page["id"], blocks)

    return page


def fire_slack(title: str, page: dict):
    notion_url = page.get("url", "https://notion.so")

    tag_ollie = f"<@{SLACK_USER_ID_OLLIE}>" if SLACK_USER_ID_OLLIE else "Ollie"
    tag_nicole = f"<@{SLACK_USER_ID_NICOLE}>" if SLACK_USER_ID_NICOLE else "Nicole"

    blocks = [
        section_block(
            f"*📝 New script ready for approval*\n"
            f"{tag_ollie} {tag_nicole} — please review and approve."
        ),
        divider_block(),
        section_block(f"*Script:* {title}"),
        divider_block(),
        button_block("Review Script in Notion →", notion_url),
    ]
    notify_content_pipeline(
        text=f"New script ready for approval: {title}",
        blocks=blocks,
    )


def main():
    print("=== Script Agent Starting ===")
    processed_ids = load_state()
    approved_ideas = get_approved_ideas()

    new_ideas = [p for p in approved_ideas if p["id"] not in processed_ids]
    print(f"Found {len(approved_ideas)} approved ideas, {len(new_ideas)} new to process.")

    if not new_ideas:
        print("No new approved ideas. Exiting.")
        return

    # Load research and competitor context once for all scripts this run
    research_text = ""
    research_page = get_latest_research_row()
    if research_page:
        research_text = get_page_text(research_page["id"])
        print(f"Research context loaded ({len(research_text)} chars).")

    competitor_analysis = get_latest_analysis()
    if competitor_analysis:
        print(f"Competitor context loaded ({len(competitor_analysis)} chars).")

    performance_insights = get_latest_performance_insights()
    if performance_insights:
        print(f"Performance insights loaded ({len(performance_insights)} chars).")
    else:
        print("No performance insights yet — scripts will generate without performance context.")

    for idea_page in new_ideas:
        idea_id = idea_page["id"]
        props = idea_page.get("properties", {})
        title_blocks = props.get("Name", {}).get("title", [])
        title = "".join(b.get("text", {}).get("content", "") for b in title_blocks)

        print(f"Processing: {title}")
        idea_context = extract_idea_context(idea_page)
        script = generate_script(idea_context, research_text, competitor_analysis, performance_insights)
        sections = parse_script_sections(script)

        script_page = write_to_notion(idea_page, sections)
        print(f"  Script written: {script_page.get('url')}")

        fire_slack(title, script_page)
        print(f"  Slack notification sent.")

        processed_ids.add(idea_id)
        save_state(processed_ids)

    print(f"=== Script Agent Done — processed {len(new_ideas)} ideas ===")


if __name__ == "__main__":
    main()
