"""
OpportunityScout scraper.

Loads university / employer portals in headless Chromium (Playwright), collects
links to downloadable call PDFs, parses them with pypdf and runs regex routines
to pull out deadlines, salaries and visa signals.

CLI usage:
    python parser.py https://example.university.edu/jobs [more urls...]
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from pypdf import PdfReader

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20
# pypdf logs harmless warnings about malformed PDFs; keep the console readable
logging.getLogger("pypdf").setLevel(logging.ERROR)
MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PAGE_CHARS = 40_000

# --------------------------------------------------------------------------- #
# Authenticity heuristics
# --------------------------------------------------------------------------- #
PRIMARY_DOMAIN_PATTERNS = [
    r"\.edu$", r"\.edu\.[a-z]{2}$", r"\.ac\.uk$", r"\.ac\.[a-z]{2}$",
    r"(^|\.)uni[a-z0-9\-]*\.it$", r"(^|\.)poli[a-z]+\.it$", r"(^|\.)cnr\.it$",
    r"(^|\.)infn\.it$", r"(^|\.)sns\.it$", r"(^|\.)sissa\.it$", r"(^|\.)iit\.it$",
    r"(^|\.)uni-[a-z\-]+\.de$", r"(^|\.)tu-[a-z\-]+\.de$", r"(^|\.)mpg\.de$",
    r"(^|\.)cnrs\.fr$", r"(^|\.)inria\.fr$", r"(^|\.)europa\.eu$",
    r"(^|\.)ethz\.ch$", r"(^|\.)epfl\.ch$", r"(^|\.)tudelft\.nl$", r"(^|\.)uva\.nl$",
]
ATS_DOMAINS = [
    "greenhouse.io", "lever.co", "myworkdayjobs.com", "workday.com",
    "smartrecruiters.com", "ashbyhq.com", "personio.de", "personio.com",
    "teamtailor.com", "icims.com", "successfactors.com", "successfactors.eu",
    "jobs.ac.uk", "euraxess.ec.europa.eu",
]
# Generic .it counts only as weak primary evidence (many .it sites are not universities)
WEAK_PRIMARY_PATTERNS = [r"\.it$", r"\.de$", r"\.fr$", r"\.nl$", r"\.es$"]

# --------------------------------------------------------------------------- #
# Regex routines
# --------------------------------------------------------------------------- #
MONTHS = {
    # English
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    # Italian
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    # German
    "januar": 1, "februar": 2, "märz": 3, "mai": 5, "juni": 6, "juli": 7,
    "oktober": 10, "dezember": 12,
    # French
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "juin": 6, "juillet": 7,
    "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
    # Spanish
    "enero": 1, "febrero": 2, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))

DEADLINE_KEYWORDS = (
    r"deadline|closing date|apply by|applications? (?:must be received|close)|"
    r"scadenza|entro (?:e non oltre )?il|termine|"
    r"bewerbungsfrist|bewerbungsschluss|"
    r"date limite|avant le|"
    r"plazo|fecha l[ií]mite"
)
DATE_PATTERNS = [
    # 2025-03-31
    re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),
    # 31/03/2025, 31.03.2025, 31-03-2025
    re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b"),
    # 31 March 2025 / 31 marzo 2025 / 31. März 2025
    re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th|\.|°|º)?\s+(?:de\s+)?({_MONTH_ALT})\.?\s+(?:de\s+)?(\d{{4}})\b", re.I),
    # March 31, 2025
    re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I),
]
DEADLINE_CONTEXT = re.compile(rf"(?:{DEADLINE_KEYWORDS})[^\n]{{0,120}}", re.I)

SALARY_PATTERN = re.compile(
    r"(?:(?:€|EUR|£|GBP|\$|USD|CHF)\s?\d[\d.,\s]{2,}(?:\s?(?:k|K))?"
    r"|\d[\d.,\s]{2,}\s?(?:€|EUR|euro|£|GBP|USD|CHF))"
    r"(?:[^\n]{0,40}?(?:per (?:year|annum|month)|p\.a\.|/year|/month|annui|lordi|brutto|gross|all'anno|al mese))?",
    re.I,
)
TVL_PATTERN = re.compile(r"\b(?:TV-?L|TVöD|TV-?H)\s?E?\s?1[0-5]\b", re.I)

VISA_KEYWORDS = {
    "[VISA SPONSORED]": [
        r"visa sponsorship (?:is )?(?:available|provided|offered)", r"we (?:will )?sponsor",
        r"sponsorship (?:is )?available", r"relocation (?:and|&) visa", r"skilled worker visa",
        r"immigration support", r"work permit (?:support|assistance|will be provided)",
    ],
    "[RESEARCH VISA ELIGIBLE]": [
        r"hosting agreement", r"convenzione di accoglienza", r"ricerca scientifica",
        r"directive\s*\(?eu\)?\s*2016/801", r"researcher (?:visa|permit)", r"scientific research permit",
        r"j-1", r"cap[- ]exempt", r"global talent", r"assegno di ricerca", r"dottorato di ricerca",
        r"international (?:applicants|candidates) (?:are )?(?:welcome|encouraged)",
        r"euraxess", r"marie (?:skłodowska-)?curie",
    ],
    "[LOCAL ONLY]": [
        r"no (?:visa )?sponsorship", r"unable to (?:offer|provide) (?:visa )?sponsorship",
        r"not (?:able to )?sponsor", r"must (?:already )?have (?:the )?right to work",
        r"(?:us|u\.s\.|eu) citizenship (?:is )?required", r"security clearance",
        r"cittadinanza italiana", r"only (?:eu|local) (?:citizens|candidates)",
    ],
}


@dataclass
class ScrapedCall:
    source_page: str
    pdf_url: str
    title: str
    text: str = ""
    deadlines: list[str] = field(default_factory=list)
    salaries: list[str] = field(default_factory=list)
    visa_status: str = "[UNCLEAR]"
    visa_evidence: list[str] = field(default_factory=list)
    authenticity_score: int = 0
    authenticity_reason: str = ""
    error: str | None = None

    @property
    def primary_deadline(self) -> str | None:
        return self.deadlines[0] if self.deadlines else None

    def to_dict(self, include_text: bool = False) -> dict:
        data = asdict(self)
        data["primary_deadline"] = self.primary_deadline
        if not include_text:
            data.pop("text", None)
        return data


# --------------------------------------------------------------------------- #
# Pure helpers (no network)
# --------------------------------------------------------------------------- #
def score_domain(url: str) -> tuple[int, str]:
    """Heuristic authenticity score for a URL based on its host."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return 0, "Invalid URL"
    if any(host == d or host.endswith("." + d) for d in ATS_DOMAINS):
        return 92, f"Direct ATS / official board ({host})"
    if any(re.search(p, host) for p in PRIMARY_DOMAIN_PATTERNS):
        return 95, f"Primary institutional domain ({host})"
    if any(re.search(p, host) for p in WEAK_PRIMARY_PATTERNS):
        return 75, f"National domain, institution not confirmed ({host})"
    return 55, f"Unverified domain ({host})"


def _to_iso(day: int, month: int, year: int) -> str | None:
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def _parse_dates(fragment: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for idx, pattern in enumerate(DATE_PATTERNS):
        for m in pattern.finditer(fragment):
            g = m.groups()
            iso = None
            if idx == 0:
                iso = _to_iso(int(g[2]), int(g[1]), int(g[0]))
            elif idx == 1:
                iso = _to_iso(int(g[0]), int(g[1]), int(g[2]))
            elif idx == 2:
                iso = _to_iso(int(g[0]), MONTHS.get(g[1].lower(), 0), int(g[2]))
            elif idx == 3:
                iso = _to_iso(int(g[1]), MONTHS.get(g[0].lower(), 0), int(g[2]))
            if iso:
                found.append((m.start(), iso))
    return [iso for _, iso in sorted(found)]


def extract_deadlines(text: str) -> list[str]:
    """Return ISO dates found near deadline keywords, most relevant first."""
    deadlines: list[str] = []
    for ctx in DEADLINE_CONTEXT.finditer(text):
        for iso in _parse_dates(ctx.group(0)):
            if iso not in deadlines:
                deadlines.append(iso)
    if not deadlines:
        # Fallback: latest future-looking date anywhere in the document
        all_dates = sorted(set(_parse_dates(text)), reverse=True)
        deadlines = all_dates[:1]
    return deadlines


def extract_salaries(text: str) -> list[str]:
    hits = [re.sub(r"\s+", " ", m.group(0)).strip() for m in SALARY_PATTERN.finditer(text)]
    hits += [m.group(0) for m in TVL_PATTERN.finditer(text)]
    seen, out = set(), []
    for h in hits:
        if h.lower() not in seen:
            seen.add(h.lower())
            out.append(h)
    return out[:5]


def detect_visa(text: str) -> tuple[str, list[str]]:
    """Return (tag, evidence snippets). LOCAL ONLY wins over positive signals."""
    lowered = text.lower()
    matches: dict[str, list[str]] = {}
    for tag, patterns in VISA_KEYWORDS.items():
        for p in patterns:
            for m in re.finditer(p, lowered):
                start, end = max(0, m.start() - 60), min(len(text), m.end() + 60)
                matches.setdefault(tag, []).append(re.sub(r"\s+", " ", text[start:end]).strip())
    for tag in ("[LOCAL ONLY]", "[VISA SPONSORED]", "[RESEARCH VISA ELIGIBLE]"):
        if tag in matches:
            return tag, matches[tag][:3]
    return "[UNCLEAR]", []


def extract_pdf_text(data: bytes, max_pages: int = 30) -> str:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
    pages = []
    for page in reader.pages[:max_pages]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(pages)


def analyse_text(call: ScrapedCall) -> ScrapedCall:
    call.deadlines = extract_deadlines(call.text)
    call.salaries = extract_salaries(call.text)
    call.visa_status, call.visa_evidence = detect_visa(call.text)
    score, reason = score_domain(call.pdf_url)
    if call.deadlines:
        score = min(100, score + 2)
    if re.search(r"\b(?:prot\.|protocollo|ref(?:erence)?\.?\s?(?:no|n)\.?|d\.r\.|decreto)\b", call.text, re.I):
        score = min(100, score + 2)
    call.authenticity_score, call.authenticity_reason = score, reason
    return call


def download_pdf(url: str) -> bytes:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT, stream=True)
    resp.raise_for_status()
    chunks, size = [], 0
    for chunk in resp.iter_content(64 * 1024):
        size += len(chunk)
        if size > MAX_PDF_BYTES:
            raise ValueError("PDF exceeds size limit")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data.startswith(b"%PDF"):
        raise ValueError("Response is not a PDF")
    return data


# --------------------------------------------------------------------------- #
# Plain-HTTP fallback (used when Chromium cannot run, e.g. on some cloud hosts)
# --------------------------------------------------------------------------- #
class _PageParser(HTMLParser):
    """Collects visible text, the <title> and <a href> links from an HTML page."""
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCKS = {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self.anchors: list[list[str]] = []
        self._skip = 0
        self._in_title = False
        self._link: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            self._link = [dict(attrs).get("href") or "", ""]
        if tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._link is not None:
            self.anchors.append([self._link[0], self._link[1].strip()])
            self._link = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip:
            return
        self.parts.append(data)
        if self._link is not None:
            self._link[1] += data

    def text(self) -> str:
        joined = re.sub(r"\n\s*\n+", "\n\n", "".join(self.parts))
        return re.sub(r"[ \t]+", " ", joined).strip()


def http_page(url: str) -> tuple[int, str, str, str, list[list[str]]]:
    """Fetch an HTML page without a browser: (status, final_url, title, text, anchors)."""
    resp = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en;q=0.9,*;q=0.5"},
                        timeout=REQUEST_TIMEOUT, allow_redirects=True)
    parser = _PageParser()
    if resp.ok and "html" in resp.headers.get("content-type", "html").lower():
        parser.feed(resp.text[:2_000_000])
    return resp.status_code, resp.url, parser.title.strip(), parser.text()[:MAX_PAGE_CHARS], parser.anchors


async def _launch_browser(p):
    """Launch headless Chromium, or return None when it is unavailable on this machine."""
    try:
        return await p.chromium.launch(headless=True)
    except Exception:
        return None

# --------------------------------------------------------------------------- #
# Playwright scraping
# --------------------------------------------------------------------------- #
async def find_pdf_links(page_url: str, timeout_ms: int = 45000) -> list[tuple[str, str]]:
    """Open a portal headlessly and return [(absolute_pdf_url, link_text)]."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await _launch_browser(p)
        if browser is None:
            _, page_url, _, _, anchors = await asyncio.to_thread(http_page, page_url)
        else:
            try:
                context = await browser.new_context(user_agent=USER_AGENT)
                page = await context.new_page()
                await page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    await page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass  # some portals never go idle; DOM content is enough
                anchors = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => [e.getAttribute('href'), (e.innerText || e.title || '').trim()])",
                )
            finally:
                await browser.close()

    links, seen = [], set()
    for href, text in anchors:
        if not href:
            continue
        absolute = urljoin(page_url, href)
        path = urlparse(absolute).path.lower()
        if path.endswith(".pdf") or "format=pdf" in absolute.lower():
            if absolute not in seen:
                seen.add(absolute)
                title = text or path.rsplit("/", 1)[-1]
                links.append((absolute, re.sub(r"\s+", " ", title)[:200]))
    return links


async def scrape_portal(page_url: str, max_pdfs: int = 10) -> list[ScrapedCall]:
    try:
        links = await find_pdf_links(page_url)
    except Exception as exc:
        return [ScrapedCall(source_page=page_url, pdf_url=page_url, title="(portal load failed)",
                            error=f"{type(exc).__name__}: {exc}")]

    async def process(pdf_url: str, title: str) -> ScrapedCall:
        call = ScrapedCall(source_page=page_url, pdf_url=pdf_url, title=title)
        try:
            data = await asyncio.to_thread(download_pdf, pdf_url)
            call.text = await asyncio.to_thread(extract_pdf_text, data)
            analyse_text(call)
        except Exception as exc:
            call.error = f"{type(exc).__name__}: {exc}"
            call.authenticity_score, call.authenticity_reason = score_domain(pdf_url)
        return call

    return list(await asyncio.gather(*(process(u, t) for u, t in links[:max_pdfs])))


async def scrape_portals(urls: Iterable[str], max_pdfs: int = 10) -> list[ScrapedCall]:
    results = await asyncio.gather(*(scrape_portal(u, max_pdfs) for u in urls))
    return [call for batch in results for call in batch]


def run_async(coro):
    """Run a coroutine from sync code (e.g. Streamlit's script thread)."""
    # Playwright needs subprocess support: on Windows that means a Proactor loop.
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def run_scrape(urls: Iterable[str], max_pdfs: int = 10) -> list[ScrapedCall]:
    """Synchronous entry point, safe to call from Streamlit's script thread."""
    urls = [u.strip() for u in urls if u and u.strip()]
    if not urls:
        return []
    return run_async(scrape_portals(urls, max_pdfs))


# --------------------------------------------------------------------------- #
# Generic document fetching (used by automatic discovery)
# --------------------------------------------------------------------------- #
CALL_LINK_HINTS = re.compile(
    r"bando|concorso|call|job|position|vacanc|phd|ph\.d|doctoral|postdoc|fellow|recruit|"
    r"announcement|avviso|assegno|stelle|ausschreibung|offre|th[eè]se|convocatoria|plaza|"
    r"description|advert",
    re.I,
)


@dataclass
class FetchedDoc:
    url: str
    final_url: str = ""
    kind: str = "page"          # "pdf" or "page"
    title: str = ""
    text: str = ""
    pdf_urls: list[str] = field(default_factory=list)
    error: str | None = None


def _probe_pdf(url: str) -> tuple[bytes | None, str]:
    """If the URL serves a PDF return (bytes, final_url); otherwise (None, final_url)."""
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT,
                        stream=True, allow_redirects=True)
    try:
        ctype = resp.headers.get("content-type", "").lower()
        if resp.ok and ("pdf" in ctype or urlparse(resp.url).path.lower().endswith(".pdf")):
            data = resp.raw.read(MAX_PDF_BYTES + 1, decode_content=True)
            if data.startswith(b"%PDF") and len(data) <= MAX_PDF_BYTES:
                return data, resp.url
        return None, resp.url
    finally:
        resp.close()


async def _fetch_one(browser, url: str, sem: asyncio.Semaphore, max_pdfs: int) -> FetchedDoc:
    doc = FetchedDoc(url=url, final_url=url)
    async with sem:
        # 1) Direct PDF?
        try:
            data, doc.final_url = await asyncio.to_thread(_probe_pdf, url)
            if data:
                doc.kind = "pdf"
                doc.title = urlparse(doc.final_url).path.rsplit("/", 1)[-1]
                doc.text = await asyncio.to_thread(extract_pdf_text, data)
                doc.pdf_urls = [doc.final_url]
                return doc
        except Exception:
            pass  # fall through to the browser; some sites block plain HTTP clients

        # 2) HTML page: rendered in headless Chromium, or plain HTTP when no browser is available
        if browser is None:
            try:
                status, doc.final_url, doc.title, doc.text, anchors = await asyncio.to_thread(http_page, url)
            except Exception as exc:
                doc.error = f"{type(exc).__name__}: {exc}"
                return doc
            if status >= 400:
                doc.error = f"HTTP {status}"
                return doc
            doc.title = doc.title or doc.final_url
        else:
            context = await browser.new_context(user_agent=USER_AGENT)
            try:
                page = await context.new_page()
                response = await page.goto(doc.final_url or url, wait_until="domcontentloaded", timeout=25000)
                if response and response.status >= 400:
                    doc.error = f"HTTP {response.status}"
                    return doc
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                doc.final_url = page.url
                doc.title = (await page.title()) or doc.final_url
                doc.text = (await page.inner_text("body"))[:MAX_PAGE_CHARS]
                anchors = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => [e.getAttribute('href'), (e.innerText || e.title || '').trim()])",
                )
            except Exception as exc:
                doc.error = f"{type(exc).__name__}: {exc}"
                return doc
            finally:
                await context.close()

    # 3) Attach call PDFs linked from the page
    pdf_links = []
    for href, text in anchors:
        if not href:
            continue
        absolute = urljoin(doc.final_url, href)
        if urlparse(absolute).path.lower().endswith(".pdf") and absolute not in pdf_links:
            if CALL_LINK_HINTS.search(f"{text} {absolute}"):
                pdf_links.append(absolute)
    for pdf_url in pdf_links[:max_pdfs]:
        try:
            data = await asyncio.to_thread(download_pdf, pdf_url)
            pdf_text = await asyncio.to_thread(extract_pdf_text, data)
            if pdf_text.strip():
                doc.text += f"\n\n[ATTACHED CALL PDF: {pdf_url}]\n{pdf_text}"
                doc.pdf_urls.append(pdf_url)
        except Exception:
            continue
    return doc


async def fetch_documents(urls: Iterable[str], max_pdfs_per_page: int = 2,
                          concurrency: int = 6) -> list[FetchedDoc]:
    """Fetch pages/PDFs with one shared headless browser (plain HTTP if Chromium is unavailable)."""
    from playwright.async_api import async_playwright

    urls = list(dict.fromkeys(u for u in urls if u))
    if not urls:
        return []
    sem = asyncio.Semaphore(concurrency)
    async with async_playwright() as p:
        browser = await _launch_browser(p)
        try:
            return list(await asyncio.gather(*(_fetch_one(browser, u, sem, max_pdfs_per_page) for u in urls)))
        finally:
            if browser is not None:
                await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python parser.py <portal_url> [portal_url ...]")
        sys.exit(1)
    for result in run_scrape(sys.argv[1:]):
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
