"""Daily pipeline: scrape website, pull CRM, match, queue proposals.

Usage:
    python -m bellhaven.pipeline            # scrape + match + queue proposals
    python -m bellhaven.pipeline --verify   # end-state reconciliation report

Nothing is ever written to the CRM here. Writes happen only when a human
approves a proposal in the review app.
"""
import json
import sys

from . import crm, matcher, scraper, store


def run(quiet: bool = False) -> dict:
    locations = scraper.scrape()
    accounts = crm.list_accounts()
    proposals, confirmed = matcher.run(locations, accounts)
    new, known = store.upsert_proposals(proposals)

    summary = {
        "website_locations": len(locations),
        "crm_accounts": len(accounts),
        "proposals_total": len(proposals),
        "proposals_new": new,
        "already_decided_or_pending": known,
        "clean_matches_no_action": len([c for c in confirmed if c[2] == "clean"]),
    }
    if not quiet:
        print(json.dumps(summary, indent=2))
        by_type = {}
        for p in proposals:
            by_type[p["change_type"]] = by_type.get(p["change_type"], 0) + 1
        print("by type:", by_type)
    return summary


def verify() -> None:
    """Re-run matching against the live CRM and report what would still be
    proposed. After a full approve-and-apply cycle this should show ~0 new."""
    locations = scraper.scrape()
    accounts = crm.list_accounts()
    proposals, confirmed = matcher.run(locations, accounts)
    live_keys = {p["key"] for p in proposals}

    decided = store.list_decisions()
    decided_map = {d["key"]: d for d in decided}
    fresh = [p for p in proposals if p["key"] not in decided_map]

    print(f"\n=== VERIFY ({len(accounts)} CRM accounts, {len(locations)} website locations) ===")
    print(f"matcher currently generates {len(proposals)} proposals")
    print(f"  of which never-before-seen: {len(fresh)}  (should be ~0 after full approval)")
    resurrected = [d["key"] for d in decided if d["key"] not in live_keys]
    print(f"  decided-but-no-longer-generated (stale keys, kept for audit): {len(resurrected)}")

    bell = [a for a in accounts if "Bellhaven Senior Living (Parent Account)" in (a.get("parent_name") or "")]
    active_bell = [a for a in bell if a.get("status") == "Active" and "Parent Account" not in a["name"]]
    matched_names = {c[0]["name"] for c in confirmed} | {p["evidence"].get("website", {}).get("name") for p in proposals if p.get("slug")}
    print(f"\nActive accounts under Bellhaven parent: {len(active_bell)}")
    for a in active_bell:
        flag = "" if a["name"] in matched_names else "   <-- not matched to a website location"
        print(f"  {a['name']:55} {a['billing_city']:15} rev={a['lifetime_revenue']:>7} ar={a['outstanding_ar']:>6}{flag}")

    print(f"\nchow_current_account set: {sum(1 for a in accounts if a.get('chow_current_account'))}")
    print(f"duplicate_of_account set: {sum(1 for a in accounts if a.get('duplicate_of_account'))}")
    print(f"created_by_candidate:     {sum(1 for a in accounts if a.get('created_by_candidate'))}")
    untouched = [a for a in accounts if not a.get("created_by_candidate") and not a.get("note")]
    print(f"untouched accounts (decoys etc., no note): {len(untouched)}")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify()
    else:
        run()
