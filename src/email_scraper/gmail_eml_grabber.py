"""Gmail EML Grabber module.
Contains functions to pull those annoying job posting emails from Gmail api, scrape & parse the details to match the output of our other job scraper pipeline. You can then upload it to the backend exactly like we already do with ingest.
"""

import argparse
import os
import base64
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import yaml

# If modifying these scopes, delete the file token.json.
# We only need read access for this task.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CONFIG_PATH = "config/email_scraper/config.yml"


# Load configuration from YAML file
with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

CREDENTIALS_PATH = config["credentials_path"]
TOKEN_PATH = config["token_path"]
LABEL_QUERY = config["label_query"]
OUTPUT_DIR = config["output_dir"]
MAX_EMAILS = config.get("max_emails")


def get_gmail_service():
    """Handles OAuth2 authentication and returns the Gmail API service object."""
    creds = None
    # token.json stores the user's access and refresh tokens
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def download_labeled_emails_as_eml(
    label_query: str,
    output_dir: str,
    max_emails: int | None = None,
):
    """Searches for emails and saves the newest matching messages as .eml files."""
    service = get_gmail_service()

    if max_emails is not None and max_emails <= 0:
        raise ValueError("max_emails must be a positive integer")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Searching for messages matching: '{label_query}'...")

    # Use standard Gmail search syntax (e.g., 'label:job-alerts is:unread').
    # Gmail returns matching messages newest-first; maxResults limits this to
    # the most recent N messages.
    list_kwargs = {"userId": "me", "q": label_query}
    if max_emails is not None:
        list_kwargs["maxResults"] = str(max_emails)

    results = service.users().messages().list(**list_kwargs).execute()
    messages = results.get("messages", [])

    if not messages:
        print("No messages found.")
        return

    print(f"Found {len(messages)} messages. Downloading...")

    for msg in messages:
        msg_id = msg["id"]

        # Fetch the message utilizing format='raw'
        # This returns the full email payload (RFC 2822) encoded in base64url format
        message_data = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="raw")
            .execute()
        )

        # Decode the base64url string
        raw_email_bytes = base64.urlsafe_b64decode(message_data["raw"].encode("ASCII"))

        # Save directly to disk
        file_path = os.path.join(output_dir, f"{msg_id}.eml")
        with open(file_path, "wb") as f:
            f.write(raw_email_bytes)

        print(f"Saved: {file_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download matching Gmail messages as .eml files."
    )
    parser.add_argument(
        "--max-emails",
        type=int,
        default=MAX_EMAILS,
        help="Only download the newest N matching emails. Defaults to config max_emails.",
    )
    args = parser.parse_args()

    download_labeled_emails_as_eml(
        label_query=LABEL_QUERY,
        output_dir=OUTPUT_DIR,
        max_emails=args.max_emails,
    )
