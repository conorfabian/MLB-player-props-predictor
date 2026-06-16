import os
from functools import lru_cache

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


@lru_cache
def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")

    if not url:
        raise RuntimeError("SUPABASE_URL is not configured.")

    if not key:
        raise RuntimeError("SUPABASE_SECRET_KEY is not configured.")

    return create_client(url, key)
