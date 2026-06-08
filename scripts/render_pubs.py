#!/usr/bin/env python3
"""Render pubs.bib to HTML with SunLab-specific formatting."""

from __future__ import annotations

import html
import re
import sys
from calendar import month_name
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import jinja2.sandbox
from pybtex.database.input import bibtex

from update_pubs import PEOPLE_PATH, author_matches, load_yaml, person_matchers
BIB_PATH = ROOT / "bib" / "pubs.bib"
TEMPLATE_PATH = ROOT / "bib" / "publications.tmpl"

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def load_all_lab_matchers() -> list[tuple[str, str]]:
    people = load_yaml(PEOPLE_PATH)
    matchers: list[tuple[str, str]] = []
    seen = set()
    for person in people.values():
        for first, last in person_matchers(person):
            key = (first.lower(), last.lower())
            if key not in seen:
                seen.add(key)
                matchers.append((first, last))
    return matchers


LAB_MATCHERS = load_all_lab_matchers()


def _andlist(items, sep=", ", seplast=", and ", septwo=" and "):
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return septwo.join(items)
    return sep.join(items[:-1]) + seplast + items[-1]


def _author_fmt(author) -> str:
    return " ".join(author.first_names + author.middle_names + author.last_names)


def _author_list(authors) -> str:
    return _andlist(list(map(_author_fmt, authors)))


def _lab_author_list(authors) -> str:
    formatted = []
    for author in authors:
        name = _author_fmt(author)
        if any(author_matches(name, first, last) for first, last in LAB_MATCHERS):
            formatted.append(f"<strong>{html.escape(name)}</strong>")
        else:
            formatted.append(html.escape(name))
    return _andlist(formatted)


def _venue_type(entry) -> str:
    if entry.type == "inbook":
        return "Chapter in "
    if entry.type == "techreport":
        return "Technical Report "
    if entry.type == "phdthesis":
        return f"Ph.D. thesis, {entry.fields['school']}"
    if entry.type == "mastersthesis":
        return f"Master's thesis, {entry.fields['school']}"
    return ""


def _base_venue(entry) -> str:
    fields = entry.fields
    venue = ""
    if entry.type == "article":
        venue = fields.get("journal", "")
        if fields.get("volume") and fields.get("number"):
            venue += f" {fields['volume']}({fields['number']})"
    elif entry.type == "inproceedings":
        venue = fields.get("booktitle", "")
        if fields.get("series"):
            venue += f" ({fields['series']})"
    elif entry.type == "inbook":
        venue = fields.get("title", "")
    elif entry.type == "techreport":
        venue = f"{fields.get('number', '')}, {fields.get('institution', '')}"
    else:
        venue = fields.get("booktitle", "") or fields.get("journal", "")

    return venue.replace("{", "").replace("}", "")


def _abbreviate_venue(venue: str) -> str:
    if "Neural Information Processing Systems" in venue:
        return "NeurIPS"
    if "Computer Vision and Pattern Recognition" in venue:
        return "CVPR"
    if venue.startswith("International Conference on Learning Representations"):
        return "ICLR"
    return venue


def _venue_with_year(entry) -> str:
    venue = _base_venue(entry)
    year = str(entry.fields.get("year", "")).strip()
    if not venue:
        return venue

    if "arxiv" in venue.lower():
        return venue

    short = _abbreviate_venue(venue)
    if year and re.search(r"\b" + re.escape(year) + r"\b", short):
        return short

    if entry.type == "inproceedings" or short in {"NeurIPS", "CVPR", "ICLR"}:
        return f"{short} {year}" if year else short

    return venue


def _title(entry) -> str:
    if entry.type == "inbook":
        title = entry.fields["chapter"]
    else:
        title = entry.fields["title"]
    return title.replace("{", "").replace("}", "")


def _main_url(entry):
    for field in ("url", "ee"):
        if field in entry.fields:
            return entry.fields[field]
    return None


def _extra_urls(entry):
    urls = {}
    for key, value in entry.fields.items():
        lowered = key.lower()
        if not lowered.endswith("_url"):
            continue
        label = lowered[:-4].replace("_", " ")
        urls[label] = value
    return urls


def _month_match(mon):
    if re.match(r"^[0-9]+$", mon):
        return int(mon)
    return MONTHS[mon.lower()[:3]]


def _month_name(monthnum):
    try:
        return month_name[int(monthnum)]
    except (ValueError, KeyError):
        return ""


def _sortkey(entry):
    year = f"{int(entry.fields['year']):04d}"
    try:
        monthnum = _month_match(entry.fields["month"])
        year += f"{monthnum:02d}"
    except KeyError:
        year += "00"
    return year


def render(bib_path: Path, template_path: Path) -> str:
    with bib_path.open(encoding="utf-8") as handle:
        db = bibtex.Parser().parse_stream(handle)

    for key, entry in db.entries.items():
        entry.fields["key"] = key

    env = jinja2.sandbox.SandboxedEnvironment()
    env.filters["author_fmt"] = _author_fmt
    env.filters["author_list"] = _author_list
    env.filters["lab_author_list"] = _lab_author_list
    env.filters["title"] = _title
    env.filters["venue_type"] = _venue_type
    env.filters["venue"] = _base_venue
    env.filters["venue_with_year"] = _venue_with_year
    env.filters["main_url"] = _main_url
    env.filters["extra_urls"] = _extra_urls
    env.filters["monthname"] = _month_name

    template = env.from_string(template_path.read_text(encoding="utf-8"))
    entries = sorted(db.entries.values(), key=_sortkey, reverse=True)
    return template.render(entries=entries)


def main() -> int:
    print(render(BIB_PATH, TEMPLATE_PATH), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
