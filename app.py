"""
OpportunityScout Streamlit dashboard.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import importlib.metadata as md
import io
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from agent import OpportunityScoutAgent, api_key_configured
from discovery import ACADEMIC_LEVELS, SearchProfile, discover, estimated_calls, evaluate_documents
from parser import FetchedDoc, extract_pdf_text, run_scrape

BASE_DIR = Path(__file__).resolve().parent
CANDIDATES_DIR = BASE_DIR / "candidates"
CANDIDATES_DIR.mkdir(exist_ok=True)

COUNTRIES = [
    "🌍 Global", "Italy", "Germany", "France", "Spain", "Netherlands", "United Kingdom",
    "Switzerland", "Sweden", "Denmark", "Finland", "Norway", "Belgium", "Austria", "Ireland",
    "Portugal", "United States", "Canada", "Australia", "Japan", "Singapore", "China",
]
VISA_BADGES = {
    "[VISA SPONSORED]": "🟢",
    "[RESEARCH VISA ELIGIBLE]": "🔵",
    "[LOCAL ONLY]": "🔴",
    "[UNCLEAR]": "⚪",
}
AUTH_THRESHOLD = 90
NO_CV = "— No CV (use domain & skills only) —"
NEW_CV = "➕ New candidate"
PRIVATE_COLS = ["_text", "_eval", "_snippet_only"]

st.set_page_config(page_title="OpportunityScout", page_icon="🧭", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem;}
      div[data-testid="stMetric"] {background: rgba(120,120,120,0.08); border-radius: 10px; padding: 10px 14px;}
      .gap-note {border-left: 4px solid #e8a33d; padding: 6px 12px; margin: 6px 0; background: rgba(232,163,61,0.08);}
      .evidence {color: #888; font-size: 0.85em;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.session_state.setdefault("positions", [])
st.session_state.setdefault("plan", None)
st.session_state.setdefault("stats", None)
st.session_state.setdefault("tailor_result", None)


@st.cache_resource(show_spinner=False)
def get_agent() -> OpportunityScoutAgent:
    return OpportunityScoutAgent()


def list_candidates() -> dict[str, Path]:
    return {p.stem.replace("_", " ").title(): p for p in sorted(CANDIDATES_DIR.glob("*.txt"))}


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.title("🧭 OpportunityScout")
    st.caption("Finds research positions & jobs aligned with your profile, verified and ranked by relevance.")

    target_country = st.selectbox("Target Country", COUNTRIES)
    career_track = st.radio("Career Track", ["Academic", "Industry"], horizontal=True)
    position_levels: list[str] = []
    if career_track == "Academic":
        position_levels = st.multiselect(
            "Position Level", list(ACADEMIC_LEVELS), default=["PhD"],
            help="Which level you are applying for. Leave empty to search all levels.",
        )
    domain_field = st.text_input("Domain Field", placeholder="e.g. Machine Learning for Medical Imaging")
    skills = st.text_area("Key Skills (comma-separated)", height=80,
                          placeholder="e.g. PyTorch, image segmentation, Python, deep learning")

    st.divider()
    candidates = list_candidates()
    candidate_name = st.selectbox("Candidate CV", list(candidates) + [NO_CV, NEW_CV])
    master_cv_default = ""
    if candidate_name == NEW_CV:
        new_name = st.text_input("Candidate name")
        uploaded = st.file_uploader("Master CV (.txt or .pdf)", type=["txt", "pdf"])
        if st.button("Save candidate", disabled=not (new_name and uploaded)):
            if uploaded.name.lower().endswith(".pdf"):
                cv_text = extract_pdf_text(uploaded.getvalue())
            else:
                cv_text = uploaded.getvalue().decode("utf-8", errors="ignore")
            slug = "".join(c if c.isalnum() else "_" for c in new_name.strip().lower())
            (CANDIDATES_DIR / f"{slug}.txt").write_text(cv_text, encoding="utf-8")
            st.success(f"Saved {new_name}.")
            st.rerun()
    elif candidate_name in candidates:
        master_cv_default = candidates[candidate_name].read_text(encoding="utf-8")

    st.divider()
    st.markdown(
        f"**Gemini:** {'🟢 key loaded' if api_key_configured() else '🔴 set GEMINI_API_KEY in .env'}"
    )

profile = SearchProfile(domain=domain_field.strip(), skills=skills.strip(), cv=master_cv_default,
                        country=target_country, track=career_track, levels=position_levels)
has_profile = bool(profile.domain or profile.skills or profile.cv.strip())

tab_dash, tab_cv, tab_cfg = st.tabs(["📊 Positions Dashboard", "✍️ CV Tailoring Studio", "⚙️ System Configuration"])

# --------------------------------------------------------------------------- #
# Tab 1 — Positions Dashboard
# --------------------------------------------------------------------------- #
with tab_dash:
    st.subheader(f"{career_track} positions · {target_country}" + (f" · {domain_field}" if domain_field else ""))

    mode = st.radio("Discovery mode", ["🤖 Automatic discovery", "🔗 Manual portal URLs"], horizontal=True,
                    label_visibility="collapsed")

    if mode.startswith("🤖"):
        st.caption("Uses your domain, skills and selected CV to search the web, open each position page and its "
                   "call PDFs, then scores how well each one fits you.")
        c1, c2, c3 = st.columns([1, 1, 1])
        n_rounds = c1.slider("Search rounds", 1, 3, 2,
                             help="Each round runs several Google searches from a different angle.")
        max_eval = c2.slider("Positions to read & score", 4, 24, 12, step=4,
                             help="Positions are scored 4 per Gemini call.")
        with c3:
            st.caption(f"≈ {estimated_calls(n_rounds, max_eval)} Gemini calls "
                       "(free tier: ~20/day per model, with automatic model fallback)")
            run_auto = st.button("🚀 Find matching positions", type="primary", width="stretch",
                                 disabled=not (api_key_configured() and has_profile))
        if not has_profile:
            st.info("Enter a **Domain Field**, **Key Skills**, or select a **Candidate CV** in the sidebar.")
        if run_auto:
            bar = st.progress(0.0, text="Starting…")
            try:
                result = discover(get_agent(), profile, n_rounds=n_rounds, max_evaluate=max_eval,
                                  progress=lambda f, msg: bar.progress(min(1.0, f), text=msg))
                st.session_state.positions = result["rows"]
                st.session_state.plan = result["plan"]
                st.session_state.stats = result["stats"]
            except Exception as exc:
                st.error(f"Discovery failed: {exc}")
            finally:
                bar.empty()
    else:
        col_urls, col_opts = st.columns([3, 1])
        with col_urls:
            portal_urls = st.text_area(
                "Portal URLs (one per line) — official university job/call pages or direct ATS boards",
                height=110,
                placeholder="https://www.example-university.edu/jobs\nhttps://boards.greenhouse.io/examplecompany",
            )
        with col_opts:
            max_pdfs = st.number_input("Max PDFs per portal", 1, 50, 10)
            use_gemini = st.toggle("Score with Gemini", value=api_key_configured(),
                                   disabled=not api_key_configured())
        if st.button("🔎 Run Scout", type="primary", disabled=not portal_urls.strip()):
            with st.spinner("Loading portals in headless Chromium and parsing PDFs…"):
                calls = run_scrape(portal_urls.splitlines(), int(max_pdfs))
            docs = [(FetchedDoc(url=c.pdf_url, final_url=c.pdf_url, kind="pdf", title=c.title, text=c.text,
                                pdf_urls=[c.pdf_url], error=c.error), {}) for c in calls]
            bar = st.progress(0.0, text="Scoring…")
            rows = evaluate_documents(get_agent() if use_gemini else None, docs, profile,
                                      progress=lambda f, msg: bar.progress(f, text=msg))
            bar.empty()
            st.session_state.positions, st.session_state.plan, st.session_state.stats = rows, None, None

    # ---------------- Results ---------------- #
    positions = st.session_state.positions
    plan, stats = st.session_state.plan, st.session_state.stats
    if plan:
        with st.expander("🧠 Search strategy used"):
            st.markdown(f"**Detected focus:** {plan.get('focus_summary', '')}")
            st.markdown("**Queries:** " + " · ".join(f"`{q}`" for q in plan.get("queries", [])))
            if stats:
                st.caption(f"{stats['search_hits']} search hits → {stats['pages_read']} pages opened → "
                           f"{stats['readable']} readable → {stats['evaluated']} scored · "
                           f"{stats['gemini_calls']} Gemini calls ({', '.join(stats['models'])})")
        for err in (stats or {}).get("errors", []):
            st.warning(err)

    if positions:
        st.divider()
        f1, f2, f3, f4 = st.columns(4)
        hide_expired = f1.toggle("Hide expired / errors", value=True)
        hide_listings = f2.toggle("Hide listing pages", value=False,
                                  help="Pages that are not a specific open position (program pages, listings, news).")
        verified_only = f3.toggle(f"Only ≥{AUTH_THRESHOLD}% authentic", value=False)
        min_rel = f4.slider("Minimum relevance %", 0, 100, 0, step=5)

        df = pd.DataFrame(positions)
        mask = pd.Series(True, index=df.index)
        if hide_expired:
            mask &= ~df["Status"].str.startswith(("⛔", "⚠️"))
        if hide_listings:
            mask &= ~df["Status"].str.contains("📋")
        if profile.target_levels and st.toggle(
                f"Only my level ({', '.join(profile.target_levels)})", value=True,
                help="Hide positions whose level differs from the one you selected. Unknown levels stay visible."):
            mask &= df["Level"].isna() | df["Level"].isin(profile.target_levels)
        if verified_only:
            mask &= df["Authenticity %"] >= AUTH_THRESHOLD
        if min_rel:
            mask &= df["Relevance %"].fillna(0) >= min_rel
        shown = df[mask]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Positions shown", f"{len(shown)} / {len(df)}")
        m2.metric("Strong matches (≥70%)", int((shown["Relevance %"].fillna(0) >= 70).sum()))
        m3.metric(f"Verified ≥{AUTH_THRESHOLD}%", int((shown["Authenticity %"] >= AUTH_THRESHOLD).sum()))
        m4.metric("Visa-friendly", int(shown["Visa Status"].isin(["[VISA SPONSORED]", "[RESEARCH VISA ELIGIBLE]"]).sum()))

        if shown.empty:
            st.info("No positions match the current filters — try switching some of them off.")
        display = shown.drop(columns=PRIVATE_COLS).copy()
        display["Visa Status"] = display["Visa Status"].map(lambda v: f"{VISA_BADGES.get(v, '')} {v}")
        st.dataframe(
            display,
            hide_index=True,
            column_config={
                "Relevance %": st.column_config.ProgressColumn("Relevance %", min_value=0, max_value=100, format="%d%%"),
                "Authenticity %": st.column_config.ProgressColumn("Authenticity %", min_value=0, max_value=100, format="%d%%"),
                "Source": st.column_config.LinkColumn("Source", display_text="Open page"),
                "PDF": st.column_config.LinkColumn("PDF", display_text="Open PDF"),
            },
        )

        buf = io.BytesIO()
        df.drop(columns=PRIVATE_COLS).to_excel(buf, index=False, engine="openpyxl")
        st.download_button("⬇️ Export all to Excel", buf.getvalue(), "opportunity_scout_positions.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.markdown("### 🎯 Position details (ranked by relevance)")
        for idx, row in shown.head(25).iterrows():
            rel = f"{int(row['Relevance %'])}%" if pd.notna(row["Relevance %"]) else "n/a"
            with st.expander(f"{rel} · {row['Title']} — {row['Institution'] or ''}"):
                a, b, c, d = st.columns(4)
                a.metric("Relevance", rel)
                b.metric("Authenticity", f"{row['Authenticity %']}%")
                c.metric("Deadline", row["Deadline"] or "—")
                d.metric("Visa", VISA_BADGES.get(row["Visa Status"], "") + " " + row["Visa Status"].strip("[]").title())
                st.caption(f"{row['Status']} · {row['Country'] or ''} · {row['Salary'] or 'salary not stated'}")
                ev = row["_eval"]
                if ev:
                    if ev.get("relevance_reason"):
                        st.info(ev["relevance_reason"])
                    l, r = st.columns(2)
                    with l:
                        st.markdown("**Why it fits you**")
                        for m in ev.get("matched_requirements") or ["—"]:
                            st.markdown(f"- ✅ {m}")
                    with r:
                        st.markdown("**Skill gaps**")
                        for m in ev.get("missing_requirements") or ["None identified"]:
                            st.markdown(f"- ❌ {m}")
                    if ev.get("visa_evidence"):
                        st.caption(f"Visa evidence: {ev['visa_evidence']}")
                    if ev.get("red_flags"):
                        st.warning("Red flags: " + "; ".join(ev["red_flags"]))
                links = f"[Open source page]({row['Source']})"
                if row["PDF"]:
                    links += f" · [Open call PDF]({row['PDF']})"
                st.markdown(links)
                if row["Error"]:
                    st.caption(f"⚠️ {row['Error']}")
                if row["_text"] and st.button("✍️ Tailor my CV for this position", key=f"tailor_{idx}"):
                    st.session_state.job_text = row["_text"]
                    st.session_state.tailor_result = None
                    st.success("Loaded — open the ✍️ CV Tailoring Studio tab and press Evaluate & Tailor.")
    elif not (st.session_state.plan or st.session_state.stats):
        st.info("Set your profile in the sidebar and press **Find matching positions**.")
    else:
        st.warning("No readable positions were found. Try a broader domain, more queries, or 🌍 Global.")

# --------------------------------------------------------------------------- #
# Tab 2 — CV Tailoring Studio
# --------------------------------------------------------------------------- #
with tab_cv:
    st.subheader("CV Tailoring Studio")
    st.caption("Zero-hallucination rule: every bullet must cite evidence from the master CV; gaps are reported, never invented.")

    c1, c2 = st.columns(2)
    master_cv = c1.text_area("Master CV", value=master_cv_default, height=380, key=f"cv_{candidate_name}")
    job_text = c2.text_area("Job Call Text", height=380, key="job_text")

    if st.button("✨ Evaluate & Tailor", type="primary",
                 disabled=not (api_key_configured() and master_cv.strip() and job_text.strip())):
        with st.spinner("Gemini is evaluating the call and tailoring your CV…"):
            try:
                st.session_state.tailor_result = get_agent().evaluate_and_tailor(
                    job_text, master_cv,
                    target_country=profile.region, domain_field=domain_field,
                    career_track=career_track + (f" — applying at level: {', '.join(profile.target_levels)}"
                                                 if profile.target_levels else ""),
                )
            except Exception as exc:
                st.session_state.tailor_result = None
                st.error(f"Evaluation failed: {exc}")
    if not api_key_configured():
        st.warning("Set GEMINI_API_KEY in `.env` and restart the app to enable tailoring.")

    res = st.session_state.tailor_result
    if res:
        pos = res["position"]
        st.markdown(f"### {pos.get('title') or 'Untitled position'}  \n{pos.get('institution') or ''}")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Authenticity", f"{res['authenticity']['score']}%")
        k2.metric("CV Match", f"{res['match']['score']}%")
        k3.metric("Visa", f"{VISA_BADGES.get(res['visa_status'], '')} {res['visa_status'].strip('[]').title()}")
        k4.metric("Deadline", pos.get("deadline") or "—")

        left, right = st.columns([3, 2])
        with left:
            st.markdown("#### Tailored CV")
            if res["tailored_cv"]["professional_summary"]:
                st.info(res["tailored_cv"]["professional_summary"])
            for b in res["tailored_cv"]["bullet_points"]:
                st.markdown(f"- {b.get('text', '')}  \n  <span class='evidence'>↳ CV evidence: “{b.get('source_cv_evidence', '')}”</span>",
                            unsafe_allow_html=True)
        with right:
            st.markdown("#### Skill-Gap Audit Notes")
            for note in res["audit_notes"]:
                st.markdown(f"<div class='gap-note'>{note}</div>", unsafe_allow_html=True)
            if res["match"]["missing_requirements"]:
                st.markdown("**Missing requirements**")
                for m in res["match"]["missing_requirements"]:
                    st.markdown(f"- ❌ {m}")
            if res["match"]["matched_requirements"]:
                st.markdown("**Matched requirements**")
                for m in res["match"]["matched_requirements"]:
                    st.markdown(f"- ✅ {m}")

        with st.expander("Authenticity evidence & red flags"):
            st.write("**Evidence**", res["authenticity"]["evidence"])
            st.write("**Red flags**", res["authenticity"]["red_flags"])
            st.write("**Visa evidence**", res["visa_evidence"])
            st.write("**Regional search terms**", res["regional_search_terms"])
        st.download_button("⬇️ Download JSON", json.dumps(res, indent=2, ensure_ascii=False),
                           "tailoring_result.json", mime="application/json")

# --------------------------------------------------------------------------- #
# Tab 3 — System Configuration
# --------------------------------------------------------------------------- #
with tab_cfg:
    st.subheader("System Configuration")

    def version(pkg: str) -> str | None:
        try:
            return md.version(pkg)
        except md.PackageNotFoundError:
            return None

    def chromium_status() -> tuple[bool, str]:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                path = Path(p.chromium.executable_path)
            return path.exists(), str(path) if path.exists() else "Run: playwright install chromium"
        except Exception as exc:
            return False, str(exc)

    pw_ver, pdf_ver, genai_ver = version("playwright"), version("pypdf"), version("google-genai")
    chrome_ok, chrome_detail = chromium_status()
    key_ok = api_key_configured()

    checks = [
        ("Playwright", bool(pw_ver) and chrome_ok, f"v{pw_ver} · Chromium: {chrome_detail}" if pw_ver else "Not installed"),
        ("PyPDF", bool(pdf_ver), f"v{pdf_ver}" if pdf_ver else "Not installed"),
        ("Gemini API", bool(genai_ver) and key_ok,
         f"google-genai v{genai_ver} · key {'loaded' if key_ok else 'missing — edit .env'}" if genai_ver else "google-genai not installed"),
    ]
    cols = st.columns(3)
    for col, (name, ok, detail) in zip(cols, checks):
        with col:
            with st.container(border=True):
                st.markdown(f"### {'🟢' if ok else '🔴'} {name}")
                st.caption(detail)
                st.markdown("**Operational**" if ok else "**Action required**")

    if st.button("Ping Gemini (live test)", disabled=not key_ok):
        try:
            st.success(f"Gemini responded: {get_agent().ping()}")
        except Exception as exc:
            st.error(f"Gemini ping failed: {exc}")

    with st.expander("Active system prompt"):
        st.code((BASE_DIR / "system_prompt.txt").read_text(encoding="utf-8"), language="text")
