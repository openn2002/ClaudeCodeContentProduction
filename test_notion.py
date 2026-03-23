"""Quick diagnostic — run this to see what your Notion integration can access."""
import requests
from dotenv import load_dotenv
import os

load_dotenv(override=True)

KEY = os.getenv("NOTION_API_KEY")
HEADERS = {"Authorization": f"Bearer {KEY}", "Notion-Version": "2022-06-28"}

DB_IDS = {
    "Research":          "e3acb755-1822-4972-bc6d-afd43bdeb0ac",
    "Ideas":             "f10f7723-3b07-40bb-b102-a0f61c0c7cc7",
    "Script Library":    "328e1b43-3099-80f7-8757-c81031ad79df",
    "Content Calendar":  "328e1b43-3099-80b9-b663-ec69cbb84088",
    "Weekly Scorecard":  "73cc6247-1de2-4c16-987b-661fb05e32e1",
}

print(f"Using key: {KEY[:20]}...\n")

for name, db_id in DB_IDS.items():
    resp = requests.get(f"https://api.notion.com/v1/databases/{db_id}", headers=HEADERS)
    status = "✅ accessible" if resp.status_code == 200 else f"❌ {resp.status_code} — {resp.json().get('message','')}"
    print(f"{name}: {status}")
