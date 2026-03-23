"""
Apify scraping wrapper for the research agent.
Pulls real, live content from TikTok, Instagram, YouTube, and Google Search.
"""

import os
from dotenv import load_dotenv
from apify_client import ApifyClient

load_dotenv(override=True)

APIFY_API_KEY = os.getenv("APIFY_API_KEY")

# Health/wellness hashtags and keywords to scrape
TIKTOK_KEYWORDS = [
    "weight loss", "GLP1", "ozempic", "wegovy", "CSIRO diet",
    "high protein diet", "gut health", "metabolic health", "dietitian",
    "healthy eating Australia", "weight loss tips"
]

INSTAGRAM_HASHTAGS = [
    "weightloss", "glp1", "ozempic", "healthyeating", "highprotein",
    "guthealth", "metabolichealth", "dietitian", "csirodiet", "australiandietitian"
]

YOUTUBE_KEYWORDS = [
    "GLP-1 weight loss 2025", "ozempic diet plan", "CSIRO diet results",
    "high protein weight loss", "gut health for weight loss",
    "weight loss over 50", "Mayo Clinic diet", "sustainable weight loss"
]

GOOGLE_KEYWORDS = [
    "GLP-1 medication Australia 2025",
    "ozempic side effects diet",
    "best diet for weight loss Australia",
    "CSIRO total wellbeing diet review",
    "Mayo Clinic diet review",
    "high protein diet weight loss",
    "weight loss program Australia",
    "gut health weight loss",
]

# Competitor accounts to monitor across platforms
COMPETITOR_KEYWORDS = [
    "weight watchers", "weightwatchers",
    "noom",
    "myfitnesspal",
    "juniper health",
    "28 by sam wood",
    "light and easy", "lite n easy",
    "the healthy mummy", "healthy mummy",
    "kic app", "keep it cleaner",
]

REDDIT_SUBREDDITS = [
    "loseit", "1200isplenty", "GLP1", "Ozempic", "WeightLoss",
    "AustralianDiet", "intermittentfasting", "HealthyFood"
]

TWITTER_KEYWORDS = [
    "GLP-1 weight loss", "ozempic diet", "CSIRO diet",
    "wegovy results", "weight loss Australia", "Mayo Clinic diet",
    "mounjaro weight loss", "high protein diet"
]


def _client() -> ApifyClient:
    return ApifyClient(APIFY_API_KEY)


def scrape_tiktok_trending(max_results: int = 50) -> list:
    """
    Scrape trending TikTok videos for health/wellness keywords in one actor run.
    Returns list of dicts with: text, views, likes, shares, comments, author, url
    """
    client = _client()
    results = []

    try:
        run_input = {
            "searchQueries": TIKTOK_KEYWORDS[:6],
            "maxResults": max_results,
            "resultType": "search",
            "shouldDownloadCovers": False,
            "shouldDownloadVideos": False,
        }
        run = client.actor("clockworks/tiktok-scraper").call(run_input=run_input)
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            # Handle both flat items and nested video arrays
            videos = item.get("videos") or item.get("items") or [item]
            for v in videos:
                if not isinstance(v, dict):
                    continue
                text = v.get("text") or v.get("desc") or v.get("caption") or ""
                views = v.get("playCount") or v.get("stats", {}).get("playCount") or 0
                likes = v.get("diggCount") or v.get("stats", {}).get("diggCount") or 0
                author_meta = v.get("authorMeta") or v.get("author") or {}
                author = author_meta.get("name") or author_meta.get("uniqueId") or ""
                url = v.get("webVideoUrl") or v.get("url") or ""
                if text or views:
                    results.append({
                        "platform": "TikTok",
                        "text": text[:500],
                        "views": views,
                        "likes": likes,
                        "shares": v.get("shareCount") or v.get("stats", {}).get("shareCount") or 0,
                        "comments": v.get("commentCount") or v.get("stats", {}).get("commentCount") or 0,
                        "author": author,
                        "url": url,
                    })
    except Exception as e:
        print(f"  TikTok scrape warning: {e}")

    return sorted(results, key=lambda x: x.get("views", 0), reverse=True)


def scrape_instagram_hashtags(max_results: int = 50) -> list:
    """
    Scrape Instagram posts/reels by hashtag in one actor run.
    Returns list with: caption, likes, comments, type, url
    """
    client = _client()
    results = []

    try:
        run_input = {
            "hashtags": INSTAGRAM_HASHTAGS[:8],
            "resultsLimit": max_results,
            "resultsType": "posts",
        }
        run = client.actor("apify/instagram-hashtag-scraper").call(run_input=run_input)
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            caption = item.get("caption") or item.get("text") or ""
            likes = item.get("likesCount") or item.get("likes") or 0
            comments = item.get("commentsCount") or item.get("comments") or 0
            hashtag = item.get("hashtag") or ""
            if caption or likes:
                results.append({
                    "platform": "Instagram",
                    "hashtag": hashtag,
                    "caption": caption[:500],
                    "likes": likes,
                    "comments": comments,
                    "type": item.get("type") or item.get("mediaType") or "",
                    "url": item.get("url") or item.get("shortCode") or "",
                    "timestamp": item.get("timestamp") or "",
                })
    except Exception as e:
        print(f"  Instagram scrape warning: {e}")

    return sorted(results, key=lambda x: x.get("likes", 0), reverse=True)


def scrape_youtube_trending(max_results: int = 20) -> list:
    """
    Scrape YouTube search results for health/wellness keywords.
    Returns list with: title, viewCount, likeCount, description, url, channelName
    """
    client = _client()
    results = []

    for keyword in YOUTUBE_KEYWORDS[:4]:
        try:
            run_input = {
                "searchKeywords": keyword,
                "maxResults": max_results // 4,
                "startUrls": [],
                "type": "video",
            }
            run = client.actor("apify/youtube-scraper").call(run_input=run_input)
            for item in client.dataset(run["defaultDatasetId"]).iterate_items():
                results.append({
                    "platform": "YouTube",
                    "keyword": keyword,
                    "title": item.get("title", ""),
                    "description": (item.get("description") or "")[:300],
                    "views": item.get("viewCount") or item.get("views") or 0,
                    "likes": item.get("likes") or 0,
                    "channel": item.get("channelName") or item.get("channel") or "",
                    "url": item.get("url") or item.get("videoUrl") or "",
                    "published": item.get("date") or item.get("publishedAt") or "",
                })
        except Exception as e:
            print(f"  YouTube scrape warning ({keyword}): {e}")

    return sorted(results, key=lambda x: x.get("views", 0), reverse=True)


def scrape_instagram_competitors(max_posts: int = 30) -> list:
    """
    Scrape Instagram posts mentioning competitor brands by keyword/hashtag.
    Returns list with: caption, likes, comments, type, url
    """
    client = _client()
    results = []

    # Use brand names as hashtags (no spaces, lowercase)
    hashtags = [kw.replace(" ", "").lower() for kw in COMPETITOR_KEYWORDS]
    # Deduplicate
    hashtags = list(dict.fromkeys(hashtags))

    try:
        run_input = {
            "hashtags": hashtags,
            "resultsLimit": max_posts,
            "resultsType": "posts",
        }
        run = client.actor("apify/instagram-hashtag-scraper").call(run_input=run_input)
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            caption = item.get("caption") or item.get("text") or ""
            likes = item.get("likesCount") or item.get("likes") or 0
            if caption or likes:
                results.append({
                    "platform": "Instagram (competitor)",
                    "hashtag": item.get("hashtag") or "",
                    "caption": caption[:500],
                    "likes": likes,
                    "comments": item.get("commentsCount") or item.get("comments") or 0,
                    "type": item.get("type") or item.get("mediaType") or "",
                    "url": item.get("url") or "",
                })
    except Exception as e:
        print(f"  Instagram competitor scrape warning: {e}")

    return sorted(results, key=lambda x: x.get("likes", 0), reverse=True)


def scrape_reddit(max_results: int = 30) -> list:
    """
    Scrape top posts from health/weight loss subreddits.
    Returns list with: subreddit, title, body, upvotes, comments, url
    """
    client = _client()
    results = []

    try:
        run_input = {
            "startUrls": [
                {"url": f"https://www.reddit.com/r/{sub}/hot/"}
                for sub in REDDIT_SUBREDDITS[:6]
            ],
            "maxItems": max_results,
            "includeComments": False,
        }
        run = client.actor("trudax/reddit-scraper").call(run_input=run_input)
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            title = item.get("title") or ""
            body = item.get("body") or item.get("text") or item.get("selftext") or ""
            if title:
                results.append({
                    "platform": "Reddit",
                    "subreddit": item.get("subreddit") or item.get("communityName") or "",
                    "title": title,
                    "body": body[:400],
                    "upvotes": item.get("upVotes") or item.get("score") or 0,
                    "comments": item.get("numberOfComments") or item.get("numComments") or 0,
                    "url": item.get("url") or "",
                })
    except Exception as e:
        print(f"  Reddit scrape warning: {e}")

    return sorted(results, key=lambda x: x.get("upvotes", 0), reverse=True)


def scrape_twitter(max_results: int = 30) -> list:
    """
    Scrape recent tweets for health/wellness keywords.
    Returns list with: text, likes, retweets, author, url
    """
    client = _client()
    results = []

    try:
        run_input = {
            "searchTerms": TWITTER_KEYWORDS[:5],
            "maxItems": max_results,
            "sort": "Latest",
        }
        run = client.actor("apidojo/tweet-scraper").call(run_input=run_input)
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            text = item.get("text") or item.get("fullText") or ""
            if text:
                results.append({
                    "platform": "Twitter/X",
                    "text": text[:500],
                    "likes": item.get("likeCount") or item.get("favorites") or 0,
                    "retweets": item.get("retweetCount") or item.get("retweets") or 0,
                    "author": item.get("author", {}).get("userName") or item.get("username") or "",
                    "url": item.get("url") or "",
                    "created": item.get("createdAt") or "",
                })
    except Exception as e:
        print(f"  Twitter scrape warning: {e}")

    return sorted(results, key=lambda x: x.get("likes", 0), reverse=True)


def scrape_google_search(max_results: int = 20) -> list:
    """
    Scrape Google search results for health/wellness keywords.
    Returns list with: title, description, url, position
    """
    client = _client()
    results = []

    for keyword in GOOGLE_KEYWORDS[:4]:
        try:
            run_input = {
                "queries": keyword,
                "maxPagesPerQuery": 1,
                "resultsPerPage": max_results // 4,
                "countryCode": "au",
                "languageCode": "en",
            }
            run = client.actor("apify/google-search-scraper").call(run_input=run_input)
            for item in client.dataset(run["defaultDatasetId"]).iterate_items():
                for result in item.get("organicResults", []):
                    results.append({
                        "platform": "Google",
                        "keyword": keyword,
                        "title": result.get("title", ""),
                        "description": result.get("description", "")[:300],
                        "url": result.get("url", ""),
                        "position": result.get("position", 0),
                    })
        except Exception as e:
            print(f"  Google scrape warning ({keyword}): {e}")

    return results


def format_for_prompt(data: dict) -> str:
    """Format all scraped data into a structured string to pass to Claude."""
    lines = []

    tiktok = data.get("tiktok", [])
    instagram = data.get("instagram", [])
    instagram_competitors = data.get("instagram_competitors", [])
    youtube = data.get("youtube", [])
    reddit = data.get("reddit", [])
    twitter = data.get("twitter", [])
    google = data.get("google", [])

    lines.append("## LIVE TIKTOK DATA — Trending Videos (Health/Wellness Keywords)")
    lines.append(f"Keywords searched: {', '.join(TIKTOK_KEYWORDS[:6])}\n")
    for i, v in enumerate(tiktok[:20], 1):
        lines.append(
            f"{i}. [{v['views']:,} views | {v['likes']:,} likes] @{v['author']}\n"
            f"   Caption: {v['text'][:200]}\n"
            f"   URL: {v['url']}"
        )

    lines.append("\n## LIVE INSTAGRAM DATA — Top Posts by Hashtag")
    lines.append(f"Hashtags: {', '.join(['#' + h for h in INSTAGRAM_HASHTAGS[:8]])}\n")
    for i, p in enumerate(instagram[:20], 1):
        lines.append(
            f"{i}. [{p['likes']:,} likes | {p['comments']:,} comments] #{p['hashtag']} — {p['type']}\n"
            f"   Caption: {p['caption'][:200]}"
        )

    if instagram_competitors:
        lines.append("\n## COMPETITOR INSTAGRAM — Recent Posts")
        lines.append(f"Accounts: {', '.join(COMPETITOR_ACCOUNTS_INSTAGRAM)}\n")
        for i, p in enumerate(instagram_competitors[:15], 1):
            lines.append(
                f"{i}. @{p['account']} [{p['likes']:,} likes] {p['type']}\n"
                f"   Caption: {p['caption'][:200]}"
            )

    lines.append("\n## LIVE YOUTUBE DATA — Top Videos by Search")
    for i, v in enumerate(youtube[:15], 1):
        lines.append(
            f"{i}. [{v['views']:,} views] {v['channel']} — \"{v['title']}\"\n"
            f"   {v['description'][:200]}"
        )

    if reddit:
        lines.append("\n## REDDIT — What People Are Asking & Discussing")
        lines.append(f"Subreddits: {', '.join(['r/' + s for s in REDDIT_SUBREDDITS[:6]])}\n")
        for i, p in enumerate(reddit[:20], 1):
            lines.append(
                f"{i}. r/{p['subreddit']} [{p['upvotes']:,} upvotes | {p['comments']:,} comments]\n"
                f"   \"{p['title']}\"\n"
                f"   {p['body'][:200]}"
            )

    if twitter:
        lines.append("\n## TWITTER/X — Real-Time Conversation")
        for i, t in enumerate(twitter[:15], 1):
            lines.append(
                f"{i}. @{t['author']} [{t['likes']:,} likes | {t['retweets']:,} RT]\n"
                f"   {t['text'][:250]}"
            )

    lines.append("\n## GOOGLE SEARCH — Top Results")
    for i, r in enumerate(google[:15], 1):
        lines.append(
            f"{i}. [{r['keyword']}] \"{r['title']}\"\n"
            f"   {r['description'][:200]}"
        )

    return "\n".join(lines)


def gather_all(verbose: bool = True) -> str:
    """Run all scrapers and return formatted string ready to pass to Claude."""

    if verbose:
        print("  Scraping TikTok (trending keywords)...")
    tiktok = scrape_tiktok_trending()
    if verbose:
        print(f"  → {len(tiktok)} TikTok videos")

    if verbose:
        print("  Scraping Instagram (hashtags)...")
    instagram = scrape_instagram_hashtags(max_results=30)
    if verbose:
        print(f"  → {len(instagram)} Instagram posts")

    if verbose:
        print("  Scraping Instagram (competitor accounts)...")
    instagram_competitors = scrape_instagram_competitors()
    if verbose:
        print(f"  → {len(instagram_competitors)} competitor posts")

    if verbose:
        print("  Scraping YouTube...")
    youtube = scrape_youtube_trending()
    if verbose:
        print(f"  → {len(youtube)} YouTube videos")

    if verbose:
        print("  Scraping Reddit...")
    reddit = scrape_reddit()
    if verbose:
        print(f"  → {len(reddit)} Reddit posts")

    if verbose:
        print("  Scraping Google Search...")
    google = scrape_google_search()
    if verbose:
        print(f"  → {len(google)} Google results")

    return format_for_prompt({
        "tiktok": tiktok,
        "instagram": instagram,
        "instagram_competitors": instagram_competitors,
        "youtube": youtube,
        "reddit": reddit,
        "twitter": [],
        "google": google,
    })
