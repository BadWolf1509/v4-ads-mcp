"""Admin CLI for Phase 1a (no panel UI yet).

Usage (run from project root with venv active):

  # Bootstrap admin (idempotent — uses email as upsert key)
  python -m src.scripts.admin bootstrap-admin --email wellington.ribeiro@v4company.com --name "Wellington Ribeiro"

  # Create an active manager with zero grants (e.g. for authenticated smoke tests)
  python -m src.scripts.admin create-manager --email smoke@v4company.com --name "Smoke Test"

  # Generate the invite URL for a manager to do OAuth
  python -m src.scripts.admin invite --email wellington.ribeiro@v4company.com [--base-url https://...]

  # Grant a manager access to all currently-active accounts
  python -m src.scripts.admin grant-all --email wellington.ribeiro@v4company.com

  # Create an MCP session token (printed once)
  python -m src.scripts.admin create-session --email wellington.ribeiro@v4company.com --label "Claude Desktop"

  # List sessions for a manager
  python -m src.scripts.admin list-sessions --email wellington.ribeiro@v4company.com

DATABASE_URL must be set in env (e.g. via Secret Manager fetch).
"""

import argparse
import asyncio
import sys
from uuid import uuid4

from src.auth.oauth_state import sign_state
from src.auth.sessions import generate_session_token, hash_session_token
from src.config import get_settings
from src.db import connection
from src.db.repositories import (
    manager_account_access,
    managers,
    mcp_sessions,
)


async def cmd_bootstrap_admin(args: argparse.Namespace) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            existing = await managers.get_by_email(conn, args.email)
            if existing:
                print(f"Manager already exists: {existing.id} ({existing.role})")
                if existing.role != "admin":
                    await conn.execute(
                        "UPDATE managers SET role = 'admin', is_active = true WHERE id = $1",
                        existing.id,
                    )
                    print("Promoted to admin.")
                return 0
            new_id = uuid4()
            m = await managers.create(
                conn, manager_id=new_id, email=args.email, full_name=args.name, role="admin"
            )
            print(f"Created admin: {m.id} ({m.email})")
            return 0
    finally:
        await connection.close_pool()


async def cmd_create_manager(args: argparse.Namespace) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            existing = await managers.get_by_email(conn, args.email)
            if existing:
                print(
                    f"Manager already exists: {existing.id} "
                    f"({existing.role}, status={existing.status})"
                )
                return 0
            new_id = uuid4()
            m = await managers.create(
                conn, manager_id=new_id, email=args.email, full_name=args.name, role="gestor"
            )
            print(f"Created manager: {m.id} ({m.email}, role={m.role}, status={m.status})")
            print("No account grants issued (zero blast radius).")
            return 0
    finally:
        await connection.close_pool()


async def cmd_invite(args: argparse.Namespace) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, args.email)
            if m is None:
                print(f"Manager not found: {args.email}", file=sys.stderr)
                return 1
        invite = sign_state({"manager_id": str(m.id)}, settings.session_signing_key)
        url = f"{args.base_url.rstrip('/')}/oauth/google/start?invite={invite}"
        print("Open this URL in a browser (logged into the desired Google account):")
        print(url)
        print()
        print("⚠️  Invite expires in 10 minutes.")
        return 0
    finally:
        await connection.close_pool()


async def cmd_grant_all(args: argparse.Namespace) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, args.email)
            if m is None:
                print(f"Manager not found: {args.email}", file=sys.stderr)
                return 1
            n = await manager_account_access.grant_all_active(
                conn, manager_id=m.id, granted_by=m.id
            )
        # I3 (revisão de branch): `n` é linhas TOCADAS pelo `ON CONFLICT DO
        # UPDATE` (Task 3) — inclui contas já concedidas e restauradas, não só
        # as genuinamente novas. Rodar grant-all duas vezes num gestor com
        # tudo concedido tocava 0 linhas novas e ainda imprimia "N new
        # accounts". Mensagem não afirma mais "new".
        print(f"Access granted for {n} active accounts (includes accounts already granted).")
        return 0
    finally:
        await connection.close_pool()


async def cmd_create_session(args: argparse.Namespace) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, args.email)
            if m is None:
                print(f"Manager not found: {args.email}", file=sys.stderr)
                return 1
            token = generate_session_token()
            sess = await mcp_sessions.create(
                conn,
                manager_id=m.id,
                token_hash=hash_session_token(token),
                label=args.label,
                ttl_days=args.ttl_days,
            )
        print(f"Session created: {sess.id} (expires {sess.expires_at})")
        print()
        print("⚠️  TOKEN — copy it now, won't be shown again:")
        print()
        print(token)
        print()
        print("MCP client config snippet (Claude Desktop):")
        print(
            f'  "v4-ads": {{ "url": "<SERVICE_URL>/mcp", "headers": {{ "Authorization": "Bearer {token}" }} }}'
        )
        return 0
    finally:
        await connection.close_pool()


async def cmd_list_sessions(args: argparse.Namespace) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, args.email)
            if m is None:
                print(f"Manager not found: {args.email}", file=sys.stderr)
                return 1
            sessions = await mcp_sessions.list_for_manager(conn, m.id, include_revoked=args.all)
        if not sessions:
            print("(no sessions)")
            return 0
        print(
            f"{'ID':38}  {'Label':20}  {'Created':25}  {'Last used':25}  {'Expires':25}  Revoked?"
        )
        for s in sessions:
            print(
                f"{str(s.id):38}  "
                f"{(s.label or '-'):20}  "
                f"{s.created_at.isoformat():25}  "
                f"{(s.last_used_at.isoformat() if s.last_used_at else '-'):25}  "
                f"{(s.expires_at.isoformat() if s.expires_at else '-'):25}  "
                f"{'Y' if s.revoked_at else 'N'}"
            )
        return 0
    finally:
        await connection.close_pool()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="admin", description="V4 Ads MCP admin CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_boot = sub.add_parser("bootstrap-admin", help="Create or promote an admin manager")
    p_boot.add_argument("--email", required=True)
    p_boot.add_argument("--name", default=None)

    p_cm = sub.add_parser(
        "create-manager", help="Create an active manager with zero account grants"
    )
    p_cm.add_argument("--email", required=True)
    p_cm.add_argument("--name", default=None)

    p_inv = sub.add_parser("invite", help="Print an OAuth invite URL")
    p_inv.add_argument("--email", required=True)
    p_inv.add_argument(
        "--base-url",
        default="https://v4-ads-mcp-299432068772.southamerica-east1.run.app",
        help="Service base URL",
    )

    p_grant = sub.add_parser("grant-all", help="Grant a manager access to all active accounts")
    p_grant.add_argument("--email", required=True)

    p_sess = sub.add_parser("create-session", help="Issue an MCP Bearer for a manager")
    p_sess.add_argument("--email", required=True)
    p_sess.add_argument("--label", default="cli")
    p_sess.add_argument("--ttl-days", type=int, default=90)

    p_ls = sub.add_parser("list-sessions", help="Print sessions for a manager")
    p_ls.add_argument("--email", required=True)
    p_ls.add_argument("--all", action="store_true", help="Include revoked sessions")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {
        "bootstrap-admin": cmd_bootstrap_admin,
        "create-manager": cmd_create_manager,
        "invite": cmd_invite,
        "grant-all": cmd_grant_all,
        "create-session": cmd_create_session,
        "list-sessions": cmd_list_sessions,
    }[args.cmd]
    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main())
