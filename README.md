# bellhaven-sync

Daily reconciliation between the Bellhaven Senior Living website (the source
of truth for which communities exist) and the CRM sandbox. Scrapes the site,
matches every community to a CRM account, queues a proposal for every
discrepancy, and waits. Nothing writes to the CRM until a human approves the
proposal in the review app.

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
# open http://localhost:8741 to review and approve; /results and /endstate
# summarize the outcome
.venv/bin/python -m bellhaven.pipeline --verify   # end-state report
```

## Matching rules

I matched all 121 CRM accounts against the 35 website locations by hand
before writing any code. The rules below are that map, not something tuned
by trial and error.

1. **Address + city before name.** A normalized street and city match is
   near-conclusive ("750 Stewart Rd" is "750 Stewart Road"). A name match
   alone also requires the zip to match and at least 0.75 token similarity.
   That is what keeps the decoys out: there is an "Amberly Manor" in Colorado
   Springs while the real one is in Hudson, OH, and a "Union Square Senior
   Living" in the same city as the real "Bellhaven at Union Square" but at a
   different address.
2. **Scope.** Only accounts under the Bellhaven, Harborview or Cedar Trail
   parents (or parentless Bellhaven-branded records) are ever written to.
   Stonebridge, Juniper Point and Millstone are never touched.
3. **Parent moves follow the billing SOP literally.** `lifetime_revenue > 0
   AND outstanding_ar > 0` means CHOW: create a new account under Bellhaven,
   set `chow_current_account` on the old one, touch nothing else (Marietta,
   Tiffin). Anything else re-parents directly. Lima has revenue but zero AR,
   so the AND is what saves it from an unnecessary CHOW.
4. **Duplicates.** When several Active accounts share an address, the
   website-confirmed record survives and the rest get `duplicate_of_account`
   + Inactive (this API has no merge). A losing copy with revenue and AR
   would be flagged Needs Review instead of deactivated.
5. **Gone from the website.** No revenue means Inactive (Alliance,
   Coldwater). Revenue and AR means Needs Review. If another operator now
   sits at the same address, the facility was sold: `chow_current_account`
   points at the new owner's account (Sandusky, sold to Millstone).
6. **Rebrands.** An address-confirmed account whose name drifted takes the
   website name (Riverbend Manor became Bellhaven of Chagrin Falls; the two
   names share no words).
7. **Phones are not synced.** The website numbers carry wrong-state area
   codes (a Lima, OH community with a 231 Michigan number). Writing them
   into billing phones would push bad data into the CRM.

## Idempotency

Every proposal key is `sha1(slug | account_id | change_type)` and the store
inserts with `INSERT OR IGNORE`, so a second run re-proposes nothing that has
ever been queued, decided or not. The matcher also skips accounts that are
already resolved (`duplicate_of_account` set, `chow_current_account` set,
non-Active), so even with the decision database deleted the corrected CRM
produces zero new proposals. Verified: a re-run after full approval gives
`proposals_new: 0`.

## Daily schedule

See `crontab.example`. The cron job only queues proposals; approvals happen
in the review app.

## End state (after approving all 28 proposals)

- 35 Active accounts under the Bellhaven parent = 35 website communities, 1:1
- 2 CHOW new accounts (Marietta, Tiffin), old accounts preserved and linked
- 1 divestiture (Sandusky sold to Millstone: CHOW link, Needs Review)
- 7 duplicates marked Inactive with `duplicate_of_account`
- 4 new communities created (including Amberly Manor of Hudson, OH, not the
  Colorado Springs decoy)
- 8 field fixes (rebrands, plus one PO Box replaced with the physical street)
- 111 decoy and unrelated accounts untouched

Run `.venv/bin/python -m bellhaven.pipeline --verify` to see this live.
