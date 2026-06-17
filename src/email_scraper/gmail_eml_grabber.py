"""Gmail EML Grabber module.
Contains functions to pull those annoying job posting emails from Gmail api, scrape & parse the details to match the output of our other job scraper pipeline. You can then upload it to the backend exactly like we already do with ingest.
"""

import os
import base64
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.json.
# We only need read access for this task.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    """Handles OAuth2 authentication and returns the Gmail API service object."""
    creds = None
    # token.json stores the user's access and refresh tokens
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def download_labeled_emails_as_eml(label_query: str, output_dir: str):
    """Searches for emails and saves them as .eml files."""
    service = get_gmail_service()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"Searching for messages matching: '{label_query}'...")

    # Use standard Gmail search syntax (e.g., 'label:job-alerts is:unread')
    results = service.users().messages().list(userId="me", q=label_query).execute()
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
    # Example usage: targeting a specific label
    download_labeled_emails_as_eml(
        label_query="label:job-alerts", output_dir="./scraped_emails"
    )
