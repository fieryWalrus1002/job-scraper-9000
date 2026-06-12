#!/usr/bin/env bash
export PATH="$HOME/.local/bin:$PATH"; cd "${JOB_SCRAPER_REPO:-$HOME/repos/job-scraper-9000}" && exec just run-overnight
