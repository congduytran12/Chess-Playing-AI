-- Database for player accounts: run once in the Supabase SQL editor (Dashboard > SQL Editor > New query).
-- Sign-up and sign-in use Supabase Auth; these tables hold everything else.
-- The game reaches them only through /api/account, which uses the service role key, so row level security is
-- switched on with no policies: nothing here can be read or written with the public keys.

create table if not exists public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    username text not null check (username ~ '^[A-Za-z0-9_]{3,20}$'),
    rating integer not null default 1200,
    rated_games integer not null default 0,
    created_at timestamptz not null default now()
);
-- usernames are unique regardless of case
create unique index if not exists profiles_username_lower on public.profiles (lower(username));
create index if not exists profiles_rating on public.profiles (rating desc) where rated_games > 0;

-- finished games, saved for the player who played them
create table if not exists public.games (
    id bigint generated always as identity primary key,
    user_id uuid not null references public.profiles (id) on delete cascade,
    mode text not null check (mode in ('ai', 'local', 'online')),
    ai_level integer,
    color text check (color in ('w', 'b')),
    opponent text,
    result text not null check (result in ('1-0', '0-1', '1/2-1/2', '*')),
    pgn text not null,
    played_at timestamptz not null default now()
);
create index if not exists games_user_played on public.games (user_id, played_at desc);

-- results of online games as each player reported them; a rating changes once per game (see api/account.py)
create table if not exists public.online_reports (
    id bigint generated always as identity primary key,
    game_hash text not null,
    reporter uuid not null references public.profiles (id) on delete cascade,
    white_id uuid not null references public.profiles (id) on delete cascade,
    black_id uuid not null references public.profiles (id) on delete cascade,
    result text not null check (result in ('1-0', '0-1', '1/2-1/2')),
    applied boolean not null default false,
    created_at timestamptz not null default now(),
    unique (game_hash, reporter)
);
create index if not exists online_reports_hash on public.online_reports (game_hash);

-- every new account gets a profile, with the username passed as sign-up metadata
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
    insert into public.profiles (id, username) values (new.id, new.raw_user_meta_data ->> 'username');
    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
    for each row execute function public.handle_new_user();

-- applies an online game to both ratings (Elo, K = 32), at most once per game even if both players
-- report at the same moment; returns the new ratings, or nothing when the game was already counted
create or replace function public.apply_rated_game(p_hash text, p_white uuid, p_black uuid, p_white_score numeric)
returns table (white_rating integer, black_rating integer)
language plpgsql security definer set search_path = public as $$
declare
    white_before integer;
    black_before integer;
    delta integer;
begin
    perform 1 from public.online_reports where game_hash = p_hash for update;
    if exists (select 1 from public.online_reports where game_hash = p_hash and applied) then
        return;
    end if;
    update public.online_reports set applied = true where game_hash = p_hash;

    select rating into white_before from public.profiles where id = p_white for update;
    select rating into black_before from public.profiles where id = p_black for update;
    delta := round(32 * (p_white_score - 1 / (1 + power(10, (black_before - white_before) / 400.0))));
    update public.profiles set rating = rating + delta, rated_games = rated_games + 1 where id = p_white;
    update public.profiles set rating = rating - delta, rated_games = rated_games + 1 where id = p_black;
    return query select white_before + delta, black_before - delta;
end;
$$;

revoke execute on function public.apply_rated_game(text, uuid, uuid, numeric) from public, anon, authenticated;

alter table public.profiles enable row level security;
alter table public.games enable row level security;
alter table public.online_reports enable row level security;
