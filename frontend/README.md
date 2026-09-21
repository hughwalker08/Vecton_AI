# Frontend — Vecton AI Construction Compliance Assistant

React + Vite frontend: Supabase-authenticated chat UI over `/api/chat`
(question + jurisdiction in, a plain-text cited answer + a clause-by-clause
source panel out) and a document upload UI over `/api/upload`.

## Setup

```bash
npm install
cp .env.example .env   # fill in VITE_SUPABASE_URL, VITE_SUPABASE_PUBLISHABLE_KEY
```

These are Supabase Auth's project URL and public "publishable" key (Settings
→ API on the same Supabase project the backend's `DATABASE_URL` points at) —
safe to ship to the browser, unlike the backend's secrets. See the root
`README.md` for why the frontend needs its own `.env` rather than sharing
the backend's.

## Run (dev server, proxies `/api` to the backend on `:8000`)

```bash
npm run dev
```

## Tests

```bash
npm test              # run once
npm run test:watch    # re-run on change
npm run test:coverage # with a coverage report
```

Uses Vitest + React Testing Library, jsdom environment (config in
`vite.config.js`'s `test` block). Tests live next to the code they cover
(`Component.test.jsx`).

## Structure

```
src/
  main.jsx                # React entry point
  App.jsx                 # auth gate (Supabase session -> onboarding -> app
                           # shell) + router; owns the chats list (persisted,
                           # see lib/chats.js) and the still-in-memory-only
                           # uploaded-files list
  theme.css                # design tokens (--paper, --ink, --accent, etc.)
  lib/
    supabase.js             # Supabase client (VITE_SUPABASE_URL/PUBLISHABLE_KEY)
    chats.js                  # chat history CRUD, direct to Supabase (RLS-secured,
                               # not routed through the backend -- see its own
                               # header comment for why)
    jurisdictions.js          # AUSTRALIAN_JURISDICTIONS (ACT/NSW/NT/QLD/SA/TAS/VIC/WA)
  api/
    client.js                 # askQuestion() / uploadDocument() -- throws with
                               # the backend's actual error detail on a non-2xx
                               # response (e.g. the 429 quota message)
  components/
    Sidebar.jsx                # chat list + upload link + sign out
    SourcePanel.jsx             # one retrieved clause (see Citation in
                                 # backend/app/api/routes/chat.py) as a source card
  pages/
    LoginPage.jsx                # Google OAuth via Supabase
    OnboardingPage.jsx            # collects jurisdiction once, on first sign-in
                                   # -> user_profiles (backend migration 0004, RLS)
    HomePage.jsx                   # start a new chat
    ChatPage.jsx                    # the chat UI itself
    UploadPage.jsx                   # drag-drop upload, per-file status
```

## Auth + onboarding flow

`App.jsx` gates the whole app on Supabase Auth: signed out -> `LoginPage`
(Google OAuth); signed in but no `user_profiles` row yet -> `OnboardingPage`
(collects a jurisdiction, upserted via Supabase directly, RLS-scoped to that
user); otherwise the real app shell (`Sidebar` + routed pages). The
jurisdiction collected here is what gets sent to `/api/chat` and used for
retrieval filtering + the system prompt on the backend (see
`backend/README.md` → "Retrieval + generation").

## Chat

`ChatPage` sends the question + jurisdiction to `/api/chat` and renders the
answer as **plain text, not Markdown** — the backend's system prompt is
written to avoid Markdown syntax specifically because this UI displays raw
text (`white-space: pre-wrap` preserves the answer's paragraph breaks; see
`generation.py`'s "Formatting" instruction). Citations come back as full
clause data (not just an ID), rendered via `SourcePanel` -- clause text,
document, applicability qualifiers, all without a second round trip to the
backend. A non-2xx response (empty question, no relevant source, Gemini/HF
quota exhausted) is surfaced as a real error message via `api/client.js`
rather than silently rendering a blank reply.

## Upload

`UploadPage` handles drag-drop / file-picker upload to `/api/upload`,
tracking each file's status (uploading / described / error) client-side.
It surfaces the image-transcription results `/api/upload` already returns
(see `backend/README.md` → "Image / diagram transcription"). It does **not**
yet call `/api/compliance/analyse` or show findings — that wiring isn't
built on this side yet (see below).

## Not yet implemented / known gaps

- **Compliance check document text is pasted, not extracted.** The
  "Compliance Check" section of `UploadPage.jsx` calls
  `/api/compliance/analyse` and shows its addressed/contradicted/missing/
  needs_review findings, but the "Document" dropdown there is only a label
  for which uploaded file the check is about -- it doesn't pull that file's
  text in automatically. The user has to paste the document text into the
  textarea themselves (see the next point for why).
- Upload **text** extraction isn't wired up on the backend yet (LlamaParse
  sign-off pending), so there's nothing to auto-fill the compliance check's
  document text field with, beyond the image transcription results
  `/api/upload` already returns.
- **Chat memory (within a chat) vs. chat history (across chats) are two
  different things, both implemented now, for different reasons.**
  `/api/chat` is multi-turn -- the frontend resends up to the last 6
  messages of the *current* chat as `history` on each question (see
  `api/client.js`, `pages/ChatPage.jsx`), and the backend folds them into
  the model's context (see `backend/app/services/generation.py`). Separately,
  the chat itself -- the sidebar list and every message in it -- is now
  persisted directly to Supabase (`lib/chats.js`, `backend/migrations/
  versions/0007_chat_history.py`), secured with Row Level Security rather
  than routed through the backend, since the backend has no per-user auth
  wired in (see `0006_compliance_feedback.py`'s docstring). So: reopening a
  chat from a previous visit, or on another device, shows its real history;
  what's *not* persisted is the extra polish around that (e.g. no chat
  deletion or renaming yet, no updated-at bump to float a chat back to the
  top of the sidebar when it's used again -- it's ordered by when it was
  started).
