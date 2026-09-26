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
from typing import Any, Callable, Dict, List, Optional, Tuple


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


def is_unverified(row: Dict[str, Any]) -> bool:
    return safe_text(row.get("Verified")).strip().upper() == "N"


def is_member_submitted(row: Dict[str, Any]) -> bool:
    return safe_text(row.get("Verified")).strip().upper() == "M"


SCRIPT_STATUS_CLASSES = {
    "In hand — shareable": "script-status-shareable",
    "In hand — restricted (copyright)": "script-status-restricted",
    "Obtainable": "script-status-obtainable",
    "Not currently available": "script-status-unavailable",
}


def script_status_class(status: str) -> str:
    return SCRIPT_STATUS_CLASSES.get(status, "")


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
    genre_marathi_value: str
    availability_value: str
    script_status_value: str
    synopsis: str
    unverified: bool
    member_submitted: bool


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


PRIMARY_NAV = [
    ("Home", "index.html", "home"),
    ("Authors", "authors/index.html", "authors"),
    ("Genres", "genres/index.html", "genres"),
    ("Script Status", "script-status/index.html", "script-status"),
    ("Selected", "selected/index.html", "selected"),
]

MORE_NAV = [
    ("With Synopsis", "with-synopsis/index.html", "with-synopsis"),
    ("Acts", "acts/index.html", "acts"),
    ("Availability", "availability/index.html", "availability"),
    ("Pages", "pages/index.html", "pages"),
    ("Duration", "duration/index.html", "duration"),
    ("Cast", "cast/index.html", "cast"),
    ("Credits", "credits/index.html", "credits"),
]


def nav(base: str, active: str) -> str:
    links = []
    for label, href, key in PRIMARY_NAV:
        cls = "active" if key == active else ""
        links.append(f'<a class="{cls}" href="{base}{href}">{html.escape(label)}</a>')

    more_active = any(key == active for _, _, key in MORE_NAV)
    more_links = []
    for label, href, key in MORE_NAV:
        cls = "active" if key == active else ""
        more_links.append(f'<a class="{cls}" href="{base}{href}">{html.escape(label)}</a>')
    open_attr = " open" if more_active else ""
    summary_cls = "active" if more_active else ""
    links.append(
        f'<details class="nav-more"{open_attr}>'
        f'<summary class="{summary_cls}">More ▾</summary>'
        f'<div class="nav-more-menu">{"".join(more_links)}</div>'
        f'</details>'
    )
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
        if p.genre_marathi_value:
            meta_parts.append(f'<span class="chip">{html.escape(p.genre_marathi_value)}</span>')
        if acts:
            meta_parts.append(f'<span class="chip">{html.escape(acts)} act(s)</span>')
        if pages and pages > 0:
            meta_parts.append(f'<span class="chip">{pages} pages</span>')
        if mins and mins > 0:
            meta_parts.append(f'<span class="chip">{mins} min</span>')
        if p.selected:
            meta_parts.append('<span class="chip">Selected</span>')
        if p.script_status_value != "Unknown":
            cls = script_status_class(p.script_status_value)
            meta_parts.append(f'<span class="chip {cls}">{html.escape(p.script_status_value)}</span>')
        if p.unverified:
            meta_parts.append('<span class="chip chip-unverified">Unverified</span>')
        if p.member_submitted:
            meta_parts.append('<span class="chip chip-member">Member-submitted</span>')

        chips = '<div class="chips">' + "".join(meta_parts) + "</div>" if meta_parts else ""
        link = f'{base}plays/{p.slug}/index.html'
        yt_link = f'<div class="small"><a href="{html.escape(yt)}">YouTube</a></div>' if yt else ""
        synopsis_snippet = ""
        if p.synopsis:
            snippet = p.synopsis if len(p.synopsis) <= 160 else p.synopsis[:157].rstrip() + "…"
            synopsis_snippet = f'<p class="card-synopsis">{html.escape(snippet)}</p>'

        cards.append(
            f"""<div class="card">
  <p class="card-title"><a href="{link}">{html.escape(p.title_display)}</a></p>
  <p class="card-kv">{html.escape(p.author_display)}</p>
  {synopsis_snippet}
  {yt_link}
  {chips}
</div>"""
        )
    return '<div class="cards">\n' + "\n".join(cards) + "\n</div>"


def letter_bucket(s: str) -> str:
    """First-letter bucket for an A-Z / Devanagari jump index. '#' for anything else."""
    s = (s or "").strip()
    if not s:
        return "#"
    ch = s[0]
    if ch.isascii() and ch.isalpha():
        return ch.upper()
    if "\u0900" <= ch <= "\u097F":  # Devanagari
        return ch
    return "#"


def anchor_id(id_prefix: str, bucket: str) -> str:
    return f"{id_prefix}-misc" if bucket == "#" else f"{id_prefix}-{bucket}"


def build_toolbar(order: List[str], id_prefix: str, toolbar_prefix: str = "") -> str:
    index_bar = " ".join(f'<a href="#{anchor_id(id_prefix, b)}">{html.escape(b)}</a>' for b in order)
    return f'<div class="browse-toolbar">{toolbar_prefix}<p class="index-bar">{index_bar}</p></div>'


def lettered_section(items: List[Tuple[str, str, str]], base: str, id_prefix: str, toolbar_prefix: str = "") -> str:
    """items: (sort_key, label, href). Renders a sticky jump-index toolbar
    plus the list grouped under a heading per letter, sorted by sort_key."""
    items_sorted = sorted(items, key=lambda it: it[0].lower())
    groups: Dict[str, List[Tuple[str, str]]] = {}
    order: List[str] = []
    for sort_key, label, href in items_sorted:
        b = letter_bucket(sort_key)
        if b not in groups:
            groups[b] = []
            order.append(b)
        groups[b].append((label, href))
    sections = [build_toolbar(order, id_prefix, toolbar_prefix)]
    for b in order:
        rows = "".join(f'<tr><td><a href="{base}{href}">{html.escape(label)}</a></td></tr>' for label, href in groups[b])
        sections.append(
            f'<h3 id="{anchor_id(id_prefix, b)}" class="index-letter">{html.escape(b)}</h3>'
            f'<table class="table"><tbody>{rows}</tbody></table>'
        )
    return "".join(sections)


def lettered_cards_section(items: List[Tuple[str, "Play"]], base: str, id_prefix: str, toolbar_prefix: str = "") -> str:
    """Like lettered_section, but renders play cards instead of a link table."""
    items_sorted = sorted(items, key=lambda it: it[0].lower())
    groups: Dict[str, List[Play]] = {}
    order: List[str] = []
    for sort_key, p in items_sorted:
        b = letter_bucket(sort_key)
        if b not in groups:
            groups[b] = []
            order.append(b)
        groups[b].append(p)
    sections = [build_toolbar(order, id_prefix, toolbar_prefix)]
    for b in order:
        sections.append(f'<h3 id="{anchor_id(id_prefix, b)}" class="index-letter">{html.escape(b)}</h3>')
        sections.append(list_cards(groups[b], base))
    return "".join(sections)


def pick_tab_order_and_default(
    mapping: Dict[str, List["Play"]], unknown_like: set, explicit_order: Optional[List[str]] = None
) -> Tuple[List[str], Optional[str]]:
    """Order facet-value labels for a tab bar, with 'unknown'-like values
    pushed to the end, and pick a sensible default: the most populated
    real (non-unknown) value, so the page shows something rather than an
    empty/unrepresentative bucket."""
    labels = list(mapping.keys())
    unknown_labels = [l for l in labels if l in unknown_like]
    real_labels = [l for l in labels if l not in unknown_like]
    if explicit_order:
        real_labels = [l for l in explicit_order if l in real_labels] + [
            l for l in real_labels if l not in explicit_order
        ]
    else:
        def sort_key(l: str):
            try:
                return (0, float(l))
            except ValueError:
                return (1, l.lower())
        real_labels.sort(key=sort_key)
    ordered = real_labels + unknown_labels
    default = max(real_labels, key=lambda l: len(mapping[l])) if real_labels else (ordered[0] if ordered else None)
    return ordered, default


def facet_tab_subnav(ordered_labels: List[str], mapping: Dict[str, List["Play"]], active_label: str, root_from_here: str) -> str:
    links = []
    for label in ordered_labels:
        cls = "active" if label == active_label else ""
        href = f"{root_from_here}{slugify(label)}/index.html"
        count = len(mapping[label])
        links.append(f'<a class="{cls}" href="{href}">{html.escape(label)} <span class="count">({count})</span></a>')
    return '<p class="subnav"><span class="subnav-label">Show:</span> ' + " · ".join(links) + "</p>"


def plain_link_table(items: List[Tuple[str, str]], base: str) -> str:
    rows = [f'<tr><td><a href="{base}{href}">{html.escape(label)}</a></td></tr>' for label, href in items]
    return f'<table class="table"><tbody>{"".join(rows)}</tbody></table>'


def facet_index(title: str, items: List[Tuple[str, str]], base: str) -> str:
    return f'<p class="meta">Browse by {html.escape(title.lower())}.</p>' + plain_link_table(items, base)


def tile_grid(tiles: List[Tuple[str, str, int, str]], base: str, trailing: set = frozenset({"Unknown"})) -> str:
    """tiles: (label, sublabel, count, href). A card-like grid for a facet
    with few enough distinct values that a letter-jump index isn't needed —
    sorted by count (most common first) so the tiles worth noticing come
    first; labels in `trailing` (e.g. "Unknown") sort after everything else
    regardless of count, since being the biggest bucket doesn't make it the
    most useful one to see first."""
    tiles_sorted = sorted(tiles, key=lambda t: (t[0] in trailing, -t[2], t[0].lower()))
    cells = []
    for label, sublabel, count, href in tiles_sorted:
        sub_html = f'<span class="tile-sub">{html.escape(sublabel)}</span>' if sublabel else ""
        plural = "play" if count == 1 else "plays"
        cells.append(
            f'<a class="tile" href="{base}{href}">'
            f'<span class="tile-label">{html.escape(label)}</span>'
            f"{sub_html}"
            f'<span class="tile-count">{count} {plural}</span>'
            f"</a>"
        )
    return '<div class="tile-grid">' + "".join(cells) + "</div>"


# Group-build edit form: (form key, label, input kind). Fields with a value
# already are shown as read-only text; only blank ones get an input.
EDIT_FORM_FIELDS = [
    ("acts", "Number of acts", "number"),
    ("males", "Male roles", "number"),
    ("females", "Female roles", "number"),
    ("minutes", "Duration (minutes)", "number"),
    ("pages", "Pages", "number"),
    ("genre", "Genre", "text"),
    ("year_written", "Year written", "number"),
    ("year_performed", "Year first performed", "number"),
    ("synopsis", "Short synopsis", "textarea"),
    ("availability", "Where to get the script", "text"),
]


def existing_values(r: Dict[str, Any]) -> Dict[str, str]:
    """Current values for EDIT_FORM_FIELDS, with the original Google Form's
    junk defaults (0, and 2024 for first performance) treated as blank."""
    def nonzero(col: str) -> str:
        v = safe_text(r.get(col))
        return "" if v == "0" else v
    males, females = safe_text(r.get("Males")), safe_text(r.get("Females"))
    if to_int(males) in (0, None) and to_int(females) in (0, None):
        males = females = ""
    year_performed = safe_text(r.get("First Performance Year"))
    return {
        "acts": nonzero("Acts"),
        "males": males,
        "females": females,
        "minutes": nonzero("Length (in minutes)"),
        "pages": nonzero("Pages"),
        "genre": safe_text(r.get("Genre")),
        "year_written": nonzero("Year of Writing"),
        "year_performed": "" if year_performed == "2024" else year_performed,
        "synopsis": safe_text(r.get("Synopsis")),
        "availability": safe_text(r.get("Availability")),
    }


def edit_form(play: Play, cfg: Dict[str, Any]) -> str:
    f = cfg["fields"]
    esc = html.escape

    def field(key: str, label: str, kind: str, value: str = "", required: bool = False) -> str:
        if value:
            return f'<div class="k">{esc(label)}</div><div class="v">{esc(value)}</div>'
        req = " required" if required else ""
        if kind == "textarea":
            control = f'<textarea name="{f[key]}" rows="4"></textarea>'
        else:
            control = f'<input type="{kind}" name="{f[key]}"{req}>'
        return f'<div class="k"><label>{esc(label)}</label></div><div class="v">{control}</div>'

    current = existing_values(play.row)
    rows = [field(k, label, kind, current[k]) for k, label, kind in EDIT_FORM_FIELDS]
    how = "".join(
        f'<label class="choice"><input type="checkbox" name="{f["how"]}" value="{esc(c)}"> {esc(c)}</label>'
        for c in ["Performed in it", "Read the script", "From a book", "From a website", "General knowledge"]
    )
    copy = "".join(
        f'<label class="choice"><input type="radio" name="{f["copy"]}" value="{esc(c)}"> {esc(c)}</label>'
        for c in ["No", "Yes, and it can be shared", "Yes, but it is restricted (copyright)"]
    )
    return (
        f'<form class="edit-form" action="{esc(cfg["action"])}" method="post">'
        "<h2>Add or correct information</h2>"
        '<p class="meta">Values already on file are shown as text. Fill in what you know; '
        "if something shown is wrong, say so under Corrections. Submissions are reviewed before they appear.</p>"
        f'<input type="hidden" name="{f["id"]}" value="{esc(safe_text(play.row.get("ID")))}">'
        f'<input type="hidden" name="{f["title"]}" value="{esc(play.title_display)}">'
        '<div class="kv">'
        + field("name", "Your name", "text", required=True)
        + field("email", "Your email (private)", "email")
        + "".join(rows)
        + f'<div class="k">How do you know this?</div><div class="v">{how}</div>'
        + field("source", "Source link", "url")
        + field("notes", "Corrections or other notes", "textarea")
        + f'<div class="k">Do you have a copy of the script? (private)</div><div class="v">{copy}</div>'
        + field("contact", "How to reach you about the script (private)", "textarea")
        + '</div><button type="submit">Submit</button></form>'
    )


def contributors_row(path: Path) -> str:
    """Credits row for group members whose submissions were merged: one name
    per line in contributors.txt, deduplicated ignoring case and spacing."""
    if not path.exists():
        return ""
    names: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name = " ".join(line.split())
        if name:
            names.setdefault(name.casefold(), name)
    if not names:
        return ""
    listed = ", ".join(html.escape(n) for n in sorted(names.values(), key=str.casefold))
    return f'<div class="k">Contributions from</div><div class="v">{listed}</div>'


def play_detail(play: Play, base: str, form_cfg: Optional[Dict[str, Any]] = None) -> str:
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
        ("Genre (English)", play.genre_value),
        ("Genre (Marathi)", play.genre_marathi_value),
        ("Acts", play.acts_value),
        ("Pages", safe_text(r.get("Pages"))),
        ("Length (in minutes)", mins_display),
        ("Length (descriptor)", safe_text(r.get("Length"))),
        ("Males", safe_text(r.get("Males"))),
        ("Females", safe_text(r.get("Females"))),
        ("Availability", play.availability_value),
        ("Script Status", play.script_status_value if play.script_status_value != "Unknown" else ""),
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
    source = safe_text(r.get("Data Source"))

    chips = [
        f'<a class="chip" href="{base}authors/{slugify(play.author_display)}/index.html">Author</a>',
        f'<a class="chip" href="{base}genres/{slugify(play.genre_value)}/index.html">Genre</a>',
        f'<a class="chip" href="{base}acts/{slugify(play.acts_value)}/index.html">Acts</a>',
        f'<a class="chip" href="{base}availability/{slugify(play.availability_value)}/index.html">Availability</a>',
        f'<a class="chip" href="{base}pages/{play.pages_bucket}/index.html">Pages: {play.pages_bucket}</a>',
        f'<a class="chip" href="{base}duration/{play.duration_bucket}/index.html">Duration: {play.duration_bucket}</a>',
        f'<a class="chip" href="{base}cast/{play.cast_bucket}/index.html">Cast: {play.cast_bucket}</a>',
    ]
    if play.script_status_value != "Unknown":
        cls = script_status_class(play.script_status_value)
        chips.append(
            f'<a class="chip {cls}" href="{base}script-status/{slugify(play.script_status_value)}/index.html">{html.escape(play.script_status_value)}</a>'
        )
    if play.selected:
        chips.append(f'<a class="chip" href="{base}selected/index.html">Selected</a>')
    if play.unverified:
        chips.append('<span class="chip chip-unverified">Unverified — needs confirmation</span>')
    if play.member_submitted:
        chips.append('<span class="chip chip-member">Member-submitted — needs confirmation</span>')
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
    if source:
        extra.append(
            f'<p><strong>Data source:</strong> <a href="{html.escape(source)}">{html.escape(source)}</a></p>'
        )
    extra_html = "\n".join(extra)

    back = f'<p class="meta"><a href="{base}index.html">← Back to all plays</a></p>'
    synopsis_html = ""
    if play.synopsis:
        synopsis_html = f'<p class="synopsis">{html.escape(play.synopsis)}</p>'
    edit_html = edit_form(play, form_cfg) if form_cfg else ""
    return back + synopsis_html + chips_html + kv_html + extra_html + edit_html


def main(csv_path: str, out_dir: str, form_cfg: Optional[Dict[str, Any]] = None) -> None:
    """form_cfg: FORM_CONFIG logged by tools/create_form.gs. When set, this is
    the group build: play pages get an edit form and every page is marked
    noindex."""
    out = Path(out_dir)
    ensure_dir(out)

    # Copy assets
    ensure_dir(out / "assets")
    shutil.copy2(Path(__file__).parent / "assets" / "style.css", out / "assets" / "style.css")
    template = load_template(Path(__file__).parent / "assets" / "template.html")
    if form_cfg:
        template = template.replace("</head>", '  <meta name="robots" content="noindex, nofollow" />\n</head>')

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
            genre_marathi = safe_text(row.get("Genre_Marathi"))
            availability = safe_text(row.get("Availability")) or "Unknown"
            script_status = safe_text(row.get("Script Status")) or "Unknown"
            synopsis = safe_text(row.get("Synopsis"))

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
                    genre_marathi_value=genre_marathi,
                    availability_value=availability if availability else "Unknown",
                    script_status_value=script_status if script_status else "Unknown",
                    synopsis=synopsis,
                    unverified=is_unverified(row),
                    member_submitted=is_member_submitted(row),
                )
            )

    plays_sorted = sorted(plays, key=lambda p: (p.author_display.lower(), p.title_display.lower()))

    facets = {
        "authors": defaultdict(list),
        "genres": defaultdict(list),
        "acts": defaultdict(list),
        "availability": defaultdict(list),
        "script-status": defaultdict(list),
        "pages": defaultdict(list),
        "duration": defaultdict(list),
        "cast": defaultdict(list),
    }
    for p in plays_sorted:
        facets["authors"][p.author_display].append(p)
        facets["genres"][p.genre_value].append(p)
        facets["acts"][p.acts_value].append(p)
        facets["availability"][p.availability_value].append(p)
        facets["script-status"][p.script_status_value].append(p)
        facets["pages"][p.pages_bucket].append(p)
        facets["duration"][p.duration_bucket].append(p)
        facets["cast"][p.cast_bucket].append(p)

    # Main index
    body = '<p class="meta">Browse plays by clicking facets in the nav, or jump to a title below.</p>'
    body += lettered_cards_section([(p.title_display, p) for p in plays_sorted], base="", id_prefix="home")
    write(out / "index.html", render_page(template, title="Plays", h1="All Plays", body_html=body, nav_html=nav("", "home"), base=""))

    # Selected
    selected = [p for p in plays_sorted if p.selected]
    sel_body = '<p class="meta">Plays where <code>Select</code> is truthy / non-zero.</p>'
    sel_body += list_cards(selected, base="../") if selected else '<p class="meta">No plays currently marked selected.</p>'
    write(out / "selected" / "index.html", render_page(template, title="Selected Plays", h1="Selected Plays", body_html=sel_body, nav_html=nav("../", "selected"), base="../"))

    # With synopsis
    with_synopsis = [p for p in plays_sorted if p.synopsis]
    syn_body = '<p class="meta">Plays that currently have a synopsis.</p>'
    syn_body += list_cards(with_synopsis, base="../") if with_synopsis else '<p class="meta">No plays currently have a synopsis.</p>'
    write(out / "with-synopsis" / "index.html", render_page(template, title="Plays With Synopsis", h1="Plays With Synopsis", body_html=syn_body, nav_html=nav("../", "with-synopsis"), base="../"))

    # Credits
    credits_body = (
        '<p class="meta">Where this database came from.</p>'
        '<div class="kv">'
        '<div class="k">Seed database</div><div class="v">'
        '<a href="https://www.calaa.org/">CALAA</a></div>'
        '<div class="k">Expanded by</div><div class="v">'
        'Volunteers from <a href="https://www.abhivyakti.org/">Abhivyakti</a>, '
        'especially Manisha Dandekar</div>'
        '<div class="k">Created by</div><div class="v">Ashish Mahabal, with Claude</div>'
        + contributors_row(Path(__file__).parent / "contributors.txt")
        + '</div>'
    )
    write(out / "credits" / "index.html", render_page(template, title="Credits", h1="Credits", body_html=credits_body, nav_html=nav("../", "credits"), base="../"))

    def build_facet(facet_key: str, title: str, active_key: str, lettered: bool = False, description_html: str = "", tabbed: bool = False, unknown_like: set = frozenset(), tiled: bool = False, sublabel_for: Optional[Callable[[str, List[Play]], str]] = None) -> None:
        mapping = facets[facet_key]
        items = []
        for label in sorted(mapping.keys(), key=lambda s: s.lower()):
            href = f"{facet_key}/{slugify(label)}/index.html"
            items.append((label, href))

        ordered_labels: List[str] = []
        default_label: Optional[str] = None
        if tabbed:
            ordered_labels, default_label = pick_tab_order_and_default(mapping, unknown_like)

        intro = description_html or f'<p class="meta">Browse by {html.escape(title.lower())}.</p>'
        if tiled:
            tiles = [
                (label, sublabel_for(label, mapping[label]) if sublabel_for else "", len(mapping[label]), href)
                for label, href in items
            ]
            top_body = intro + tile_grid(tiles, base="../")
        elif tabbed and default_label:
            top_body = intro + facet_tab_subnav(ordered_labels, mapping, default_label, "") + list_cards(mapping[default_label], base="../")
        elif lettered:
            top_body = intro + lettered_section(
                [(label, f"{label} ({len(mapping[label])})", href) for label, href in items],
                base="../", id_prefix=facet_key,
            )
        else:
            top_body = intro + plain_link_table(items, base="../")
        write(out / facet_key / "index.html", render_page(template, title=title, h1=title, body_html=top_body, nav_html=nav("../", active_key), base="../"))

        for label, plist in mapping.items():
            page_body = f'<p class="meta">{html.escape(title[:-1] if title.endswith("s") else title)}: <strong>{html.escape(label)}</strong></p>'
            if tabbed:
                page_body += facet_tab_subnav(ordered_labels, mapping, label, "../")
            page_body += list_cards(plist, base="../../")
            write(out / facet_key / slugify(label) / "index.html", render_page(template, title=f"{title}: {label}", h1=f"{title}: {label}", body_html=page_body, nav_html=nav("../../", active_key), base="../../"))

    # Authors: four lettered indexes (English/Marathi x First/Last name),
    # each its own page with a small view-switcher — not stacked on one long
    # page, since browsing by surname (the standard bibliographic
    # convention) is a genuinely different task from browsing by given name,
    # and forcing a reader to scroll past three lists they don't want isn't
    # a real "index."
    author_mapping = facets["authors"]
    en_first_items: List[Tuple[str, str, str]] = []
    en_last_items: List[Tuple[str, str, str]] = []
    mr_first_items: List[Tuple[str, str, str]] = []
    mr_last_items: List[Tuple[str, str, str]] = []
    for label, plist in author_mapping.items():
        href = f"authors/{slugify(label)}/index.html"
        r = plist[0].row
        en_first = safe_text(r.get("Author_First_English"))
        en_last = safe_text(r.get("Author_Last_English"))
        mr_first = safe_text(r.get("Author_First_Marathi"))
        mr_last = safe_text(r.get("Author_Last_Marathi"))
        if en_first or en_last:
            en_first_items.append((en_first or en_last, label, href))
            en_last_items.append((en_last or en_first, label, href))
        if mr_first or mr_last:
            mr_first_items.append((mr_first or mr_last, label, href))
            mr_last_items.append((mr_last or mr_first, label, href))

    # (view key, label, path relative to authors/, item count) — "en-last"
    # lives at authors/index.html itself so the main nav's "Authors" link
    # goes straight to real content.
    author_views = [
        ("en-last", "English — Last Name", "index.html", len(en_last_items)),
        ("en-first", "English — First Name", "by-en-first/index.html", len(en_first_items)),
        ("mr-last", "Marathi — Last Name", "by-mr-last/index.html", len(mr_last_items)),
        ("mr-first", "Marathi — First Name", "by-mr-first/index.html", len(mr_first_items)),
    ]

    def author_subnav(active_key: str, base_authors: str) -> str:
        links = []
        for key, label, relpath, count in author_views:
            cls = "active" if key == active_key else ""
            links.append(
                f'<a class="{cls}" href="{base_authors}{relpath}">{html.escape(label)} '
                f'<span class="count">({count})</span></a>'
            )
        return '<p class="subnav"><span class="subnav-label">View by:</span> ' + " · ".join(links) + "</p>"

    def write_author_view(active_key: str, subdir: str, items: List[Tuple[str, str, str]], depth_base: str, authors_base: str) -> None:
        _, view_label, _, _ = next(v for v in author_views if v[0] == active_key)
        title = "Authors" if active_key == "en-last" else f"Authors: {view_label}"
        body = '<p class="meta">Browse by author.</p>'
        body += lettered_section(items, base=depth_base, id_prefix="au", toolbar_prefix=author_subnav(active_key, authors_base))
        target = out / "authors" if not subdir else out / "authors" / subdir
        write(target / "index.html", render_page(template, title=title, h1=title, body_html=body, nav_html=nav(depth_base, "authors"), base=depth_base))

    write_author_view("en-last", "", en_last_items, "../", "")
    write_author_view("en-first", "by-en-first", en_first_items, "../../", "../")
    if mr_last_items:
        write_author_view("mr-last", "by-mr-last", mr_last_items, "../../", "../")
    if mr_first_items:
        write_author_view("mr-first", "by-mr-first", mr_first_items, "../../", "../")

    for label, plist in author_mapping.items():
        page_body = f'<p class="meta">Author: <strong>{html.escape(label)}</strong></p>'
        page_body += list_cards(plist, base="../../")
        write(out / "authors" / slugify(label) / "index.html", render_page(template, title=f"Author: {label}", h1=f"Author: {label}", body_html=page_body, nav_html=nav("../../", "authors"), base="../../"))

    build_facet("genres", "Genres", "genres", tiled=True, sublabel_for=lambda label, plist: plist[0].genre_marathi_value)
    build_facet("acts", "Acts", "acts", tabbed=True, unknown_like={"Unknown", "?"})
    build_facet("availability", "Availability", "availability")
    script_status_description = (
        '<p class="meta">What it takes to actually get a copy of the script.</p>'
        '<ul class="status-legend">'
        '<li><span class="chip script-status-shareable">In hand — shareable</span> someone in the group has a copy and it can be shared freely.</li>'
        '<li><span class="chip script-status-restricted">In hand — restricted (copyright)</span> someone has a copy, but it cannot be redistributed publicly.</li>'
        '<li><span class="chip script-status-obtainable">Obtainable</span> not in hand, but a specific named publisher/bookseller is confirmed to hold the Marathi text — a real next step exists.</li>'
        '<li><span class="chip script-status-unavailable">Not currently available</span> no copy in hand and no confirmed source — may still be worth contacting the author, publisher, or another group.</li>'
        '<li><span class="chip">Unknown</span> not yet researched, or the lead found (e.g. an unconfirmed publisher, an old magazine printing) isn\'t concrete enough to act on.</li>'
        '</ul>'
    )
    build_facet("script-status", "Script Status", "script-status", description_html=script_status_description)

    def build_bucket_facet(facet_key: str, title: str, active_key: str, order: List[str], tabbed: bool = False) -> None:
        mapping = facets[facet_key]
        items = []
        for label in order:
            if label in mapping:
                href = f"{facet_key}/{label}/index.html"
                items.append((label, href))
        for label in sorted(set(mapping.keys()) - set(order), key=lambda s: s.lower()):
            href = f"{facet_key}/{slugify(label)}/index.html"
            items.append((label, href))

        ordered_labels: List[str] = []
        default_label: Optional[str] = None
        if tabbed:
            ordered_labels, default_label = pick_tab_order_and_default(mapping, unknown_like={"unknown"}, explicit_order=order)

        if tabbed and default_label:
            top_body = f'<p class="meta">Browse by {html.escape(title.lower())}.</p>'
            top_body += facet_tab_subnav(ordered_labels, mapping, default_label, "") + list_cards(mapping[default_label], base="../")
        else:
            top_body = facet_index(title, items, base="../")
        write(out / facet_key / "index.html", render_page(template, title=title, h1=title, body_html=top_body, nav_html=nav("../", active_key), base="../"))

        for label, plist in mapping.items():
            href_label = label if label in order else slugify(label)
            page_body = f'<p class="meta">{html.escape(title[:-1] if title.endswith("s") else title)}: <strong>{html.escape(label)}</strong></p>'
            if tabbed:
                page_body += facet_tab_subnav(ordered_labels, mapping, label, "../")
            page_body += list_cards(plist, base="../../")
            write(out / facet_key / href_label / "index.html", render_page(template, title=f"{title}: {label}", h1=f"{title}: {label}", body_html=page_body, nav_html=nav("../../", active_key), base="../../"))

    build_bucket_facet("pages", "Pages", "pages", ["unknown", "short", "medium", "long"], tabbed=True)
    build_bucket_facet("duration", "Duration", "duration", ["unknown", "short", "medium", "long"], tabbed=True)
    build_bucket_facet("cast", "Cast", "cast", ["unknown", "small", "medium", "large"])

    # Per play pages
    for p in plays_sorted:
        body = play_detail(p, base="../../", form_cfg=form_cfg)
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
    if len(sys.argv) not in (3, 4):
        print("Usage: generator.py <csv_path> <out_dir> [form_config_json]")
        raise SystemExit(2)
    main(sys.argv[1], sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) == 4 else None)
