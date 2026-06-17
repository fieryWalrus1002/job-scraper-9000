"""Fixtures for email_scraper tests.

Extracts the text/plain part from the real ZR email fixture (.eml file)
and provides both the raw QP-encoded payload and the decoded text.
"""

import email
import quopri
from pathlib import Path

import pytest

# Resolve the single .eml fixture in tests/email_scraper/data/
_FIXTURE_DIR = Path(__file__).resolve().parent / "data"
_EML_FILE = next(_FIXTURE_DIR.glob("*.eml"), None)


def _extract_text_plain(raw_bytes: bytes):
    """Return (qp_encoded_payload, decoded_text) from the text/plain MIME part."""
    msg = email.message_from_bytes(raw_bytes)
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            # get_payload() without decode=True returns the raw QP-encoded string
            qp_payload = part.get_payload(decode=False)
            decoded = quopri.decodestring(qp_payload).decode("utf-8")
            return qp_payload, decoded
    raise RuntimeError("No text/plain part found in email fixture")


@pytest.fixture(scope="package")
def eml_raw_bytes():
    """Raw bytes of the .eml fixture file."""
    if _EML_FILE is None:
        pytest.skip("No .eml fixture found in tests/email_scraper/data/")
    return _EML_FILE.read_bytes()


@pytest.fixture(scope="package")
def zr_email_qp_payload(eml_raw_bytes):
    """QP-encoded text/plain payload (what parse_zr_plaintext receives)."""
    return _extract_text_plain(eml_raw_bytes)[0]


@pytest.fixture(scope="package")
def zr_email_decoded_text(eml_raw_bytes):
    """Fully decoded text/plain body (for readable assertions)."""
    return _extract_text_plain(eml_raw_bytes)[1]
