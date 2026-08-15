from pathlib import Path

from conclave.config import settings
from conclave.domain.files import read_attachment_text
from conclave.domain.redact import redact_pii


def test_email_phone_ssn_ip_redacted():
    text = (
        "Contact john.doe@example.com or (404) 555-1234. "
        "SSN 123-45-6789, server at 192.168.1.10."
    )
    out = redact_pii(text)
    assert "john.doe@example.com" not in out
    assert "555-1234" not in out
    assert "123-45-6789" not in out
    assert "192.168.1.10" not in out
    assert "[EMAIL-1]" in out and "[PHONE-1]" in out and "[SSN-1]" in out and "[IP-1]" in out


def test_luhn_valid_card_redacted_invalid_number_kept():
    valid = "4111 1111 1111 1111"  # Luhn-valid test card
    invalid = "1234 5678 9012 3456"  # fails Luhn — e.g. a record number, keep it
    out = redact_pii(f"card {valid} vs id {invalid}")
    assert valid not in out and "[CARD-1]" in out
    assert invalid in out


def test_same_value_same_placeholder():
    out = redact_pii("mail a@b.co, again a@b.co, and c@d.co")
    assert out.count("[EMAIL-1]") == 2
    assert "[EMAIL-2]" in out


def test_clinical_text_untouched():
    text = "74 yo male, low grade Ta lesion, cystoscopy q3 months, mitomycin 40mg."
    assert redact_pii(text) == text


def test_attachment_read_applies_redaction(tmp_path: Path, monkeypatch):
    f = tmp_path / "record.txt"
    f.write_text("Patient reachable at jane@clinic.org, MRN follow-up.", encoding="utf-8")

    monkeypatch.setattr(settings, "redact_pii", True)
    assert "[EMAIL-1]" in read_attachment_text(str(f))
    assert "jane@clinic.org" not in read_attachment_text(str(f))

    monkeypatch.setattr(settings, "redact_pii", False)
    assert "jane@clinic.org" in read_attachment_text(str(f))
