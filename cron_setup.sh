#!/bin/bash
# cron_setup.sh
# Alternative to scheduler.py — add these lines to your crontab with: crontab -e
#
# All times are in AEST (UTC+10). If daylight saving is active (AEDT = UTC+11), adjust by -1hr.
#
# Replace /path/to/project and /path/to/python with your actual paths.
# Example: /Users/olliepenn/ClaudeCodeContentProduction

PROJECT=/Users/olliepenn/ClaudeCodeContentProduction
PYTHON=$PROJECT/.venv/bin/python
LOG=$PROJECT/logs

# Create logs dir if needed
mkdir -p $LOG

# ── Friday night pipeline ────────────────────────────────────────────────────

# Friday 22:00 AEST (12:00 UTC) — Research Agent (trends, industry news, GLP-1)
# 0 12 * * 5 $PYTHON $PROJECT/agents/research_agent.py >> $LOG/research_agent.log 2>&1

# Friday 22:30 AEST (12:30 UTC) — Competitor Agent (competitor content scan)
# 30 12 * * 5 $PYTHON $PROJECT/agents/competitor_agent.py >> $LOG/competitor_agent.log 2>&1

# Friday 23:00 AEST (13:00 UTC) — Performance Agent (refresh metrics + cumulative synthesis)
# 0 13 * * 5 $PYTHON $PROJECT/agents/performance_agent.py >> $LOG/performance_agent.log 2>&1

# ── Saturday morning ─────────────────────────────────────────────────────────

# Saturday 08:00 AEST (22:00 UTC Friday) — Video Idea Agent (reads all 3 fresh reports)
# 0 22 * * 5 $PYTHON $PROJECT/agents/video_idea_agent.py >> $LOG/video_idea_agent.log 2>&1

# ── Continuous ───────────────────────────────────────────────────────────────

# Every hour — Script Agent (polls for newly approved ideas)
# 0 * * * * $PYTHON $PROJECT/agents/script_agent.py >> $LOG/script_agent.log 2>&1

echo "Copy the cron lines above (remove the # prefix) into your crontab."
echo "Run: crontab -e"
