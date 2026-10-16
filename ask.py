# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["anthropic", "trafilatura"]
# ///
"""Ask your own questions of every processed article, via Claude Haiku or a local LM Studio model.

Questions live in a text file, one per line (# for comments). Answers go to
out/answers/<questions file name>.csv, one row per (article, question, model).
Re-running only asks what's missing, so you can add questions or articles and run again.

    uv run ask.py questions.txt --limit 5                          # Claude (default Haiku; needs ANTHROPIC_API_KEY)
    uv run ask.py questions.txt --backend lmstudio --model qwen3-32b   # LM Studio server on :1234
"""
import argparse, csv, json, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from pipeline import OUT, append, get_text

HAIKU = "claude-haiku-5-5"
LMSTUDIO_URL = "http://localhost:1234/v1/chat/completions"
COLS = ["article_id", "question", "answered", "answer", "evidence", "evidence_found", "model", "asked_at"]

SYSTEM = """You answer research questions about a single news article for an investigative journalism team.
Use only what the article says. Do not add outside knowledge.
If the article does not address a question, set answered to false and leave answer and evidence empty.
Otherwise give a short, specific answer and copy the sentence that supports it word for word as evidence."""

SCHEMA = {
    "type": "object",
    "properties": {"answers": {"type": "array", "items": {
        "type": "object",
        "properties": {"question_id": {"type": "integer"}, "answered": {"type": "boolean"},
                       "answer": {"type": "string"}, "evidence": {"type": "string"}},
        "required": ["question_id", "answered", "answer", "evidence"],
        "additionalProperties": False}}},
    "required": ["answers"],
    "additionalProperties": False,
}


def prompt(title, text, questions):
    qs = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    return f"<article>\n<title>{title}</title>\n{text}\n</article>\n\nQuestions:\n{qs}"


def ask_haiku(client, model, user):
    r = client.messages.create(
        model=model, max_tokens=8000, system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if r.stop_reason != "end_turn":
        raise RuntimeError(f"stop_reason={r.stop_reason}")
    return json.loads(next(b.text for b in r.content if b.type == "text"))


def ask_lmstudio(model, user):
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "answers", "strict": True, "schema": SCHEMA}}}
    req = Request(LMSTUDIO_URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urlopen(req, timeout=600) as f:
        msg = json.load(f)["choices"][0]["message"]["content"]
    return json.loads(re.sub(r"(?s)^.*</think>", "", msg))  # reasoning models may prefix their thinking


def squash(s):
    return " ".join(s.casefold().split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", type=Path)
    ap.add_argument("--backend", choices=["claude", "lmstudio"], default="claude")
    ap.add_argument("--model", help=f"default {HAIKU} for claude; the loaded model's id for lmstudio")
    ap.add_argument("--limit", type=int, default=0, help="at most N articles (0 = all)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if a.backend == "lmstudio" and not a.model:
        sys.exit("--model is required for lmstudio (the model id shown in LM Studio)")
    model = a.model or HAIKU
    questions = [q.strip() for q in a.questions.read_text("utf-8").splitlines() if q.strip() and not q.startswith("#")]

    out = OUT / "answers" / f"{a.questions.stem}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        with out.open(encoding="utf-8") as f:
            done = {(r["article_id"], r["question"], r["model"]) for r in csv.DictReader(f)}
    with (OUT / "articles.csv").open(encoding="utf-8") as f:
        articles = list(csv.DictReader(f))
    jobs = [(art, [q for q in questions if (art["id"], q, model) not in done]) for art in articles]
    jobs = [(art, qs) for art, qs in jobs if qs]
    if a.limit:
        jobs = jobs[:a.limit]
    print(f"{len(questions)} questions, {len(jobs)} articles with something to ask, model={model}")

    if a.backend == "claude":
        import anthropic
        client = anthropic.Anthropic()
        call = lambda user: ask_haiku(client, model, user)
    else:
        call = lambda user: ask_lmstudio(model, user)
        a.workers = 1  # one local model, one request at a time

    def run(art, qs):
        _, text = get_text(art["id"], art["url"], art["title"])
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        got = {x["question_id"]: x for x in call(prompt(art["title"], text, qs))["answers"]}
        rows = []
        for i, q in enumerate(qs, 1):
            x = got.get(i, {"answered": False, "answer": "", "evidence": ""})
            ev = x["evidence"].strip()
            rows.append({"article_id": art["id"], "question": q, "answered": x["answered"],
                         "answer": x["answer"], "evidence": ev,
                         # flags quotes the model paraphrased or invented
                         "evidence_found": bool(ev) and squash(ev) in squash(text),
                         "model": model, "asked_at": now})
        return art, rows

    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(run, art, qs) for art, qs in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                art, rows = fut.result()
            except Exception as e:  # skipped rows are retried on the next run
                print(f"[{i}/{len(jobs)}] FAILED: {e}", file=sys.stderr)
                continue
            append(out, COLS, rows)
            print(f"[{i}/{len(jobs)}] {sum(r['answered'] for r in rows)}/{len(rows)} answered  {art['title'][:70]}")


if __name__ == "__main__":
    main()
