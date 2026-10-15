import httpx
import pytest

from opspilot.triage.llm import AnthropicClient, LLMError, build_prompt, parse_suggestion
from opspilot.triage.retriever import RetrievedRunbook
from opspilot.triage.rules import rule_based_suggestion, runbook_steps

INCIDENT = {
    "id": 7,
    "service_name": "orders-db",
    "severity": "SEV2",
    "title": "Error spike on orders-db",
    "sample_message": "connection pool exhausted after 30s",
    "error_count": 42,
}
RUNBOOK = RetrievedRunbook(
    id=1,
    slug="pool",
    title="Pool exhausted",
    body="1. Check sessions\n2. Kill leaks\n",
    score=3.2,
    rank=1,
)


def test_parse_suggestion_accepts_wrapped_json():
    raw = (
        'Sure!\n{"probable_cause": "Leaked connections", "steps": ["a", " b "], "severity": "SEV1"}'
    )
    assert parse_suggestion(raw) == {
        "probable_cause": "Leaked connections",
        "steps": ["a", "b"],
        "severity": "SEV1",
    }


def test_parse_suggestion_drops_unknown_severity():
    raw = '{"probable_cause": "x", "steps": ["a"], "severity": "critical"}'
    assert parse_suggestion(raw)["severity"] is None


@pytest.mark.parametrize(
    "raw",
    [
        "no json here",
        "{not: valid}",
        '{"steps": ["a"]}',
        '{"probable_cause": "x", "steps": []}',
        '{"probable_cause": "x", "steps": "do things"}',
    ],
)
def test_parse_suggestion_rejects_bad_replies(raw):
    with pytest.raises(LLMError):
        parse_suggestion(raw)


def test_prompt_is_grounded_in_retrieved_runbooks():
    prompt = build_prompt(INCIDENT, [RUNBOOK])
    assert "orders-db" in prompt and "[Runbook 1: Pool exhausted]" in prompt
    assert "connection pool exhausted" in prompt


def test_runbook_steps_extracts_numbered_lines():
    assert runbook_steps("intro\n1. first\n  2. second  \nnote") == ["first", "second"]


def test_rules_match_pool_exhaustion_and_use_runbook_steps():
    result = rule_based_suggestion(INCIDENT, [RUNBOOK])
    assert "pool" in result["probable_cause"].lower()
    assert result["steps"] == ["Check sessions", "Kill leaks"]
    assert result["severity"] == "SEV2"


def test_rules_generic_fallback_without_match_or_runbook():
    result = rule_based_suggestion({"title": "weird", "severity": "SEV3"}, [])
    assert "No known failure pattern" in result["probable_cause"]
    assert len(result["steps"]) >= 3


def test_anthropic_client_sends_messages_request(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, body=json)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "{}"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = AnthropicClient("test-key", "test-model", timeout=5)
    assert client.complete("sys", "hello") == "{}"
    assert captured["headers"]["x-api-key"] == "test-key"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hello"}]


def test_anthropic_client_wraps_http_errors(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(529, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(LLMError):
        AnthropicClient("k", "m").complete("s", "p")
