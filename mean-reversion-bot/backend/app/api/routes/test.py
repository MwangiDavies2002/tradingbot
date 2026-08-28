"""Temporary, server-side Supabase connectivity check."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.database.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/test")
def test_supabase_connection() -> dict:
    """Confirm service-role access to the trades table without exposing trade data."""
    try:
        # supabase-py calls this `table`; it is equivalent to the JS SDK call:
        # supabase.from('trades').select('*').limit(1)
        response = get_supabase_client().table("trades").select("*").limit(1).execute()
        return {
            "connected": True,
            "table": "trades",
            "rows_returned": len(response.data or []),
        }
    except Exception as exc:
        logger.exception("Supabase test query failed")
        raise HTTPException(
            status_code=500,
            detail="Supabase connection test failed. Check Vercel function logs.",
        ) from exc
