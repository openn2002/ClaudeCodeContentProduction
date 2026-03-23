"""
Competitor Agent — runs Friday night after research_agent.

Workflow:
1. Uses Apify to scrape competitor accounts across TikTok, Instagram
2. Also uses Reddit, Twitter/X for audience conversation signals
3. Runs Claude with competitor-social-analyst prompt to extract:
   - Top hook styles per competitor
   - Best-performing formats
   - Winning topics & themes
   - Content gaps Digital Wellness can exploit
4. Saves analysis to reports/competitor-analysis-[date].md
5. Returns analysis string for video_idea_agent to consume
"""

import os
import sys
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.notion import DB_RESEARCH, create_page, append_blocks, prop_title, prop_select, prop_checkbox, prop_date
from lib.slack import notify_content_pipeline, section_block, divider_block, button_block
from lib.apify import (
    scrape_instagram_competitors,
    scrape_tiktok_trending,
    scrape_reddit,
    scrape_twitter,
    COMPETITOR_KEYWORDS,
)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
REPORTS_DIR = Path(__file__).parent.parent / "reports"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8096

COMPETITORS = [
    "Noom", "Weight Watchers", "Light & Easy", "Juniper",
    "28 by Sam Wood", "MyFitnessPal", "The Healthy Mummy", "KIC (Keep It Cleaner)"
]


def load_system_prompt() -> str:
    return (PROMPTS_DIR / "competitor_social_analyst.md").read_text()


def format_competitor_data(
    instagram_posts: list,
    tiktok_posts: list,
    reddit_posts: list,
    twitter_posts: list,
) -> str:
    lines = []

    lines.append("# LIVE COMPETITOR & AUDIENCE DATA")
    lines.append(f"Date: {date.today().isoformat()}")
    lines.append(f"Competitors monitored: {', '.join(COMPETITORS)}\n")

    # Competitor Instagram
    lines.append("## COMPETITOR INSTAGRAM POSTS")
    lines.append(f"Keywords monitored: {', '.join(COMPETITOR_KEYWORDS)}\n")
    if instagram_posts:
        for i, p in enumerate(instagram_posts[:25], 1):
            lines.append(
                f"{i}. #{p['hashtag']} | {p['type']} | "
                f"{p['likes']:,} likes | {p['comments']:,} comments\n"
                f"   Caption: {p['caption'][:300]}\n"
                f"   URL: {p['url']}"
            )
    else:
        lines.append("No Instagram competitor data retrieved.")

    # Competitor TikTok — filter for competitor-related content
    competitor_tiktoks = [
        v for v in tiktok_posts
        if any(kw in (v.get("author", "") + v.get("text", "")).lower()
               for kw in COMPETITOR_KEYWORDS)
    ]

    lines.append("\n## COMPETITOR TIKTOK CONTENT")
    if competitor_tiktoks:
        for i, v in enumerate(competitor_tiktoks[:15], 1):
            lines.append(
                f"{i}. @{v['author']} | {v['views']:,} views | {v['likes']:,} likes\n"
                f"   Hook/Caption: {v['text'][:300]}\n"
                f"   URL: {v['url']}"
            )
    else:
        lines.append("No direct competitor TikTok accounts found in results.")
        lines.append("Top health/wellness TikToks (proxy for competitive landscape):")
        for i, v in enumerate(tiktok_posts[:10], 1):
            lines.append(
                f"{i}. @{v['author']} | {v['views']:,} views\n"
                f"   {v['text'][:200]}"
            )

    # Reddit — what the audience is actually saying
    lines.append("\n## REDDIT — AUDIENCE CONVERSATIONS (What people are asking/frustrated by)")
    if reddit_posts:
        for i, p in enumerate(reddit_posts[:20], 1):
            lines.append(
                f"{i}. r/{p['subreddit']} | {p['upvotes']:,} upvotes | {p['comments']:,} comments\n"
                f"   \"{p['title']}\"\n"
                f"   {p['body'][:250]}"
            )
    else:
        lines.append("No Reddit data retrieved.")

    # Twitter/X
    lines.append("\n## TWITTER/X — REAL-TIME CONVERSATION")
    if twitter_posts:
        for i, t in enumerate(twitter_posts[:15], 1):
            lines.append(
                f"{i}. @{t['author']} | {t['likes']:,} likes | {t['retweets']:,} RT\n"
                f"   {t['text'][:300]}"
            )
    else:
        lines.append("No Twitter/X data retrieved.")

    return "\n".join(lines)


def run_competitor_analysis(competitor_data: str) -> str:
    """Run Claude with competitor-social-analyst prompt to generate structured analysis."""
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    system_prompt = load_system_prompt()

    user_message = (
        f"Today is {date.today().isoformat()}.\n\n"
        "Below is live scraped data from competitor social media accounts and "
        "audience conversations. Please analyse this data and produce a full "
        "competitor intelligence report.\n\n"
        "Focus especially on:\n"
        "- The top 5 hook styles that appear in highest-engagement posts\n"
        "- Which content formats are outperforming (video length, style, format)\n"
        "- Which topics/pain points are generating the most engagement\n"
        "- What content gaps exist that Digital Wellness (CSIRO/Mayo Clinic) could own\n"
        "- What audience frustrations/questions are not being answered well by competitors\n\n"
        "This analysis will be fed directly into our video idea generation agent, "
        "so make it as specific and actionable as possible.\n\n"
        "---\n\n"
        f"{competitor_data}"
    )

    print("Running competitor analysis with Claude...")
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


def save_analysis(analysis: str) -> Path:
    """Save competitor analysis to reports/ folder."""
    REPORTS_DIR.mkdir(exist_ok=True)
    filename = REPORTS_DIR / f"competitor-analysis-{date.today().isoformat()}.md"
    filename.write_text(analysis)
    return filename


def write_to_notion(analysis: str) -> dict:
    """Write competitor analysis report as a page in the Research DB."""
    from datetime import timedelta
    from agents.research_agent import markdown_to_blocks
    today = date.today()
    next_monday = today + timedelta(days=(7 - today.weekday()))
    next_sunday = next_monday + timedelta(days=6)

    blocks = markdown_to_blocks(analysis)
    page = create_page(
        DB_RESEARCH,
        {
            "Name": prop_title(f"Competitor Analysis — {today.isoformat()}"),
            "Content Week": prop_date(str(next_monday), str(next_sunday)),
            "Market": prop_select("Australia"),
            "Type": prop_select("Competitor Analysis"),
            "Status": prop_select("New"),
            "Agent Generated": prop_checkbox(True),
        },
        children=blocks[:100],
    )
    if len(blocks) > 100:
        append_blocks(page["id"], blocks[100:])
    return page


def get_latest_analysis() -> str:
    """Load the most recent competitor analysis file."""
    if not REPORTS_DIR.exists():
        return ""
    files = sorted(REPORTS_DIR.glob("competitor-analysis-*.md"), reverse=True)
    if not files:
        return ""
    return files[0].read_text()


def main():
    print("=== Competitor Agent Starting ===")

    print("Scraping competitor Instagram accounts...")
    instagram_posts = scrape_instagram_competitors(max_posts=15)
    print(f"  → {len(instagram_posts)} competitor Instagram posts")

    print("Scraping TikTok for competitor/industry signals...")
    tiktok_posts = scrape_tiktok_trending(max_results=40)
    print(f"  → {len(tiktok_posts)} TikTok videos")

    print("Scraping Reddit for audience conversations...")
    reddit_posts = scrape_reddit(max_results=30)
    print(f"  → {len(reddit_posts)} Reddit posts")

    print("Scraping Twitter/X...")
    twitter_posts = scrape_twitter(max_results=30)
    print(f"  → {len(twitter_posts)} tweets")

    competitor_data = format_competitor_data(
        instagram_posts, tiktok_posts, reddit_posts, twitter_posts
    )
    print(f"Competitor data compiled ({len(competitor_data)} chars).")

    analysis = run_competitor_analysis(competitor_data)
    print(f"Analysis generated ({len(analysis)} chars).")

    report_path = save_analysis(analysis)
    print(f"Saved to: {report_path}")

    page = write_to_notion(analysis)
    print(f"Notion row created: {page.get('url')}")

    print("=== Competitor Agent Done ===")
    return analysis


if __name__ == "__main__":
    main()
