"""Database module for SignalFlow application.

Provides Supabase client and typed table operations.
"""

from app.db.supabase_client import get_supabase, get_supabase_client

__all__ = [
    "get_supabase",
    "get_supabase_client",
]
