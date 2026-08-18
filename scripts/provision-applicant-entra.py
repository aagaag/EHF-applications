#!/usr/bin/env python3
"""Silently provision verified applicants in the fixed EHF Entra group."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path


AZURE_CLI = Path(r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd")
TENANT_ID = "8226a4c2-10fa-4742-b4c0-f4fdb97a0534"
GROUP_ID = "55caf353-80bb-4805-81f0-e31b6fc84b23"
REDIRECT_URL = "https://ehf.isab.science/applicant/sign-in"


def _az(*arguments: str) -> object:
    completed = subprocess.run(
        [str(AZURE_CLI), *arguments], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return json.loads(completed.stdout or "null")


def _az_retry(*arguments: str) -> object:
    for attempt in range(25):
        try:
            return _az(*arguments)
        except subprocess.CalledProcessError:
            if attempt == 24:
                raise
            time.sleep(2)
    raise AssertionError("unreachable")


def provision(input_path: Path, output_path: Path) -> dict[str, int]:
    account = _az("account", "show", "--output", "json")
    if not isinstance(account, dict) or account.get("tenantId") != TENANT_ID:
        raise RuntimeError("Azure CLI is not authenticated to the ISAB tenant.")
    rows = json.loads(input_path.read_text(encoding="utf-8"))
    resolved = [row for row in rows if row.get("email")]
    if len({row["applicationId"] for row in resolved}) != len(resolved):
        raise RuntimeError("The applicant mapping contains duplicate application IDs.")
    if len({row["email"].casefold() for row in resolved}) != len(resolved):
        raise RuntimeError("The applicant mapping contains duplicate email addresses.")
    provisioned = []
    for row in resolved:
        existing = _az_retry(
            "ad", "user", "list", "--filter", f"mail eq '{row['email']}'",
            "--query", "[].id", "--output", "json",
        )
        if not isinstance(existing, list) or len(existing) > 1:
            raise RuntimeError("The Entra directory has an ambiguous applicant identity.")
        invitation = None
        if existing:
            object_id = existing[0]
        else:
            invitation = _az(
                "rest", "--method", "post",
                "--url", "https://graph.microsoft.com/v1.0/invitations",
                "--headers", "Content-Type=application/json",
                "--body", json.dumps({
                    "invitedUserEmailAddress": row["email"],
                    "inviteRedirectUrl": REDIRECT_URL,
                    "sendInvitationMessage": False,
                }, separators=(",", ":")),
                "--output", "json",
            )
            if not isinstance(invitation, dict) or not invitation.get("invitedUser", {}).get("id"):
                raise RuntimeError("Microsoft Graph returned an invalid invitation response.")
            object_id = invitation["invitedUser"]["id"]
        membership = _az_retry(
            "ad", "group", "member", "check", "--group", GROUP_ID,
            "--member-id", object_id, "--output", "json",
        )
        if not isinstance(membership, dict) or not membership.get("value"):
            _az_retry("ad", "group", "member", "add", "--group", GROUP_ID,
                      "--member-id", object_id, "--output", "json")
        provisioned.append({
            "applicationId": row["applicationId"],
            "email": row["email"],
            "entraObjectId": object_id,
            "inviteRedeemUrl": invitation.get("inviteRedeemUrl") if invitation else None,
        })
    output_path.write_text(json.dumps(provisioned, separators=(",", ":")), encoding="utf-8")
    output_path.chmod(0o600)
    return {"eligible": len(resolved), "provisioned": len(provisioned)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(provision(arguments.input, arguments.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
