"""Web search is a provider-native declaration, not a tool we execute: assert the
declaration per provider, that citations survive each provider's response shape,
and that a room holding documents cannot enable search without acknowledging
that queries leave the machine."""

from __future__ import annotations

import httpx
import pytest

from conclave.db.session import engine, init_db
from conclave.main import app
from conclave.runtime.citations import extract_citations, used_web_search
from conclave.runtime.providers import native_search_tool


def test_each_provider_declares_its_own_search_tool():
    assert native_search_tool("anthropic")["type"] == "web_search_20260209"
    assert native_search_tool("openai")["type"] == "web_search"
    assert "google_search" in native_search_tool("google")
    assert native_search_tool("fake") is None


def test_citations_from_anthropic_shape():
    content = [
        {
            "type": "web_search_tool_result",
            "content": [
                {"type": "web_search_result", "url": "https://uroweb.org/guideline", "title": "EAU NMIBC"},
                {"type": "web_search_result", "url": "https://www.nice.org.uk/ng2", "title": "NICE NG2"},
            ],
        },
        {
            "type": "text",
            "text": "Guidelines agree on 3-month cystoscopy.",
            "citations": [{"url": "https://uroweb.org/guideline", "title": "EAU NMIBC"}],
        },
    ]
    cites = extract_citations(content)
    assert [c["url"] for c in cites] == [
        "https://uroweb.org/guideline",
        "https://www.nice.org.uk/ng2",
    ]
    assert cites[0]["title"] == "EAU NMIBC"


def test_citations_from_openai_annotations_shape():
    content = [
        {
            "type": "text",
            "text": "Recent guidance…",
            "annotations": [
                {"type": "url_citation", "url": "https://example.org/a", "title": "A"},
                {"type": "url_citation", "url": "https://example.org/a", "title": "A"},
            ],
        }
    ]
    cites = extract_citations(content)
    assert len(cites) == 1  # de-duplicated


def test_citations_from_openai_tool_call_path():
    """When an expert answers via a tool call there is no text block to annotate,
    so the pages the model opened are the only record of what it read."""
    content = [
        {"type": "reasoning", "summary": []},
        {
            "type": "web_search_call",
            "status": "completed",
            "action": {"type": "search", "queries": ["EAU cystoscopy interval"]},
        },
        {
            "type": "web_search_call",
            "status": "completed",
            "action": {
                "type": "open_page",
                "url": "https://uroweb.org/guidelines/non-muscle-invasive-bladder-cancer",
            },
        },
        {"type": "function_call", "name": "TurnAct"},
    ]
    cites = extract_citations(content)
    assert [c["url"] for c in cites] == [
        "https://uroweb.org/guidelines/non-muscle-invasive-bladder-cancer"
    ]
    assert used_web_search(content) is True


def test_search_without_extractable_url_is_still_reported():
    content = [
        {"type": "web_search_call", "status": "completed",
         "action": {"type": "search", "queries": ["something"]}},
    ]
    assert extract_citations(content) == []
    assert used_web_search(content) is True


def test_no_search_is_not_reported():
    assert used_web_search([{"type": "text", "text": "answered from memory"}]) is False
    assert used_web_search("plain") is False


def test_citations_tolerate_unknown_shapes():
    assert extract_citations("plain string") == []
    assert extract_citations([{"type": "text", "text": "no sources"}]) == []
    assert extract_citations([{"url": "not-a-url"}]) == []


@pytest.fixture
async def client():
    try:
        await init_db()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres not reachable: {exc}")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await engine.dispose()


async def test_web_search_toggles_and_guards_document_egress(client):
    room = (await client.post("/api/conversations", json={"topic": "search toggle"})).json()
    cid = room["id"]
    try:
        assert room["web_search"] is False

        # No documents: enabling is unremarkable.
        on = await client.patch(f"/api/conversations/{cid}", json={"web_search": True})
        assert on.status_code == 200 and on.json()["web_search"] is True

        await client.patch(f"/api/conversations/{cid}", json={"web_search": False})
        await client.post(
            f"/api/conversations/{cid}/files",
            files={"file": ("record.md", b"# Case notes\n\nPatient history.", "text/markdown")},
        )

        # With documents attached, enabling requires acknowledgement.
        blocked = await client.patch(f"/api/conversations/{cid}", json={"web_search": True})
        assert blocked.status_code == 400
        assert "leave" in blocked.json()["detail"] or "queries" in blocked.json()["detail"]
        assert (await client.get(f"/api/conversations/{cid}")).json()["web_search"] is False

        ok = await client.patch(
            f"/api/conversations/{cid}",
            json={"web_search": True, "confirm_egress": True},
        )
        assert ok.status_code == 200 and ok.json()["web_search"] is True

        # Turning it off never needs confirmation.
        off = await client.patch(f"/api/conversations/{cid}", json={"web_search": False})
        assert off.status_code == 200 and off.json()["web_search"] is False
    finally:
        await client.delete(f"/api/conversations/{cid}")
