#!/usr/bin/env bash
# I don't want to stay up late, but I want to run this in the early morning.
# BOOM! Automation.
# Use the at command to run it:
# at 12:05 AM -f scripts/run_overnight.sh

# Exit immediately if any command fails
set -e

# Change directory to your exact project root
cd "$HOME/repos/job-scraper-9000"

# Explicitly pull in your shell environment so 'uv' can be found by the system daemon
export PATH="$HOME/.local/bin:$PATH"

# Resolve the dynamic execution date
RUN_DATE=$(date +%F)

# Ensure a local logs directory exists
mkdir -p logs

# Define our log file path
LOG_FILE="logs/pipeline_${RUN_DATE}.log"

# ==============================================================================
# SAFE REDIRECTION BLOCK
# Synchronously append stdout (1) and stderr (2) straight to the file.
# No background process pipelines or subshells for atd to kill early.
# ==============================================================================
exec >> "$LOG_FILE" 2>&1

# Log the starting timestamp
echo "=== Pipeline started at $(date) ==="
echo "Logging output to $LOG_FILE"
echo "Target Run Date: $RUN_DATE"
printenv | grep -E 'PATH|HOME|USER' # Good for tracking down daemon environment quirks

uv run job-scraper-9000 run-config config/search.yml --save --run-date "$RUN_DATE"
uv run job-scraper-9000 prefilter --run-date "$RUN_DATE"
uv run job-scraper-9000 remote-filter --run-date "$RUN_DATE"
uv run job-scraper-9000 skills-fit --run-date "$RUN_DATE"

uv run scripts/db_ingest.py --run-date "$RUN_DATE"

echo "=== Pipeline finished successfully at $(date) ==="
