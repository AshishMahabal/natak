#!/usr/bin/env bash
set -euo pipefail

CSV_PATH="${1:-Plays20260103.csv}"

CONTENT_DIR="content"
OUT_DIR="natak"
ASSETS_DIR="assets"

# 1) Generate Markdown sources (with immutable AUTO blocks)
rm -rf "$CONTENT_DIR"
mkdir -p "$CONTENT_DIR"
python3 generator_pandoc_md.py "$CSV_PATH" "$CONTENT_DIR"

# 2) Prepare output dir
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"
mkdir -p "$OUT_DIR/assets"
cp -R "$ASSETS_DIR/"* "$OUT_DIR/assets/"

# 3) Build a pandoc template from the existing HTML template
python3 tools/make_pandoc_template.py "$ASSETS_DIR/template.html" "$OUT_DIR/.pandoc_template.html"

# 4) Convert every markdown file to HTML into natak/
#    We keep the same relative paths: content/foo/index.md -> natak/foo/index.html
while IFS= read -r -d '' md; do
  rel="${md#$CONTENT_DIR/}"
  out_rel="${rel%.md}.html"
  out_path="$OUT_DIR/$out_rel"
  out_dir="$(dirname "$out_path")"
  mkdir -p "$out_dir"

  pandoc "$md" \
    --from markdown+yaml_metadata_block \
    --to html5 \
    --standalone \
    --template "$OUT_DIR/.pandoc_template.html" \
    -o "$out_path"
done < <(find "$CONTENT_DIR" -type f -name "*.md" -print0)

# 5) GitHub Pages niceties
touch "$OUT_DIR/.nojekyll"

echo "Built site into $OUT_DIR/ (open $OUT_DIR/index.html)"
