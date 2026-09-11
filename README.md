# bellhaven-sync

Daily reconciliation between the Bellhaven Senior Living website (source of
truth for which communities exist) and the CRM sandbox. Scrapes the site,
matches every community to a CRM account, classifies the discrepancy, queues a
proposal, and waits. **Nothing writes to the CRM until a human approves the
proposal in the review app.**

```
scraper.py ──▶ 35 communities (JSON)
crm.py     ──▶ 121 accounts (API)
        │
matcher.py ──▶ proposals w/ evidence + rationale
        │
store.py   ──▶ decisions.db (SQLite)  ← idempotency lives here
        │
app.py     ──▶ review UI  →  approve/reject  →  apply.py → CRM API
```

## Run it

```bash
uv venv .venv && uv pip install --python .venv -r requirements.txt  # or: python -m venv + pip
cp .env.example .env          # put your token in
.venv/bin/python -m bellhaven.pipeline       # scrape + match + queue proposals
.venv/bin/uvicorn bellhaven.app:app --port 8741
# open http://localhost:8741 — review, approve; /results and /endstate summarize
.venv/bin/python -m bellhaven.pipeline --verify   # end-state report
```

## The matching rules (in order)

1. **Address + city first, name second.** A normalized street+city match is
   near-conclusive ("750 Stewart Rd" = "750 Stewart Road"). Name-only matches
   additionally require zip equality and ≥0.75 token similarity — that is what
   keeps the decoy families (Amberly ×4, Bristol Manor ×3, "Union Square Senior
   Living" in the same city at a different address) out of the results.
2. **Scope.** Only accounts under the Bellhaven / Harborview / Cedar Trail
   parents (or parentless Bellhaven-branded accounts) are ever touched.
   Stonebridge, Juniper Point and Millstone accounts are never written to.
3. **Parent moves follow the billing SOP exactly.** `lifetime_revenue > 0 AND
   outstanding_ar > 0` → CHOW: create the new account under Bellhaven, set
   `chow_current_account` on the old one, touch nothing else (Marietta,
   Tiffin). Anything else re-parents directly (Lima has revenue but zero AR —
   the AND matters).
4. **Duplicates.** Multiple Active accounts at the same address: the
   website-confirmed record survives, the rest get `duplicate_of_account` +
   Inactive (there is no merge/delete in this API). A losing copy with revenue
   AND AR would be flagged Needs Review instead of deactivated.
5. **Gone from the website.** In-scope Active accounts no longer listed:
   no revenue → Inactive (Alliance, Coldwater); revenue + AR → Needs Review;
   and if another operator already sits at the same address, the facility was
   sold — `chow_current_account` points at the new owner's account and status
   becomes Needs Review (Sandusky → Millstone).
6. **Rebrands.** An address-confirmed account whose name drifted takes the
   website name unconditionally (Riverbend Manor → Bellhaven of Chagrin Falls,
   Sunny Acres → Bellhaven Willow Creek, "Health Care Center" → "Healthcare
   Centre").
7. **Phones are deliberately not synced.** The website's phone numbers carry
   area codes from the wrong states (a Lima, OH community with a 231 Michigan
   number); overwriting billing phones with them would degrade the CRM.

## Idempotency

Every proposal has a stable key `sha1(slug | account_id | change_type)`. The
store inserts with `INSERT OR IGNORE` — a second pipeline run re-proposes
nothing that has ever been queued, decided or not. On top of that, the matcher
itself skips resolved accounts (`duplicate_of_account` set, `chow_current_account`
set, non-Active), so even with the decision database deleted the corrected CRM
produces zero new proposals. Verified live: re-run after full approval →
`proposals_new: 0`.

## Daily schedule

See `crontab.example`. The cron job only queues proposals for review; it never
writes to the CRM.

## End state (after approving all 28 proposals)

- 35 Active accounts under the Bellhaven parent = 35 website communities, 1:1
- 2 CHOW new accounts (Marietta, Tiffin) with old accounts preserved and linked
- 1 divestiture linked (Sandusky → Millstone's account, Needs Review)
- 7 duplicates marked Inactive + `duplicate_of_account`
- 4 genuinely new communities created (incl. Amberly Manor, Hudson OH — not the
  Colorado Springs decoy)
- 8 field fixes (rebrands + one PO-Box → physical street)
- 111 decoy/unrelated accounts untouched

Run `.venv/bin/python -m bellhaven.pipeline --verify` to see this live.
