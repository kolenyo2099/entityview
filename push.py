"""Upload out/*.csv and out/answers/*.csv to the results Google Sheet (via apps_script.gs).

    SHEET_URL=https://script.google.com/macros/s/.../exec SHEET_TOKEN=... python3 push.py

Each CSV replaces its tab: articles, mentions, answers_<question set>.
"""
import csv, json, os, sys
from urllib.request import Request, urlopen

from pipeline import OUT, norm

BATCH = 5000  # rows per request, keeps each Apps Script call well under its 6-minute limit
ENTITIES = OUT.parent / "entities.csv"


def curate(rows):
    """Add entity/type columns to mentions from the team's entities.csv.
    GLiNER finds names reliably but labels them inconsistently (CoreCivic came out as
    'armed group' more often than 'company'); the list fixes the type and merges aliases."""
    known = {}
    if ENTITIES.exists():
        with ENTITIES.open(encoding="utf-8") as f:
            for e in csv.DictReader(f):
                for alias in [e["name"], *filter(None, e["aliases"].split("|"))]:
                    known[norm(alias)] = (e["name"], e["type"])
    h = rows[0]
    li, ti, ni = h.index("label"), h.index("text"), h.index("norm")
    return [h + ["entity", "type"]] + [r + list(known.get(r[ni], (r[ti], r[li]))) for r in rows[1:]]


def push(url, token):
    files = sorted(OUT.glob("*.csv")) + sorted((OUT / "answers").glob("*.csv"))
    if not files:
        sys.exit("nothing to push: run extraction first")
    for f in files:
        tab = f.stem if f.parent == OUT else f"answers_{f.stem}"
        with f.open(encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        if tab == "mentions":
            rows = curate(rows)
        # ponytail: replace-whole-tab, so viewers briefly see a partial tab mid-push. Swap tabs atomically if that bites.
        for i in range(0, len(rows), BATCH):
            body = json.dumps({"token": token, "tab": tab, "rows": rows[i:i + BATCH], "reset": i == 0}).encode()
            with urlopen(Request(url, body, {"Content-Type": "application/json"}), timeout=360) as r:
                res = json.load(r)
            if not res.get("ok"):
                sys.exit(f"push failed on {tab}: {res}")
        print(f"pushed {tab}: {len(rows) - 1} rows", flush=True)


if __name__ == "__main__":
    url, token = os.environ.get("SHEET_URL"), os.environ.get("SHEET_TOKEN")
    if not url or not token:
        sys.exit("set SHEET_URL and SHEET_TOKEN")
    push(url, token)
