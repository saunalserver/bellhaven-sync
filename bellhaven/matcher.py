"""Match website locations to CRM accounts and classify every discrepancy.

Design: match on *address + city* first (normalized), name second. High name
similarity alone (the Amberly / Bristol / Willowbrook decoy families) never
pulls an account in. Only accounts under the Bellhaven/Harborview/Cedar Trail
parents (or parentless Bellhaven-named accounts) are ever proposed against;
Stonebridge, Juniper Point and Millstone accounts are never touched, except
reading Millstone's Sandusky account as the CHOW target it is.

Every proposal carries stable key = sha1(slug|account_id|change_type) so re-runs
never re-propose a decision that has already been made.
"""
import datetime
import hashlib
import json

from .config import IN_SCOPE_PARENTS
from .normalize import (CARE_MAP, name_similarity, norm_city,
                        norm_phone, norm_street)

TODAY = datetime.date.today().isoformat()
BELLHAVEN_PARENT_NAME = IN_SCOPE_PARENTS["Bellhaven"]


def _key(slug: str, account_id: str, change_type: str) -> str:
    return hashlib.sha1(f"{slug}|{account_id}|{change_type}".encode()).hexdigest()[:16]


def _today() -> str:
    return datetime.date.today().isoformat()


def _is_parent_account(a: dict) -> bool:
    return "Parent Account" in (a.get("name") or "")


def _superseded(a: dict) -> bool:
    """Accounts already resolved: chow-linked (replaced by a newer account) or
    marked as duplicates. Re-runs must not touch these."""
    return bool(a.get("chow_current_account")) or bool(a.get("duplicate_of_account"))


def _in_scope(a: dict) -> bool:
    """Facility accounts whose parent linkage is Bellhaven's business."""
    if _is_parent_account(a) or _superseded(a):
        return False
    parent_name = a.get("parent_name") or ""
    if any(p in parent_name for p in IN_SCOPE_PARENTS.values()):
        return True
    # Parentless accounts are only ours if they carry the Bellhaven brand
    # (e.g. Bellhaven Meadows of Findlay). Other orphans belong to nobody.
    if not a.get("parent_id") and "bellhaven" in (a.get("name") or "").lower():
        return True
    return False


def _bellhaven_parent_id(accounts: list[dict]) -> str:
    for a in accounts:
        if a.get("name") == BELLHAVEN_PARENT_NAME:
            return a["account_id"]
    raise RuntimeError("Bellhaven parent account not found in CRM")


def _chow_required(a: dict) -> bool:
    """The billing SOP: preserve the old account only when it has revenue
    history AND outstanding AR. Anything else re-parents directly."""
    return a.get("lifetime_revenue", 0) > 0 and a.get("outstanding_ar", 0) > 0


def _match(location: dict, accounts: list[dict]):
    """Best CRM account for a website location. Address+city wins; a strong
    name+city match is the fallback (catches the Ashtabula PO Box case)."""
    best = None
    for a in accounts:
        if _is_parent_account(a) or _superseded(a):
            continue
        addr_eq = (norm_street(location["street"]) == norm_street(a.get("billing_street"))
                   and norm_city(location["city"]) == norm_city(a.get("billing_city")))
        city_eq = norm_city(location["city"]) == norm_city(a.get("billing_city"))
        zip_eq = (location.get("zip") or "") == (a.get("billing_zip") or "")
        name_sim = name_similarity(location["name"], a.get("name") or "")
        if addr_eq:
            score, tier = 2 + name_sim, "address"
        elif city_eq and zip_eq and name_sim >= 0.75:
            # Name+city+zip fallback, for records whose billing street is a
            # PO Box (Ashtabula). The zip requirement plus a high threshold
            # keeps same-city decoys like "Union Square Senior Living" out.
            score, tier = 1 + name_sim, "name"
        else:
            continue
        # Prefer address matches; among ties prefer exact-name, then
        # Bellhaven-parented, then already-Active accounts (stability).
        rank = (score, name_sim == 1.0, BELLHAVEN_PARENT_NAME in (a.get("parent_name") or ""))
        if best is None or rank > best[0]:
            best = (rank, a, tier, name_sim)
    if best is None:
        return None, None, None
    return best[1], best[2], best[3]


def run(locations: list[dict], accounts: list[dict]):
    """Returns (proposals, confirmed_matches) where confirmed_matches are the
    locations that matched cleanly and need no proposal."""
    proposals, confirmed = [], []
    bellhaven_pid = _bellhaven_parent_id(accounts)
    matched_ids = set()

    # ---- Pass 1: website location -> CRM account --------------------------
    for loc in locations:
        acct, tier, name_sim = _match(loc, accounts)
        if acct is None:
            proposals.append(_proposal_create(loc, bellhaven_pid))
            continue
        matched_ids.add(acct["account_id"])
        in_scope = _in_scope(acct)
        wrong_parent = in_scope and BELLHAVEN_PARENT_NAME not in (acct.get("parent_name") or "")

        if not in_scope:
            # Matched an out-of-scope account (e.g. a decoy). Address+city is a
            # strong signal, so surface it for review rather than acting.
            proposals.append(_proposal_out_of_scope(loc, acct, bellhaven_pid))
            continue

        fields, reasons = {}, []

        if not acct.get("parent_id"):
            fields["parent_id"] = bellhaven_pid
            reasons.append("parentless -> link to Bellhaven parent")
        elif wrong_parent:
            if _chow_required(acct):
                proposals.append(_proposal_chow(loc, acct, bellhaven_pid))
                confirmed.append((loc, acct, "chow"))
                continue
            fields["parent_id"] = bellhaven_pid
            reasons.append(
                f"acquired from {acct['parent_name'].replace(' (Parent Account)', '')} "
                f"(rev={acct['lifetime_revenue']}, ar={acct['outstanding_ar']} -> direct re-parent)")

        if loc["name"] != acct["name"] and (tier == "address" or name_sim >= 0.3):
            # Address-confirmed accounts take the website name unconditionally:
            # the facility was rebranded (Riverbend Manor -> Bellhaven of
            # Chagrin Falls) even though the names share no words.
            fields["name"] = loc["name"]
            reasons.append(f"name drift: CRM '{acct['name']}' -> website '{loc['name']}'")

        if (norm_street(loc["street"]) != norm_street(acct.get("billing_street"))
                and norm_city(loc["city"]) == norm_city(acct.get("billing_city"))
                and tier == "name"):
            fields["billing_street"] = loc["street"]
            reasons.append(f"billing street is '{acct['billing_street']}', website lists physical '{loc['street']}'")

        web_care = {CARE_MAP[c] for c in loc["care"] if c in CARE_MAP}
        if web_care and acct.get("care_type") not in web_care:
            fields["care_type"] = sorted(web_care)[0]
            reasons.append(f"care type '{acct.get('care_type')}' not in website offerings {sorted(web_care)}")

        # Phones: deliberately NOT synced. Website phone numbers are unreliable
        # (wrong area codes for their states); overwriting billing phones with
        # them would degrade the CRM. Documented in the writeup.

        if fields:
            proposals.append(_proposal_field_fix(loc, acct, fields, reasons))
        else:
            confirmed.append((loc, acct, "clean"))

    # ---- Pass 2: duplicate groups (same normalized street + city) ----------
    # Scope: every Active facility account at that address, whatever its
    # parent (or none) — duplicates of a physical facility are exactly that.
    # The group only fires when it contains a website-matched survivor; the
    # Sandusky pair (no website match) is a divestiture, not a duplicate, and
    # is handled by the gone pass below.
    groups = {}
    for a in accounts:
        if _is_parent_account(a) or _superseded(a) or a.get("status") != "Active":
            continue
        groups.setdefault((norm_street(a.get("billing_street")), norm_city(a.get("billing_city"))), []).append(a)

    handled = {p["account_id"] for p in proposals if p.get("account_id")}
    for key, group in groups.items():
        matched_in_group = [a for a in group if a["account_id"] in matched_ids]
        if not matched_in_group:
            continue
        survivor = _pick_survivor(matched_in_group, matched_ids)
        for a in group:
            if a["account_id"] == survivor["account_id"] or a["account_id"] in handled:
                continue
            if _chow_required(a):
                # Billing SOP: a losing copy with revenue AND AR must be
                # preserved for billing — flag instead of deactivating.
                proposals.append(_proposal_gone_review(a))
            else:
                proposals.append(_proposal_duplicate(a, survivor))
            handled.add(a["account_id"])

    # ---- Pass 3: in-scope accounts that no website location claims ---------
    for a in accounts:
        if not _in_scope(a) or a.get("status") != "Active":
            continue
        if a["account_id"] in matched_ids or a["account_id"] in handled:
            continue
        twin = _address_twin_other_parent(a, accounts)
        if twin:
            proposals.append(_proposal_gone_chow(a, twin))
        elif _chow_required(a):
            proposals.append(_proposal_gone_review(a))
        else:
            proposals.append(_proposal_gone_inactive(a))

    proposals.sort(key=lambda p: (p["change_type"], p["title"]))
    return proposals, confirmed


def _pick_survivor(group: list[dict], matched_ids: set) -> dict:
    """Survivor preference: the account the website matched (already claimed),
    then Bellhaven-parented, then parentless (Kettering case: the parentless
    record is the least-stale), then lowest id for determinism."""
    def rank(a):
        return (
            a["account_id"] in matched_ids,
            BELLHAVEN_PARENT_NAME in (a.get("parent_name") or ""),
            not a.get("parent_id"),
        )
    return sorted(group, key=lambda a: (rank(a), a["account_id"]), reverse=True)[0]


def _address_twin_other_parent(a: dict, accounts: list[dict]):
    """A different-parent account at the same address — evidence the facility
    was sold to that operator (the Sandusky/Millstone case)."""
    for b in accounts:
        if b["account_id"] == a["account_id"] or _is_parent_account(b) or _superseded(b):
            continue
        if b.get("parent_id") == a.get("parent_id"):
            continue
        if (norm_street(b.get("billing_street")) == norm_street(a.get("billing_street"))
                and norm_city(b.get("billing_city")) == norm_city(a.get("billing_city"))):
            return b
    return None


# ---- proposal builders ----------------------------------------------------

def _base(change_type, slug, account_id, title, rationale, evidence, ops):
    return {
        "key": _key(slug, account_id, change_type),
        "change_type": change_type,
        "slug": slug,
        "account_id": account_id,
        "title": title,
        "rationale": rationale,
        "evidence": evidence,
        "ops": ops,
    }

def _web_ev(loc):
    return {k: loc[k] for k in ("name", "street", "city", "state", "zip", "care", "phone")}

def _crm_ev(acct):
    return {k: acct.get(k) for k in (
        "account_id", "name", "parent_name", "billing_street", "billing_city",
        "billing_state", "care_type", "status", "lifetime_revenue", "outstanding_ar")}


def _proposal_create(loc, bellhaven_pid):
    care = sorted({CARE_MAP[c] for c in loc["care"] if c in CARE_MAP})
    fields = {
        "name": loc["name"], "parent_id": bellhaven_pid,
        "billing_street": loc["street"], "billing_city": loc["city"],
        "billing_state": loc["state"], "billing_zip": loc["zip"],
        "care_type": care[0] if care else "", "phone": loc["phone"],
        "status": "Active",
        "note": f"Created by pipeline {_today()}: listed on Bellhaven website, no matching CRM account.",
    }
    return _base("create", loc["slug"], "",
                 f"CREATE {loc['name']} ({loc['city']}, {loc['state']})",
                 "Website community with no CRM account at this address/city.",
                 {"website": _web_ev(loc), "crm": None},
                 [{"op": "create", "fields": fields}])

def _proposal_chow(loc, acct, bellhaven_pid):
    care = sorted({CARE_MAP[c] for c in loc["care"] if c in CARE_MAP})
    new_fields = {
        "name": loc["name"], "parent_id": bellhaven_pid,
        "billing_street": loc["street"], "billing_city": loc["city"],
        "billing_state": loc["state"], "billing_zip": loc["zip"],
        "care_type": care[0] if care else "", "phone": loc["phone"],
        "status": "Active",
        "note": (f"Created by pipeline {_today()} for CHOW: facility acquired by Bellhaven "
                 f"but old account {acct['account_id']} has revenue history "
                 f"(${acct['lifetime_revenue']}) and outstanding AR (${acct['outstanding_ar']}), "
                 f"so it must be preserved per billing SOP."),
    }
    return _base("chow", loc["slug"], acct["account_id"],
                 f"CHOW {acct['name']} -> new account under Bellhaven",
                 (f"Acquired facility under {acct['parent_name'].replace(' (Parent Account)','')} with "
                  f"lifetime_revenue=${acct['lifetime_revenue']} AND outstanding_ar=${acct['outstanding_ar']}. "
                  f"Billing SOP: do NOT re-parent; create new account under Bellhaven and set "
                  f"chow_current_account on the old one. Old account left otherwise untouched."),
                 {"website": _web_ev(loc), "crm": _crm_ev(acct)},
                 [{"op": "create", "fields": new_fields},
                  {"op": "patch", "account_id": acct["account_id"],
                   "fields": {"chow_current_account": "{new_account_id}"}}])

def _proposal_field_fix(loc, acct, fields, reasons):
    ct = "reparent" if "parent_id" in fields else "field_fix"
    return _base(ct, loc["slug"], acct["account_id"],
                 f"FIX {acct['name']} ({acct['billing_city']})",
                 "; ".join(r[0].upper() + r[1:] for r in reasons) + ".",
                 {"website": _web_ev(loc), "crm": _crm_ev(acct)},
                 [{"op": "patch", "account_id": acct["account_id"], "fields": fields}])

def _proposal_out_of_scope(loc, acct, bellhaven_pid):
    return _base("out_of_scope", loc["slug"], acct["account_id"],
                 f"REVIEW {loc['name']} matched non-Bellhaven account",
                 (f"Address/city matches {acct['name']} under {acct['parent_name']}, which is outside "
                  f"the Bellhaven family. Almost certainly a different facility (decoy); needs a human "
                  f"eye before anything is created or linked."),
                 {"website": _web_ev(loc), "crm": _crm_ev(acct)},
                 [{"op": "noop"}])

def _proposal_duplicate(loser, survivor):
    return _base("duplicate", "", loser["account_id"],
                 f"DUPLICATE {loser['name']} -> {survivor['name']}",
                 (f"Same address as {survivor['name']} ({survivor['account_id']}), which is the "
                  f"website-confirmed record. Loser has rev=${loser['lifetime_revenue']}, "
                  f"ar=${loser['outstanding_ar']} (nothing billing-critical). Marking it the duplicate "
                  f"and Inactive per CRM conventions (no merge/delete in this API)."),
                 {"website": None, "crm": _crm_ev(loser), "survivor": _crm_ev(survivor)},
                 [{"op": "patch", "account_id": loser["account_id"],
                   "fields": {"duplicate_of_account": survivor["account_id"], "status": "Inactive",
                              "note": (f"Duplicate of {survivor['account_id']} ({survivor['name']}): "
                                       f"same address, legacy record from {loser['parent_name'] or 'no parent'}. "
                                       f"Set by pipeline {_today()}.")}}])

def _proposal_gone_inactive(acct):
    return _base("gone_inactive", "", acct["account_id"],
                 f"INACTIVE {acct['name']} ({acct['billing_city']})",
                 (f"Under the Bellhaven parent but not listed on the website. No revenue history "
                  f"and no AR, so nothing to preserve: marking Inactive."),
                 {"website": None, "crm": _crm_ev(acct)},
                 [{"op": "patch", "account_id": acct["account_id"],
                   "fields": {"status": "Inactive",
                              "note": (f"No longer on Bellhaven website as of {_today()}. "
                                       f"No revenue/AR. Set by pipeline.")}}])

def _proposal_gone_review(acct):
    return _base("gone_review", "", acct["account_id"],
                 f"NEEDS REVIEW {acct['name']} ({acct['billing_city']})",
                 (f"Not on the website but carries revenue (${acct['lifetime_revenue']}) and "
                  f"AR (${acct['outstanding_ar']}) — billing history must be preserved, so only "
                  f"flagging for a human rather than deactivating."),
                 {"website": None, "crm": _crm_ev(acct)},
                 [{"op": "patch", "account_id": acct["account_id"],
                   "fields": {"status": "Needs Review",
                              "note": (f"Not on Bellhaven website as of {_today()} but has revenue/AR; "
                                       f"needs human confirmation before any status change. "
                                       f"Set by pipeline.")}}])

def _proposal_gone_chow(acct, twin):
    return _base("gone_chow", "", acct["account_id"],
                 f"CHOW (sold) {acct['name']} -> {twin['name']}",
                 (f"Not on the Bellhaven website, and {twin['name']} ({twin['account_id']}) under "
                  f"{twin['parent_name'].replace(' (Parent Account)','')} sits at the same address — "
                  f"the facility was evidently sold/divested. Account has revenue "
                  f"(${acct['lifetime_revenue']}) and AR (${acct['outstanding_ar']}), so per the CHOW "
                  f"SOP spirit we preserve it, point chow_current_account at the current owner's "
                  f"account, and set Needs Review rather than leave a stale Active record."),
                 {"website": None, "crm": _crm_ev(acct), "twin": _crm_ev(twin)},
                 [{"op": "patch", "account_id": acct["account_id"],
                   "fields": {"chow_current_account": twin["account_id"],
                              "status": "Needs Review",
                              "note": (f"Divested: not on Bellhaven website as of {_today()}; "
                                       f"{twin['name']} under {twin['parent_name']} now at this address. "
                                       f"chow_current_account points to the current owner's account. "
                                       f"Revenue/AR preserved per billing SOP. Set by pipeline.")}}])
