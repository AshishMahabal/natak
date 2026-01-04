#!/usr/bin/env python3
"""
Create a pandoc HTML template from our existing template.html.

We keep your look & feel by reusing the same HTML and CSS.
We just replace the generator placeholders with pandoc variables.
"""
from __future__ import annotations

import sys
from pathlib import Path


MAP = {
    "{{TITLE}}": "$title$",
    "{{H1}}": "$h1$",
    "{{NAV}}": "$nav$",
    "{{BODY}}": "$body$",
    "{{BASE}}": "$base$",
    "{{GENERATED_AT}}": "$generated_at$",
}


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: make_pandoc_template.py <template.html> <out_template.html>", file=sys.stderr)
        raise SystemExit(2)

    src = Path(sys.argv[1]).read_text(encoding="utf-8")
    out = src
    for k, v in MAP.items():
        out = out.replace(k, v)

    Path(sys.argv[2]).write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
