# Plays site (static, no JS)

This repo generates a browsable static site from `Plays20260103.csv`, in the spirit of a simple "writings" site.

## Build

```bash
./build.sh
# or specify paths:
./build.sh Plays20260103.csv docs
```

## Preview locally

```bash
cd docs
python3 -m http.server 8000
# open http://localhost:8000
```

## Publish via GitHub Pages

- Keep output in `docs/`
- GitHub repo Settings → Pages → Deploy from branch → `main` / `/docs`

## Notes

- "Selected" is inferred from the `Select` column:
  - numeric non-zero is treated as selected
  - also accepts: Y/Yes/True/Selected/Shortlist
- Buckets (auto-derived):
  - Pages: unknown/short/medium/long
  - Duration (minutes): unknown/short/medium/long
  - Cast size (Males+Females): unknown/small/medium/large
