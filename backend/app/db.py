from functools import lru_cache

from supabase import Client, create_client

from app.settings import get_api_settings


@lru_cache
def get_supabase() -> Client:
    settings = get_api_settings()
    if not settings.supabase_url:
        raise RuntimeError("SUPABASE_URL is not configured.")
    if not settings.supabase_secret_key:
        raise RuntimeError("SUPABASE_SECRET_KEY is not configured.")
    return create_client(
        settings.supabase_url,
        settings.supabase_secret_key,
    )
