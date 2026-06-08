#!/usr/bin/env python3
"""Fetch Jennifer Sun's Google Scholar publications and keep papers
with at least one other SunLab member as co-author."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PEOPLE_PATH = ROOT / "_data" / "people.yml"
SCHOLAR_PATH = ROOT / "_data" / "scholar.yml"
CACHE_PATH = ROOT / "bib" / ".scholar_cache.json"
OUTPUT_PATH = ROOT / "bib" / "pubs.bib"
FACULTY_KEY = "profx"


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def normalize_display_name(name: str) -> str:
    return re.sub(r"^Dr\.?\s+", "", name).strip()


def person_matchers(person: dict) -> list[tuple[str, str]]:
    """Return (first_name, last_name) pairs used to match author strings."""
    matchers: list[tuple[str, str]] = []
    display = normalize_display_name(person.get("display_name", ""))
    parts = display.split()
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        matchers.append((first, last))

    for alias in person.get("bib_names", []) or []:
        alias = alias.strip()
        if "," in alias:
            last, first = [part.strip() for part in alias.split(",", 1)]
            if first and last:
                matchers.append((first.split()[0], last))
        else:
            alias_parts = alias.split()
            if len(alias_parts) >= 2:
                matchers.append((alias_parts[0], alias_parts[-1]))

    deduped: list[tuple[str, str]] = []
    seen = set()
    for first, last in matchers:
        key = (first.lower(), last.lower())
        if key not in seen:
            seen.add(key)
            deduped.append((first, last))
    return deduped


def split_authors(author_field: str) -> list[str]:
    if not author_field:
        return []
    authors = re.split(r"\s+and\s+", author_field)
    return [author.strip() for author in authors if author.strip()]


def author_matches(author: str, first: str, last: str) -> bool:
    text = author.strip()
    if not text:
        return False

    first_l = first.lower()
    last_l = last.lower()

    if "," in text:
        last_name, given_names = [part.strip().lower() for part in text.split(",", 1)]
        if last_name != last_l:
            return False
        given = given_names.split()
        if not given:
            return False
        return given[0] == first_l or given[0].startswith(first_l)

    words = text.lower().split()
    if len(words) < 2 or words[-1] != last_l:
        return False

    given = words[0]
    return given == first_l or given.startswith(first_l)


def person_in_authors(author_field: str, matchers: list[tuple[str, str]]) -> bool:
    authors = split_authors(author_field)
    return any(
        author_matches(author, first, last)
        for author in authors
        for first, last in matchers
    )


def load_lab_roster() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    people = load_yaml(PEOPLE_PATH)
    faculty_matchers: list[tuple[str, str]] = []
    lab_matchers: list[tuple[str, str]] = []

    for key, person in people.items():
        matchers = person_matchers(person)
        if not matchers:
            continue
        if key == FACULTY_KEY:
            faculty_matchers.extend(matchers)
        else:
            lab_matchers.extend(matchers)

    if not faculty_matchers:
        raise RuntimeError(f"No faculty matchers found for key '{FACULTY_KEY}'.")

    return faculty_matchers, lab_matchers


def should_include(author_field: str, faculty_matchers, lab_matchers) -> bool:
    has_faculty = person_in_authors(author_field, faculty_matchers)
    has_lab_member = person_in_authors(author_field, lab_matchers)
    return has_faculty and has_lab_member


def cache_is_fresh(config: dict) -> bool:
    if not CACHE_PATH.exists():
        return False
    max_age_days = int(config.get("cache_max_age_days", 7))
    age_seconds = time.time() - CACHE_PATH.stat().st_mtime
    return age_seconds < max_age_days * 86400


def load_cache() -> list[dict]:
    with CACHE_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("publications", [])


def save_cache(publications: list[dict], scholar_id: str) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scholar_id": scholar_id,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "publications": publications,
    }
    with CACHE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def fetch_publications(scholar_id: str) -> list[dict]:
    try:
        from scholarly import scholarly
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'scholarly'. Run: python3 -m venv .venv && "
            ".venv/bin/pip install -r requirements.txt"
        ) from exc

    print(f"Fetching publications from Google Scholar ({scholar_id})...")
    author = scholarly.search_author_id(scholar_id)
    scholarly.fill(author, sections=["publications"])

    publications: list[dict] = []
    total = len(author.get("publications", []))
    for index, publication in enumerate(author["publications"], start=1):
        scholarly.fill(publication)
        bib = publication.get("bib", {})
        publications.append(
            {
                "bib": bib,
                "scholar_id": publication.get("author_pub_id", ""),
                "pub_url": publication.get("pub_url", ""),
                "num_citations": publication.get("num_citations", 0),
            }
        )
        title = bib.get("title", "(untitled)")
        print(f"  [{index}/{total}] {title[:70]}")

    return publications


def make_cite_key(bib: dict, index: int) -> str:
    for field in ("cite_id", "pub_id"):
        if bib.get(field):
            return re.sub(r"[^a-zA-Z0-9:_-]", "", str(bib[field]))

    authors = split_authors(bib.get("author", ""))
    first_author = authors[0] if authors else "unknown"
    last_name = first_author.split()[-1].lower()
    year = bib.get("year") or bib.get("pub_year") or "unknown"
    title_word = re.sub(r"[^a-z]", "", bib.get("title", "paper").split()[0].lower())
    return f"{last_name}{year}{title_word}{index}"


def bib_field(key: str, value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, int):
        value = str(value)
    value = str(value).strip()
    if not value:
        return ""
    return f"  {key} = {{{value}}}"


def publication_year(bib: dict) -> int | None:
    for field in ("year", "pub_year"):
        if bib.get(field):
            return int(bib[field])

    for field in ("booktitle", "journal", "citation"):
        value = bib.get(field, "")
        match = re.search(r"(20\d{2})", str(value))
        if match:
            return int(match.group(1))
    return None


def normalize_title(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", title.lower())
    return cleaned


def paper_url(bib: dict, pub_url: str = "") -> str | None:
    if bib.get("url"):
        return bib["url"]
    if pub_url:
        return pub_url
    if bib.get("doi"):
        return f"https://doi.org/{bib['doi']}"
    if bib.get("eprint"):
        return f"https://arxiv.org/abs/{bib['eprint']}"

    for field in ("journal", "citation"):
        value = str(bib.get(field, ""))
        match = re.search(r"arXiv:([\d.]+)", value, re.IGNORECASE)
        if match:
            return f"https://arxiv.org/abs/{match.group(1)}"
    return None


def scholar_citation_url(citation_id: str, faculty_scholar_id: str) -> str | None:
    if not citation_id or not faculty_scholar_id:
        return None
    return (
        "https://scholar.google.com/citations?"
        f"view_op=view_citation&hl=en&user={faculty_scholar_id}"
        f"&citation_for_view={citation_id}"
    )


def enrich_bib(
    bib: dict,
    publication: dict,
    faculty_scholar_id: str,
) -> dict:
    enriched = dict(bib)
    link = paper_url(enriched, publication.get("pub_url", ""))
    if link:
        enriched["url"] = link

    scholar_link = scholar_citation_url(
        publication.get("scholar_id", ""),
        faculty_scholar_id,
    )
    if scholar_link:
        enriched["google_scholar_url"] = scholar_link
    return enriched


def to_bibtex_entry(key: str, bib: dict) -> str:
    if bib.get("conference") or bib.get("booktitle"):
        entry_type = "inproceedings"
        venue_key = "booktitle"
        venue_value = bib.get("booktitle") or bib.get("conference")
    else:
        entry_type = "article"
        venue_key = "journal"
        venue_value = bib.get("journal") or bib.get("citation")

    year = bib.get("year") or bib.get("pub_year") or publication_year(bib)
    fields = [
        bib_field("title", bib.get("title")),
        bib_field("author", bib.get("author")),
        bib_field("year", year),
        bib_field(venue_key, venue_value),
        bib_field("volume", bib.get("volume")),
        bib_field("number", bib.get("number")),
        bib_field("pages", bib.get("pages")),
        bib_field("doi", bib.get("doi")),
        bib_field("url", bib.get("url")),
        bib_field("google_scholar_url", bib.get("google_scholar_url")),
        bib_field("eprint", bib.get("eprint")),
        bib_field("archiveprefix", bib.get("archiveprefix")),
        bib_field("primaryclass", bib.get("primaryclass")),
    ]
    fields = [field for field in fields if field]
    body = ",\n".join(fields)
    return f"@{entry_type}{{{key},\n{body}\n}}"


def write_publications(
    publications: list[dict],
    faculty_matchers,
    lab_matchers,
    faculty_scholar_id: str,
) -> int:
    selected_by_title: dict[str, tuple[int, str, dict]] = {}

    for index, publication in enumerate(publications):
        bib = publication.get("bib", {})
        author_field = bib.get("author", "")
        title = bib.get("title", "")
        year = publication_year(bib)

        if not title or not year:
            continue
        if not should_include(author_field, faculty_matchers, lab_matchers):
            continue

        key = make_cite_key(bib, index)
        normalized = normalize_title(title)
        enriched = enrich_bib(bib, publication, faculty_scholar_id)
        current = selected_by_title.get(normalized)
        if current is None or year > current[0]:
            selected_by_title[normalized] = (year, key, enriched)

    selected = sorted(selected_by_title.values(), key=lambda item: (-item[0], item[1]))
    entries = [to_bibtex_entry(key, bib) for _, key, bib in selected]
    header = (
        "% Auto-generated by scripts/update_pubs.py\n"
        "% Papers where Jennifer Sun and at least one SunLab member are co-authors.\n"
        "% Re-generate with: make update-pubs\n\n"
    )
    OUTPUT_PATH.write_text(header + "\n\n".join(entries) + "\n", encoding="utf-8")
    return len(selected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force a fresh fetch from Google Scholar (ignores cache).",
    )
    args = parser.parse_args()

    config = load_yaml(SCHOLAR_PATH)
    scholar_id = config.get("scholar_id")
    if not scholar_id:
        print("Missing scholar_id in _data/scholar.yml", file=sys.stderr)
        return 1

    faculty_matchers, lab_matchers = load_lab_roster()

    if args.refresh or not cache_is_fresh(config):
        publications = fetch_publications(scholar_id)
        save_cache(publications, scholar_id)
    else:
        print(f"Using cached Scholar data from {CACHE_PATH.name}.")
        publications = load_cache()

    count = write_publications(
        publications,
        faculty_matchers,
        lab_matchers,
        scholar_id,
    )
    print(f"Wrote {count} publications to {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
