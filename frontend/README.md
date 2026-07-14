# Gene Autoannotator Frontend

This [Next.js](https://nextjs.org) app is the web interface for the gene
autoannotator API. It has pages for usage guidance, queued job submission,
local profile management (via the coordinator API), and searching generated
annotation history.

## Getting Started

Copy the example environment file and point it at the Python API:

```bash
cp .env.example .env.local
```

Then run the development server:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

The Python backend should be running separately on port `8000`. Browser API
calls go through the same-origin `/api/backend` proxy, so remote devices only
need to reach the frontend on port `3000`. If FastAPI is not on the same
machine as Next.js, set `BACKEND_API_BASE_URL` to its internal URL.

Set `MONGO_URI` in `.env.local` when you want the frontend's annotation search
and review routes to read stored generated annotations directly from MongoDB.
Profile management is proxied through FastAPI and stored as local JSON on the
coordinator (`data/profiles` / `PROFILES_DIR`); MongoDB is not required for
profiles.

## Scripts

- `npm run dev`: start the local frontend server.
- `npm run test`: run lightweight helper tests.
- `npm run lint`: run ESLint.
- `npm run build`: build the production app.

## Pages

- `/`: explains what the annotator does, how jobs work, and important limits.
- `/jobs`: shows backend health, submits annotation jobs, and polls the shared
  sequential queue. Jobs can use a saved profile or a custom organism plus a
  gene name, locus, or both.
- `/profiles`: lists local organism profiles and creates, edits, or deletes
  them for reuse in job submissions.
- `/annotations`: searches Mongo-backed generated annotations, displays the
  current annotation, loads older versions on demand, and links back to `/jobs`
  for update runs.
