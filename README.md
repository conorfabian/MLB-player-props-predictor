# MLB Player Props Predictor

Walking skeleton for an MLB player-props predictor.

Current deployed shape:

```text
Next.js frontend -> FastAPI backend -> Supabase Postgres
```

The frontend reads only from FastAPI. Supabase and PropLine credentials are
backend-only.

## PropLine Pipeline

```text
PropLine -> ingestion run -> prop snapshots
         -> placeholder scorer -> model run
         -> candidate predictions -> daily board
         -> FastAPI /api/boards/latest -> Next.js page
```

This phase supports only:

- Sport: MLB (`baseball_mlb`)
- Market: batter hits (`batter_hits`)
- Bookmaker: PrizePicks (`prizepicks`)
- Side: Over
- PrizePicks flavor: standard lines
- Model version: `placeholder-v0`
- Feature version: `none-v0`

PrizePicks prices are synthetic `+100/+100`, so the pipeline stores the price
for debugging but does not use it as an implied probability.

The current scorer is deterministic placeholder test data. It uses a SHA-256
hash of event/player/line and a small line penalty. The future PyTorch model
should replace `PlaceholderScorer` behind the `CandidateScorer` interface
without redesigning ingestion, persistence, publication, the API endpoint, or
the frontend.

## Backend Environment

Copy `backend/.env.example` to `backend/.env` locally and set real values:

```env
SUPABASE_URL=
SUPABASE_SECRET_KEY=
FRONTEND_ORIGINS=http://localhost:3000,http://localhost:3001

PROPLINE_API_KEY=
PROPLINE_BASE_URL=https://api.prop-line.com/v1
PROPLINE_TIMEOUT_SECONDS=30
SLATE_TIMEZONE=America/New_York
CRON_JOB_SECRET=
```

Never create `NEXT_PUBLIC_PROPLINE_API_KEY` or expose Supabase service-role
credentials to the frontend.

## Database

Apply SQL migrations in order from `database/migrations/`.

Current migration:

```text
database/migrations/001_prop_ingestion_pipeline.sql
database/migrations/002_board_grading.sql
```

It adds:

- `prop_ingestion_runs`
- `prop_snapshots`
- `model_runs`
- `candidate_predictions`
- `publish_daily_board(...)` RPC for atomic board replacement
- Nullable source metadata columns on existing board tables
- Grading columns on `board_picks`: `actual_value`, `graded_at`, and
  `grading_metadata`

The full reproducible schema is mirrored in `database/schema.sql`.

Useful inspection queries:

```sql
select * from public.prop_ingestion_runs order by started_at desc limit 10;
select * from public.prop_snapshots order by captured_at desc limit 20;
select * from public.model_runs order by started_at desc limit 10;
select * from public.candidate_predictions order by created_at desc limit 20;
select * from public.daily_boards order by slate_date desc limit 5;
select * from public.board_picks order by board_id desc, rank asc limit 20;
```

## Commands

Backend setup and tests:

```bash
cd backend
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/python -m pytest
```

PropLine ingestion:

```bash
cd backend
./.venv/bin/python -m jobs.ingest_props --dry-run
./.venv/bin/python -m jobs.ingest_props
```

Board generation:

```bash
cd backend
./.venv/bin/python -m jobs.generate_board --dry-run
./.venv/bin/python -m jobs.generate_board
./.venv/bin/python -m jobs.generate_board --slate-date YYYY-MM-DD
```

Results grading:

```bash
cd backend
./.venv/bin/python -m jobs.grade_board --dry-run
./.venv/bin/python -m jobs.grade_board
./.venv/bin/python -m jobs.grade_board --slate-date YYYY-MM-DD
```

Scheduled daily board job:

cron-job.org calls one authenticated backend endpoint. The endpoint runs
PropLine ingestion first, then publishes the placeholder-scored board.

```text
URL: https://mlb-player-props-predictor.onrender.com/api/jobs/daily-board
Method: POST
Header: Authorization: Bearer <CRON_JOB_SECRET>
Header: Content-Type: application/json
Body: {}
Schedule: 00:00 America/New_York
```

Set the same `CRON_JOB_SECRET` value in Render and cron-job.org. Keep it
backend-only; do not prefix it with `NEXT_PUBLIC_`.

Manual endpoint verification:

```bash
BACKEND_URL=https://mlb-player-props-predictor.onrender.com
curl -X POST "$BACKEND_URL/api/jobs/daily-board" \
  -H "Authorization: Bearer $CRON_JOB_SECRET" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Manual production grading endpoint verification:

```bash
BACKEND_URL=https://mlb-player-props-predictor.onrender.com
curl -X POST "$BACKEND_URL/api/jobs/grade-board" \
  -H "Authorization: Bearer $CRON_JOB_SECRET" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Scheduled grading job:

Create a separate cron-job.org job after the daily board job.

```text
URL: https://mlb-player-props-predictor.onrender.com/api/jobs/grade-board
Method: POST
Header: Authorization: Bearer <CRON_JOB_SECRET>
Header: Content-Type: application/json
Body: {}
Schedule: 05:00 America/New_York
```

Use the same `CRON_JOB_SECRET` value configured in Render. Keep it
backend-only and never prefix it with `NEXT_PUBLIC_`. Enable failure
notifications in cron-job.org if available.

Local API:

```bash
cd backend
./.venv/bin/python -m uvicorn app.main:app --reload
curl http://localhost:8000/api/boards/latest
```

Frontend:

```bash
cd frontend
npm run lint
npm run build
npm run dev
```

## Verification Notes

Dry-run ingestion performs real PropLine fetching and normalization but does
not write Supabase rows. Dry-run board generation reads stored snapshots,
scores/ranks candidates, and prints the proposed board without creating model
runs or replacing the current board.

Dry-run grading reads pending board picks and PropLine event stats, then prints
the summary it would apply without updating `board_picks`.

Do not run the non-dry-run jobs against production until migrations are applied
and dry runs/tests pass.
