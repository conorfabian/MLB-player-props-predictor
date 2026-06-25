from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.propline_client import (
    PropLineClient,
    PropLineClientError,
    _retry_after_seconds,
)
from app.settings import Settings
from tests.fixtures import odds_payload


def settings() -> Settings:
    return Settings(
        supabase_url="https://example.supabase.co",
        supabase_secret_key="secret",
        frontend_origins=("http://localhost:3000",),
        propline_api_key="api-secret",
        propline_base_url="https://api.prop-line.com/v1",
        propline_timeout_seconds=30,
        slate_timezone="America/New_York",
        cron_job_secret="",
    )


def test_client_sends_key_and_uses_event_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[odds_payload(event_id="evt-1")])

    client = PropLineClient(
        settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    events = client.list_mlb_events()

    assert events[0].id == "evt-1"
    assert seen[0].headers["X-API-Key"] == "api-secret"
    assert seen[0].url.path == "/v1/sports/baseball_mlb/events"


def test_client_uses_batter_hits_market_and_parses_optional_fields() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = odds_payload(event_id="evt-2")
        payload["bookmakers"][1]["markets"][0]["outcomes"][0].pop(
            "recorded_at"
        )
        return httpx.Response(200, json=payload)

    client = PropLineClient(
        settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    odds = client.get_batter_hit_odds("evt-2")

    assert odds.id == "evt-2"
    assert seen[0].url.path == "/v1/sports/baseball_mlb/events/evt-2/odds"
    assert seen[0].url.params["markets"] == "batter_hits"
    assert odds.bookmakers[1].markets[0].outcomes[0].recorded_at is None


def test_client_retries_transient_errors() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=[])

    client = PropLineClient(
        settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _delay: None,
    )

    assert client.list_mlb_events() == []
    assert attempts == 2


def test_client_retries_network_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadError("network interrupted", request=request)
        return httpx.Response(200, json=[])

    client = PropLineClient(
        settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _delay: None,
    )

    assert client.list_mlb_events() == []
    assert attempts == 2


def test_retry_after_accepts_http_date() -> None:
    retry_at = datetime.now(UTC) + timedelta(seconds=30)

    delay = _retry_after_seconds(
        retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT")
    )

    assert delay is not None
    assert 0 <= delay <= 31


@pytest.mark.parametrize("status_code", [401, 403])
def test_client_does_not_retry_auth_errors(status_code: int) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status_code)

    client = PropLineClient(
        settings(),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleeper=lambda _delay: None,
    )

    with pytest.raises(PropLineClientError) as exc_info:
        client.list_mlb_events()

    assert attempts == 1
    assert "api-secret" not in str(exc_info.value)
    assert str(status_code) in str(exc_info.value)
