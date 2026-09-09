"""Thin client for the CRM sandbox API."""
import requests

from .config import API_ROOT, TOKEN


def _headers():
    if not TOKEN:
        raise RuntimeError("BELHAVEN_TOKEN not set (put it in .env)")
    return {"Authorization": f"Bearer {TOKEN}"}


def list_accounts() -> list[dict]:
    """All accounts, all pages."""
    out, page = [], 1
    while True:
        r = requests.get(f"{API_ROOT}/accounts", headers=_headers(),
                         params={"page": page, "page_size": 50}, timeout=30)
        r.raise_for_status()
        d = r.json()
        out.extend(d["data"])
        if len(out) >= d["total"]:
            return out
        page += 1


def get_account(account_id: str) -> dict:
    r = requests.get(f"{API_ROOT}/accounts/{account_id}", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def patch_account(account_id: str, fields: dict) -> dict:
    r = requests.patch(f"{API_ROOT}/accounts/{account_id}", headers=_headers(),
                       json=fields, timeout=30)
    r.raise_for_status()
    return r.json()


def create_account(fields: dict) -> dict:
    r = requests.post(f"{API_ROOT}/accounts", headers=_headers(),
                      json=fields, timeout=30)
    r.raise_for_status()
    return r.json()
