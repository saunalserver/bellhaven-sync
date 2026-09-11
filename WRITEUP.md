# Submission writeup

**Matching approach.** The website is the source of truth for *which*
communities exist; the CRM is only ever compared against it. I match on
normalized address + city first and name second. A name+city match additionally
requires zip equality and high token similarity, because the dataset (like a
real market) is full of high-similarity decoys: an "Amberly Manor" in Colorado
Springs vs the real one in Hudson OH, a "Union Square Senior Living" in the
same city as the real "Bellhaven at Union Square" but at a different address.
Scope discipline does the rest: only accounts under the Bellhaven / Harborview /
Cedar Trail parents (or parentless Bellhaven-branded records) are ever written
to. 111 of 127 accounts were left untouched.

Parent moves follow the billing SOP exactly: `lifetime_revenue > 0 AND
outstanding_ar > 0` → new account under Bellhaven + `chow_current_account` on
the preserved old one (Marietta, Tiffin); anything else re-parents directly.
Lima has $47k revenue but zero AR, and the AND is what saves it from an
unnecessary CHOW. Duplicates (Owosso ×2, Monroe ×3, Kettering ×3, Port Clinton,
Erie) resolve to the website-confirmed survivor; losers get
`duplicate_of_account` + Inactive since the API has no merge. Accounts gone
from the website: no revenue → Inactive (Alliance, Coldwater). The
interesting one is Sandusky: Millstone Health Partners now sits at the same
address, so the facility was sold. I pointed `chow_current_account` at the new owner's
account and set Needs Review rather than leave a stale Active record, keeping
the $130k/$5.2k billing history intact.

Two data quirks worth flagging: the homepage claims 35 communities but the
directory lists 34. The missing one is Bellhaven Meadows of Findlay, linked
from the homepage as "new this year" but absent from the directory, so the
scraper unions both link sources. And the website's phone numbers are
unreliable (wrong-state area codes all over), so I deliberately do not sync
phones: overwriting billing phones with them would churn good data.

**How I used AI.** I used Claude (Opus, then a coding agent session) the way
I'd use a strong analyst pair: a first-pass read of the About page and one CRM
page surfaced the acquisition history and likely trap categories before I wrote
any code; the agent then built the scraper, matcher, review app and pipeline,
and I checked its work the whole way, which mattered: the first
matcher version had five real bugs (a name-similarity threshold that silently
dropped two rebrand renames, a fallback that nearly matched a same-city decoy,
a duplicate-survivor selection that picked the wrong record, a 500 on
patch-only proposals, and the missing-from-directory Findlay location that had
silently dropped the scrape to 34). Every proposal in the queue was eyeballed
against the raw JSON before approval; the AI never wrote to the CRM, only the
review app did, after my click. The writeup itself is mine.

**What I'd build next.** (1) Alerts: the daily run should notify a human when
the queue is non-empty, with a diff-style summary; a review queue nobody
watches is theater. (2) Confidence tiers + auto-approve rules for the boring
95% (pure name drift on an address-confirmed match), keeping humans for
CHOW/duplicates/divestitures. (3) A snapshot table of every run (site state,
CRM state, queue) so "what changed and who approved it" is answerable months
later. (4) Move the website diff upstream: if the scraper sees a community
appear or disappear, that event, not the field delta, should drive the
workflow.
