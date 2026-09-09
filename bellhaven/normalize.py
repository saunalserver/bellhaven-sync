"""Normalization helpers. The CRM and the website describe the same streets and
names in different styles ("750 Stewart Rd" vs "750 Stewart Road"), so every
comparison goes through these normalizers first."""
import re

STREET_EXPANSIONS = [
    (r"\bnorthwest\b", "nw"), (r"\bnortheast\b", "ne"), (r"\bsouthwest\b", "sw"), (r"\bsoutheast\b", "se"),
    (r"\bnorth\b", "n"), (r"\bsouth\b", "s"), (r"\beast\b", "e"), (r"\bwest\b", "w"),
    (r"\bstreet\b", "st"), (r"\bavenue\b", "ave"), (r"\bav\b", "ave"), (r"\broad\b", "rd"),
    (r"\bdrive\b", "dr"), (r"\bboulevard\b", "blvd"), (r"\blane\b", "ln"), (r"\bpike\b", "pk"),
    (r"\bcourt\b", "ct"), (r"\bplace\b", "pl"), (r"\bcircle\b", "cir"), (r"\bpkwy\b", "pkwy"),
    (r"\bparkway\b", "pkwy"), (r"\bterrace\b", "ter"), (r"\btrail\b", "trl"),
]

def norm_street(s: str) -> str:
    s = (s or "").lower().strip()
    for pat, rep in STREET_EXPANSIONS:
        s = re.sub(pat, rep, s)
    return re.sub(r"[^a-z0-9]", "", s)

def norm_city(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def norm_phone(s: str) -> str:
    return (re.sub(r"\D", "", s or "") or "")[-10:]

# Care offering names as they appear on the website -> CRM care_type vocabulary.
CARE_MAP = {
    "Short-Term Rehabilitation & Nursing": "Skilled Nursing",
    "Assisted Living": "Assisted Living",
    "Memory Support": "Memory Care",
    "Independent Living": "Independent Living",
}

NAME_STOPWORDS = {
    "the", "of", "at", "and", "care", "center", "centre", "senior", "living",
    "rehab", "rehabilitation", "nursing", "commons", "campus", "manor", "home",
    "estate", "estates", "gardens", "court", "crossings", "shores", "terrace",
    "woods", "meadows", "village", "acres", "acre", "retirement", "healthcare",
    "health", "place", "square",
}

def norm_name_tokens(s: str) -> set:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return {t for t in s.split() if t not in NAME_STOPWORDS}

def name_similarity(a: str, b: str) -> float:
    """Jaccard over meaningful name tokens. 'Bellhaven of Owosso' vs
    'Bellhaven of Owosso' -> 1.0; catches drift like 'Sunny Acres Retirement
    Home' vs 'Bellhaven Willow Creek' only weakly (address does that job)."""
    ta, tb = norm_name_tokens(a), norm_name_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
