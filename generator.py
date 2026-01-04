#!/usr/bin/env python3
"""
Static site generator for Plays20260103.csv

- No JS. Navigation and filtering via facet/tag pages.
- Output goes to natak/ (GitHub Pages-friendly).
"""
from __future__ import annotations

import csv
import html
import json
import math
import re
import shutil
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def slugify(value: str) -> str:
    s = (value or "").strip()
    if not s:
        return "untitled"
    s = unicodedata.normalize("NFKD", s)
    out = []
    prev_dash = False
    for ch in s:
        if ch.isalnum():
            out.append(ch.lower())
            prev_dash = False
        elif "\u0900" <= ch <= "\u097F":  # Devanagari
            out.append(ch)
            prev_dash = False
        elif ch in " _-/:;,.–—()[]{}|+&":
            if not prev_dash:
                out.append("-")
                prev_dash = True
        else:
            if not prev_dash:
                out.append("-")
                prev_dash = True
    slug = "".join(out).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or "untitled"


def to_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        f = float(s)
        if math.isfinite(f):
            return int(round(f))
    except Exception:
        return None
    return None


def truthy_select(x: Any) -> bool:
    if x is None:
        return False
    s = str(x).strip()
    if not s or s.lower() == "nan":
        return False
    try:
        f = float(s)
        return abs(f) > 1e-9
    except Exception:
        pass
    return s.lower() in {"y", "yes", "true", "t", "1", "selected", "shortlist"}


def bucket_pages(pages: Optional[int]) -> str:
    if not pages or pages <= 0:
        return "unknown"
    if pages <= 10:
        return "short"
    if pages <= 30:
        return "medium"
    return "long"


def bucket_minutes(minutes: Optional[int]) -> str:
    if not minutes or minutes <= 0:
        return "unknown"
    if minutes <= 30:
        return "short"
    if minutes <= 60:
        return "medium"
    return "long"


def bucket_cast(males: Optional[int], females: Optional[int]) -> str:
    m = males or 0
    f = females or 0
    tot = m + f
    if tot <= 0:
        return "unknown"
    if tot <= 4:
        return "small"
    if tot <= 10:
        return "medium"
    return "large"


def safe_text(x: Any) -> str:
    """Return a trimmed string; treat common null-ish sentinels as empty."""
    if x is None:
        return ""
    s = str(x).strip()
    if not s:
        return ""
    if s.lower() in {"nan", "none", "null"}:
        return ""
    return s


@dataclass
class Play:
    row: Dict[str, Any]
    slug: str
    title_display: str
    author_display: str
    selected: bool
    pages_bucket: str
    duration_bucket: str
    cast_bucket: str
    acts_value: str
    genre_value: str
    availability_value: str


def load_template(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_page(template: str, *, title: str, h1: str, body_html: str, nav_html: str, base: str) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        template.replace("{{TITLE}}", html.escape(title))
        .replace("{{H1}}", html.escape(h1))
        .replace("{{BODY}}", body_html)
        .replace("{{NAV}}", nav_html)
        .replace("{{BASE}}", base)
        .replace("{{GENERATED_AT}}", generated_at)
    )


def nav(base: str, active: str) -> str:
    items = [
        ("Home", "index.html", "home"),
        ("Selected", "selected/index.html", "selected"),
        ("Authors", "authors/index.html", "authors"),
        ("Genres", "genres/index.html", "genres"),
        ("Acts", "acts/index.html", "acts"),
        ("Availability", "availability/index.html", "availability"),
        ("Pages", "pages/index.html", "pages"),
        ("Duration", "duration/index.html", "duration"),
        ("Cast", "cast/index.html", "cast"),
    ]
    links = []
    for label, href, key in items:
        cls = "active" if key == active else ""
        links.append(f'<a class="{cls}" href="{base}{href}">{html.escape(label)}</a>')
    return "\n".join(links)


def play_title(row: Dict[str, Any]) -> str:
    te = safe_text(row.get("Title_English"))
    tm = safe_text(row.get("Title_Marathi"))
    if te and tm and te != tm:
        return f"{te} / {tm}"
    return te or tm or safe_text(row.get("ID")) or "Untitled"


def play_author(row: Dict[str, Any]) -> str:
    ae = safe_text(row.get("Author_English"))
    am = safe_text(row.get("Author_Marathi"))
    if ae and am and ae != am:
        return f"{ae} / {am}"
    return ae or am or "Unknown"


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def list_cards(plays: List[Play], base: str) -> str:
    cards = []
    for p in plays:
        r = p.row
        yt = safe_text(r.get("YouTube"))
        genre = p.genre_value if p.genre_value != "Unknown" else ""
        acts = p.acts_value if p.acts_value != "Unknown" else ""
        mins = to_int(r.get("Length (in minutes)"))
        pages = to_int(r.get("Pages"))

        meta_parts = []
        if p.author_display:
            meta_parts.append(f'<span class="chip">{html.escape(p.author_display)}</span>')
        if genre:
            meta_parts.append(f'<span class="chip">{html.escape(genre)}</span>')
        if acts:
            meta_parts.append(f'<span class="chip">{html.escape(acts)} act(s)</span>')
        if pages and pages > 0:
            meta_parts.append(f'<span class="chip">{pages} pages</span>')
        if mins and mins > 0:
            meta_parts.append(f'<span class="chip">{mins} min</span>')
        if p.selected:
            meta_parts.append('<span class="chip">Selected</span>')

        chips = '<div class="chips">' + "".join(meta_parts) + "</div>" if meta_parts else ""
        link = f'{base}plays/{p.slug}/index.html'
        yt_link = f'<div class="small"><a href="{html.escape(yt)}">YouTube</a></div>' if yt else ""

        cards.append(
            f"""<div class="card">
  <p class="card-title"><a href="{link}">{html.escape(p.title_display)}</a></p>
  <p class="card-kv">{html.escape(p.author_display)}</p>
  {yt_link}
  {chips}
</div>"""
        )
    return '<div class="cards">\n' + "\n".join(cards) + "\n</div>"


def facet_index(title: str, items: List[Tuple[str, str]], base: str) -> str:
    rows = []
    for label, href in items:
        rows.append(f'<tr><td><a href="{base}{href}">{html.escape(label)}</a></td></tr>')
    return (
        f'<p class="meta">Browse by {html.escape(title.lower())}.</p>'
        f'<table class="table"><tbody>{"".join(rows)}</tbody></table>'
    )


def play_detail(play: Play, base: str) -> str:
    r = play.row
    mins_num = to_int(r.get("Length (in minutes)"))
    if mins_num == 0:
        mins_display = "?"
    elif mins_num is None:
        mins_display = "Unknown"
    else:
        mins_display = str(mins_num)
    fields = [
        ("ID", safe_text(r.get("ID"))),
        ("Author (English)", safe_text(r.get("Author_English"))),
        ("Title (English)", safe_text(r.get("Title_English"))),
        ("Author (Marathi)", safe_text(r.get("Author_Marathi"))),
        ("Title (Marathi)", safe_text(r.get("Title_Marathi"))),
        ("Genre", play.genre_value),
        ("Acts", play.acts_value),
        ("Pages", safe_text(r.get("Pages"))),
        ("Length (in minutes)", mins_display),
        ("Length (descriptor)", safe_text(r.get("Length"))),
        ("Males", safe_text(r.get("Males"))),
        ("Females", safe_text(r.get("Females"))),
        ("Availability", play.availability_value),
        ("Property", safe_text(r.get("Property"))),
        ("Certified By", safe_text(r.get("Certified By"))),
        ("Submitted By", safe_text(r.get("Submitted By"))),
        ("Year of Writing", safe_text(r.get("Year of Writing"))),
        ("First Performance Year", safe_text(r.get("First Performance Year"))),
        ("Performance Dates", safe_text(r.get("Performance Dates"))),
        ("Date", safe_text(r.get("Date"))),
    ]

    yt = safe_text(r.get("YouTube"))
    notes = safe_text(r.get("Notes"))

    chips = [
        f'<a class="chip" href="{base}authors/{slugify(play.author_display)}/index.html">Author</a>',
        f'<a class="chip" href="{base}genres/{slugify(play.genre_value)}/index.html">Genre</a>',
        f'<a class="chip" href="{base}acts/{slugify(play.acts_value)}/index.html">Acts</a>',
        f'<a class="chip" href="{base}availability/{slugify(play.availability_value)}/index.html">Availability</a>',
        f'<a class="chip" href="{base}pages/{play.pages_bucket}/index.html">Pages: {play.pages_bucket}</a>',
        f'<a class="chip" href="{base}duration/{play.duration_bucket}/index.html">Duration: {play.duration_bucket}</a>',
        f'<a class="chip" href="{base}cast/{play.cast_bucket}/index.html">Cast: {play.cast_bucket}</a>',
    ]
    if play.selected:
        chips.append(f'<a class="chip" href="{base}selected/index.html">Selected</a>')
    chips_html = '<div class="chips">' + "".join(chips) + "</div>"

    kv_rows = []
    for k, v in fields:
        if not v:
            continue
        kv_rows.append(
            f'<div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div>'
        )
    kv_html = '<div class="kv">' + "".join(kv_rows) + "</div>"

    extra = []
    if yt:
        extra.append(
            f'<p><strong>YouTube:</strong> <a href="{html.escape(yt)}">{html.escape(yt)}</a></p>'
        )
    if notes:
        extra.append(
            "<p><strong>Notes:</strong><br>"
            + html.escape(notes).replace("\n", "<br>")
            + "</p>"
        )
    extra_html = "\n".join(extra)

    back = f'<p class="meta"><a href="{base}index.html">← Back to all plays</a></p>'
    return back + chips_html + kv_html + extra_html


def main(csv_path: str, out_dir: str) -> None:
    out = Path(out_dir)
    ensure_dir(out)

    # Copy assets
    ensure_dir(out / "assets")
    shutil.copy2(Path(__file__).parent / "assets" / "style.css", out / "assets" / "style.css")
    template = load_template(Path(__file__).parent / "assets" / "template.html")

    plays: List[Play] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row = {k: v for k, v in row.items() if k and not k.startswith("Unnamed")}
            title = play_title(row)
            author = play_author(row)

            base_slug = slugify(safe_text(row.get("Title_English")) or safe_text(row.get("Title_Marathi")) or title)
            pid = safe_text(row.get("ID"))
            slug = f"{base_slug}-{slugify(pid)}" if pid else base_slug

            acts_raw = safe_text(row.get("Acts"))
            acts_num = to_int(acts_raw) if acts_raw else None
            if acts_num == 0:
                acts = "?"
            elif acts_raw:
                acts = acts_raw
            else:
                acts = "Unknown"
            genre = safe_text(row.get("Genre")) or "Unknown"
            availability = safe_text(row.get("Availability")) or "Unknown"

            males = to_int(row.get("Males"))
            females = to_int(row.get("Females"))
            pages = to_int(row.get("Pages"))
            mins = to_int(row.get("Length (in minutes)"))

            plays.append(
                Play(
                    row=row,
                    slug=slug,
                    title_display=title,
                    author_display=author,
                    selected=truthy_select(row.get("Select")),
                    pages_bucket=bucket_pages(pages),
                    duration_bucket=bucket_minutes(mins),
                    cast_bucket=bucket_cast(males, females),
                    acts_value=acts,
                    genre_value=genre if genre else "Unknown",
                    availability_value=availability if availability else "Unknown",
                )
            )

    plays_sorted = sorted(plays, key=lambda p: (p.author_display.lower(), p.title_display.lower()))

    facets = {
        "authors": defaultdict(list),
        "genres": defaultdict(list),
        "acts": defaultdict(list),
        "availability": defaultdict(list),
        "pages": defaultdict(list),
        "duration": defaultdict(list),
        "cast": defaultdict(list),
    }
    for p in plays_sorted:
        facets["authors"][p.author_display].append(p)
        facets["genres"][p.genre_value].append(p)
        facets["acts"][p.acts_value].append(p)
        facets["availability"][p.availability_value].append(p)
        facets["pages"][p.pages_bucket].append(p)
        facets["duration"][p.duration_bucket].append(p)
        facets["cast"][p.cast_bucket].append(p)

    # Main index
    body = '<p class="meta">Browse plays by clicking facets in the nav, or start from the full list below.</p>'
    body += list_cards(plays_sorted, base="")
    write(out / "index.html", render_page(template, title="Plays", h1="All Plays", body_html=body, nav_html=nav("", "home"), base=""))

    # Selected
    selected = [p for p in plays_sorted if p.selected]
    sel_body = '<p class="meta">Plays where <code>Select</code> is truthy / non-zero.</p>'
    sel_body += list_cards(selected, base="../") if selected else '<p class="meta">No plays currently marked selected.</p>'
    write(out / "selected" / "index.html", render_page(template, title="Selected Plays", h1="Selected Plays", body_html=sel_body, nav_html=nav("../", "selected"), base="../"))

    def build_facet(facet_key: str, title: str, active_key: str) -> None:
        mapping = facets[facet_key]
        items = []
        for label in sorted(mapping.keys(), key=lambda s: s.lower()):
            href = f"{facet_key}/{slugify(label)}/index.html"
            items.append((label, href))
        top_body = facet_index(title, items, base="../")
        write(out / facet_key / "index.html", render_page(template, title=title, h1=title, body_html=top_body, nav_html=nav("../", active_key), base="../"))

        for label, plist in mapping.items():
            page_body = f'<p class="meta">{html.escape(title[:-1] if title.endswith("s") else title)}: <strong>{html.escape(label)}</strong></p>'
            page_body += list_cards(plist, base="../../")
            write(out / facet_key / slugify(label) / "index.html", render_page(template, title=f"{title}: {label}", h1=f"{title}: {label}", body_html=page_body, nav_html=nav("../../", active_key), base="../../"))

    build_facet("authors", "Authors", "authors")
    build_facet("genres", "Genres", "genres")
    build_facet("acts", "Acts", "acts")
    build_facet("availability", "Availability", "availability")

    def build_bucket_facet(facet_key: str, title: str, active_key: str, order: List[str]) -> None:
        mapping = facets[facet_key]
        items = []
        for label in order:
            if label in mapping:
                href = f"{facet_key}/{label}/index.html"
                items.append((label, href))
        for label in sorted(set(mapping.keys()) - set(order), key=lambda s: s.lower()):
            href = f"{facet_key}/{slugify(label)}/index.html"
            items.append((label, href))
        top_body = facet_index(title, items, base="../")
        write(out / facet_key / "index.html", render_page(template, title=title, h1=title, body_html=top_body, nav_html=nav("../", active_key), base="../"))

        for label, plist in mapping.items():
            href_label = label if label in order else slugify(label)
            page_body = f'<p class="meta">{html.escape(title[:-1] if title.endswith("s") else title)}: <strong>{html.escape(label)}</strong></p>'
            page_body += list_cards(plist, base="../../")
            write(out / facet_key / href_label / "index.html", render_page(template, title=f"{title}: {label}", h1=f"{title}: {label}", body_html=page_body, nav_html=nav("../../", active_key), base="../../"))

    build_bucket_facet("pages", "Pages", "pages", ["unknown", "short", "medium", "long"])
    build_bucket_facet("duration", "Duration", "duration", ["unknown", "short", "medium", "long"])
    build_bucket_facet("cast", "Cast", "cast", ["unknown", "small", "medium", "large"])

    # Per play pages
    for p in plays_sorted:
        body = play_detail(p, base="../../")
        write(out / "plays" / p.slug / "index.html", render_page(template, title=p.title_display, h1=p.title_display, body_html=body, nav_html=nav("../../", "home"), base="../../"))

    # JSON export (optional, for future use)
    export = []
    for p in plays_sorted:
        r = dict(p.row)
        r["_slug"] = p.slug
        r["_title_display"] = p.title_display
        r["_author_display"] = p.author_display
        r["_selected"] = p.selected
        r["_pages_bucket"] = p.pages_bucket
        r["_duration_bucket"] = p.duration_bucket
        r["_cast_bucket"] = p.cast_bucket
        export.append(r)
    write(out / "plays.json", json.dumps(export, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: generator.py <csv_path> <out_dir>")
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2])
