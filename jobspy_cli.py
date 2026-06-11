#!/usr/bin/env python3
"""
jobspy_cli.py — full-featured command-line interface over the JobSpy library.

Exposes every scrape_jobs() parameter plus extra post-processing (strict-city
filter, title include/exclude, dedup, sort, multi-format export).

Quick start:
    source .venv/bin/activate
    python jobspy_cli.py --help

Examples:
    # Business Analyst, Germany, Indeed + LinkedIn, last 3 days, save csv+xlsx
    python jobspy_cli.py -q "Business Analyst" -l "Germany" --country germany \
        --sites indeed,linkedin --hours-old 72 -n 100 --format all

    # Any role, strictly the city of Heidelberg, last 24h, LinkedIn only
    python jobspy_cli.py -l "Heidelberg, Germany" --sites linkedin \
        --hours-old 24 -n 200 --city-only Heidelberg

    # Remote full-time, with full LinkedIn descriptions, exclude internships
    python jobspy_cli.py -q "Data Engineer" -l "Berlin, Germany" --country germany \
        --remote --job-type fulltime --fetch-description --exclude Praktikum,Werkstudent

    # Use proxies and search Indeed with exact-match operators
    python jobspy_cli.py -q '"product manager" -senior' -l "Munich, Germany" \
        --country germany --sites indeed --proxies user:pass@host:port,localhost

    # Discover what's supported
    python jobspy_cli.py --list-sites
    python jobspy_cli.py --list-countries
    python jobspy_cli.py --list-job-types
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime

from jobspy import scrape_jobs
from jobspy.model import Country, JobType, Site

# Sites that actually accept a country (Indeed/Glassdoor); others are global/regional.
SUPPORTED_SITES = [s.value for s in Site]
JOB_TYPES = sorted({jt.value[0] for jt in JobType})
PREVIEW_COLS = ["site", "title", "company", "location", "date_posted",
                "job_type", "min_amount", "max_amount", "currency", "is_remote", "job_url"]


# --------------------------- discovery helpers ---------------------------
def list_sites() -> None:
    print("Supported sites (--sites):")
    for s in SUPPORTED_SITES:
        note = {
            "linkedin": "global, uses --location; rate-limits fast (use --proxies for big pulls)",
            "indeed": "best scraper, needs --country; supports advanced query operators",
            "glassdoor": "needs --country; often blocks without proxies",
            "google": "uses --google-search-term ONLY; needs very specific phrasing",
            "zip_recruiter": "US/Canada only, uses --location",
            "bayt": "international, uses --search-term only",
            "naukri": "India-focused; returns skills/experience fields",
            "bdjobs": "Bangladesh-focused",
        }.get(s, "")
        print(f"  {s:<14} {note}")


def list_countries() -> None:
    print("Supported --country values (for Indeed/Glassdoor). '*' = Glassdoor too.")
    rows = []
    for c in Country:
        if c in (Country.US_CANADA, Country.WORLDWIDE):
            continue
        name = c.value[0].split(",")[0]
        glassdoor = "*" if len(c.value) == 3 else " "
        rows.append(f"  {glassdoor} {name}")
    for r in sorted(rows):
        print(r)


def list_job_types() -> None:
    print("Supported --job-type values:")
    for jt in JOB_TYPES:
        print(f"  {jt}")


# --------------------------- arg parsing ---------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Full-featured CLI over the JobSpy scraping library.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Discovery (exit-early)
    d = p.add_argument_group("discovery (print and exit)")
    d.add_argument("--list-sites", action="store_true", help="list supported job boards and exit")
    d.add_argument("--list-countries", action="store_true", help="list supported countries and exit")
    d.add_argument("--list-job-types", action="store_true", help="list supported job types and exit")

    # Core search
    s = p.add_argument_group("search")
    s.add_argument("--sites", default="indeed,linkedin",
                   help="comma list: " + ",".join(SUPPORTED_SITES))
    s.add_argument("-q", "--search-term", default=None, help="keyword query ('' or omit = all roles)")
    s.add_argument("--google-search-term", default=None,
                   help="natural-language query used ONLY by the google site")
    s.add_argument("-l", "--location", default=None, help="e.g. 'Heidelberg, Germany'")
    s.add_argument("--country", default="usa",
                   help="country for Indeed/Glassdoor (see --list-countries)")
    s.add_argument("--distance", type=int, default=50, help="search radius in miles")
    s.add_argument("--remote", action="store_true", help="remote jobs only")
    s.add_argument("--job-type", default=None, choices=JOB_TYPES + [None],
                   help="filter by employment type")
    s.add_argument("--easy-apply", action="store_true", help="only board-hosted easy-apply jobs")
    s.add_argument("-n", "--results", type=int, default=50, help="results wanted per site")
    s.add_argument("--hours-old", type=int, default=None,
                   help="only jobs posted in the last N hours")
    s.add_argument("--offset", type=int, default=0, help="start from the Nth result")

    # LinkedIn extras
    li = p.add_argument_group("linkedin")
    li.add_argument("--fetch-description", action="store_true",
                    help="fetch full LinkedIn description + direct url (slower, O(n) requests)")
    li.add_argument("--company-ids", default=None,
                    help="comma list of LinkedIn company ids to restrict to")

    # Network / output
    o = p.add_argument_group("network & output")
    o.add_argument("--proxies", default=None,
                   help="comma list 'user:pass@host:port,localhost' (round-robined)")
    o.add_argument("--ca-cert", default=None, help="path to CA cert for proxies")
    o.add_argument("--user-agent", default=None, help="override default user agent")
    o.add_argument("--description-format", default="markdown",
                   choices=["markdown", "html", "plain"])
    o.add_argument("--enforce-annual-salary", action="store_true",
                   help="convert hourly/monthly wages to annual")
    o.add_argument("--verbose", type=int, default=1, choices=[0, 1, 2],
                   help="0=errors, 1=+warnings, 2=all")

    # Post-processing
    pp = p.add_argument_group("post-processing")
    pp.add_argument("--city-only", default=None,
                    help="keep only rows whose location contains this substring (case-insensitive)")
    pp.add_argument("--include", default=None,
                    help="keep only titles containing ANY of these comma terms")
    pp.add_argument("--exclude", default=None,
                    help="drop titles containing ANY of these comma terms")
    pp.add_argument("--dedup", action="store_true",
                    help="drop duplicate postings (by job_url)")
    pp.add_argument("--no-sort", action="store_true", help="do not sort by date posted")
    pp.add_argument("--preview", type=int, default=15, help="rows to print (0 = none)")

    # Export
    e = p.add_argument_group("export")
    e.add_argument("-o", "--output", default=None,
                   help="output base path (default: jobs_<timestamp>)")
    e.add_argument("--format", default="csv", choices=["csv", "xlsx", "json", "all", "none"],
                   help="export format(s)")

    return p


def _csv_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


# --------------------------- main ---------------------------
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_sites:
        list_sites(); return 0
    if args.list_countries:
        list_countries(); return 0
    if args.list_job_types:
        list_job_types(); return 0

    sites = _csv_list(args.sites) or []
    unknown = [s for s in sites if s not in SUPPORTED_SITES]
    if unknown:
        print(f"Unknown site(s): {unknown}. Valid: {SUPPORTED_SITES}", file=sys.stderr)
        return 2

    company_ids = None
    if args.company_ids:
        try:
            company_ids = [int(x) for x in _csv_list(args.company_ids)]
        except ValueError:
            print("--company-ids must be integers", file=sys.stderr)
            return 2

    print(f"Scraping {sites} | term={args.search_term!r} | location={args.location!r} "
          f"| country={args.country} | last={args.hours_old}h | n={args.results}/site ...")

    try:
        jobs = scrape_jobs(
            site_name=sites,
            search_term=args.search_term,
            google_search_term=args.google_search_term,
            location=args.location,
            distance=args.distance,
            is_remote=args.remote,
            job_type=args.job_type,
            easy_apply=args.easy_apply or None,
            results_wanted=args.results,
            country_indeed=args.country,
            proxies=_csv_list(args.proxies),
            ca_cert=args.ca_cert,
            description_format=args.description_format,
            linkedin_fetch_description=args.fetch_description,
            linkedin_company_ids=company_ids,
            offset=args.offset,
            hours_old=args.hours_old,
            enforce_annual_salary=args.enforce_annual_salary,
            verbose=args.verbose,
            user_agent=args.user_agent,
        )
    except ValueError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1

    print(f"\nFound {len(jobs)} jobs in the searched area.")
    if len(jobs) == 0:
        print("Nothing returned. Try a larger --hours-old/--distance, different --sites, or --proxies.")
        return 0

    # ---- post-processing ----
    if args.city_only and "location" in jobs.columns:
        before = len(jobs)
        jobs = jobs[jobs["location"].fillna("").str.contains(args.city_only, case=False)]
        print(f"city-only '{args.city_only}': kept {len(jobs)}/{before}")

    if args.include and "title" in jobs.columns:
        terms = _csv_list(args.include)
        before = len(jobs)
        mask = jobs["title"].fillna("").str.contains("|".join(terms), case=False, regex=True)
        jobs = jobs[mask]
        print(f"include {terms}: kept {len(jobs)}/{before}")

    if args.exclude and "title" in jobs.columns:
        terms = _csv_list(args.exclude)
        before = len(jobs)
        mask = ~jobs["title"].fillna("").str.contains("|".join(terms), case=False, regex=True)
        jobs = jobs[mask]
        print(f"exclude {terms}: kept {len(jobs)}/{before}")

    if args.dedup and "job_url" in jobs.columns:
        before = len(jobs)
        jobs = jobs.drop_duplicates(subset="job_url")
        print(f"dedup: kept {len(jobs)}/{before}")

    if not args.no_sort and "date_posted" in jobs.columns:
        jobs = jobs.sort_values("date_posted", ascending=False, na_position="last")

    jobs = jobs.reset_index(drop=True)

    if len(jobs) == 0:
        print("All jobs filtered out. Loosen --city-only/--include/--exclude.")
        return 0

    # ---- preview ----
    if args.preview > 0:
        cols = [c for c in PREVIEW_COLS if c in jobs.columns]
        print()
        print(jobs[cols].head(args.preview).to_string(index=False))

    # ---- export ----
    base = args.output or f"jobs_{datetime.now().strftime('%Y-%m-%d_%H%M')}"
    fmt = args.format
    if fmt == "none":
        print(f"\n{len(jobs)} jobs (not exported; --format none).")
        return 0

    wrote = []
    if fmt in ("csv", "all"):
        path = f"{base}.csv"
        jobs.to_csv(path, quoting=csv.QUOTE_NONNUMERIC, escapechar="\\", index=False)
        wrote.append(path)
    if fmt in ("xlsx", "all"):
        try:
            path = f"{base}.xlsx"
            jobs.to_excel(path, index=False)
            wrote.append(path)
        except Exception as e:
            print(f"(xlsx skipped: {e} — run `pip install openpyxl`)")
    if fmt in ("json", "all"):
        path = f"{base}.json"
        jobs.to_json(path, orient="records", date_format="iso", force_ascii=False, indent=2)
        wrote.append(path)

    print(f"\nSaved {len(jobs)} jobs to: " + ", ".join(wrote))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
