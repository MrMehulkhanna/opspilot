"""LLM client and prompt for triage suggestions.

The model only ever *suggests*: its output is parsed into a strict shape and
validated, and anything that does not fit is discarded so the rule-based
triager takes over. An engineer reviews every suggestion before it is used.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from opspilot.lifecycle import SEVERITIES
from opspilot.triage.retriever import RetrievedRunbook


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, prompt: str) -> str: ...


class AnthropicClient:
    """Minimal client for the Anthropic Messages API (no SDK dependency)."""

    url = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, prompt: str) -> str:
        try:
            response = httpx.post(
                self.url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 800,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            blocks = response.json().get("content", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise LLMError("LLM returned no text")
        return text


SYSTEM_PROMPT = (
    "You are an SRE assistant helping a production-support engineer triage an incident. "
    "Use the runbook excerpts when they are relevant and never invent tools or systems "
    "that are not mentioned. Reply with a single JSON object and nothing else."
)


def build_prompt(incident: dict, runbooks: list[RetrievedRunbook]) -> str:
    context = "\n\n".join(
        f"[Runbook {rb.rank}: {rb.title}]\n{rb.body[:1500]}" for rb in runbooks
    ) or "(no matching runbooks)"
    return (
        f"Incident #{incident['id']} on service '{incident['service_name']}'\n"
        f"Severity: {incident['severity']}\n"
        f"Title: {incident['title']}\n"
        f"Most common error: {incident.get('sample_message') or 'n/a'}\n"
        f"Errors counted: {incident.get('error_count', 0)}\n\n"
        f"Relevant runbooks:\n{context}\n\n"
        "Respond with JSON of the form:\n"
        '{"probable_cause": "<one or two sentences>", '
        '"steps": ["<step 1>", "<step 2>", "..."], '
        '"severity": "SEV1|SEV2|SEV3"}'
    )


_JSON_OBJECT = re.compile(r"\{.*\}", re.S)


def parse_suggestion(raw: str) -> dict:
    """Extract and validate the JSON object from a model reply."""
    match = _JSON_OBJECT.search(raw)
    if not match:
        raise LLMError("no JSON object in LLM reply")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON from LLM: {exc}") from exc

    cause = data.get("probable_cause")
    steps = data.get("steps")
    severity = data.get("severity")
    if not isinstance(cause, str) or not cause.strip():
        raise LLMError("probable_cause missing")
    if not isinstance(steps, list) or not steps or not all(isinstance(s, str) for s in steps):
        raise LLMError("steps must be a non-empty list of strings")
    if severity not in SEVERITIES:
        severity = None
    return {
        "probable_cause": cause.strip()[:1000],
        "steps": [s.strip() for s in steps if s.strip()][:8],
        "severity": severity,
    }
