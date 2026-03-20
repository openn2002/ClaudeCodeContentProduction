"""
Scheduler — runs the pipeline on the defined cron schedule.

Schedule (all times AEST):
  - Friday  22:00  → research_agent
  - Saturday 08:00 → video_idea_agent
  - Hourly         → script_agent (polls for newly approved ideas)
  - Monday  08:00  → performance_agent

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


def run_video_ideas():
    run_agent("video_idea_agent.py")


def run_scripts():
    run_agent("script_agent.py")


def run_performance():
    run_agent("performance_agent.py")


# ---------------------------------------------------------------------------
# Schedule definitions
# ---------------------------------------------------------------------------

# Friday 22:00 AEST — research
schedule.every().friday.at("22:00").do(run_research)

# Saturday 08:00 AEST — video ideas (after research)
schedule.every().saturday.at("08:00").do(run_video_ideas)

# Every hour — script agent polls for newly approved ideas
schedule.every().hour.do(run_scripts)

# Monday 08:00 AEST — performance report
schedule.every().monday.at("08:00").do(run_performance)


if __name__ == "__main__":
    print("Scheduler running. Press Ctrl+C to stop.")
    print("Active jobs:")
    for job in schedule.get_jobs():
        print(f"  {job}")
    print()

    while True:
        schedule.run_pending()
        time.sleep(60)
