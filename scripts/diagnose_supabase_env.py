#!/usr/bin/env python3
"""Report non-secret Supabase environment metadata for local diagnosis."""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse


def key_format(value: str) -> str:
    if value.startswith("sb_secret_"):
        return "supabase_secret"
    parts = value.split(".")
    if len(parts) == 3 and all(
        re.fullmatch(r"[A-Za-z0-9_-]+", part or "") for part in parts
    ):
        return "jwt"
    return "unknown"


def main() -> int:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    hostname = urlparse(url).hostname if url else None
    result = {
        "SUPABASE_URL_exists": bool(url),
        "SUPABASE_URL_hostname": hostname,
        "SUPABASE_SERVICE_ROLE_KEY_exists": bool(key),
        "SUPABASE_SERVICE_ROLE_KEY_length": len(key),
        "SUPABASE_SERVICE_ROLE_KEY_format": key_format(key) if key else None,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if url and key else 1


if __name__ == "__main__":
    raise SystemExit(main())
