"""Gmail delivery over OAuth 2.0 — send-only, least privilege (book App. A, rule #30).

The token MUST carry exactly the ``gmail.send`` scope: a broader token (e.g. the
gmail.modify one from earlier coursework) is refused outright, because scope creep
is a disqualifiable security violation. Mint a compliant token once with
``scripts/gmail_auth.py``.
"""

import base64
import json
import logging
import time
from email.message import EmailMessage
from pathlib import Path

from moamteam.exceptions import MoamteamError

logger = logging.getLogger(__name__)

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


class EmailAuthError(MoamteamError):
    """Missing/invalid/over-scoped OAuth material — never silently degraded."""


class GmailSender:
    def __init__(self, credentials_path: str | Path, token_path: str | Path):
        self._token_path = Path(token_path)
        self._credentials_path = Path(credentials_path)
        self._service = None

    def _connect(self):
        if self._service is not None:
            return self._service
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not self._token_path.exists():
            raise EmailAuthError(
                f"no Gmail token at {self._token_path} — run scripts/gmail_auth.py once"
            )
        token_data = json.loads(self._token_path.read_text(encoding="utf-8"))
        scopes = set(token_data.get("scopes", []))
        if scopes != {SEND_SCOPE}:
            raise EmailAuthError(
                f"token scopes {sorted(scopes)} violate least-privilege (rule #30): "
                f"exactly [{SEND_SCOPE}] is required — mint a fresh token with "
                "scripts/gmail_auth.py"
            )
        creds = Credentials.from_authorized_user_file(str(self._token_path), [SEND_SCOPE])
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._token_path.write_text(creds.to_json(), encoding="utf-8")
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    def send(self, *, to: str, subject: str, body: str,
             attachments: list[Path] | None = None) -> str:
        """Send one report mail; returns the Gmail message id. JSON attachments only
        (rule #34: a plaintext report is a rejected report)."""
        service = self._connect()
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        for path in attachments or []:
            message.add_attachment(
                path.read_bytes(), maintype="application", subtype="json",
                filename=path.name,
            )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return sent.get("id", "")

    def send_with_backoff(self, *, to: str, subject: str, body: str,
                          attachments: list[Path] | None, max_retries: int,
                          backoff_seconds: float) -> str:
        """Honor HTTP 429 (book iron rule): back off and retry, never hammer."""
        from googleapiclient.errors import HttpError

        attempt = 0
        while True:
            try:
                return self.send(to=to, subject=subject, body=body, attachments=attachments)
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                attempt += 1
                if status != 429 or attempt > max_retries:
                    raise
                wait = backoff_seconds * (2 ** (attempt - 1))
                logger.warning("Gmail 429 — backing off %.0fs (attempt %d/%d)",
                               wait, attempt, max_retries)
                time.sleep(wait)
