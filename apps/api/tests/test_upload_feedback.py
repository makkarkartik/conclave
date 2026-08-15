"""Uploads are parsed at ingest: readable files record chars+method, unreadable
files are rejected with an explanation instead of failing later inside a turn."""

from __future__ import annotations

import httpx
import pytest

from conclave.db.session import engine, init_db
from conclave.domain.files import extract_attachment
from conclave.main import app


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


async def _room(client: httpx.AsyncClient) -> str:
    r = await client.post("/api/conversations", json={"topic": "attachment feedback"})
    return r.json()["id"]


async def test_readable_upload_records_extraction(client):
    cid = await _room(client)
    try:
        r = await client.post(
            f"/api/conversations/{cid}/files",
            files={"file": ("notes.md", b"# Plan\n\nShip the canary.", "text/markdown")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["extraction_method"] == "text"
        assert body["extracted_chars"] > 10

        conv = (await client.get(f"/api/conversations/{cid}")).json()
        att = conv["attachments"][0]
        assert att["extracted_chars"] == body["extracted_chars"]
        assert att["extraction_method"] == "text"
    finally:
        await client.delete(f"/api/conversations/{cid}")


async def test_unreadable_pdf_is_rejected_with_reason(client):
    cid = await _room(client)
    try:
        r = await client.post(
            f"/api/conversations/{cid}/files",
            files={"file": ("broken.pdf", b"%PDF-1.4 not actually a pdf", "application/pdf")},
        )
        assert r.status_code == 400
        assert "broken.pdf" in r.json()["detail"]

        conv = (await client.get(f"/api/conversations/{cid}")).json()
        assert conv["attachments"] == []  # nothing half-attached
    finally:
        await client.delete(f"/api/conversations/{cid}")


async def test_empty_file_is_rejected(client):
    cid = await _room(client)
    try:
        r = await client.post(
            f"/api/conversations/{cid}/files",
            files={"file": ("blank.txt", b"   \n  ", "text/plain")},
        )
        assert r.status_code == 400
    finally:
        await client.delete(f"/api/conversations/{cid}")


async def test_unsupported_type_is_rejected(client):
    cid = await _room(client)
    try:
        r = await client.post(
            f"/api/conversations/{cid}/files",
            files={"file": ("sheet.xlsx", b"binary", "application/vnd.ms-excel")},
        )
        assert r.status_code == 400
    finally:
        await client.delete(f"/api/conversations/{cid}")


def test_extraction_reports_method(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("hello world", encoding="utf-8")
    e = extract_attachment(str(f))
    assert e.method == "text" and e.chars == 11 and e.usable

    missing = extract_attachment(str(tmp_path / "nope.md"))
    assert missing.method == "missing" and not missing.usable
