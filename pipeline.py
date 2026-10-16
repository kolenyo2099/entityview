# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["gliner", "trafilatura", "protobuf"]  # protobuf: needed to load mdeberta's tokenizer
# ///
"""Canary -> GLiNER entity extraction.

Reads the published Canary sheet, skips rows already in out/articles.csv,
fetches article text, runs GLiNER, appends to out/articles.csv + out/mentions.csv.

    uv run pipeline.py --limit 50
"""
import argparse, csv, re, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from urllib.request import urlopen

CANARY_CSV = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTapAMv0H6WBEwm1_YdEv6x6NKnz30vEDpbYi4gHEUhSumry70hjQRq61gjWWZ2YVWrFAlnybaE9WEO/pub?output=csv"
MODEL = "urchade/gliner_multi-v2.1"  # multilingual: eng/spa/fra/...
# Specific labels matter: with a vague "organization" label, companies get absorbed by it
# (e.g. Omni Air International came out as "government agency"). "news outlet" soaks up media names.
LABELS = ["company", "airline", "state-owned company", "news outlet", "person", "government agency",
          "non-profit organization", "international organization", "armed group", "political party",
          "country", "city", "detention facility", "court", "law or policy", "money amount", "date"]
THRESHOLD = 0.5
# ponytail: hard cap; a few "articles" are database pages (one is 4 MB). Raise if long-form pieces get cut.
MAX_CHARS = 60_000
OUT = Path(__file__).parent / "out"
ARTICLE_COLS = ["id", "project_id", "saved_at", "saved_by", "source_type", "datetime_utc", "language",
                "title", "url", "tags", "text_source", "text_chars", "n_entities", "processed_at"]
MENTION_COLS = ["article_id", "label", "text", "norm", "score", "context"]

SUFFIXES = r"(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|plc|sa|s a|sas|ag|gmbh|lp|llp|nv|bv)"


def norm(name):
    """Grouping key: casefold, drop punctuation and legal suffixes. 'GEO Group, Inc.' -> 'geo group'."""
    s = re.sub(r"[^\w\s&]", " ", name.casefold())
    s = re.sub(r"^the\s+", "", " ".join(s.split()))
    while (t := re.sub(rf"\s+{SUFFIXES}$", "", s)) != s:
        s = t
    return s


def keep(e):
    """Drop generic nouns ('lawyers', 'centros de detención'): named entities have a capital or digit."""
    return e["label"] == "date" or any(c.isupper() or c.isdigit() for c in e["text"])


def label(e):
    """A legal-form suffix (LLC, Inc., S.A.) makes it a company whatever GLiNER said."""
    if re.search(rf"\s{SUFFIXES}\.?$", re.sub(r"[^\w\s&]", " ", e["text"].casefold()).strip()):
        return "company"
    return e["label"]


def chunks(text, max_words=120):
    """Pack paragraphs into <=max_words chunks. GLiNER truncates at 384 tokens; 120 words stays under it even in Spanish/French."""
    out, cur = [], []
    for para in text.split("\n"):
        words = para.split()
        while words:
            room = max_words - len(cur)
            if room == 0:
                out.append(" ".join(cur)); cur = []
                continue
            cur += words[:room]; words = words[room:]
    if cur:
        out.append(" ".join(cur))
    return out


def fetch_text(url, title, snippet=""):
    import trafilatura
    # ponytail: Google News redirect URLs aren't decoded; those fall back to title. Add googlenewsdecoder if they matter.
    if "news.google.com" not in url:
        try:
            html = trafilatura.fetch_url(url)
            text = html and trafilatura.extract(html, include_comments=False)
            if text and len(text) > 300:
                return "article", text
        except Exception as e:
            print(f"  fetch failed {url}: {e}", file=sys.stderr)
    if snippet.strip():
        return "snippet", f"{title}\n{snippet}"
    return "title", title


def get_text(id, url, title, snippet=""):
    """fetch_text, cached in out/texts/<id>.<source>.txt so later runs (ask.py) don't refetch."""
    cached = next((OUT / "texts").glob(f"{id}.*.txt"), None)
    if cached:
        return cached.suffixes[0][1:], cached.read_text("utf-8")
    src, text = fetch_text(url, title, snippet)
    (OUT / "texts").mkdir(parents=True, exist_ok=True)
    (OUT / "texts" / f"{id}.{src}.txt").write_text(text, "utf-8")
    return src, text


def read_ids(path):
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as f:
        return {r["id"] for r in csv.DictReader(f)}


def append(path, cols, rows):
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols)
        if new:
            w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="process at most N new rows (0 = all)")
    ap.add_argument("--source", default=CANARY_CSV, help="Canary CSV url or path")
    a = ap.parse_args()

    raw = urlopen(a.source).read().decode("utf-8") if a.source.startswith("http") else Path(a.source).read_text("utf-8")
    done = read_ids(OUT / "articles.csv")
    todo, seen = [], set(done)
    for r in csv.DictReader(StringIO(raw)):
        if r["l"] not in seen:  # also dedupes repeated ids within the sheet
            seen.add(r["l"]); todo.append(r)
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(done)} already processed, {len(todo)} to do")
    if not todo:
        return

    with ThreadPoolExecutor(8) as ex:
        texts = list(ex.map(lambda r: get_text(r["l"], r["url"], r["title_or_summary"], r["snippet_or_context"]), todo))

    from gliner import GLiNER
    model = GLiNER.from_pretrained(MODEL)
    OUT.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for i, (r, (src, text)) in enumerate(zip(todo, texts), 1):
        mentions = []
        for ch in chunks(text[:MAX_CHARS]):
            for e in filter(keep, model.predict_entities(ch, LABELS, threshold=THRESHOLD)):
                mentions.append({"article_id": r["l"], "label": label(e), "text": e["text"],
                                 "norm": norm(e["text"]), "score": round(e["score"], 3),
                                 "context": ch[max(0, e["start"] - 120):e["end"] + 120]})
        # write per article so a crash mid-run loses nothing already done
        append(OUT / "mentions.csv", MENTION_COLS, mentions)
        append(OUT / "articles.csv", ARTICLE_COLS, [{
            "id": r["l"], "project_id": r["project_id"], "saved_at": r["saved_at"], "saved_by": r["saved_by"],
            "source_type": r["source_type"], "datetime_utc": r["datetime_utc"], "language": r["doc_language"],
            "title": r["title_or_summary"], "url": r["url"], "tags": r["tags"], "text_source": src,
            "text_chars": len(text), "n_entities": len(mentions), "processed_at": now}])
        print(f"[{i}/{len(todo)}] {src:7} {len(mentions):3} ents  {r['title_or_summary'][:70]}", flush=True)


if __name__ == "__main__":
    main()
