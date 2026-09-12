# Embedding the NCC / ABCB chunks

We split the two Codes into ~3,300 text chunks (`app/ingest/output/*_chunks.json`).
Each chunk needs an **embedding vector** so we can do semantic search over it.
`scripts/embed_chunks.py` calls the Gemini embedding model for every chunk and
writes the vector back into the chunk record.

The free Gemini tier has a **daily quota per API key**, and one key isn't enough
to finish all 3,300 in a day. So this is a shared job: everyone runs it with
their own key, the script picks up where the last person left off, and progress
is committed back to git. **You will not re-embed chunks someone else already
did** — the script skips them.

---

## What you need to do (short version)

1. Make a free Gemini API key (below).
2. Put it in `backend/.env`.
3. `git pull`, run the script for your assigned file, let it run until it stops.
4. Commit the updated `.embedded.json` and push.
5. Tell the next person it's their turn (for that file).

---

## 1. Make a Gemini API key

1. Go to **<https://aistudio.google.com/apikey>**
2. Sign in with any Google account (use your uni or personal Google account —
   each account gets its own free quota).
3. Click **Create API key** → **Create API key in new project**.
4. Copy the key. It looks like `AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`.

It's on the free tier by default — no billing, no card. If you have two Google
accounts you can make two keys and the script will rotate between them.

## 2. Add the key to `backend/.env`

If you don't have a `.env` yet:

```bash
cd backend
cp .env.example .env
```

Open `backend/.env` and set:

```
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Two keys? Use this instead (comma-separated, no spaces):

```
GEMINI_API_KEYS=AIzaKeyFromAccountA,AIzaKeyFromAccountB
```

`.env` is git-ignored — your key never gets committed.

## 3. Set up the environment (once)

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 4. Run it

Always `git pull` first so you start from the latest progress.

```bash
cd backend
source venv/bin/activate

# check status without spending any quota:
python scripts/embed_chunks.py --dry-run

# run it — do the file you were assigned:
python scripts/embed_chunks.py --file app/ingest/output/ncc_volume_two_chunks.json
#   or
python scripts/embed_chunks.py --file app/ingest/output/abcb_housing_provisions_chunks.json
```

It prints a running count, rate, and ETA. Leave it going. It will stop on its
own when your key's quota runs out:

```
  stopping — every key is out of quota (812 embedded this run)
  wrote 1472/2010 vectors → abcb_housing_provisions_chunks.embedded.json
incomplete — 812 embedded this run
```

`incomplete` and exit code `3` just mean "not finished, run again later" — it's
not an error. **Ctrl-C** is also safe: it stops after the current batch and
saves everything so far.

## 5. Commit your progress

The vectors go into `*_chunks.embedded.json` (a big file — that's expected).

```bash
git add app/ingest/output/*.embedded.json app/ingest/output/embeddings/*.meta.json
git commit -m "Embed chunks: <file> now at N/total"
git push
```

Then message the group so the next person can pull and continue that file.

---

## How the team coordinates

- **One person per file at a time.** The two files
  (`ncc_volume_two_chunks` and `abcb_housing_provisions_chunks`) are
  independent, so two people *can* work in parallel **as long as they're on
  different files** — no git conflict.
- Two people on the *same* file at the same time = merge conflict on a 10 MB
  JSON. Don't. Go one after another: pull → run → push → hand off.
- The `*.embedded.json` file **is** the shared progress. When you pull it and
  run the script, it reads the vectors already in there and only embeds the
  chunks that are still missing. Nothing is paid for twice.

Current state (update as you go):

| file | chunks | embedded |
| --- | --- | --- |
| `ncc_volume_two_chunks` | 1,286 | 660 |
| `abcb_housing_provisions_chunks` | 2,010 | 0 |

---

## Settings — don't change these

Everyone must embed with the **same** model and dimension or the vectors won't
be comparable. The defaults are already correct:

- model: `gemini-embedding-2`
- dimensions: `768`
- content: chunk text only (no `--with-heading`)

The script enforces this — if the `.embedded.json` was built with different
settings it refuses to run rather than mixing incompatible vectors. Just run the
plain command in step 4 and you'll be fine.

---

## Troubleshooting

| symptom | what it means |
| --- | --- |
| `No API key found` | `GEMINI_API_KEY` missing/empty in `backend/.env` |
| `429 ... waiting 20s (per-minute limit)` | normal — free tier is 100 requests/min, it throttles itself |
| `quota exhausted` then `incomplete` / exit 3 | your key's **daily** quota is gone; commit + push, someone else continues tomorrow or now with their key |
| `google-generativeai is not installed` | run `pip install -r requirements.txt` inside the venv |
| refuses to run, mentions "already holds ... vectors" | someone used different settings; don't override — ask the group |

## Files the script touches

| path | committed? | what |
| --- | --- | --- |
| `app/ingest/output/<name>_chunks.json` | yes (input) | the chunks, untouched |
| `app/ingest/output/<name>_chunks.embedded.json` | **yes** | output — chunks + `embedding` (768 floats), `embedding_model`, `embedding_dim`. This is the shared progress. |
| `app/ingest/output/embeddings/<name>_chunks.jsonl` | no (git-ignored) | local append-only log; safe to delete, it rebuilds from the `.embedded.json` |
| `app/ingest/output/embeddings/<name>_chunks.meta.json` | yes (tiny) | records the model/dim/mode so everyone stays consistent |

Once every chunk in both files has an `embedding`, we're done — the next step is
loading the `.embedded.json` files into the database.
