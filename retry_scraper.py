#!/usr/bin/env python3.10
"""Auto-retry wrapper: runs scraper.py --force, waits on failure, retries.

Each run picks up more geocode results from cache, so retries are progressively faster.
Cooldowns: 30 min → 45 min → 60 min between attempts.
"""
import subprocess, sys, time
from datetime import datetime

COOLDOWNS_MIN = [30, 45, 60]

def ts():
    return datetime.now().strftime("%H:%M:%S")

for attempt, cooldown_min in enumerate(COOLDOWNS_MIN + [None], start=1):
    print(f"\n{ts()} — Attempt {attempt} …")
    result = subprocess.run([sys.executable, "scraper.py", "--force"])
    if result.returncode == 0:
        print(f"\n{ts()} — Completed successfully on attempt {attempt}!")
        sys.exit(0)
    print(f"{ts()} — Scraper exited with code {result.returncode}.")
    if cooldown_min is None:
        print("Max retries reached.")
        sys.exit(1)
    print(f"{ts()} — Waiting {cooldown_min} min before retry (geocode cache builds up each run) …")
    time.sleep(cooldown_min * 60)

sys.exit(1)
