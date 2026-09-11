"""Review app: a human sees every proposal with its evidence and approves or
rejects it. Approvals write to the CRM through the API. Nothing writes without
approval. Run: uvicorn bellhaven.app:app --reload --port 8741"""
import json
import os
from datetime import datetime

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import os

from . import apply as apply_mod
from . import pipeline, store

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "..", "templates"))
app = FastAPI(title="Bellhaven CRM Review")


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%b %-d, %Y \u00b7 %H:%M UTC")
    except ValueError:
        return iso


def _proposal_dicts(status: str | None = None) -> list[dict]:
    rows = store.list_decisions(status)
    out = []
    for r in rows:
        p = json.loads(r["proposal"])
        p["status"] = r["status"]
        p["decided_at"] = _fmt_dt(r["decided_at"])
        p["apply_log"] = json.loads(r["apply_log"]) if r["apply_log"] else None
        out.append(p)
    return out


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    counts = store.counts()
    return templates.TemplateResponse(request, "index.html", {
        "counts": counts,
        "pending": _proposal_dicts("pending"),
        "decided": [p for p in _proposal_dicts() if p["status"] != "pending"],
    })


@app.post("/run")
def run_pipeline():
    pipeline.run(quiet=True)
    return RedirectResponse("/", status_code=303)


@app.get("/proposal/{key}", response_class=HTMLResponse)
def proposal_detail(request: Request, key: str):
    p = next((p for p in _proposal_dicts() if p["key"] == key), None)
    if not p:
        return HTMLResponse("not found", status_code=404)
    return templates.TemplateResponse(request, "proposal.html", {"p": p})


@app.post("/proposal/{key}/decision")
def decide(key: str, decision: str = Form(...)):
    p = store.get(key)
    if not p or decision not in ("approved", "rejected"):
        return HTMLResponse("bad request", status_code=400)
    if p["status"] != "pending":
        # Already decided: never re-apply ops (double-click, back-button resubmit).
        return HTMLResponse(f"already {p['status']}", status_code=400)
    log = None
    if decision == "approved":
        log = apply_mod.apply(json.loads(p["proposal"]))
        print(f"[app] APPROVED {p['title']}: {log}")
    else:
        print(f"[app] REJECTED {p['title']}")
    store.decide(key, decision, log)
    return RedirectResponse("/", status_code=303)


@app.post("/approve-all")
def approve_all():
    for p in _proposal_dicts("pending"):
        log = apply_mod.apply(p)
        store.decide(p["key"], "approved", log)
        print(f"[app] APPROVED {p['title']}: {log}")
    return RedirectResponse("/", status_code=303)


@app.get("/results", response_class=HTMLResponse)
def results(request: Request):
    """One-page picture of the reconciliation: every website location with its
    outcome, plus the CRM-side retirements. Reads the decision store and the
    last scrape; hits no API."""
    loc_path = os.path.join(os.path.dirname(__file__), "..", "data", "website_locations.json")
    locations = json.load(open(loc_path)) if os.path.exists(loc_path) else []
    decided = _proposal_dicts()
    by_slug = {d["slug"]: d for d in decided if d.get("slug")}
    rows = []
    for loc in locations:
        d = by_slug.get(loc["slug"])
        rows.append({
            "loc": loc,
            "outcome": (d["change_type"] if d else "clean"),
            "d": d,
        })
    retired = [d for d in decided if not d.get("slug")]
    outcomes = {}
    for r in rows:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return templates.TemplateResponse(request, "results.html", {
        "rows": rows,
        "retired": retired,
        "outcomes": outcomes,
        "approved": sum(1 for d in decided if d["status"] == "approved"),
        "pending": sum(1 for d in decided if d["status"] == "pending"),
    })


@app.get("/endstate", response_class=HTMLResponse)
def endstate(request: Request):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pipeline.verify()
    return templates.TemplateResponse(request, "endstate.html", {"report": buf.getvalue()})
