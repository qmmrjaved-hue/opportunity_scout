"""
OpportunityScout Gemini agent.

Wraps google-genai with the OpportunityScout system prompt and strict JSON output.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

BASE_DIR = Path(__file__).resolve().parent
SYSTEM_PROMPT_PATH = BASE_DIR / "system_prompt.txt"
DEFAULT_MODEL = "gemini-2.5-flash"
PLACEHOLDER_KEY = "your_gemini_api_key_here"
MAX_JOB_CHARS = 60_000
MAX_CV_CHARS = 30_000

load_dotenv(BASE_DIR / ".env")


def api_key_configured() -> bool:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    return bool(key) and key != PLACEHOLDER_KEY


NO_AFC = types.AutomaticFunctionCallingConfig(disable=True)
RETRY_CODES = {429, 500, 503}
# Tried in order after DEFAULT_MODEL when a model's daily free-tier quota is exhausted
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]
# Google Search grounding is only in the free tier of gemini-2.5-flash, so web search goes there first and
# analysis (screening, tailoring) prefers the other models to leave that quota for searching.
SEARCH_MODELS = [DEFAULT_MODEL, "gemini-flash-latest"]
ANALYSIS_MODELS = ["gemini-flash-latest", DEFAULT_MODEL, "gemini-flash-lite-latest"]
# Keyed by (API-key fingerprint, model): quotas belong to each key, and several users may share one server
_exhausted_models: dict[tuple[str, str], date] = {}


class QuotaExhaustedError(RuntimeError):
    pass


def parse_json_loose(raw: str):
    """Parse a JSON object or array from model output, tolerating fences and prose."""
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start, end = text.find(open_ch), text.rfind(close_ch)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    continue
        raise


_parse_json = parse_json_loose


class OpportunityScoutAgent:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL, temperature: float = 0.2):
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key or api_key == PLACEHOLDER_KEY:
            raise ValueError("GEMINI_API_KEY is not set. Add your key to the .env file.")
        self.client = genai.Client(api_key=api_key)
        self._key_id = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        self.model = model
        self.last_model: str | None = None
        self.system_instruction = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        self.config = types.GenerateContentConfig(
            system_instruction=self.system_instruction,
            response_mime_type="application/json",
            temperature=temperature,
            automatic_function_calling=NO_AFC,
        )

    def generate(self, contents, config: types.GenerateContentConfig, models: list[str] | None = None,
                 attempts: int = 4):
        """generate_content with backoff on per-minute limits and model fallback on quotas.

        Each Gemini model has its own free-tier quota, so when one model's daily quota is used up
        (or a feature such as Google Search is not included in its free tier) the request moves on
        to the next model.
        """
        models = models or [self.model] + [m for m in FALLBACK_MODELS if m != self.model]
        for model in models:
            if _exhausted_models.get((self._key_id, model)) == date.today():
                continue
            for attempt in range(attempts):
                try:
                    response = self.client.models.generate_content(model=model, contents=contents, config=config)
                    self.last_model = model
                    return response
                except genai_errors.APIError as exc:
                    message = str(exc)
                    hinted = re.search(r"retry in ([\d.]+)s", message)
                    if exc.code == 429 and "PerDay" in message:
                        _exhausted_models[(self._key_id, model)] = date.today()
                        break  # daily quota gone: next model
                    if exc.code == 404 or (exc.code == 429 and not hinted):
                        break  # model (or this feature) unavailable for this key: next model
                    if exc.code not in RETRY_CODES or attempt == attempts - 1:
                        raise
                    time.sleep(min(60.0, float(hinted.group(1)) + 1) if hinted else 5 * 2 ** attempt)
        raise QuotaExhaustedError(
            f"Gemini quota exhausted for {', '.join(models)} on this API key. Free-tier quotas reset at "
            "midnight Pacific Time; enabling billing in Google AI Studio raises the limits."
        )

    def evaluate_and_tailor(
        self,
        job_text: str,
        candidate_cv: str,
        *,
        target_country: str | None = None,
        career_track: str | None = None,
        domain_field: str | None = None,
        source_url: str | None = None,
    ) -> dict:
        """Evaluate a job call against a master CV and return the parsed JSON evaluation."""
        if not job_text or not job_text.strip():
            raise ValueError("job_text is empty.")

        context = {
            "target_country": target_country,
            "career_track": career_track,
            "domain_field": domain_field,
            "source_url": source_url,
        }
        prompt = (
            "SEARCH CONTEXT:\n"
            f"{json.dumps(context, ensure_ascii=False)}\n\n"
            "JOB CALL TEXT:\n<<<\n"
            f"{job_text[:MAX_JOB_CHARS]}\n>>>\n\n"
            "MASTER CV:\n<<<\n"
            f"{(candidate_cv or '')[:MAX_CV_CHARS]}\n>>>\n\n"
            "Evaluate authenticity, visa status and fit, then tailor the CV following every rule "
            "in your instructions. Return only the JSON object."
        )

        response = self.generate(prompt, self.config, models=ANALYSIS_MODELS)
        if not response.text:
            raise RuntimeError("Gemini returned an empty response (possibly blocked by safety filters).")
        try:
            result = _parse_json(response.text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Gemini returned invalid JSON: {exc}\n\n{response.text[:1000]}") from exc
        return self._normalise(result)

    @staticmethod
    def _normalise(result: dict) -> dict:
        """Guarantee the keys the UI relies on exist."""
        result.setdefault("position", {})
        result.setdefault("regional_search_terms", [])
        auth = result.setdefault("authenticity", {})
        auth.setdefault("score", 0)
        auth.setdefault("verified_primary_source", False)
        auth.setdefault("evidence", [])
        auth.setdefault("red_flags", [])
        if result.get("visa_status") not in {
            "[VISA SPONSORED]", "[RESEARCH VISA ELIGIBLE]", "[LOCAL ONLY]", "[UNCLEAR]"
        }:
            result["visa_status"] = "[UNCLEAR]"
        result.setdefault("visa_evidence", "")
        match = result.setdefault("match", {})
        match.setdefault("score", 0)
        match.setdefault("matched_requirements", [])
        match.setdefault("missing_requirements", [])
        cv = result.setdefault("tailored_cv", {})
        cv.setdefault("professional_summary", "")
        cv.setdefault("bullet_points", [])
        result.setdefault("audit_notes", [])
        return result

    def ping(self) -> str:
        """Tiny request used by the System Configuration tab."""
        response = self.generate(
            'Reply with {"status": "ok"}',
            types.GenerateContentConfig(response_mime_type="application/json", temperature=0,
                                        automatic_function_calling=NO_AFC),
            models=ANALYSIS_MODELS,
        )
        return response.text or ""


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("Usage: python agent.py <job_text_file> <cv_text_file>")
        sys.exit(1)
    agent = OpportunityScoutAgent()
    out = agent.evaluate_and_tailor(Path(sys.argv[1]).read_text(encoding="utf-8"),
                                    Path(sys.argv[2]).read_text(encoding="utf-8"))
    print(json.dumps(out, indent=2, ensure_ascii=False))
