#!/usr/bin/env python3
"""
Natak static site generator (CSV -> Markdown with immutable AUTO blocks).

This generator:
- reads Plays CSV
- writes Markdown sources under ./content/ (tracked or not, up to you)
- preserves any human-authored text outside the AUTO block
- does NOT generate HTML (pandoc build step handles that)

Build pipeline:
  ./build.sh -> runs this generator, then pandoc converts content/**/*.md to natak/**/*.html
"""

from __future__ import annotations

import csv
import html
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


AUTO_BEGIN = "<!-- AUTO:BEGIN -->"
AUTO_END = "<!-- AUTO:END -->"


# ----------------------------
# small helpers
# ----------------------------
def safe_text(x: Any) -> str:
    """Normalize CSV cell values; suppress common 'empty' sentinels."""
    if x is None:
        return ""
    s = str(x).strip()
    if not s:
        return ""
    if s.lower() in {"nan", "none", "null"}:
        return ""
    return s


def to_int(x: Any) -> Optional[int]:
    s = safe_text(x)
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def truthy(x: Any) -> bool:
    s = safe_text(x).strip().lower()
    return s in {"y", "yes", "true", "1", "selected", "t"}


def slugify(s: str) -> str:
    s = safe_text(s)
    if not s:
        return "untitled"
    s = s.replace("/", " ")
    s = re.sub(r"[\s_]+", "-", s.strip())
    s = re.sub(r"[^0-9A-Za-z\-\u0900-\u097F]+", "", s)  # keep Devanagari
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s.lower() or "untitled"


def yaml_escape(s: str) -> str:
    """Conservative YAML scalar quoting for pandoc metadata blocks."""
    if s is None:
        return '""'
    s = str(s)

    # Values that are special in YAML or commonly mis-parsed by parsers
    special_words = {
        "y", "yes", "n", "no", "true", "false", "on", "off", "null", "~",
    }

    if (
        s.strip() == ""
        or s.strip() == "?"
        or s.strip().lower() in special_words
        or any(
            c in s
            for c in [
                ":", "#", "{", "}", "[", "]", "\n", '"', "'", "?",
                "&", "*", "!", "%", "@", "`", "|", ">", ","
            ]
        )
        or s.lstrip().startswith(("-", "?", ":", "#"))
    ):
        s2 = s.replace("\\", "\\\\").replace('"', '\\"')
        return '"' + s2 + '"'
    return s


def bilingual_display(en: str, mr: str) -> str:
    en_s = safe_text(en)
    mr_s = safe_text(mr)
    if en_s and mr_s and en_s != mr_s:
        return f"{en_s} / {mr_s}"
    return en_s or mr_s


def sort_key_en(author_en: str, title_en: str) -> str:
    return f"{safe_text(author_en)} {safe_text(title_en)}".casefold().strip()


def sort_key_mr(author_mr: str, title_mr: str, fallback_author_en: str, fallback_title_en: str) -> str:
    # Unicode sort (stable). Falls back to English when Marathi is missing.
    a = safe_text(author_mr) or safe_text(fallback_author_en)
    t = safe_text(title_mr) or safe_text(fallback_title_en)
    return f"{a} {t}".strip()


def normalize_acts(x: Any) -> str:
    n = to_int(x)
    if n == 0:
        return "?"
    s = safe_text(x)
    return s or "Unknown"


def normalize_minutes_display(x: Any) -> str:
    n = to_int(x)
    if n is None:
        return "Unknown"
    if n == 0:
        return "?"
    return str(n)


# ----------------------------
# markdown file writer that preserves human text
# ----------------------------
def md_write_with_auto_block(
    path: Path,
    front_matter: Dict[str, str],
    auto_block_html: str,
    heading: str = "",
) -> None:
    """
    Writes a Markdown file with YAML front matter + an immutable AUTO block.

    If the file already exists, everything outside the AUTO block is preserved.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    preserved_tail = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if AUTO_BEGIN in existing and AUTO_END in existing:
            preserved_tail = existing.split(AUTO_END, 1)[1].lstrip("\n")
        else:
            preserved_tail = "\n\n" + existing

    if "generated_at" not in front_matter:
        front_matter["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    fm_lines = ["---"]
    for k, v in front_matter.items():
        v = v if v is not None else ""
        if "\n" in v:
            fm_lines.append(f"{k}: |")
            for line in v.splitlines():
                fm_lines.append(f"  {line}")
        else:
            fm_lines.append(f"{k}: {yaml_escape(v)}")
    fm_lines.append("---")

    parts: List[str] = []
    parts.append("\n".join(fm_lines))
    if heading:
        parts.append("")
        parts.append(f"# {heading}")
    parts.append("")
    parts.append(AUTO_BEGIN)
    parts.append(auto_block_html.rstrip())
    parts.append(AUTO_END)
    if preserved_tail:
        parts.append("")
        parts.append(preserved_tail.rstrip())
    parts.append("")

    path.write_text("\n".join(parts), encoding="utf-8")


# ----------------------------
# model
# ----------------------------
@dataclass
class Play:
    row: Dict[str, str]
    slug: str

    title_en: str
    title_mr: str
    author_en: str
    author_mr: str

    title_display: str
    author_display: str

    sort_en: str
    sort_mr: str

    acts_value: str
    genre_value: str
    availability_value: str
    selected: bool


def load_plays(csv_path: Path) -> List[Play]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        plays: List[Play] = []
        for r in reader:
            row = {k: (v if v is not None else "") for k, v in r.items()}

            title_en = safe_text(row.get("Title_English"))
            title_mr = safe_text(row.get("Title_Marathi"))
            author_en = safe_text(row.get("Author_English"))
            author_mr = safe_text(row.get("Author_Marathi"))

            title_display = bilingual_display(title_en, title_mr) or safe_text(row.get("ID")) or "Untitled"
            author_display = bilingual_display(author_en, author_mr)

            acts_value = normalize_acts(row.get("Acts"))
            genre_value = safe_text(row.get("Genre")) or "Unknown"
            availability_value = safe_text(row.get("Availability")) or "Unknown"
            selected = truthy(row.get("Select"))

            s_en = sort_key_en(author_en, title_en)
            s_mr = sort_key_mr(author_mr, title_mr, author_en, title_en)

            # slug uses english-first display, but remains stable
            slug_source = f"{author_en or author_mr}-{title_en or title_mr}" or safe_text(row.get("ID"))
            base_slug = slugify(slug_source)

            plays.append(
                Play(
                    row=row,
                    slug=base_slug,
                    title_en=title_en,
                    title_mr=title_mr,
                    author_en=author_en,
                    author_mr=author_mr,
                    title_display=title_display,
                    author_display=author_display,
                    sort_en=s_en,
                    sort_mr=s_mr,
                    acts_value=acts_value,
                    genre_value=genre_value,
                    availability_value=availability_value,
                    selected=selected,
                )
            )
    # default stable sort: English/Roman (for deterministic output)
    plays.sort(key=lambda p: (p.sort_en or "zzz", p.title_display.casefold()))
    return plays


# ----------------------------
# HTML fragments embedded into MD AUTO blocks
# ----------------------------
def nav_html(base: str, active: str) -> str:
    items = [
        ("home", "Plays", f"{base}index.html"),
        ("selected", "Selected", f"{base}selected/index.html"),
        ("authors", "Authors", f"{base}authors/index.html"),
        ("genres", "Genres", f"{base}genres/index.html"),
        ("acts", "Acts", f"{base}acts/index.html"),
        ("availability", "Availability", f"{base}availability/index.html"),
    ]
    parts = ['<nav class="nav">']
    for key, label, href in items:
        cls = "nav-item active" if key == active else "nav-item"
        parts.append(f'<a class="{cls}" href="{href}">{html.escape(label)}</a>')
    parts.append("</nav>")
    return "\n".join(parts)


def list_cards_html(plays: List[Play], base: str) -> str:
    cards = []
    for p in plays:
        r = p.row
        yt = safe_text(r.get("YouTube"))

        genre = p.genre_value if p.genre_value != "Unknown" else ""
        acts = p.acts_value if p.acts_value != "Unknown" else ""

        mins_num = to_int(r.get("Length (in minutes)"))
        pages_num = to_int(r.get("Pages"))

        # duration chip: show ? when explicitly 0
        mins_chip: Optional[str] = None
        if mins_num is None:
            mins_chip = None
        elif mins_num == 0:
            mins_chip = "? min"
        else:
            mins_chip = f"{mins_num} min"

        meta_parts = []
        if p.author_display:
            meta_parts.append(f'<span class="chip">{html.escape(p.author_display)}</span>')
        if genre:
            meta_parts.append(f'<span class="chip">{html.escape(genre)}</span>')
        if acts:
            meta_parts.append(f'<span class="chip">{html.escape(acts)} act(s)</span>')
        if pages_num is not None and pages_num > 0:
            meta_parts.append(f'<span class="chip">{pages_num} pages</span>')
        if mins_chip:
            meta_parts.append(f'<span class="chip">{html.escape(mins_chip)}</span>')
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


def kv_table_html(fields: List[Tuple[str, str]]) -> str:
    rows = []
    for k, v in fields:
        v = safe_text(v)
        if not v:
            continue
        rows.append(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>")
    if not rows:
        return ""
    return '<table class="kv">\n' + "\n".join(rows) + "\n</table>"


def play_detail_html(p: Play, base: str) -> str:
    r = p.row

    yt = safe_text(r.get("YouTube"))
    yt_html = f'<p><a href="{html.escape(yt)}">YouTube link</a></p>' if yt else ""

    males = safe_text(r.get("Males"))
    females = safe_text(r.get("Females"))
    mf = ""
    if males or females:
        mf = f"{males or '?'} / {females or '?'}"

    fields: List[Tuple[str, str]] = [
        ("Title", p.title_display),
        ("Author", p.author_display),
        ("ID", safe_text(r.get("ID"))),
        ("Genre", safe_text(r.get("Genre"))),
        ("Acts", p.acts_value),
        ("Characters (M/F)", mf),
        ("Pages", safe_text(r.get("Pages"))),
        ("Length (in minutes)", normalize_minutes_display(r.get("Length (in minutes)"))),
        ("First Performance Year", safe_text(r.get("First Performance Year"))),
        ("Year of Writing", safe_text(r.get("Year of Writing"))),
        ("Availability", safe_text(r.get("Availability"))),
        ("Property", safe_text(r.get("Property"))),
        ("Certified By", safe_text(r.get("Certified By"))),
        ("Submitted By", safe_text(r.get("Submitted By"))),
        ("Performance Dates", safe_text(r.get("Performance Dates"))),
        ("Date", safe_text(r.get("Date"))),
        ("Notes", safe_text(r.get("Notes"))),
    ]

    top_links = f'<p class="small"><a href="{base}index.html">All plays</a></p>'
    return (
        top_links
        + yt_html
        + kv_table_html(fields)
    )


def facet_index_md(title: str, heading: str, base: str, active: str, links: List[Tuple[str, str]]) -> str:
    # links: (label, href)
    items = "\n".join([f'<li><a href="{html.escape(href)}">{html.escape(label)}</a></li>' for label, href in links])
    body = f"<ul>\n{items}\n</ul>"
    fm = {"title": title, "h1": heading, "base": base, "active": active, "nav": nav_html(base, active)}
    return fm, body


# ----------------------------
# site build (MD)
# ----------------------------
def build_content(csv_path: Path, content_root: Path) -> None:
    plays = load_plays(csv_path)

    # Two sort orders (no-JS "option to sort")
    plays_en = sorted(plays, key=lambda p: (p.sort_en or "zzz", p.title_display.casefold()))
    plays_mr = sorted(plays, key=lambda p: (p.sort_mr or "zzz", p.title_display))

    # Home (EN)
    sort_links = (
        '<p class="small">Sort: '
        '<a href="index.html">English/Roman</a> | '
        '<a href="index_mr.html">Marathi/Devanagari</a>'
        '</p>'
    )
    home_auto = sort_links + list_cards_html(plays_en, base="")
    fm = {"title": "Natak", "h1": "Natak", "base": "", "active": "home", "nav": nav_html("", "home")}
    md_write_with_auto_block(content_root / "index.md", fm, home_auto, heading="")

    # Home (MR)
    home_mr_auto = sort_links + list_cards_html(plays_mr, base="")
    fm = {"title": "Natak (मराठी क्रम)", "h1": "नाटके (मराठी क्रम)", "base": "", "active": "home", "nav": nav_html("", "home")}
    md_write_with_auto_block(content_root / "index_mr.md", fm, home_mr_auto, heading="")

    # Selected
    selected = [p for p in plays_en if p.selected]
    sel_auto = list_cards_html(selected, base="../") if selected else "<p>No selected plays yet.</p>"
    fm = {"title": "Selected", "h1": "Selected", "base": "../", "active": "selected", "nav": nav_html("../", "selected")}
    md_write_with_auto_block(content_root / "selected" / "index.md", fm, sel_auto, heading="")

    # Individual play pages
    for p in plays:
        base = "../../"
        auto = play_detail_html(p, base=base)
        fm = {"title": p.title_display, "h1": p.title_display, "base": base, "active": "home", "nav": nav_html(base, "home")}
        md_write_with_auto_block(content_root / "plays" / p.slug / "index.md", fm, auto, heading="")

    # Facets: authors / genres / acts / availability
    def facet_values(key: str) -> List[str]:
        vals = []
        for p in plays:
            if key == "authors":
                v = p.author_display or "Unknown"
            elif key == "genres":
                v = p.genre_value
            elif key == "acts":
                v = p.acts_value
            elif key == "availability":
                v = p.availability_value
            else:
                v = "Unknown"
            vals.append(v or "Unknown")
        return sorted(set(vals))

    facets: List[Tuple[str, str, str]] = [
        ("authors", "Authors", "authors"),
        ("genres", "Genres", "genres"),
        ("acts", "Acts", "acts"),
        ("availability", "Availability", "availability"),
    ]

    for facet_key, facet_title, facet_active in facets:
        # facet index pages: EN and MR sort options for link labels where relevant
        values = facet_values(facet_key)

        # index
        base = "../"
        links = [(v, f"{v_slug}/index.html") for v in values for v_slug in [slugify(v)]]
        fm = {"title": facet_title, "h1": facet_title, "base": base, "active": facet_active, "nav": nav_html(base, facet_active)}
        body = "<ul>\n" + "\n".join([f'<li><a href="{slugify(v)}/index.html">{html.escape(v)}</a></li>' for v in values]) + "\n</ul>"
        md_write_with_auto_block(content_root / facet_key / "index.md", fm, body, heading="")

        # each value page
        for v in values:
            v_slug = slugify(v)
            matches = [p for p in plays if (
                (facet_key == "authors" and (p.author_display or "Unknown") == v) or
                (facet_key == "genres" and p.genre_value == v) or
                (facet_key == "acts" and p.acts_value == v) or
                (facet_key == "availability" and p.availability_value == v)
            )]

            # two sort pages
            matches_en = sorted(matches, key=lambda p: (p.sort_en or "zzz", p.title_display.casefold()))
            matches_mr = sorted(matches, key=lambda p: (p.sort_mr or "zzz", p.title_display))

            sort_links_f = (
                '<p class="small">Sort: '
                '<a href="index.html">English/Roman</a> | '
                '<a href="index_mr.html">Marathi/Devanagari</a>'
                '</p>'
            )

            base = "../../"
            fm = {"title": v, "h1": v, "base": base, "active": facet_active, "nav": nav_html(base, facet_active)}
            md_write_with_auto_block(
                content_root / facet_key / v_slug / "index.md",
                fm,
                sort_links_f + list_cards_html(matches_en, base=base),
                heading="",
            )
            md_write_with_auto_block(
                content_root / facet_key / v_slug / "index_mr.md",
                fm,
                sort_links_f + list_cards_html(matches_mr, base=base),
                heading="",
            )


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="Input CSV (e.g., Plays20260103.csv)")
    ap.add_argument("content", help="Output content directory (e.g., content)")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    content_root = Path(args.content)

    content_root.mkdir(parents=True, exist_ok=True)
    build_content(csv_path, content_root)


if __name__ == "__main__":
    main()
