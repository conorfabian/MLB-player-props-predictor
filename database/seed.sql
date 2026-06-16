with board as (
    insert into public.daily_boards (
        slate_date,
        model_version,
        status
    )
    values (
        current_date,
        'skeleton-v0',
        'published'
    )
    on conflict (slate_date)
    do update set
        model_version = excluded.model_version,
        status = excluded.status
    returning id
)

insert into public.board_picks (
    board_id,
    rank,
    player_name,
    team,
    opponent,
    prop_type,
    line,
    side,
    model_probability,
    game_time,
    result_status
)
select
    id,
    1,
    'Test Player',
    'LAD',
    'SD',
    'hits',
    0.5,
    'over',
    0.712,
    now() + interval '4 hours',
    'pending'
from board

on conflict (board_id, rank)
do update set
    player_name = excluded.player_name,
    model_probability = excluded.model_probability;
