"""Server-only Supabase REST client used for lightweight API checks."""

from __future__ import annotations

import os

from supabase import Client, create_client


def get_supabase_client() -> Client:
    """Create a service-role client, accepting either current or legacy names."""
    # Python equivalent of:
    # process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")

    # Python equivalent of:
    # process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_SECRET_KEY
    service_role_key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SECRET_KEY")
    )

    if not supabase_url or not service_role_key:
        raise RuntimeError(
            "Missing Supabase credentials. Set SUPABASE_URL (or "
            "NEXT_PUBLIC_SUPABASE_URL) and SUPABASE_SERVICE_ROLE_KEY (or "
            "SUPABASE_SECRET_KEY)."
        )

    return create_client(supabase_url, service_role_key)
