"""
Scheduler — runs the pipeline on the defined cron schedule.

Schedule (all times AEST):
  - Friday  22:00  → research_agent       (trends, industry news, GLP-1)
  - Friday  22:30  → competitor_agent     (competitor content scan)
  - Friday  23:00  → performance_agent    (refresh metrics + cumulative synthesis)
  - Saturday 08:00 → video_idea_agent     (reads all 3 fresh reports)
  - Hourly         → script_agent         (polls for newly approved ideas)

Usage:
  python scheduler.py

Keep this process running (e.g. via screen, tmux, or a system service).
Alternatively, use the system cron commands in cron_setup.sh.
"""

import schedule
import time
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
PYTHON = sys.executable


def run_agent(agent_file: str):
    """Run an agent script as a subprocess."""
    path = BASE_DIR / "agents" / agent_file
    print(f"[scheduler] Running {agent_file}...")
    result = subprocess.run([PYTHON, str(path)], capture_output=False)
    if result.returncode != 0:
        print(f"[scheduler] WARNING: {agent_file} exited with code {result.returncode}")
    else:
        print(f"[scheduler] {agent_file} completed successfully.")


def run_research():
    run_agent("research_agent.py")


def run_competitor_analysis():
    run_agent("competitor_agent.py")


def run_video_ideas():
    run_agent("video_idea_agent.py")


def run_scripts():
    run_agent("script_agent.py")


def run_performance():
    run_agent("performance_agent.py")


# ---------------------------------------------------------------------------
# Schedule definitions
# ---------------------------------------------------------------------------

# Friday 22:00 AEST — research (trends, industry news, GLP-1)
schedule.every().friday.at("22:00").do(run_research)

# Friday 22:30 AEST — competitor analysis (30 mins after research)
schedule.every().friday.at("22:30").do(run_competitor_analysis)

# Friday 23:00 AEST — performance analysis (refreshes metrics + cumulative synthesis)
schedule.every().friday.at("23:00").do(run_performance)

# Saturday 08:00 AEST — video ideas (reads all 3 fresh reports from Friday night)
schedule.every().saturday.at("08:00").do(run_video_ideas)

# Every hour — script agent polls for newly approved ideas
schedule.every().hour.do(run_scripts)


if __name__ == "__main__":
    print("Scheduler running. Press Ctrl+C to stop.")
    print("Active jobs:")
    for job in schedule.get_jobs():
        print(f"  {job}")
    print()

    while True:
        schedule.run_pending()
        time.sleep(60)
