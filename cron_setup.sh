#!/bin/bash
# cron_setup.sh
# Alternative to scheduler.py — add these lines to your crontab with: crontab -e
#
# All times are in your system timezone. If your server is UTC, adjust accordingly.
# AEST = UTC+10  |  AEDT = UTC+11 (daylight saving)
#
# Replace /path/to/project and /path/to/python with your actual paths.
# Example: /Users/olliepenn/ClaudeCodeContentProduction

PROJECT=/Users/olliepenn/ClaudeCodeContentProduction
PYTHON=$PROJECT/.venv/bin/python
LOG=$PROJECT/logs

# Create logs dir if needed
mkdir -p $LOG

# Friday 22:00 AEST (12:00 UTC) — Research Agent
# 0 12 * * 5 $PYTHON $PROJECT/agents/research_agent.py >> $LOG/research_agent.log 2>&1

# Saturday 08:00 AEST (22:00 UTC Friday) — Video Idea Agent
# 0 22 * * 5 $PYTHON $PROJECT/agents/video_idea_agent.py >> $LOG/video_idea_agent.log 2>&1

# Every hour — Script Agent (polls for approved ideas)
# 0 * * * * $PYTHON $PROJECT/agents/script_agent.py >> $LOG/script_agent.log 2>&1

# Monday 08:00 AEST (22:00 UTC Sunday) — Performance Agent
# 0 22 * * 0 $PYTHON $PROJECT/agents/performance_agent.py >> $LOG/performance_agent.log 2>&1

echo "Copy the cron lines above (remove the # prefix) into your crontab."
echo "Run: crontab -e"
