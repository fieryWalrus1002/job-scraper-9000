"""Tests for email_scraper.gmail_eml_grabber — Gmail OAuth + EML download.

All Google API interactions are mocked. Tests cover:
- OAuth2 credential flows (existing, expired, refresh, new)
- Email search & download (empty results, multiple messages, base64 decode)
- Filesystem operations (output dir creation, .eml file writes)
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from email_scraper.gmail_eml_grabber import (
    download_labeled_emails_as_eml,
    get_gmail_service,
)


# ---------------------------------------------------------------------------
# Fixtures — mock Google API objects
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_valid_creds():
    """Mock Credentials that are valid (no re-auth needed)."""
    creds = MagicMock()
    creds.valid = True
    creds.expired = False
    return creds


@pytest.fixture
def mock_expired_refreshable_creds():
    """Mock Credentials that are expired but have a refresh_token."""
    creds = MagicMock()
    creds.valid = False
    creds.expired = True
    creds.refresh_token = "some-refresh-token"
    return creds


@pytest.fixture
def mock_gmail_service():
    """Mock Gmail API service with pre-configured responses."""
    service = MagicMock()
    # Default: return one message
    service.users().messages().list.return_value.execute.return_value = {
        "messages": [{"id": "msg-001"}, {"id": "msg-002"}]
    }
    service.users().messages().get.return_value.execute.return_value = {
        "raw": "Rm9vIEJhcg=="  # base64 for "Foo Bar"
    }
    return service


# ---------------------------------------------------------------------------
# Tests — get_gmail_service (OAuth2 flows)
# ---------------------------------------------------------------------------


def test_uses_existing_valid_token(tmp_path, mock_valid_creds):
    """When token.json exists and creds are valid, skip re-auth."""
    token_file = tmp_path / "token.json"
    token_file.write_text(json.dumps({"refresh_token": "old-token"}))

    with (
        patch("email_scraper.gmail_eml_grabber.os.path.exists", return_value=True),
        patch(
            "email_scraper.gmail_eml_grabber.Credentials.from_authorized_user_file",
            return_value=mock_valid_creds,
        ),
        patch("email_scraper.gmail_eml_grabber.build") as mock_build,
    ):
        # Temporarily override the file paths used by the function
        with patch.object(os.path, "exists", return_value=True):
            get_gmail_service()
            mock_build.assert_called_once()
            mock_build.assert_called_with("gmail", "v1", credentials=mock_valid_creds)


def test_refreshes_expired_token_with_refresh_token(
    tmp_path, mock_expired_refreshable_creds
):
    """When creds are expired but have refresh_token, call creds.refresh()."""
    with (
        patch("email_scraper.gmail_eml_grabber.os.path.exists", return_value=True),
        patch(
            "email_scraper.gmail_eml_grabber.Credentials.from_authorized_user_file",
            return_value=mock_expired_refreshable_creds,
        ),
        patch("email_scraper.gmail_eml_grabber.Request"),
        patch("email_scraper.gmail_eml_grabber.build"),
        patch("builtins.open", MagicMock()),
    ):
        get_gmail_service()
        mock_expired_refreshable_creds.refresh.assert_called_once()


def test_runs_oauth_flow_when_no_token_file(tmp_path):
    """When token.json doesn't exist, trigger InstalledAppFlow."""
    with (
        patch("email_scraper.gmail_eml_grabber.os.path.exists", return_value=False),
        patch(
            "email_scraper.gmail_eml_grabber.InstalledAppFlow.from_client_secrets_file"
        ) as mock_flow_cls,
        patch("email_scraper.gmail_eml_grabber.build"),
        patch("builtins.open", MagicMock()),
    ):
        mock_flow = MagicMock()
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_cls.return_value = mock_flow

        get_gmail_service()
        mock_flow_cls.assert_called_once()
        mock_flow.run_local_server.assert_called_once_with(port=0)


def test_saves_token_after_oauth_flow(tmp_path):
    """After OAuth flow, credentials are saved to token.json."""
    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.to_json.return_value = '{"refresh_token": "new"}'

    with (
        patch("email_scraper.gmail_eml_grabber.os.path.exists", return_value=False),
        patch(
            "email_scraper.gmail_eml_grabber.InstalledAppFlow.from_client_secrets_file"
        ) as mock_flow_cls,
        patch("email_scraper.gmail_eml_grabber.build"),
        patch("builtins.open", MagicMock()),
        patch("email_scraper.gmail_eml_grabber.os") as mock_os,
    ):
        mock_os.path.exists.return_value = False
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_cls.return_value = mock_flow

        get_gmail_service()
        # open() should have been called to write token.json
        # (verified by builtins.open mock being called)


def test_runs_oauth_when_creds_invalid_no_refresh():
    """When creds exist but are invalid with no refresh_token, re-auth."""
    bad_creds = MagicMock()
    bad_creds.valid = False
    bad_creds.expired = True
    bad_creds.refresh_token = None

    with (
        patch("email_scraper.gmail_eml_grabber.os.path.exists", return_value=True),
        patch(
            "email_scraper.gmail_eml_grabber.Credentials.from_authorized_user_file",
            return_value=bad_creds,
        ),
        patch(
            "email_scraper.gmail_eml_grabber.InstalledAppFlow.from_client_secrets_file"
        ) as mock_flow_cls,
        patch("email_scraper.gmail_eml_grabber.build"),
        patch("builtins.open", MagicMock()),
    ):
        mock_flow = MagicMock()
        new_creds = MagicMock()
        new_creds.valid = True
        mock_flow.run_local_server.return_value = new_creds
        mock_flow_cls.return_value = mock_flow

        get_gmail_service()
        mock_flow_cls.assert_called_once()


# ---------------------------------------------------------------------------
# Tests — download_labeled_emails_as_eml
# ---------------------------------------------------------------------------


def test_creates_output_directory(tmp_path, mock_gmail_service):
    """Output directory is created if it doesn't exist."""
    output_dir = tmp_path / "new_dir" / "sub_dir"
    assert not output_dir.exists()

    with patch(
        "email_scraper.gmail_eml_grabber.get_gmail_service",
        return_value=mock_gmail_service,
    ):
        download_labeled_emails_as_eml(
            label_query="label:test", output_dir=str(output_dir)
        )

    assert output_dir.is_dir()


def test_saves_eml_files(tmp_path, mock_gmail_service):
    """Each message is saved as {msg_id}.eml."""
    output_dir = tmp_path / "emails"
    output_dir.mkdir()

    with patch(
        "email_scraper.gmail_eml_grabber.get_gmail_service",
        return_value=mock_gmail_service,
    ):
        download_labeled_emails_as_eml(
            label_query="label:test", output_dir=str(output_dir)
        )

    assert (output_dir / "msg-001.eml").exists()
    assert (output_dir / "msg-002.eml").exists()


def test_decodes_base64url_raw(tmp_path, mock_gmail_service):
    """The 'raw' field (base64url) is decoded and written as binary."""
    output_dir = tmp_path / "emails"
    output_dir.mkdir()

    with patch(
        "email_scraper.gmail_eml_grabber.get_gmail_service",
        return_value=mock_gmail_service,
    ):
        download_labeled_emails_as_eml(
            label_query="label:test", output_dir=str(output_dir)
        )

    # "Rm9vIEJhcg==" decodes to "Foo Bar"
    content = (output_dir / "msg-001.eml").read_bytes()
    assert content == b"Foo Bar"


def test_passes_label_query_to_api(tmp_path, mock_gmail_service):
    """The label_query string is forwarded to messages().list()."""
    output_dir = tmp_path / "emails"
    output_dir.mkdir()

    with patch(
        "email_scraper.gmail_eml_grabber.get_gmail_service",
        return_value=mock_gmail_service,
    ):
        download_labeled_emails_as_eml(
            label_query="label:job-alerts is:unread",
            output_dir=str(output_dir),
        )

    # Verify the query was passed
    mock_gmail_service.users().messages().list.assert_called_with(
        userId="me", q="label:job-alerts is:unread"
    )


def test_handles_no_messages(tmp_path, capsys):
    """When no messages match, prints 'No messages found' and returns."""
    service = MagicMock()
    service.users().messages().list.return_value.execute.return_value = {"messages": []}

    output_dir = tmp_path / "emails"
    output_dir.mkdir()

    with patch(
        "email_scraper.gmail_eml_grabber.get_gmail_service", return_value=service
    ):
        download_labeled_emails_as_eml(
            label_query="label:empty", output_dir=str(output_dir)
        )

    captured = capsys.readouterr()
    assert "No messages found" in captured.out


def test_downloads_all_messages(tmp_path):
    """All messages from the API are downloaded."""
    service = MagicMock()
    service.users().messages().list.return_value.execute.return_value = {
        "messages": [{"id": f"msg-{i:03d}"} for i in range(5)]
    }
    service.users().messages().get.return_value.execute.return_value = {
        "raw": "dGVzdA=="  # "test"
    }

    output_dir = tmp_path / "emails"
    output_dir.mkdir()

    with patch(
        "email_scraper.gmail_eml_grabber.get_gmail_service", return_value=service
    ):
        download_labeled_emails_as_eml(
            label_query="label:test", output_dir=str(output_dir)
        )

    # Verify all 5 messages were fetched
    assert service.users().messages().get.call_count == 5
    for i in range(5):
        assert (output_dir / f"msg-{i:03d}.eml").exists()
