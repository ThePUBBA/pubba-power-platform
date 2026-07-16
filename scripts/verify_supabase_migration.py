#!/usr/bin/env python3
"""Verify the PUBBA Power Supabase ledger without modifying data."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from supabase import SupabaseError, verify_migration  # noqa: E402


def main() -> int:
    try:
        summary = verify_migration()
    except SupabaseError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_code": exc.error_code,
                    "message": str(exc),
                },
                indent=2,
            )
        )
        return 1
    status = (
        "ok"
        if summary["orphaned_dispatch_count"] == 0
        and not summary["duplicate_dispatch_ids"]
        and summary["records_outside_default_portfolio"] == 0
        else "integrity_warning"
    )
    print(json.dumps({"status": status, **summary}, indent=2, sort_keys=True))
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
