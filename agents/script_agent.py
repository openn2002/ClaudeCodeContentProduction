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
    prop_select,
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
We are building the most credible, trustworthy voice in the Australian health and nutrition space. That means most of our content is purely educational or informational — it exists to genuinely help people, full stop. No agenda, no pitch, no product mention required.

Brand trust is built by being useful. If someone watches a video and thinks "that actually helped me", we've won — whether or not we mentioned the program. The commercial results follow from the trust, not the other way around.

**On product mentions:**
Many scripts should have zero product mention. That is not a failure — it is the point. A video about "3 ways to eat more protein on a budget" doesn't need to reference the program at all. It just needs to be genuinely good advice from a credible source.

When product mention is appropriate (e.g. the video is explicitly about the program, or a scientific claim needs backing), follow these rules:
- Default to "the program", "our plan", "our approach", or "we" — not the full name
- Use the full name "CSIRO Total Wellbeing Diet" at most once, only where it's contextually earned
- Never use it as a closing argument or a reason to sign up
- CSIRO is a credibility signal, not a sales pitch

**On CTAs:**
Do not force a product CTA at the end of every video. The closing moment should match the energy of the content:
- Educational content → soft community action (save this, share it, follow for more)
- Content that naturally leads somewhere → a relevant next step ("comment your go-to budget meal below")
- Explicitly product-focused content only → a product mention is appropriate
When in doubt, end with something that invites connection — not conversion.

Every script must be:
- Warm, direct, and genuinely useful — like advice from a knowledgeable friend
- Free from shame, fear-mongering, or miracle-cure framing
- Structured for short-form video (TikTok, Reels, YouTube Shorts) unless otherwise specified
- Grounded in real science where relevant — CSIRO research adds authority when cited naturally, not as decoration
- Informed by what hooks, formats, and caption styles are actually working right now (see context below)

You will be given:
1. The approved video idea (title, pillar, platform, source signal)
2. This week's research report — what topics are trending, what keywords matter, what platform formats are performing
3. Competitor analysis — what hooks competitors are using, what formats are winning, what gaps exist

Use inputs 2 and 3 to shape the hook style, script format, and caption — not just the idea itself.

For each idea, produce a script with these exact six sections in order:

## Creative Direction
Start with the specific opening action — what is the talent physically doing in the first 2 seconds that the viewer sees before a single word is spoken? This is the visual hook: it should immediately signal what the video is about and make someone stop scrolling. Be concrete and specific. "Someone closes the fridge" is not enough — "hand reaches into an open fridge, pulls out leftover pasta, eats it standing up in the dark kitchen at 10pm" is. Think: caught in the act, relatable moment, something people recognise from their own lives.

Then briefly cover: who the talent is, tone and energy, setting, and whether it's raw/handheld or slightly more composed. Keep it to 3–4 sentences total. This is a filming brief, not a shot list.

## Hook
Three hook options, each one designed to stop the scroll. A great hook has two components that work together: a **visual hook** (what the viewer sees) and a **spoken hook** (what they hear). On TikTok and Reels, many viewers watch on mute or decide to keep watching before they've heard a word — the visual must earn attention on its own, and the spoken line must reward it.

For each option write:
- **Option [A/B/C]:** Hook style in a few words (e.g. "caught in the act", "myth-bust", "surprising stat", "relatable POV")
- **Visual hook:** What is happening on screen in the first 2 seconds — the specific action or image that stops the scroll
- **Spoken line:** The exact words — punchy, direct, under 10 seconds when read aloud. Lead with tension, a relatable behaviour, a surprising fact, or a direct call-out. The science or payoff comes after the hook earns attention, not before.

The visual and spoken hooks should complement each other — the visual sets up the tension, the spoken line names it or twists it.

The hook style should match the content pillar — use these as a guide:

- **Science & Credibility** — visual: something unexpected or counterintuitive on screen (a food label, a surprising comparison). Spoken: lead with the surprising fact or myth-bust. "You're not lazy. You're just eating lunch at the wrong time." / "This one habit has more impact on weight loss than the food you eat."

- **Weight Loss Results** — visual: a relatable "before" moment — someone looking frustrated at the scale, staring at the wardrobe. Spoken: the struggle or the social proof. "Most people quit their diet by week 3. Here's the one thing that changes that." / "She lost 12kg without ever feeling hungry. Here's what she did differently."

- **Nutrition & Meal Planning** — visual: a grocery receipt, a fridge full of cheap ingredients, a budget meal being prepped. Spoken: the practical problem or counterintuitive tip. "Eating healthy doesn't have to cost more — here's proof." / "The cheapest protein sources nutritionists actually recommend."

- **Habit & Behaviour Change** — visual: caught in the act — hand in the chip bag, closing the fridge at night, phone in hand at 11pm instead of sleeping. Spoken: the relatable failure or the "it's not your fault" reframe. "Raiding the fridge every night? Science finally explains why your healthy habits fall apart after 8pm." / "The reason you keep falling off your diet has nothing to do with motivation."

- **GLP-1 & Medication Support** — visual: someone reading a prescription, or a question appearing on screen. Spoken: the question people are scared to ask, the myth, or "what no one tells you". "Going on GLP-1 medication? Here's what most people aren't told about nutrition." / "The one thing that makes GLP-1 medication actually work long-term."

- **Exercise & Movement** — visual: someone doing something low-effort and accessible — a walk, stretching at a desk. Spoken: the low-barrier entry point or the challenge to the "exercise has to be hard" assumption. "You don't need the gym. You need 10 minutes and this." / "The most underrated form of exercise for weight loss — and you're probably already doing it."

- **Promotion & Offers** — visual: the offer on screen, a countdown, or social proof (member testimonials). Spoken: urgency, value, or proof. "Our biggest offer of the year is live — and it closes Sunday." / "Thousands of Australians started their health journey this month. Here's why."

- **People & Community** — visual: a relatable human moment with no staging — messy kitchen, sad desk lunch, Sunday meal prep chaos. Spoken: a POV, a self-aware observation, or something that makes people think "that's literally me". Humour and self-awareness work better here than science. "POV: it's 6pm and you have no idea what's for dinner again." / "When you meal prep on Sunday and eat it all by Tuesday 😅"

For People & Community content especially, don't force a credibility angle where a human moment works better.

## Script Outline
Scene-by-scene breakdown with rough timing (e.g. 0:00–0:10). For each scene, write the spoken content only — what the talent actually says. Do not include visual directions or on-screen text notes inside this section; those belong in Creative Direction and Key On-Screen Text respectively.

The final scene is the closing moment. It should feel like a natural end to this specific video — not a generic sign-off. Choose whichever of the following fits the content, pillar, and tone:

- **Loop back to the hook** — if the hook posed a question or tension, resolve it and close the loop
- **Participation prompt** — invite the audience into a conversation ("Drop your go-to budget meal below", "What's one swap you're making this week?")
- **Save or share** — when the content is reference-worthy ("Save this for your next grocery shop", "Share this with someone who needs it")
- **Follow for more** — when the video naturally leads somewhere ("Follow for more evidence-based tips like this")
- **Soft curiosity** — when there's a natural next step ("We go deeper on this — link in bio")
- **Community signal** — when it fits organically ("Our members do this every week")

Only include a product reference in the closing if the entire video has been about the program. Do not manufacture a reason to mention it.

## Key On-Screen Text
Bullet list of every text overlay that appears throughout the video, in order. Keep each one short — these are the words that flash on screen to reinforce or punctuate what's being said.

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
        "Creative Direction": extract(script, "Creative Direction", ["Hook", "Script Outline", "Key On-Screen", "Caption"]),
        "Hook": extract(script, "Hook", ["Script Outline", "Key On-Screen", "Caption", "Creative"]),
        "Script Outline": extract(script, "Script Outline", ["Key On-Screen", "Caption", "Hook", "Creative"]),
        "Key On-Screen Text": extract(script, "Key On-Screen", ["Caption", "Hook", "Script", "Creative"]),
        "Caption": extract(script, "Caption", ["Hook", "Script", "Key", "Creative"]),
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

    # Extract pillar and priority from the source idea page
    pillar_sel = props.get("Pillar", {}).get("select") or {}
    pillar = pillar_sel.get("name", "")
    priority_sel = props.get("Priority", {}).get("select") or {}
    priority = priority_sel.get("name", "")

    # Create the page — Caption as property for quick copying, Pillar + Priority for filtering
    page_props = {
        "Name": prop_title(title),
        "Agent Generated": prop_checkbox(True),
        "Science Approved": prop_checkbox(False),
        "Approved for filming": prop_checkbox(False),
        "Caption": prop_rich_text(sections.get("Caption", "")[:2000]),
    }
    if pillar:
        page_props["Pillar"] = prop_select(pillar)
    if priority:
        page_props["Priority"] = prop_select(priority)

    page = create_page(DB_SCRIPT_LIBRARY, page_props)

    # Build the full script as page body blocks for proper formatting
    section_order = [
        "Creative Direction",
        "Hook",
        "Script Outline",
        "Key On-Screen Text",
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
