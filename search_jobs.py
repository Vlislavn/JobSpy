"""
Ready-to-run job search for Business Analyst roles in Germany.

Usage:
    source .venv/bin/activate
    python search_jobs.py

Edit the CONFIG block below to change the search term, city, recency, etc.
Results are printed to the console and saved to jobs.csv (+ jobs.xlsx if openpyxl is installed).
"""

import csv
from datetime import datetime

from jobspy import scrape_jobs

# --------------------------- CONFIG ---------------------------
SEARCH_TERM = ""              # "" = any role / all vacancies
LOCATION = "Heidelberg, Germany"  # e.g. "Berlin, Germany", "Munich, Germany", or just "Germany"
COUNTRY_INDEED = "Germany"     # required for Indeed & Glassdoor
RESULTS_WANTED = 200          # per site (pull broad, then filter to the city)
HOURS_OLD = 24                # only jobs posted in the last N hours (24 = last day)
IS_REMOTE = False             # False = no remote filter (remote AND on-site returned)
DISTANCE = 10                 # LinkedIn search radius in miles (keep small for one city)

# Keep only jobs located in this city (LinkedIn searches a radius, not a single city).
# Set to "" to disable and keep the whole searched area.
CITY_ONLY = "Heidelberg"

# LinkedIn only — searches globally using LOCATION.
SITES = ["linkedin"]

# Google jobs needs a natural-language query (this is its only filter):
GOOGLE_SEARCH_TERM = "jobs in Heidelberg Germany since yesterday"
# --------------------------------------------------------------


def main() -> None:
    print(f"Searching '{SEARCH_TERM}' in {LOCATION} across {SITES} ...")
    jobs = scrape_jobs(
        site_name=SITES,
        search_term=SEARCH_TERM,
        google_search_term=GOOGLE_SEARCH_TERM,
        location=LOCATION,
        country_indeed=COUNTRY_INDEED,
        results_wanted=RESULTS_WANTED,
        hours_old=HOURS_OLD,
        is_remote=IS_REMOTE,
        distance=DISTANCE,
        linkedin_fetch_description=False,  # off: faster + avoids rate limits on large pulls
        description_format="markdown",
        verbose=1,
    )

    print(f"\nFound {len(jobs)} jobs in the searched area.")
    if len(jobs) == 0:
        print("No jobs returned. Try widening HOURS_OLD, changing LOCATION, or removing a site.")
        return

    # Keep only the target city (LinkedIn returns a commuting radius, not one city)
    if CITY_ONLY and "location" in jobs.columns:
        before = len(jobs)
        jobs = jobs[jobs["location"].fillna("").str.contains(CITY_ONLY, case=False)].reset_index(drop=True)
        print(f"Filtered to '{CITY_ONLY}': {len(jobs)} of {before} jobs.")
    if len(jobs) == 0:
        print(f"No jobs located in '{CITY_ONLY}' in the last {HOURS_OLD}h. Try a larger HOURS_OLD or DISTANCE.")
        return
    print()

    # Most recent first
    if "date_posted" in jobs.columns:
        jobs = jobs.sort_values("date_posted", ascending=False, na_position="last").reset_index(drop=True)

    # Show a compact preview
    preview_cols = [c for c in ["site", "title", "company", "location", "date_posted", "job_url"] if c in jobs.columns]
    with_preview = jobs[preview_cols].head(15)
    print(with_preview.to_string(index=False))

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    csv_path = f"jobs_{stamp}.csv"
    jobs.to_csv(csv_path, quoting=csv.QUOTE_NONNUMERIC, escapechar="\\", index=False)
    print(f"\nSaved {len(jobs)} jobs to {csv_path}")

    try:
        xlsx_path = f"jobs_{stamp}.xlsx"
        jobs.to_excel(xlsx_path, index=False)
        print(f"Saved {len(jobs)} jobs to {xlsx_path}")
    except Exception as e:  # openpyxl not installed or other issue — CSV is enough
        print(f"(Skipped Excel export: {e})")


if __name__ == "__main__":
    main()
