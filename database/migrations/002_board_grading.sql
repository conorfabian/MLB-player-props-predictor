alter table public.board_picks
    add column if not exists actual_value double precision,
    add column if not exists graded_at timestamptz,
    add column if not exists grading_metadata jsonb not null default '{}'::jsonb;
