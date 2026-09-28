# 🧭 OpportunityScout

OpportunityScout is an AI agent that finds **academic and industry job openings** for international candidates. It **checks that each opening is genuine** and **tags whether the employer offers visa sponsorship**. It also **tailors your CV to each call without inventing anything**.

## 🚀 Quick Start (new users)

**You need:** Python 3.10 or newer ([download](https://www.python.org/downloads/). On Windows, tick **"Add python.exe to PATH"** during installation). You also need a free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).

**Windows**
1. Download this project: **Code → Download ZIP** on GitHub, then unzip it. Or run `git clone`.
2. Double-click **`setup.bat`**. It installs everything (about 5 minutes) and asks for your Gemini API key.
3. Double-click **`start.bat`**. The app opens in your browser at http://localhost:8501.

**macOS / Linux**
```bash
chmod +x setup.sh && ./setup.sh   # one-time install, asks for your key
./start.sh                        # launch the app
```

**First steps in the app:**
- In the sidebar, choose a country, a career track and a position level, and enter your domain and skills.
- Upload your CV under **Candidate CV → ➕ New candidate**.
- Click **🚀 Find matching positions**.

**Privacy:** your API key (`.env`) and your uploaded CVs (`candidates/`) stay on your computer. Git is set to ignore them, so they are never uploaded.

> **Free-tier note:** Google's free Gemini quota allows only a few searches a day (see Section 6). For regular use, enable billing in Google AI Studio.

---

It combines three components:

| Layer | Technology | Responsibility |
|---|---|---|
| Scraper | **Playwright** (headless Chromium) + **pypdf** + regex | Loads university/employer portals, finds call PDFs, extracts text, deadlines, salaries and visa keywords |
| Reasoning | **Google Gemini** (`gemini-2.5-flash` via `google-genai`) | Verifies authenticity, classifies visa status, scores fit, tailors the CV, all as strict JSON |
| Interface | **Streamlit** + **pandas** | Dashboard, CV Tailoring Studio, system health checks, Excel export |

---

## 1. System Architecture

```
            ┌────────────────────────────────────────────────────────┐
            │                  Streamlit UI (app.py)                  │
            │  Sidebar: Country · Track · Domain · Candidate         │
            │  Tab 1 Positions Dashboard │ Tab 2 CV Studio │ Tab 3 Config │
            └──────────────┬──────────────────────────┬──────────────┘
                           │ portal URLs              │ job text + master CV
                           ▼                          ▼
      ┌─────────────────────────────────┐   ┌──────────────────────────────────┐
      │        parser.py (async)         │   │           agent.py                │
      │ Playwright → collect *.pdf links │   │ OpportunityScoutAgent             │
      │ requests  → download PDFs        │──▶│  model: gemini-2.5-flash          │
      │ pypdf     → extract text         │   │  system_instruction: system_prompt│
      │ regex     → deadlines / salary / │   │  response_mime_type: JSON, T=0.2  │
      │             visa / domain score  │   │  evaluate_and_tailor(job, cv)     │
      └─────────────────────────────────┘   └──────────────────────────────────┘
```

**Automatic discovery** (`discovery.py`, default mode)

1. Choose a **country** (or 🌍 Global) and a **track** in the sidebar. Then give your **domain**, **key skills**, a **CV**, or any combination.
2. **Search rounds:** in each round, one Gemini call with Google Search does several searches, using the official local terms (for example *bando*, *assegno di ricerca* or *Stellenausschreibung*). Each round searches from a different angle. For the Academic track these are university calls, EU research portals and faculty posts.
3. Playwright opens every result and attaches any call PDFs linked from the page. Pages that return an HTTP error are dropped. No Gemini calls are used in this step.
4. The documents are ranked by how many of your keywords they contain. The top *N* go to **batch screening**, where Gemini scores 4 documents per call. For each one it gives a **relevance %** (with reasons and skill gaps), an authenticity %, a visa tag and the deadline.
5. Results are sorted by relevance. You can hide expired calls and general pages. Click **✍️ Tailor my CV** on any position to send it to the CV Tailoring Studio.

A run costs `search rounds + ceil(positions / 4)` Gemini calls. With the defaults of 2 rounds and 12 positions, that is 5 calls.

**Manual mode:** the steps below apply when you paste portal URLs yourself.

1. You enter one or more official portal URLs (for example a university *Bandi* page or a company's Greenhouse or Lever board).
2. `parser.py` opens each portal in headless Chromium and collects every link to a `.pdf` file. It downloads up to *N* PDFs per portal at the same time.
3. `pypdf` extracts the text of each PDF. Regex routines then pull out:
   - **Deadlines** in English, Italian, German, French and Spanish date formats, near keywords such as *deadline*, *scadenza*, *Bewerbungsfrist* and *date limite*.
   - **Salaries**, in currency formats and German TV-L pay grades.
   - **Visa signals** such as *hosting agreement*, *no sponsorship* or *Directive 2016/801*.
   - A **domain-based authenticity score**.
4. If you turn on **Deep-verify with Gemini**, each call's text goes to `OpportunityScoutAgent` with the selected candidate's master CV. The dashboard keeps the lower of the regex score and Gemini's authenticity score, so the result is always the more cautious of the two.
5. Results appear as a pandas DataFrame. You can filter it to openings verified at ≥ 90% and export it to Excel.

## 2. Project Structure

```
opportunity_scout/
├── app.py                 # Streamlit dashboard
├── agent.py               # Gemini agent (OpportunityScoutAgent), retries + model fallback
├── discovery.py           # Automatic discovery: search → read pages/PDFs → relevance ranking
├── parser.py              # Playwright + pypdf scraper
├── system_prompt.txt      # Agent instructions / JSON schema
├── candidates/            # Master CVs (.txt), one per candidate
│   └── sample_candidate.txt
├── requirements.txt
├── setup.bat / setup.sh   # One-click install (Windows / macOS-Linux)
├── start.bat / start.sh   # One-click launch
├── .env.example           # Template for .env
├── .env                   # GEMINI_API_KEY (not committed)
├── .streamlit/config.toml # Streamlit settings
├── .gitignore
└── venv/                  # Local virtual environment (not committed)
```

## 3. Setup & Execution

**Prerequisites:** Python 3.10+ and a Gemini API key from <https://aistudio.google.com/apikey>.

```bash
cd opportunity_scout

# 1. Create & activate the virtual environment
python -m venv venv
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# macOS / Linux
source venv/bin/activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install the headless browser used by Playwright
playwright install chromium

# 4. Add your key to .env
#    GEMINI_API_KEY=your_real_key

# 5. Launch the dashboard
streamlit run app.py
```

The app opens at <http://localhost:8501>.

**Command-line tools**

```bash
python parser.py https://www.example-university.edu/jobs    # scrape a portal, print JSON
python agent.py job_call.txt candidates/sample_candidate.txt # evaluate + tailor, print JSON
```

**Adding candidates:** put a plain-text CV in `candidates/<name>.txt`, or use **➕ New candidate** in the sidebar. The sidebar also accepts a `.txt` or `.pdf` upload.

**Command-line discovery**

```bash
python -c "import agent, discovery as D; p=D.SearchProfile(domain='medical imaging', country='Italy'); print(D.discover(agent.OpportunityScoutAgent(), p)['stats'])"
```

## 4. Core Constraints

### 4.1 Dual-track search (Academic / Industry)
Each evaluation is placed in either the **ACADEMIC** track (PhD, postdoc, fellowship, faculty, research staff) or the **INDUSTRY** track (companies, R&D labs, startups). The agent also translates your domain field into the terms that official calls use in the target country. For example, a PhD search in Italy becomes *"Bando di Concorso"*, *"Dottorato di Ricerca"* and *"Assegno di Ricerca"*. In Germany it becomes *"Promotionsstelle"*, *"Wissenschaftliche/r Mitarbeiter/in"* and *"TV-L E13"*.

### 4.2 90–95% authenticity verification
An opening counts as **verified** only when its authenticity score is at least 90%. The score is built in two stages:

- **Heuristic stage (`parser.py`):**

  | Source | Score |
  |---|---|
  | Primary institutional domains (`.edu`, `.ac.uk`, `.ac.*`, Italian `uni*.it`, `polimi.it`, `cnr.it`, `uni-*.de`, `cnrs.fr` …) | 95 |
  | Direct ATS boards (Greenhouse, Lever, Workday, SmartRecruiters, Ashby, Personio …) | 92 |
  | Generic national domains | 75 |
  | Anything else | 55 |

  A detected deadline or a protocol/decree number adds a small bonus.
- **LLM stage (`agent.py`):** Gemini looks for a reference code, a named contact, the legal framework and a realistic salary. It also flags warning signs, such as personal email addresses used for applications, requests for payment, or an aggregator site with no primary source.

The dashboard hides anything below 90% by default. You can switch this off to review the unverified calls.

### 4.3 Visa tagging
Each call gets exactly one visa tag. The regex stage and Gemini both record the exact text that justified the tag:

| Tag | Meaning |
|---|---|
| 🟢 `[VISA SPONSORED]` | The call explicitly offers sponsorship or a work permit |
| 🔵 `[RESEARCH VISA ELIGIBLE]` | A research contract that qualifies for a researcher permit (EU Directive 2016/801 hosting agreement, *convenzione di accoglienza*, J-1, cap-exempt H-1B …) |
| 🔴 `[LOCAL ONLY]` | Requires existing right to work or citizenship, or states that there is no sponsorship. This tag takes priority over positive signals. |
| ⚪ `[UNCLEAR]` | No reliable signal. The agent does not guess. |

### 4.4 Zero-hallucination CV tailoring
- The agent may only **rephrase, reorder or condense** facts already present in the master CV.
- Every tailored bullet includes `source_cv_evidence`, a quote from the master CV. A bullet without evidence is dropped.
- Requirements that the CV does not show are listed in `missing_requirements` and explained in **audit notes**. They are never added to the tailored CV.
- `temperature=0.2` and a strict JSON response keep the output predictable.

## 5. Output Schema

`evaluate_and_tailor()` returns:

```json
{
  "position": {"title": "...", "institution": "...", "country": "...", "track": "ACADEMIC",
               "deadline": "2026-11-30", "salary": "€ 25,000 gross/year",
               "reference_code": "...", "source_url": "..."},
  "regional_search_terms": ["Bando di Concorso", "Assegno di Ricerca"],
  "authenticity": {"score": 94, "verified_primary_source": true, "evidence": [], "red_flags": []},
  "visa_status": "[RESEARCH VISA ELIGIBLE]",
  "visa_evidence": "…convenzione di accoglienza…",
  "match": {"score": 78, "matched_requirements": [], "missing_requirements": []},
  "tailored_cv": {"professional_summary": "...",
                  "bullet_points": [{"text": "...", "source_cv_evidence": "..."}]},
  "audit_notes": ["GAP: The call requires C1 Italian; the CV lists none."]
}
```

## 6. Gemini Quotas (Free Tier)

- Each model has its own daily limit on the free tier. `gemini-2.5-flash` allows about **20 requests a day**. Quotas reset at midnight Pacific Time.
- On the free tier, **Google Search is only available with `gemini-2.5-flash`**. For that reason, web searches go to `gemini-2.5-flash` first, while scoring and tailoring go to `gemini-flash-latest` first. This saves the searching quota for searches.
- If a model's daily quota runs out, the agent moves to the next model automatically. If a request hits a per-minute limit, it waits and tries again.
- When the search quota is used up, the dashboard says so. Manual portal mode and the CV Tailoring Studio keep working, because they don't need web search.
- Enabling billing in Google AI Studio raises all of these limits a lot.

## 7. Notes & Limitations
- Some portals render their links with JavaScript or require a login. Playwright handles JavaScript, but pages behind a login are not supported.
- Scanned PDFs that contain only images have no extractable text, and OCR is not included.
- Respect each site's terms of use and `robots.txt`, and keep scraping volumes modest.
- Authenticity scores support your judgement but do not replace it. Always apply through the official link.
