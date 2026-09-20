"""Production Access identity and internal metrics projection tests."""

from types import SimpleNamespace
import logging

from starlette.requests import Request

from app.identity import CloudflareAccessIdentityResolver
from app.metrics import SqlMetricRepository
from uuid import UUID


def _request() -> Request:
    headers = [
        (b"cf-access-jwt-assertion", b"signed-token"),
        (b"cookie", b"CF_Authorization=session-token"),
    ]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_access_resolver_logs_only_a_safe_failure_stage(caplog) -> None:  # type: ignore[no-untyped-def]
    resolver = CloudflareAccessIdentityResolver(
        issuer="https://team.cloudflareaccess.com",
        audience="audience",
        administrator_group_id="admin-id",
        trustee_group_id="trustee-id",
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"cf-access-jwt-assertion", b"secret-signed-token")],
        }
    )

    with caplog.at_level(logging.WARNING, logger="ehf.identity"):
        assert resolver(request) is None

    assert "missing-cookie" in caplog.text
    assert "secret-signed-token" not in caplog.text


def test_access_resolver_requires_verified_full_entra_group_membership(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    resolver = CloudflareAccessIdentityResolver(
        issuer="https://team.cloudflareaccess.com",
        audience="audience",
        administrator_group_id="admin-id",
        trustee_group_id="trustee-id",
    )
    resolver._keys = SimpleNamespace(  # type: ignore[attr-defined]
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key="public-key")
    )
    monkeypatch.setattr(
        "app.identity.jwt.decode",
        lambda *_args, **_kwargs: {
            "type": "app",
            "email": "person@example.org",
            "sub": "subject-1",
        },
    )
    monkeypatch.setattr(
        "app.identity.httpx.get",
        lambda *_args, **_kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "email": "person@example.org",
                "idp": {"name": "Example Person", "groups": ["ADMIN-ID"]},
            },
        ),
    )

    principal = resolver(_request())

    assert principal is not None
    assert principal.groups == frozenset({"EHF-Administrators"})


def test_access_resolver_accepts_cloudflare_group_objects_with_entra_ids(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    resolver = CloudflareAccessIdentityResolver(
        issuer="https://team.cloudflareaccess.com",
        audience="audience",
        administrator_group_id="admin-id",
        trustee_group_id="trustee-id",
    )
    resolver._keys = SimpleNamespace(  # type: ignore[attr-defined]
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key="public-key")
    )
    monkeypatch.setattr(
        "app.identity.jwt.decode",
        lambda *_args, **_kwargs: {
            "type": "app",
            "email": "person@example.org",
            "sub": "subject-1",
        },
    )
    monkeypatch.setattr(
        "app.identity.httpx.get",
        lambda *_args, **_kwargs: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "email": "person@example.org",
                "name": "Example Person",
                "idp": {"name": "Example Person"},
                "groups": [
                    {"id": "ADMIN-ID", "name": "EHF-Administrators"},
                    {"id": "unrelated-id", "name": "Unrelated Group"},
                ],
            },
        ),
    )

    principal = resolver(_request())

    assert principal is not None
    assert principal.groups == frozenset({"EHF-Administrators"})


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str, role: str):
        assert "GetInternalApplicationMetrics" in statement
        assert role == "EHF-Trustees"
        return SimpleNamespace(
            fetchall=lambda: [
                ("Example Applicant", "PhD", 31, 4.5, None, 2, 0, 7, 5, 101, None, 110, "reviewed", 125, "OPENALEX", None, 6, "a7000000-0000-4000-8000-000000000001", "EHF-2026-001")
            ]
        )


def test_sql_metric_repository_maps_role_scoped_projection() -> None:
    records = SqlMetricRepository(lambda: _Connection()).load("EHF-Trustees")

    assert len(records) == 1
    assert records[0].applicant == "Example Applicant"
    assert records[0].academic_age == 4.5
    assert records[0].google_scholar_citations == 110
    assert records[0].verified_citations == 125
    assert records[0].verified_citation_source == "OPENALEX"
    assert records[0].validated_published_papers == 6
    assert records[0].application_number == "EHF-2026-001"


class _DetailCursor:
    def __init__(self) -> None:
        self._set = 0

    def fetchone(self):
        return ("EHF-2026-001", "Example Applicant", 31, 4.5)

    def nextset(self):
        self._set += 1
        return True

    def fetchall(self):
        return [
            (
                "A paper",
                "Journal",
                2024,
                "10.1000/example",
                "https://journal.example/paper",
                "https://openalex.org/W123",
                9,
                '{"counts_by_year":{"2024":4,"2025":5}}',
                "Example Applicant; Ben Biologist",
            )
        ]


class _DetailConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement: str, application_id: UUID, role: str):
        assert "GetInternalApplicantMetricDetail" in statement
        assert application_id == UUID("a7000000-0000-4000-8000-000000000001")
        assert role == "EHF-Trustees"
        return _DetailCursor()


def test_sql_metric_repository_maps_annual_citation_detail() -> None:
    detail = SqlMetricRepository(lambda: _DetailConnection()).load_detail(
        UUID("a7000000-0000-4000-8000-000000000001"), "EHF-Trustees"
    )

    assert detail.application_number == "EHF-2026-001"
    assert detail.publications[0].doi == "10.1000/example"
    assert detail.publications[0].citations_by_year == ((2024, 4), (2025, 5))
    assert detail.publications[0].authors_text == "Example Applicant; Ben Biologist"
