"""Explicit one-time bootstrap for the first verified OIDC Admin profile."""

from __future__ import annotations

import argparse

from supabase import create_operator, get_operator_by_subject, list_operators


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the first PUBBA Admin from a provider-verified OIDC subject."
    )
    parser.add_argument("--subject", required=True, help="Exact verified OIDC sub claim; never an email")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument(
        "--confirm-first-admin", action="store_true",
        help="Required acknowledgement that the subject was verified in the OIDC provider",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Perform the insert after a successful dry run; omitted means no database write",
    )
    args = parser.parse_args()
    if not args.confirm_first_admin:
        parser.error("--confirm-first-admin is required")
    if "@" in args.subject or args.subject.strip().lower() == args.email.strip().lower():
        parser.error("--subject must be the stable OIDC sub claim, not an email address")
    if get_operator_by_subject(args.subject.strip()):
        parser.error("An operator already exists for this OIDC subject")
    if any(item.get("role") == "admin" for item in list_operators(limit=1000)):
        parser.error("An Admin already exists; use the authenticated Admin API for additional Admins")
    if not args.execute:
        print("Dry run passed: verified-subject checks succeeded; no operator was created")
        return 0
    created = create_operator({
        "auth_subject": args.subject.strip(),
        "email": args.email.strip().lower(),
        "display_name": args.display_name.strip(),
        "role": "admin", "status": "active",
    })
    print(f"Created first Admin operator {created['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
