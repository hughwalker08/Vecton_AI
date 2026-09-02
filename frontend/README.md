# Frontend — Vecton AI Construction Compliance Assistant

React + Vite frontend. Skeleton only — no real chat/upload functionality yet.

## Setup

```bash
npm install
```

## Run (dev server, proxies /api to backend on :8000)

```bash
npm run dev
```

## Structure

```
src/
  main.jsx          # React entry point
  App.jsx           # Router + nav
  pages/
    ChatPage.jsx     # placeholder
    UploadPage.jsx   # placeholder
  api/
    client.js        # fetch helpers for /api/chat and /api/upload (unused so far)
```

## Not yet implemented

- Actual chat UI (message list, input, citation display / split-screen source view)
- Upload UI (drag-drop, progress, findings display)
- Any styling beyond bare defaults
