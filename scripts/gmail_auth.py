"""One-time OAuth consent flow: mints a SEND-ONLY Gmail token (book App. A §1.3).

Usage (opens a browser window once):
    uv run python scripts/gmail_auth.py ^
        --credentials C:/Users/moham/secrets/moamteam-google/credentials.json ^
        --token C:/Users/moham/secrets/moamteam-google/token-gmail-send.json

The resulting token carries exactly the gmail.send scope — the only scope the
project is allowed to hold (rule #30). Nothing here is ever committed.
"""

import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", required=True,
                        help="OAuth client file downloaded from Google Cloud Console")
    parser.add_argument("--token", required=True,
                        help="where to save the minted send-only token")
    args = parser.parse_args()

    flow = InstalledAppFlow.from_client_secrets_file(args.credentials, [SEND_SCOPE])
    creds = flow.run_local_server(port=0)
    token_path = Path(args.token)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"send-only token saved to {token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
