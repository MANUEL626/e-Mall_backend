"""
Package de configuration pour le projet
"""

from .supabase_client import supabase, supabase_admin, get_supabase_client

__all__ = ["supabase", "supabase_admin", "get_supabase_client"]

