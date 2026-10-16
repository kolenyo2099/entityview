# Canary pipeline

Pulls new rows from the Canary sheet, fetches each article, extracts the entity types you choose locally with GLiNER,
optionally asks your own questions with an LLM (local LM Studio or Claude), and pushes everything
to a results Google Sheet.

## Start

```bash
python3 app.py
```

Open http://127.0.0.1:8765. Needs [uv](https://docs.astral.sh/uv/); dependencies install on first run.
The first extraction also downloads the GLiNER model (~1.5 GB, once).

## Set it up for your research

Nothing is tied to one topic. In the panel's **What to extract** box, list the entity types your
research cares about, one per line, in plain words: GLiNER takes them as written, no training.
For example, a land-rights project might use `person, company, community, river, mining concession,
court, law or policy, money amount, date`. Specific types work better than vague ones: with a
catch-all "organization", companies get absorbed into it.

After changing the types, tick **Re-extract every article** and press **Extract entities (GLiNER)**
once. That reprocesses everything from cached text, about an hour for 2,000 articles; normal runs
only process new rows. Then push, and the viewer picks up the new types on its own.

## Connect the results sheet (once)

1. Create a Google Sheet for results → Extensions → Apps Script → paste `apps_script.gs`.
2. Project Settings → Script properties → add `TOKEN` = a long random string.
3. Deploy → New deployment → Web app, Execute as **Me**, access **Anyone** → copy the `/exec` URL.
4. Paste URL and token into the panel. "Push to sheet" fills these tabs:

| Tab | One row per |
|---|---|
| `articles` | article: who saved it, project, tags, language, whether full text was fetched |
| `mentions` | entity found: `label` (company, person, government agency, money amount…), text, `norm` (grouping key), score, surrounding text |
| `answers_<set>` | article × question: answer, supporting quote, `evidence_found` (quote really is in the article) |

## Explorer: `index.html`

The team's view of the data. It reads the results sheet live every time it opens (it must stay
published: File → Share → Publish to web), so it is always current after a push. It shows:
- how the database grows, per person or project;
- the most-mentioned entities of the **Focus** type you pick (companies, people, facilities, any type in the data);
- a network connecting any combination of up to five types (people and companies, agencies and courts…) through the articles that mention them;
- a world map of coverage;
- a searchable table of every entity.

Selecting any name opens its source sentences, linked to the exact sentence in the original article,
plus everything it appears alongside.

Open it by double-clicking the file, at http://127.0.0.1:8765/explorer while the panel runs, or host the
single file anywhere static (GitHub Pages, Netlify Drop, a shared drive). The sheet links and readable
project names are set at the top of its script (`PROJECT_NAMES`).

## Curating entities: `entities.csv`

GLiNER finds names reliably but labels the same organization inconsistently from article to article
(CoreCivic came out as "armed group" more often than "company"). `entities.csv` fixes that:
one row per entity with its canonical `name`, `type`, and `|`-separated `aliases`. It's applied at
push time, adding `entity` and `type` columns to the `mentions` tab, so editing it only needs a re-push,
never a re-extraction. Group by `entity`/`type` in dashboards, not by the raw `text`/`label`.

## How runs work

- **Extract** only processes Canary rows not already in `out/articles.csv`. Delete `out/articles.csv` and `out/mentions.csv` to reprocess everything (article text stays cached in `out/texts/`).
- **Ask** only asks questions an article hasn't been asked yet by that model. Add a question and re-run: only the new one is asked.
- **Push** replaces each tab with the current local CSV.

## Files

`pipeline.py` extraction · `ask.py` LLM questions · `push.py` upload · `app.py` + `ui.html` control panel ·
`apps_script.gs` sheet receiver · `entities.csv` curated names/types · `test_pipeline.py` self-check (`python3 test_pipeline.py`)

All three scripts also run from the command line; see the docstring at the top of each.
