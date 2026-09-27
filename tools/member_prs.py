#!/usr/bin/env python3
"""
Turn member form responses (Google Sheet) into one pull request each.

Run by .github/workflows/member-prs.yml. For every sheet row:
- no PR yet: branch from main, fill blank CSV fields, set Verified=M, add the
  name to contributors.txt, open a PR, and record its number in the sheet's
  "PR" column (so a response is never picked up twice);
- PR still open: rebuild its branch on top of current main, so PRs can be
  merged in any order without Git conflicts;
- PR merged/closed, or a note like "skipped: ...": leave alone.

Private answers (email, script copy, contact) never leave the sheet.

Env: SHEET_ID, GOOGLE_SA_KEY (service-account JSON), CSV_PATH, GH_TOKEN.
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from generator import existing_values, safe_text  # noqa: E402

CONTRIBUTORS = ROOT / "contributors.txt"

# Form question title -> (existing_values key, CSV column).
FIELDS = {
    "Number of acts": ("acts", "Acts"),
    "Male roles": ("males", "Males"),
    "Female roles": ("females", "Females"),
    "Duration (minutes)": ("minutes", "Length (in minutes)"),
    "Pages": ("pages", "Pages"),
    "Genre": ("genre", "Genre"),
    "Year written": ("year_written", "Year of Writing"),
    "Year first performed": ("year_performed", "First Performance Year"),
    "Short synopsis": ("synopsis", "Synopsis"),
    "Where to get the script": ("availability", "Availability"),
}


# ---------- CSV changes (no network) ----------

def apply_response(rows: List[Dict[str, str]], resp: Dict[str, str]) -> Tuple[Dict[str, str], List[str], List[str]]:
    """Fill blank fields of the play named in resp. Returns (row or {},
    filled lines, conflict lines). Mutates the matching row in place."""
    pid = resp.get("Play ID", "").strip()
    row = next((r for r in rows if r.get("ID", "").strip() == pid), None)
    if row is None:
        return {}, [], []
    current = existing_values(row)
    filled, conflicts, filled_cols = [], [], []
    for question, (key, col) in FIELDS.items():
        value = resp.get(question, "").strip()
        if not value:
            continue
        have = current[key]
        if have:
            if have != value:
                conflicts.append(f"- **{question}**: submitted `{value}`, on file `{have}`")
            continue
        row[col] = value
        filled.append(f"- **{question}**: {value}")
        filled_cols.append(col)
    if filled_cols:
        row["Verified"] = "M"
        stamp = f"[Member {date.today().isoformat()}] filled: {', '.join(filled_cols)}"
        source = resp.get("Source link", "").strip()
        if source:
            stamp += f" (source: {source})"
        row["Notes"] = f"{row['Notes']} | {stamp}" if safe_text(row.get("Notes")) else stamp
    return row, filled, conflicts


def add_contributor(name: str) -> None:
    name = " ".join(name.split())
    lines = CONTRIBUTORS.read_text(encoding="utf-8").splitlines() if CONTRIBUTORS.exists() else []
    if name and name.casefold() not in {" ".join(l.split()).casefold() for l in lines}:
        lines.append(name)
        CONTRIBUTORS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    # Default dialect (CRLF, minimal quoting) round-trips the file byte for byte.
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def pr_body(resp: Dict[str, str], row: Dict[str, str], filled: List[str], conflicts: List[str]) -> str:
    title = safe_text(row.get("Title_English")) or safe_text(row.get("Title_Marathi"))
    parts = [f"Member submission from {resp.get('Timestamp', '')} for play {row['ID']}, *{title}*."]
    parts.append("**Filled (was blank):**\n" + ("\n".join(filled) if filled else "- nothing"))
    if conflicts:
        parts.append("**Not applied, a value is already on file (decide by hand):**\n" + "\n".join(conflicts))
    notes = resp.get("Corrections or other notes", "").strip()
    if notes:
        parts.append("**Corrections / notes from the member:**\n" + "\n".join("> " + l for l in notes.splitlines()))
    how = resp.get("How do you know this?", "").strip()
    if how:
        parts.append(f"**How they know:** {how}")
    source = resp.get("Source link", "").strip()
    if source:
        parts.append(f"**Source link:** {source}")
    parts.append("Merging publishes the filled values with `Verified=M` and adds the "
                 "submitter to the Credits page. Closing this PR rejects the submission. "
                 "This branch is rebuilt automatically while the PR is open, so don't edit it by hand.")
    return "\n\n".join(parts)


# ---------- git / GitHub ----------

def run(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=ROOT).stdout.strip()


def same_as_remote(branch: str) -> bool:
    """True if the remote branch already has this content on current main,
    so refreshing an unchanged PR doesn't push a new commit every week."""
    try:
        run("git", "fetch", "-q", "origin", branch)
    except subprocess.CalledProcessError:
        return False  # new branch
    return (run("git", "rev-parse", "FETCH_HEAD^{tree}", "FETCH_HEAD^") ==
            run("git", "rev-parse", "HEAD^{tree}", "HEAD^"))


def build_branch(branch: str, csv_path: Path, resp: Dict[str, str]):
    """Recreate branch from origin/main with this response applied. Returns
    (row, body) or None if the play ID is unknown."""
    run("git", "checkout", "-q", "-B", branch, "origin/main")
    fieldnames, rows = read_csv(csv_path)
    row, filled, conflicts = apply_response(rows, resp)
    if not row:
        return None
    write_csv(csv_path, fieldnames, rows)
    add_contributor(resp.get("Your name", ""))
    run("git", "add", str(csv_path), str(CONTRIBUTORS))
    run("git", "commit", "-q", "--allow-empty", "-m", f"Member info for play {row['ID']}")
    if not same_as_remote(branch):
        run("git", "push", "-q", "-f", "origin", branch)
    return row, pr_body(resp, row, filled, conflicts)


# ---------- Google Sheet ----------

def sheet_session():
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_SA_KEY"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return AuthorizedSession(creds)


def col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def main() -> None:
    if not os.environ.get("SHEET_ID") or not os.environ.get("GOOGLE_SA_KEY"):
        print("SHEET_ID / GOOGLE_SA_KEY not set; nothing to do")
        return
    csv_path = ROOT / os.environ["CSV_PATH"]
    api = f"https://sheets.googleapis.com/v4/spreadsheets/{os.environ['SHEET_ID']}"
    s = sheet_session()
    tab = s.get(api, params={"fields": "sheets.properties.title"}).json()["sheets"][0]["properties"]["title"]
    values = s.get(f"{api}/values/'{tab}'").json().get("values", [])
    if not values:
        return
    header = values[0]

    def set_cell(row_num: int, col: int, value: str) -> None:
        rng = f"'{tab}'!{col_letter(col)}{row_num}"
        s.put(f"{api}/values/{rng}", params={"valueInputOption": "RAW"},
              json={"values": [[value]]}).raise_for_status()

    if "PR" not in header:
        set_cell(1, len(header), "PR")
        header.append("PR")
    pr_col = header.index("PR")

    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "fetch", "-q", "origin", "main")

    for row_num, cells in enumerate(values[1:], start=2):
        resp = dict(zip(header, cells + [""] * (len(header) - len(cells))))
        pr = resp["PR"].strip()
        if not pr:
            branch = "member/" + re.sub(r"\D", "", resp.get("Timestamp", "")) + f"-{row_num}"
            built = build_branch(branch, csv_path, resp)
            if built is None:
                set_cell(row_num, pr_col, "skipped: unknown play ID")
                continue
            row, body = built
            title = safe_text(row.get("Title_English")) or safe_text(row.get("Title_Marathi"))
            url = run("gh", "pr", "create", "--base", "main", "--head", branch,
                      "--title", f"Member info: {title} (ID {row['ID']})", "--body", body)
            set_cell(row_num, pr_col, url.rstrip("/").rsplit("/", 1)[-1])
            print(f"row {row_num}: opened {url}")
        elif pr.isdigit():
            info = json.loads(run("gh", "pr", "view", pr, "--json", "state,headRefName"))
            if info["state"] != "OPEN":
                continue
            built = build_branch(info["headRefName"], csv_path, resp)
            if built is not None:
                run("gh", "pr", "edit", pr, "--body", built[1])
                print(f"row {row_num}: refreshed PR #{pr}")


if __name__ == "__main__":
    main()
