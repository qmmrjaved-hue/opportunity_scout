"""
OpportunityScout automatic discovery.

Designed around the Gemini free tier (~20 requests/day per model), so a full run costs only
`n_rounds + ceil(max_evaluate / BATCH_SIZE)` requests (5 with the defaults):

  1. search rounds    – one grounded Gemini call per round plans AND runs several Google searches
  2. fetch_documents  – Playwright/pypdf read every hit and the call PDFs it links to (no Gemini)
  3. pre-rank         – keyword overlap keeps the most promising documents (no Gemini)
  4. batch screening  – Gemini scores relevance/authenticity/visa for BATCH_SIZE documents per call
Full CV tailoring runs later, on demand, for a single position (CV Tailoring Studio).
"""

from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Callable
from urllib.parse import urlparse

import requests
from google.genai import types

from agent import (ANALYSIS_MODELS, NO_AFC, SEARCH_MODELS, OpportunityScoutAgent, QuotaExhaustedError,
                   parse_json_loose)
from parser import USER_AGENT, FetchedDoc, extract_deadlines, fetch_documents, run_async, score_domain

ProgressFn = Callable[[float, str], None]

BATCH_SIZE = 4
DOC_CHARS_IN_BATCH = 7000
MIN_TEXT_CHARS = 400
VISA_TAGS = {"[VISA SPONSORED]", "[RESEARCH VISA ELIGIBLE]", "[LOCAL ONLY]", "[UNCLEAR]"}
# Social and reference sites that never hold a job posting. Job boards (LinkedIn, Seek, Indeed…) are
# allowed: they usually block automated reading, so they appear as "snippet only" results.
BLOCKED_HOSTS = (
    "google.com", "youtube.com", "facebook.com", "instagram.com", "x.com", "twitter.com",
    "reddit.com", "wikipedia.org", "quora.com", "medium.com", "tiktok.com",
)
SEARCH_ANGLES = {
    "Academic": [
        "official university and research-institute calls: PhD scholarships, postdoc/research fellow "
        "contracts, research assistant posts, including links to the official call PDFs",
        "EU and national research job portals (e.g. EURAXESS) and funded project positions "
        "(ERC, Marie Skłodowska-Curie doctoral networks, national grants) hosted by research groups",
        "faculty and permanent/fixed-term research staff openings, and lab or group pages that "
        "advertise open positions",
    ],
    "Industry": [
        "company careers pages and applicant-tracking boards (Greenhouse, Lever, Workday, "
        "SmartRecruiters, Ashby, Personio) for matching roles",
        "corporate R&D labs and applied research institutes hiring scientists or engineers",
        "startups and scale-ups in this field with open roles",
    ],
}
STOPWORDS = set("the and for with from that this into have has are was were your you our their of in on at "
                "to a an or by as is be".split())


# Academic levels → what they mean and the terms official calls use for them
ACADEMIC_LEVELS = {
    "Master's": "Master's degree places and master's scholarships (e.g. Erasmus Mundus, 'laurea magistrale' "
                "scholarships, DAAD master's scholarships, 'bourse de master', 'beca de máster')",
    "PhD": "doctoral positions and PhD scholarships (e.g. 'dottorato di ricerca', 'borsa di dottorato', "
           "'Promotionsstelle', 'Doktorand', 'contrat doctoral', 'offre de thèse', 'contrato predoctoral', "
           "'PhD studentship', 'doctoral candidate')",
    "Post-doc": "postdoctoral positions (e.g. 'assegno di ricerca', 'postdoc', 'Postdoktorand', "
                "'wissenschaftliche/r Mitarbeiter/in (Postdoc)', 'post-doctorat', 'contrato posdoctoral', "
                "'research associate', 'postdoctoral fellow')",
    "Research Assistant / Fellow": "research assistant and research fellow posts not requiring a PhD "
                                   "(e.g. 'borsa di ricerca', 'research assistant', 'wissenschaftliche Hilfskraft', "
                                   "'ingénieur d'études', 'research fellow')",
    "Faculty": "lecturer / professor / tenure-track posts (e.g. 'RTD-A', 'RTD-B', 'professore associato', "
               "'W1/W2/W3 Professur', 'maître de conférences', 'lecturer', 'assistant professor')",
}
LEVEL_ENUM = list(ACADEMIC_LEVELS) + ["Other"]


@dataclass
class SearchProfile:
    domain: str = ""
    skills: str = ""
    cv: str = ""
    country: str = "Global"
    track: str = "Academic"
    levels: list[str] = field(default_factory=list)   # empty = any level

    @property
    def is_global(self) -> bool:
        return not self.country or self.country.lower().startswith(("global", "🌍"))

    @property
    def region(self) -> str:
        return "anywhere in the world" if self.is_global else self.country

    @property
    def target_levels(self) -> list[str]:
        return self.levels if self.track == "Academic" else []

    def level_instruction(self) -> str:
        if not self.target_levels:
            return ""
        wanted = "\n".join(f"  - {lvl}: {ACADEMIC_LEVELS[lvl]}" for lvl in self.target_levels)
        return (f"The candidate is applying ONLY at these level(s):\n{wanted}\n"
                "Ignore positions at any other level.")

    def as_text(self, cv_chars: int = 5000) -> str:
        parts = []
        if self.target_levels:
            parts.append(f"Applying for level(s): {', '.join(self.target_levels)}")
        if self.domain:
            parts.append(f"Domain / field: {self.domain}")
        if self.skills:
            parts.append(f"Key skills: {self.skills}")
        if self.cv.strip():
            parts.append(f"CV:\n{self.cv[:cv_chars]}")
        return "\n".join(parts)

    def candidate_cv(self) -> str:
        """Text given to the tailoring step: the real CV, or a clearly labelled profile."""
        if self.cv.strip():
            return self.cv
        return ("CANDIDATE PROFILE (no full CV supplied — tailor only from these facts)\n"
                f"Domain: {self.domain or 'n/a'}\nSkills: {self.skills or 'n/a'}")


@dataclass
class DiscoveryLog:
    focus_summary: str = ""
    keywords: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    gemini_calls: int = 0
    models_used: set[str] = field(default_factory=set)


# --------------------------------------------------------------------------- #
# 1. Grounded search rounds
# --------------------------------------------------------------------------- #
def _resolve(url: str) -> str | None:
    """Follow Google grounding redirects to the real destination URL."""
    if "grounding-api-redirect" not in url:
        return url
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15,
                            allow_redirects=True, stream=True)
        resp.close()
        return resp.url
    except Exception:
        return None


def _allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and not any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


def search_round(agent: OpportunityScoutAgent, profile: SearchProfile, angle: str, log: DiscoveryLog) -> list[dict]:
    prompt = f"""Today is {date.today().isoformat()}.
You are searching for CURRENTLY OPEN {profile.track.upper()} positions located {profile.region}
that fit this candidate:

{profile.as_text()}

{profile.level_instruction()}
Search angle for this round: {angle}.

Instructions:
- Run several Google searches (at least 4). Keep each query short and natural (4-10 words), no
  site:/filetype: operators. Mix English with the official regional terms for the target country
  (e.g. Italy "bando", "assegno di ricerca", "dottorato"; Germany "Stellenausschreibung",
  "wissenschaftliche Mitarbeiter"; France "offre de thèse", "post-doctorat"; Spain "convocatoria").
- For a global search, cover several strong research countries.
- Keep only postings whose deadline has not passed (or is not stated) and that match the candidate's
  field. Prefer official institution pages, official call PDFs and employer ATS boards, but also
  include scholarship/position listing pages of universities and research institutes.

Answer in plain text (NOT JSON): list as many distinct matching positions as you can find (aim for
10-15), one short paragraph each with title, institution, level, deadline if known, and a one-line
description, citing the search results you used. Do not write URLs yourself.
End with exactly two lines:
FOCUS: <one sentence on the candidate's core focus>
KEYWORDS: <10-20 lowercase skill/topic keywords, comma-separated>"""
    # Plain-text answers keep Google's citation metadata; asking for JSON drops it and makes the
    # model type URLs from memory, which are mostly invalid.
    cfg = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.3,
        automatic_function_calling=NO_AFC,
    )
    resp = agent.generate(prompt, cfg, models=SEARCH_MODELS)
    log.gemini_calls += 1
    log.models_used.add(agent.last_model or agent.model)
    text = resp.text or ""

    focus = re.search(r"^\W*FOCUS:\s*(.+)$", text, re.M)
    if focus and not log.focus_summary:
        log.focus_summary = focus.group(1).strip()
    kw = re.search(r"^\W*KEYWORDS:\s*(.+)$", text, re.M)
    if kw:
        log.keywords += [k.strip().lower() for k in kw.group(1).split(",") if k.strip()]

    found: list[dict] = []
    meta = resp.candidates[0].grounding_metadata if resp.candidates else None
    if meta:
        log.queries += list(meta.web_search_queries or [])
        # Text segments citing each source become that source's search snippet
        snippets: dict[int, list[str]] = {}
        for support in meta.grounding_supports or []:
            for idx in support.grounding_chunk_indices or []:
                if support.segment and support.segment.text:
                    snippets.setdefault(idx, []).append(support.segment.text)
        for idx, chunk in enumerate(meta.grounding_chunks or []):
            if chunk.web and chunk.web.uri:
                found.append({"url": chunk.web.uri, "title": chunk.web.title or "", "origin": "grounding",
                              "snippet": " ".join(dict.fromkeys(snippets.get(idx, [])))[:2000]})
    if not found:
        log.errors.append(f"A search round ({angle[:40]}…) returned no citable sources.")
    return found


def search_web(agent: OpportunityScoutAgent, profile: SearchProfile, n_rounds: int, log: DiscoveryLog) -> list[dict]:
    hits: list[dict] = []
    for angle in SEARCH_ANGLES[profile.track][:n_rounds]:
        try:
            hits.extend(search_round(agent, profile, angle, log))
        except QuotaExhaustedError:
            if not hits:
                raise QuotaExhaustedError(
                    "Today's web-search quota is used up. On the free tier, Google Search runs only on "
                    "gemini-2.5-flash (about 20 requests/day, reset at midnight Pacific Time). Meanwhile you "
                    "can use 🔗 Manual portal URLs mode, or enable billing in Google AI Studio for higher limits."
                ) from None
            log.errors.append("Search quota ran out part-way; showing results from completed rounds.")
            break
        except Exception as exc:
            log.errors.append(f"Search round failed: {exc}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        resolved = list(pool.map(lambda h: _resolve(h["url"]), hits))
    unique: dict[str, dict] = {}
    for hit, url in zip(hits, resolved):
        if not url or not _allowed(url):
            continue
        key = url.split("#")[0].rstrip("/")
        existing = unique.get(key)
        if existing is None:
            unique[key] = {**hit, "url": key}
        elif hit.get("snippet"):  # same page cited in several rounds: combine what each said about it
            existing["snippet"] = f"{existing.get('snippet', '')} {hit['snippet']}".strip()[:3000]
    return list(unique.values())


# --------------------------------------------------------------------------- #
# 2-3. Pre-ranking
# --------------------------------------------------------------------------- #
def _keywords(profile: SearchProfile, extra: list[str]) -> list[str]:
    words = list(extra)
    for source in (profile.domain, profile.skills):
        words += [w.strip().lower() for w in re.split(r"[,;/\n]", source) if len(w.strip()) > 2]
    return [w for w in dict.fromkeys(words) if w not in STOPWORDS]


def keyword_overlap(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    lowered = text.lower()
    return sum(1 for k in keywords if k in lowered) / len(keywords)


# --------------------------------------------------------------------------- #
# 4. Batch screening → dashboard rows
# --------------------------------------------------------------------------- #
def _parse_iso(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def base_row(doc: FetchedDoc, hint: dict | None = None) -> dict:
    """Row built from scraping only (used as-is when Gemini is off)."""
    hint = hint or {}
    url = doc.final_url or doc.url
    auth, basis = score_domain(doc.pdf_urls[0] if doc.pdf_urls else url)
    if hint.get("snippet_only"):
        # Never "verified" when the page itself was not read
        auth, basis = min(auth, 85), f"Search snippet only — page not readable automatically ({basis})"
    deadlines = extract_deadlines(doc.text) if doc.text else []
    return {
        "Relevance %": None,
        "Title": hint.get("title") or doc.title or url,
        "Level": None,
        "Institution": hint.get("institution") or (urlparse(url).hostname or ""),
        "Country": hint.get("country"),
        "Deadline": deadlines[0] if deadlines else hint.get("deadline"),
        "Status": "",
        "Visa Status": "[UNCLEAR]",
        "Authenticity %": auth,
        "Salary": None,
        "Why relevant": "",
        "Skill gaps": "",
        "Verification Basis": basis,
        "Source": url,
        "PDF": doc.pdf_urls[0] if doc.pdf_urls else None,
        "Error": doc.error,
        "_text": doc.text,
        "_eval": None,
        "_snippet_only": bool(hint.get("snippet_only")),
    }


def apply_evaluation(row: dict, ev: dict) -> dict:
    row["Title"] = ev.get("title") or row["Title"]
    row["Level"] = ev.get("position_level") if ev.get("position_level") in LEVEL_ENUM else None
    row["Institution"] = ev.get("institution") or row["Institution"]
    row["Country"] = ev.get("country") or row["Country"]
    row["Deadline"] = ev.get("deadline") or row["Deadline"]
    row["Salary"] = ev.get("salary") or row["Salary"]
    row["Visa Status"] = ev.get("visa_status") if ev.get("visa_status") in VISA_TAGS else "[UNCLEAR]"
    # Conservative: never let the model raise authenticity above the domain heuristic
    row["Authenticity %"] = min(row["Authenticity %"], int(ev.get("authenticity_score") or 0))
    row["Relevance %"] = int(ev.get("relevance_score") or 0)
    row["Why relevant"] = "; ".join(ev.get("matched_requirements", [])[:5])
    row["Skill gaps"] = "; ".join(ev.get("missing_requirements", [])[:5])
    row["Verification Basis"] = "; ".join(ev.get("authenticity_evidence", [])[:2]) or row["Verification Basis"]
    row["_eval"] = ev
    return row


def finalize_status(row: dict) -> dict:
    d = _parse_iso(row.get("Deadline"))
    ev = row.get("_eval") or {}
    if row.get("Error"):
        row["Status"] = "⚠️ Error"
    elif d and d < date.today():
        row["Status"] = "⛔ Expired"
    elif ev and ev.get("is_specific_posting") is False:
        row["Status"] = "📋 Listing page (may hold several positions)"
    elif d:
        row["Status"] = f"✅ Open ({(d - date.today()).days} days left)"
    else:
        row["Status"] = "❔ Deadline unknown"
    if row.get("_snippet_only") and not row["Status"].startswith(("⛔", "⚠️")):
        row["Status"] = f"🔒 Snippet only, open link to verify · {row['Status']}"
    if row.pop("_unscored", False):
        row["Status"] = f"⏸ Not scored (Gemini quota) · {row['Status']}"
    return row


def screen_batch(agent: OpportunityScoutAgent, docs: list[FetchedDoc], profile: SearchProfile) -> list[dict]:
    """One Gemini call that screens several documents against the candidate profile."""
    blocks = []
    for i, d in enumerate(docs):
        blocks.append(f"=== DOCUMENT {i} ===\nSOURCE URL: {d.final_url or d.url}\n"
                      f"PDF URLS: {', '.join(d.pdf_urls) or 'none'}\n{d.text[:DOC_CHARS_IN_BATCH]}")
    prompt = f"""BATCH SCREENING REQUEST — this overrides the single-object output format in section 5
of your instructions. Do NOT tailor the CV here. Apply your authenticity, visa and zero-hallucination
rules to each document. Today is {date.today().isoformat()}.

TARGET: {profile.track} positions located {profile.region}.
{profile.level_instruction()}
{"If a document's position_level is not one of the candidate's target levels, relevance_score must be "
 "at most 30 and relevance_reason must say the level does not match." if profile.target_levels else ""}
CANDIDATE:
{profile.as_text(cv_chars=6000)}

{chr(10).join(blocks)}

Return ONLY JSON: {{"evaluations": [ one object per document, same order:
{{"id": int, "is_specific_posting": bool,   // false for listing pages, news, general info
  "title": str|null, "institution": str|null, "country": str|null,
  "position_level": {" | ".join(f'"{lvl}"' for lvl in LEVEL_ENUM)},
  "deadline": "YYYY-MM-DD"|null, "salary": str|null,
  "relevance_score": int,        // 0-100 fit between candidate and this position
  "authenticity_score": int,     // 0-100 per your authenticity rules
  "authenticity_evidence": [str], "red_flags": [str],
  "visa_status": "[VISA SPONSORED]"|"[RESEARCH VISA ELIGIBLE]"|"[LOCAL ONLY]"|"[UNCLEAR]",
  "visa_evidence": str,
  "matched_requirements": [str],  // only strengths actually shown by the candidate
  "missing_requirements": [str],
  "relevance_reason": str }} ]}}"""
    cfg = types.GenerateContentConfig(
        system_instruction=agent.system_instruction,
        response_mime_type="application/json",
        temperature=0.2,
        automatic_function_calling=NO_AFC,
    )
    data = parse_json_loose(agent.generate(prompt, cfg, models=ANALYSIS_MODELS).text or "{}")
    evals = data.get("evaluations", []) if isinstance(data, dict) else data
    by_id = {e.get("id"): e for e in evals if isinstance(e, dict)}
    return [by_id.get(i, evals[i] if i < len(evals) else {}) for i in range(len(docs))]


def evaluate_documents(agent: OpportunityScoutAgent | None, docs: list[tuple[FetchedDoc, dict]],
                       profile: SearchProfile, progress: ProgressFn | None = None,
                       log: DiscoveryLog | None = None) -> list[dict]:
    rows = [base_row(d, h) for d, h in docs]

    def screen(batch: list[int]) -> None:
        evals = screen_batch(agent, [docs[i][0] for i in batch], profile)
        if log:
            log.gemini_calls += 1
            log.models_used.add(agent.last_model or agent.model)
        for i, ev in zip(batch, evals):
            if not ev:
                continue
            apply_evaluation(rows[i], ev)
            if profile.track != "Academic":
                rows[i]["Level"] = None
            elif profile.target_levels and rows[i]["Level"] and rows[i]["Level"] not in profile.target_levels:
                rows[i]["Relevance %"] = min(rows[i]["Relevance %"], 30)

    if agent is not None:
        todo = [i for i, (d, _) in enumerate(docs) if d.text.strip() and not d.error]
        batches = [todo[k:k + BATCH_SIZE] for k in range(0, len(todo), BATCH_SIZE)]
        try:
            for n, batch in enumerate(batches, 1):
                if progress:
                    progress((n - 1) / len(batches), f"Reading & scoring positions… batch {n}/{len(batches)}")
                try:
                    screen(batch)
                except QuotaExhaustedError:
                    raise
                except Exception:
                    # One bad document (odd characters, huge text…) can break a whole batch: retry singly
                    for i in batch:
                        try:
                            screen([i])
                        except QuotaExhaustedError:
                            raise
                        except Exception as exc:
                            rows[i]["Error"] = f"Gemini: {type(exc).__name__}: {str(exc)[:200]}"
        except QuotaExhaustedError as exc:
            if log:
                log.errors.append(f"Scoring stopped early: {exc}")
        for i in todo:
            if rows[i]["_eval"] is None and not rows[i]["Error"]:
                rows[i]["_unscored"] = True
        if progress:
            progress(1.0, "Scoring complete")
    rows = _dedupe([finalize_status(r) for r in rows])
    rows.sort(key=lambda r: ("📋" in r["Status"], -(r["Relevance %"] or 0)))
    return rows


def _dedupe(rows: list[dict]) -> list[dict]:
    """The same posting often appears on several pages (e.g. two Seek searches): keep the best copy."""
    best: dict[tuple, dict] = {}
    for r in rows:
        if not r["_eval"] or "📋" in r["Status"]:
            best[("url", r["Source"])] = r
            continue
        key = (re.sub(r"\W+", " ", str(r["Title"]).lower()).strip(), str(r["Institution"]).lower().strip())
        kept = best.get(key)
        if kept is None or (r["Authenticity %"], r["Relevance %"] or 0) > (kept["Authenticity %"], kept["Relevance %"] or 0):
            best[key] = r
    return list(best.values())


# --------------------------------------------------------------------------- #
# End-to-end
# --------------------------------------------------------------------------- #
def estimated_calls(n_rounds: int, max_evaluate: int) -> int:
    return n_rounds + math.ceil(max_evaluate / BATCH_SIZE)


def discover(agent: OpportunityScoutAgent, profile: SearchProfile, n_rounds: int = 2,
             max_evaluate: int = 10, progress: ProgressFn | None = None) -> dict:
    log = DiscoveryLog()
    step = (lambda f, msg: progress(f, msg)) if progress else (lambda f, msg: None)

    step(0.03, f"Searching the web ({n_rounds} search round(s), several queries each)…")
    hits = search_web(agent, profile, n_rounds, log)

    step(0.35, f"Opening {len(hits)} pages and reading call PDFs…")
    fetched = run_async(fetch_documents([h["url"] for h in hits])) if hits else []
    by_url = {h["url"]: h for h in hits}

    keywords = _keywords(profile, log.keywords)
    usable: list[tuple[FetchedDoc, dict]] = []
    for d in fetched:
        hint = by_url.get(d.url, {})
        if not d.error and len(d.text.strip()) >= MIN_TEXT_CHARS:
            usable.append((d, hint))
        elif hint.get("snippet"):
            # Page blocks automated readers (403) or had no readable text: keep the position using
            # what Google's results said about it, clearly marked as unverified.
            reason = d.error or "too little readable text"
            usable.append((FetchedDoc(
                url=d.url, final_url=d.final_url or d.url, kind="snippet", title=d.title or hint.get("title", ""),
                text=(f"[NOTE: the page itself could not be read automatically ({reason}). The text below is "
                      f"only what Google search results said about it; treat every detail as unverified.]\n"
                      f"{hint['snippet']}"),
            ), {**hint, "snippet_only": True}))
    usable.sort(key=lambda dh: keyword_overlap(dh[0].text, keywords) + (0.15 if dh[0].pdf_urls else 0),
                reverse=True)
    selected = usable[:max_evaluate]

    step(0.55, f"Scoring relevance of {len(selected)} positions with Gemini…")
    rows = evaluate_documents(agent, selected, profile,
                              lambda f, msg: step(0.55 + 0.45 * f, msg), log)
    step(1.0, "Done")

    return {
        "plan": {"focus_summary": log.focus_summary, "queries": list(dict.fromkeys(log.queries)),
                 "keywords": keywords},
        "rows": rows,
        "stats": {
            "search_hits": len(hits),
            "pages_read": len(fetched),
            "readable": len(usable),
            "evaluated": len(selected),
            "gemini_calls": log.gemini_calls,
            "models": sorted(log.models_used),
            "errors": log.errors,
        },
    }
