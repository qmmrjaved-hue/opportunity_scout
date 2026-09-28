# 🧭 OpportunityScout

**An AI assistant that finds research positions and jobs that match your profile, reads the official calls (including PDFs), and ranks them by how well they fit you.**

Tell it your field, your skills and your CV. Choose a country (or the whole world) and the level you are applying for (Master's, PhD, Post-doc and so on). OpportunityScout then:

- 🔎 **searches the web** for current openings, using the terms each country uses in its official calls (for example *bando di concorso* in Italy or *Stellenausschreibung* in Germany);
- 📄 **opens each page and reads the call PDFs attached to it**;
- 🎯 **scores how relevant each position is to you**, and explains why it fits and which skills you are missing;
- ✅ **checks authenticity**, by looking at whether the posting comes from an official university or employer source;
- 🛂 **tags visa status**: sponsored, research-visa eligible, local only, or unclear;
- ✍️ **tailors your CV** to a chosen position **without inventing anything**, since every bullet point must quote your real CV.

---

## 📑 Contents

1. [Use it online (no installation)](#1-use-it-online-no-installation)
2. [Install it on your own computer](#2-install-it-on-your-own-computer)
3. [How to use the app, step by step](#3-how-to-use-the-app-step-by-step)
4. [Understanding the results](#4-understanding-the-results)
5. [Free Gemini quota: what to expect](#5-free-gemini-quota-what-to-expect)
6. [Troubleshooting & FAQ](#6-troubleshooting--faq)
7. [Deploy your own online copy](#7-deploy-your-own-online-copy)
8. [How it works (technical)](#8-how-it-works-technical)

---

## 1. Use it online (no installation)

👉 **Open the app: https://opportunity-scout.streamlit.app**

1. Get a **free Gemini API key** at <https://aistudio.google.com/apikey>. Sign in with a Google account and click **Create API key**.
2. In the app's left sidebar, open **🔑 Gemini API key** and paste your key.
3. Follow [Section 3](#3-how-to-use-the-app-step-by-step).

> 🔒 **Privacy:** your key is used only for your own session and is never stored. Your uploaded CV stays in your browser session and is deleted when you close the tab. Nobody else can see it.
>
> ⏳ The first time the app is opened after a quiet period, it may take about a minute to wake up. This is normal on the free hosting plan.

---

## 2. Install it on your own computer

Choose this if you use the app often, or want your CVs saved between sessions.

**You need:**
- **Python 3.10 or newer**, from <https://www.python.org/downloads/>. ⚠️ On Windows, tick **"Add python.exe to PATH"** on the first installer screen.
- A **free Gemini API key**, from <https://aistudio.google.com/apikey>.

### Windows
1. On this GitHub page, click the green **Code** button, choose **Download ZIP**, and unzip it anywhere, for example in *Documents*.
2. Open the unzipped folder and double-click **`setup.bat`**.
   - It installs everything, which takes about 5 minutes the first time.
   - When it asks, paste your Gemini API key and press Enter.
3. Double-click **`start.bat`**. The app opens in your browser at <http://localhost:8501>.
   Keep the black window open while you use the app, and close it to stop the app.

From then on, only step 3 is needed.

### macOS / Linux
```bash
git clone https://github.com/qmmrjaved-hue/opportunity_scout.git
cd opportunity_scout
chmod +x setup.sh && ./setup.sh     # one-time install, asks for your key
./start.sh                          # launch the app (Ctrl+C to stop)
```

### Updating to the newest version
- **ZIP users:** download the ZIP again, and copy your old `.env` file and `candidates` folder into the new folder.
- **git users:** run `git pull`, then `setup.bat` or `./setup.sh` again.

---

## 3. How to use the app, step by step

### Step 1: Describe yourself (left sidebar)
| Setting | What to enter | Example |
|---|---|---|
| **Target Country** | Where you want to work, or **🌍 Global** | Australia |
| **Career Track** | **Academic** (universities, institutes) or **Industry** (companies) | Academic |
| **Position Level** *(Academic only)* | One or more of: Master's, PhD, Post-doc, Research Assistant / Fellow, Faculty | Post-doc |
| **Domain Field** | Your research or professional area | Machine learning for medical imaging |
| **Key Skills** | Comma-separated skills | PyTorch, image segmentation, Python |
| **Candidate CV** | Your CV (strongly recommended) | *see below* |

**Adding your CV:**
1. Choose **➕ New candidate** in the *Candidate CV* list.
2. Type your name.
3. Upload your CV as **.pdf** or **.txt**.
4. Click **Save candidate**, then select your name in the list.

Notes:
- A PDF CV must contain real text. If you can select the text in a PDF viewer, it will work. Scanned or image-only PDFs won't.
- For a Word CV, choose *File → Save as PDF* first.

### Step 2: Find positions (📊 Positions Dashboard tab)
1. Leave the defaults (**2 search rounds, 12 positions**) and click **🚀 Find matching positions**.
2. Wait 2–5 minutes. The progress bar shows each stage: searching the web, opening pages and PDFs, and scoring.
3. The results appear **ranked by relevance to you**.

### Step 3: Review the best matches
- Use the **filters** above the table:
  - hide expired calls;
  - show only official (≥90% authentic) postings;
  - show only your level;
  - set a minimum relevance.
- Open any position under **🎯 Position details** to see:
  - why it fits you (✅) and which skills you are missing (❌);
  - the visa evidence and any warning signs;
  - links to the page and to the call PDF.
- Click **⬇️ Export all to Excel** to keep a list.

### Step 4: Tailor your CV for a position (✍️ CV Tailoring Studio tab)
1. In a position's details, click **✍️ Tailor my CV for this position**. You can also paste any job ad into the *Job Call Text* box yourself.
2. Open the **✍️ CV Tailoring Studio** tab and click **✨ Evaluate & Tailor**.
3. You get:
   - a tailored summary;
   - bullet points, each showing **the line of your CV it comes from**;
   - **skill-gap audit notes**, which list requirements you don't meet. The app never pretends you meet them.

### Other option: 🔗 Manual portal URLs
Already know a university's jobs or calls page? Choose **🔗 Manual portal URLs** at the top of the dashboard and paste the page address. The app collects every call PDF on that page. This mode uses **very little Gemini quota**.

---

## 4. Understanding the results

| Column | Meaning |
|---|---|
| **Relevance %** | How well the position matches your CV, skills and field. 70% or more is a strong match. |
| **Level** | PhD, Post-doc and so on, as detected by the app. A position at a level you didn't choose is capped at 30%. |
| **Authenticity %** | How sure the app is that this is a genuine, official posting. **90% or more** means an official university or employer source. |
| **Visa Status** | 🟢 Visa sponsored · 🔵 Research-visa eligible · 🔴 Local candidates only · ⚪ Unclear |
| **Deadline / Status** | ✅ Open (with days left) · ⛔ Expired · ❔ Deadline not found |
| **Why relevant / Skill gaps** | Your matching strengths, and the requirements you don't yet meet |

**Special status labels:**
- **🔒 Snippet only**: the site (for example Seek, Indeed or LinkedIn) blocks automated reading, so the details come from Google's search result only. **Open the link and check the ad yourself.** For a full evaluation, paste the ad text into the CV Tailoring Studio.
- **📋 Listing page**: a page that lists several positions, such as a university's scholarships page. Open it and browse.
- **⏸ Not scored**: the Gemini quota ran out before this position was scored. See Section 5.

> ⚠️ Always apply through the **official link**, and check deadlines and eligibility on the original call. The app supports your judgement but does not replace it.

---

## 5. Free Gemini quota: what to expect

The app uses Google's Gemini AI. With a **free** API key:
- Each search run uses about **5 Gemini requests**.
- Web search works only with the `gemini-2.5-flash` model, which allows about **20 requests a day**. That means roughly **3–4 search runs a day**.
- The quota resets every day at **midnight Pacific Time** (07:00 UTC in summer).
- When it runs out, the app says so clearly. **CV tailoring and Manual URL mode** often keep working, because they can use other models.

**Want more searches?** Turn on billing for your key in [Google AI Studio](https://aistudio.google.com). Paid usage for one search run typically costs a few cents, with no daily cut-off.

---

## 6. Troubleshooting & FAQ

**"Python was not found" when I run setup.bat**
Install Python from python.org and tick **"Add python.exe to PATH"**. Then run `setup.bat` again.

**"Today's web-search quota is used up"**
The free daily limit has been reached. Try again after the reset (see Section 5), use **Manual portal URLs** mode, or turn on billing.

**The search finished but shows few or no positions**
- Switch off some filters, especially *Only ≥90% authentic* and *Only my level*.
- Use broader keywords, or try **🌍 Global**.
- Add your CV. It helps the search understand your field.
- Increase the **Search rounds**.

**Why can't it read Indeed / Seek / LinkedIn directly?**
These sites block automated access and don't offer a public job-search service. The app still lists their postings as **🔒 Snippet only** results. Open them in your browser and paste the text into the CV Tailoring Studio.

**My PDF CV shows empty text**
It is probably a scanned image. Export your CV from Word or Google Docs as PDF, or upload it as .txt.

**Is my data safe?**
- **On your own computer:** your key (`.env`) and CVs (`candidates/`) never leave your machine. They are also excluded from GitHub.
- **Online:** your key and CV exist only in your browser session and are not saved on the server.
- Job texts and your CV are sent to Google's Gemini service to be analysed.

**Where is my API key stored when installed locally?**
In the `.env` file in the project folder. Open it with Notepad to change the key.

---

## 7. Deploy your own online copy

This uses [Streamlit Community Cloud](https://share.streamlit.io), which is free and deploys straight from GitHub.

1. **Fork** this repository, or use your own copy of it.
2. Go to <https://share.streamlit.io>, sign in with GitHub, and click **Create app → Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `your-username/opportunity_scout`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** choose a name, for example `opportunity-scout`
4. Open **Advanced settings**:
   - **Python version:** 3.12
   - **Secrets:** paste the lines from [`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example) and fill them in:
     ```toml
     PUBLIC_MODE = "true"                      # visitors must use their own key
     GEMINI_API_KEY = "your-own-key"           # optional: your key…
     APP_PASSWORD = "a-long-private-password"  # …unlocked only with this password
     ```
5. Click **Deploy** and wait a few minutes.
6. Put your app's address at the top of this README (Section 1).

**How access works online:**
- **Visitors** paste their own free Gemini key, so your quota is never used by others.
- **You** type your `APP_PASSWORD` in the sidebar to use your own key.
- Uploaded CVs are kept per browser session and are never written to the server.
- `packages.txt` installs the Linux libraries Chromium needs on Streamlit Cloud (Debian 13). If the host still cannot run the browser, the app falls back to plain page reading, so PDFs and most university pages still work. **⚙️ System Configuration** shows which mode is active.

---

## 8. How it works (technical)

```
 Sidebar profile ──► discovery.py
                      1. Gemini + Google Search (grounded): several searches per round,
                         using the official terms for each country and level; only real, cited result links are used
                      2. parser.py: Playwright (headless Chromium) or plain HTTP opens each page
                         and pypdf reads the attached call PDFs
                      3. Keyword pre-ranking, then Gemini batch screening (4 documents per call):
                         relevance, level, authenticity, visa, deadline, skill gaps
                      4. Duplicates merged; statuses: open, expired, snippet-only, listing
 CV Studio ─────────► agent.py: evaluate_and_tailor(job_text, cv): strict JSON,
                      zero-hallucination bullets, each tied to a CV quote
```

| File | Purpose |
|---|---|
| `app.py` | Streamlit interface (dashboard, CV studio, system checks) |
| `discovery.py` | Automatic search → reading → relevance ranking pipeline |
| `parser.py` | Page and PDF reading (Playwright or plain HTTP), deadline, salary and visa regex |
| `agent.py` | Gemini client: retries, per-key model fallback, CV tailoring |
| `system_prompt.txt` | The agent's rules (authenticity, visa tags, zero-hallucination tailoring, JSON schema) |
| `setup.bat` / `setup.sh`, `start.bat` / `start.sh` | One-click install and launch |
| `.env.example`, `.streamlit/secrets.toml.example` | Configuration templates |
| `packages.txt` | Linux system libraries for Chromium on Streamlit Cloud (Debian 13) |

**Main rules the AI follows:**
- **Dual-track search:** Academic or Industry, with local terminology for each country and level.
- **Authenticity:** 90–95% requires an official domain (.edu, .ac.uk, .edu.au, university .it and similar) or a direct applicant-tracking board. A posting read only from a snippet can never count as "verified".
- **Visa tagging:** exactly one tag, with the supporting quote. When local-only wording is found, it overrides positive signals.
- **Zero-hallucination CV tailoring:** the AI may only rephrase what is in your CV. Every bullet cites its source, and gaps are reported, never filled in.

**Models:**
- `gemini-2.5-flash` handles web search.
- Analysis runs on `gemini-flash-latest`, with automatic fallback to other models when a daily quota runs out.
- Output is structured JSON at temperature 0.2.

**Command line:**
```bash
python parser.py https://university.example/jobs            # scrape a portal
python agent.py job_call.txt candidates/sample_candidate.txt  # evaluate + tailor
```

---

*Built with Streamlit, Playwright, pypdf and Google Gemini. Use responsibly: respect each website's terms, and always verify postings at the official source.*
