# Chunking & Embedding Pipeline

How the NCC 2025 Volume Two and ABCB Housing Provisions source documents become
searchable, embedded rows in `clause_chunks`. Two independent stages:

1. **Chunking** (`backend/app/ingest/`) — parse the raw XML export into structured
   JSON chunk records, resolving cross-references and folding in figure
   descriptions along the way. No network calls, no database.
2. **Embedding** (`backend/scripts/`) — call the Gemini embedding model over
   every chunk's text and write the resulting vector back into the chunk
   record, ready to load into Postgres.

```
ncc-2025-volume-two-v1.2/contents.xml  ─┐
ncc-2025-housing-provisions-v1.2/...   ─┤
image description store (.jsonl)       ─┤
                                        ▼
                          app/ingest/cli.py  (python -m app.ingest.cli)
                                        │
                                        ▼
        output/ncc_volume_two_chunks.json           (1,286 chunks)
        output/abcb_housing_provisions_chunks.json   (2,010 chunks)
        output/ingest.report.json                    (validation stats)
                                        │
                                        ▼
                     scripts/embed_chunks.py  (Gemini gemini-embedding-2, 768-dim)
                                        │
                                        ▼
        output/ncc_volume_two_chunks.embedded.json
        output/abcb_housing_provisions_chunks.embedded.json
                                        │
                                        ▼
                             clause_chunks table (Supabase / pgvector)
```

---

## 1. Chunking — `backend/app/ingest/`

### Source data

Both documents ship as a single `contents.xml` per corpus (a real nested tree:
`ncc-volume`/`ncc-standard` → `ncc-section` → `part`/`specification` → `subtopic`
→ `clause` → `subclause` → `content`), plus a sibling `images/` folder
referenced by plain filename. This is the "v1.2 schema" referenced throughout
the code — a full re-export from the client, not an incremental change from
whatever came before it.

### What one chunk is

One chunk = one `<subclause>` — that's the granularity the NCC is actually
cited at (e.g. "H1D4(2)"). Everything else that should be independently
retrievable and citable also becomes its own chunk: notes/callouts, tables,
figures, glossary entries, Parts/Specifications (their intro text), and
state-specific clause/part variations.

`ChunkRecord` ([records.py](../backend/app/ingest/records.py)) is the shape
every parser builds and the shape written to JSON — it mirrors the
`clause_chunks` DB columns 1:1 so nothing needs remapping at load time:

| field | meaning |
|---|---|
| `id` | UUID, becomes the DB primary key |
| `node_type` | `subclause` \| `note` \| `table` \| `figure` \| `glossary` \| `part` \| `specification` |
| `clause_id` | the real citable number, e.g. `H1D4`, `10.8` |
| `hierarchy` | ancestor path, e.g. `["NCC 2025 Volume Two", "A Governing requirements", "A1 Interpreting the NCC", "A1G1"]` |
| `heading` | clause/table/figure title |
| `doc` | which corpus this came from |
| `text` | the actual content that gets embedded |
| `defined_terms` | glossary terms referenced from this chunk |
| `cross_refs` | raw citation text as printed (e.g. `"AS 3600"`) |
| `internal_refs` | resolved links to other chunks *in this corpus pair* — `{clause_id, chunk_id}` |
| `external_refs` | hand-offs outside the corpus — AS/NZS standards, or a citation into the other volume |
| `image_refs` | figures referenced inline from this chunk's text |
| `building_classes` / `jurisdictions` / `climate_zones` / `applicability_note` | applicability qualifiers, `NULL`/empty = applies to everything |

### Module map

| file | responsibility |
|---|---|
| [`corpus.py`](../backend/app/ingest/corpus.py) | loads one `contents.xml` into an lxml tree + its `images/` path |
| [`chunker.py`](../backend/app/ingest/chunker.py) | the core: `<clause>` → one `ChunkRecord` per `<subclause>`/`<callout>`; renders paragraphs/lists/equations/MathML to plain text (`render_content`); walks every `<a href="#_GUID">` and classifies it (`extract_refs`) |
| [`hierarchy.py`](../backend/app/ingest/hierarchy.py) | `ancestor_path()` — walks `iterancestors()` directly (the schema is a real tree, no GUID-stub indirection needed) |
| [`applicability.py`](../backend/app/ingest/applicability.py) | reads `building=`/`climate=`/`state=` attributes into `building_classes`/`climate_zones`/`jurisdictions` |
| [`guid_index.py`](../backend/app/ingest/guid_index.py) | builds one GUID→element index across **both** corpora, so a citation from Volume Two into Housing Provisions (or vice versa) resolves directly, no fuzzy text matching |
| [`resolve_internal_refs.py`](../backend/app/ingest/resolve_internal_refs.py) | final pass, run once every chunk from both corpora exists: turns each ref's target GUID into a real `chunk_id` (a `<clause>` root maps to its first `<subclause>`/`<callout>` chunk, since chunks are subclause-granularity) |
| [`standards.py`](../backend/app/ingest/standards.py) | regex-extracts bare "AS 1288" / "AS/NZS 3500.1" mentions (never `<a>`-wrapped in the source) and matches them against every "Schedule of referenced documents" table in the corpus |
| [`housing_citations.py`](../backend/app/ingest/housing_citations.py) | same idea for a different bug: NCC text citing the Housing Provisions in bare prose with no link at all (e.g. *"...Section 4 of the ABCB Housing Provisions"*) — regex-extracted, then matched against the Housing Provisions' own Part/Clause/Table/Figure numbering |
| [`table_parser.py`](../backend/app/ingest/table_parser.py) | `<table-reference>` → one chunk, real cell content rendered as `\|`-delimited rows (not just the caption) |
| [`figure_parser.py`](../backend/app/ingest/figure_parser.py) | `<image-reference>` → one chunk; folds in a figure's transcription (see below) if one is on file, otherwise the chunk is caption-only |
| [`image_descriptions.py`](../backend/app/ingest/image_descriptions.py) | loads the `DescriptionStore` written by `scripts/describe_images.py` so figure chunks carry the drawing's actual labels/dimensions, not just a title; `describe_missing()` can transcribe on the fly (`--describe-missing-images`, needs `GEMINI_API_KEY`) but is opt-in — ingest itself makes no network calls by default |
| [`part_spec_parser.py`](../backend/app/ingest/part_spec_parser.py) | `<part>`/`<specification>` intro text, plus `<part-variation>` (a whole-Part jurisdiction note, e.g. "this Part doesn't apply in Tasmania") |
| [`glossary_parser.py`](../backend/app/ingest/glossary_parser.py) | `<glossentry>` → one chunk per defined term |
| [`serialize.py`](../backend/app/ingest/serialize.py) | writes the chunk list to JSON — this stage's only output |
| [`report.py`](../backend/app/ingest/report.py) | the validation summary the CLI prints (and writes to `ingest.report.json`) after every run: chunk counts by type, image/standards/ref match rates |
| [`cli.py`](../backend/app/ingest/cli.py) | orchestrates all of the above end to end |

### Running it

```bash
cd backend
python -m app.ingest.cli \
    --data-dir /path/containing/both/ncc-2025-*-v1.2/folders
```

Both corpora are always loaded together — required so a citation from one
into the other resolves to a real `chunk_id` — but each is still written to
its own file:

- `output/ncc_volume_two_chunks.json`
- `output/abcb_housing_provisions_chunks.json`
- `output/ingest.report.json` — the validation report

Flags:
- `--image-descriptions <path...>` — point at a figure-description store from
  `scripts/describe_images.py` (defaults to `<out-dir>/{vol2,housing}_image_descriptions.jsonl`)
- `--describe-missing-images` — transcribe any matched figure with no stored
  description before parsing (costs one Gemini call per figure)

This stage makes **no other network calls** and writes **no database rows** —
its only output is the JSON above.

---

## 2. Embedding — `backend/scripts/`

### Decisions

- **Model:** `gemini-embedding-2` — `text-embedding-004` (the originally
  planned model) has since been **retired** from the Gemini API.
- **Dimension:** `768`, requested via `output_dimensionality` (the model's
  native output is 3072; pgvector's HNSW index is capped at 2000 dimensions
  for a plain `vector` column, so the output is truncated to fit).
- **Content embedded:** chunk `text` only (not `heading`).

### `scripts/test_embedding.py` — smoke test

Grabs one chunk from an ingest output file, embeds it, prints the vector.
Nothing is written anywhere; it exists purely to confirm the API key, model
name and SDK work before running the real job.

```bash
python scripts/test_embedding.py --clause-id H1D4
```

### `scripts/embed_chunks.py` — the real job

Batch-embeds both ingest output files and writes the vector into each chunk
record, producing `output/<name>_chunks.embedded.json` — the file that
actually gets loaded into the database.

**Why it's more than a for-loop:** the free Gemini tier has a per-key daily
quota that one key cannot cover for ~3,300 chunks, so this is a job the whole
team runs together, and it has to survive that:

- **Resumable across people, not just across runs.** The merged
  `.embedded.json` file — the thing that gets committed and pulled — *is* the
  shared progress record. On startup the script reads whatever vectors are
  already in it and only embeds what's missing, so pulling a teammate's
  partial progress and continuing never re-embeds (and never re-pays for) a
  chunk twice. A local, git-ignored, append-only `.jsonl` log backs this up
  batch-by-batch in case of a crash mid-run.
- **Settings guard.** A committed `.meta.json` records the model/dimension/
  content-mode a file's vectors were built with; the script refuses to
  resume with different settings rather than silently mixing incompatible
  vectors.
- **Ctrl-C safe.** Stops after the current batch; everything embedded so far
  is already on disk.
- **Quota handling.** A short per-minute 429 is waited out; a long/repeated
  one is treated as that key's daily quota being spent, and the script
  rotates to the next key in `GEMINI_API_KEYS=k1,k2,k3` (env var / `.env`).
  When every key is exhausted it writes what it has and exits non-zero —
  re-run later, or with more keys, to keep going.

```bash
python scripts/embed_chunks.py --dry-run                                    # see the plan, no API calls
python scripts/embed_chunks.py --file app/ingest/output/ncc_volume_two_chunks.json
```

Team workflow and full instructions (making a free API key, where it goes,
coordinating so two people don't fight over the same file): see
[`backend/EMBEDDING.md`](../backend/EMBEDDING.md).

### Output shape

Every chunk in `<name>_chunks.embedded.json` gains three keys:

```json
{
  "...": "...every ChunkRecord field, unchanged...",
  "embedding": [0.0290292, 0.0329909, "...", 768 floats total],
  "embedding_model": "gemini-embedding-2",
  "embedding_dim": 768
}
```

---

## 3. Loading into the database

`clause_chunks` (Supabase Postgres + pgvector) is defined in
[`backend/app/models/clause_chunk.py`](../backend/app/models/clause_chunk.py)
and created by Alembic migrations `0001`–`0003`
([`backend/migrations/versions/`](../backend/migrations/versions/)). The two
`.embedded.json` files are loaded as-is — one row per chunk, `embedding`
already populated, a generated `text_tsv` column giving lexical (BM25-style)
search alongside the vector column for hybrid retrieval later.

At time of writing: **NCC 660/1,286** embedded, **ABCB 0/2,010** — check
current counts with `python scripts/embed_chunks.py --dry-run` or
`SELECT doc, count(*) FROM clause_chunks GROUP BY doc;` against the DB.

---

## 4. Contributors

| commit | date | author | what |
|---|---|---|---|
| [`9be96f3`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/9be96f37cba694d03ce8f5dfdc066c713fa50d00) | 2026-09-02 | Jonathan Wong | Initial scaffold |
| [`c521ee7`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/c521ee7d3964b3314033753030fa5bc84446c813) | 2026-09-03 | Shrikha Pentakota | Lock in Gemini + LlamaParse; add Alembic and initial DB schema |
| [`8d7cfb0`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/8d7cfb045efbf133490b8510443ce1744f6c7e2d) | 2026-09-03 | Shrikha Pentakota | Migration 0002: typed refs, applicability qualifiers, node_type |
| [`af1ce69`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/af1ce6962ddb263ff0cef4027de65b8c4a072855) | 2026-09-03 | Shrikha Pentakota | Migration 0003: full-text tsvector column + GIN index |
| [`2fbd014`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/2fbd014454436a035788b649755a735dd9eaeadb) / [`122e04e`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/122e04efe5e78dc3029f991c9f531260c498101a) | 2026-09-06 | Rishi Vanal | Added the ingest pipeline (`app/ingest/`) that creates the chunks |
| [`c1466a7`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/c1466a79e599f9f1c3c53d8f4b2ef3da01dafd99) | 2026-09-08 | Aston Bailey-Fong | Image reader (`scripts/describe_images.py`, `services/image_description.py`) |
| [`ee39778`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/ee397787a8f1a234ba04bac23591daa221e178e3) | 2026-09-10 | Rishi Vanal | Chunk JSONs (ingest run output committed) |
| [`c58a983`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/c58a9833a841b37f8a5a316371dec24e973c277d) | 2026-09-10 | Rishi Vanal | Embedding started (`scripts/embed_chunks.py`, `scripts/test_embedding.py`) |
| [`072f539`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/072f539d1d7a8d8196cb29d312509121bc1a2f69) | 2026-09-10 | Rishi Vanal | Embedding team instructions (`backend/EMBEDDING.md`) |
| [`9294bab`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/9294baba546d5f2ed03ca329f47450a4d3411835) | 2026-09-12 | Aston Bailey-Fong | Integrated image transcription into ingest + document upload (`image_descriptions.py`, `figure_parser.py` description folding) |
| [`9265349`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/926534938eefce4545d48d2eb4637a42364725d5) | 2026-09-12 | Rishi Vanal | Embedding finished (first NCC batch through) |
| [`ff28a91`](https://github.sydney.edu.au/abai9699/COMP3888_TH10_01/commit/ff28a91e4ebc1532d6e73aaef2f8692e40d4ffc9) | 2026-09-12 | Rishi Vanal | Merged `embedding` branch into `main` |

*(Generated from `git log`; re-run `git log --pretty=format:'%h\|%ad\|%an\|%s' --date=short -- backend/app/ingest/ backend/scripts/` to refresh after new commits.)*

---

## 5. Not yet done

- Hybrid retrieval (dense + lexical, RRF fusion) and reranking — schema is
  ready (`embedding` + `text_tsv`), services are stubs
  (`app/services/retrieval.py`)
- Finish embedding ABCB Housing Provisions (0/2,010 so far) and the remaining
  NCC chunks
- Load both finished `.embedded.json` files into `clause_chunks`
- Move off `google-generativeai` (end-of-life) to `google-genai`
