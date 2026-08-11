from __future__ import annotations

from app.auth.turnstile import TurnstileVerifier


def test_turnstile_accepts_one_valid_bound_token_and_rejects_replay() -> None:
    """Break caught: a valid anti-bot token could be replayed across code requests."""
    verifier = TurnstileVerifier(
        "synthetic-secret",
        "ehf.isab.science",
        lambda _secret, _token, _ip: {
            "success": True,
            "hostname": "ehf.isab.science",
            "action": "applicant-code-request",
        },
    )

    assert verifier.verify("valid-token", "192.0.2.10", "applicant-code-request") is True
    assert verifier.verify("valid-token", "192.0.2.10", "applicant-code-request") is False


def test_turnstile_fails_closed_for_error_wrong_host_action_and_transport_failure() -> None:
    """Break caught: malformed or unavailable Turnstile validation could fail open."""
    responses = iter(
        (
            {"success": False, "hostname": "ehf.isab.science", "action": "applicant-code-request"},
            {"success": True, "hostname": "attacker.invalid", "action": "applicant-code-request"},
            {"success": True, "hostname": "ehf.isab.science", "action": "different-action"},
        )
    )
    verifier = TurnstileVerifier(
        "synthetic-secret",
        "ehf.isab.science",
        lambda _secret, _token, _ip: next(responses),
    )

    assert verifier.verify("failed", "192.0.2.10", "applicant-code-request") is False
    assert verifier.verify("wrong-host", "192.0.2.10", "applicant-code-request") is False
    assert verifier.verify("wrong-action", "192.0.2.10", "applicant-code-request") is False

    broken = TurnstileVerifier(
        "synthetic-secret",
        "ehf.isab.science",
        lambda _secret, _token, _ip: (_ for _ in ()).throw(OSError("synthetic outage")),
    )
    assert broken.verify("outage", "192.0.2.10", "applicant-code-request") is False
