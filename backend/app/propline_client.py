from __future__ import annotations

import logging
import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import ValidationError

from app.propline_models import (
    PropLineEvent,
    PropLineEventOdds,
    PropLineEventStats,
)
from app.settings import Settings

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class PropLineClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        endpoint: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.endpoint = endpoint
        self.status_code = status_code


class PropLineClient:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        timeout = httpx.Timeout(
            settings.propline_timeout_seconds,
            connect=min(10.0, settings.propline_timeout_seconds),
            read=settings.propline_timeout_seconds,
        )
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None
        self._base_url = settings.propline_base_url.rstrip("/")
        self._api_key = settings.propline_api_key
        self._sleeper = sleeper

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "PropLineClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def list_mlb_events(self) -> list[PropLineEvent]:
        endpoint = "/sports/baseball_mlb/events"
        data = self._get(endpoint)
        if not isinstance(data, list):
            raise PropLineClientError(
                f"PropLine endpoint {endpoint} returned a non-list response.",
                endpoint=endpoint,
            )
        try:
            return [PropLineEvent.model_validate(item) for item in data]
        except ValidationError as exc:
            raise PropLineClientError(
                f"PropLine endpoint {endpoint} returned invalid event data.",
                endpoint=endpoint,
            ) from exc

    def get_batter_hit_odds(self, event_id: str) -> PropLineEventOdds:
        endpoint = f"/sports/baseball_mlb/events/{event_id}/odds"
        data = self._get(endpoint, params={"markets": "batter_hits"})
        try:
            return PropLineEventOdds.model_validate(data)
        except ValidationError as exc:
            raise PropLineClientError(
                f"PropLine endpoint {endpoint} returned invalid odds data.",
                endpoint=endpoint,
            ) from exc

    def get_event_stats(
        self,
        sport_key: str,
        event_id: str,
    ) -> PropLineEventStats:
        endpoint = f"/sports/{sport_key}/events/{event_id}/stats"
        data = self._get(endpoint)
        try:
            return PropLineEventStats.model_validate(data)
        except ValidationError as exc:
            raise PropLineClientError(
                f"PropLine endpoint {endpoint} returned invalid stats data.",
                endpoint=endpoint,
            ) from exc

    def _get(
        self,
        endpoint: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self._base_url}{endpoint}"
        attempts = 3
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = self._client.get(
                    url,
                    params=params,
                    headers={"X-API-Key": self._api_key},
                )
            except (httpx.NetworkError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt == attempts:
                    break
                self._sleep_before_retry(endpoint, attempt, None)
                continue

            if response.status_code in TRANSIENT_STATUS_CODES:
                if attempt == attempts:
                    raise self._http_error(endpoint, response)
                self._sleep_before_retry(endpoint, attempt, response)
                continue

            if response.status_code >= 400:
                raise self._http_error(endpoint, response)

            try:
                return response.json()
            except ValueError as exc:
                raise PropLineClientError(
                    f"PropLine endpoint {endpoint} returned invalid JSON.",
                    endpoint=endpoint,
                    status_code=response.status_code,
                ) from exc

        raise PropLineClientError(
            f"PropLine endpoint {endpoint} failed after {attempts} attempts.",
            endpoint=endpoint,
        ) from last_error

    def _sleep_before_retry(
        self,
        endpoint: str,
        attempt: int,
        response: httpx.Response | None,
    ) -> None:
        retry_after = response.headers.get("Retry-After") if response else None
        delay = _retry_after_seconds(retry_after)
        if delay is None:
            delay = 0.5 * (2 ** (attempt - 1))
        logger.warning(
            "Retrying PropLine request",
            extra={"endpoint": endpoint, "attempt": attempt + 1},
        )
        self._sleeper(delay)

    @staticmethod
    def _http_error(
        endpoint: str,
        response: httpx.Response,
    ) -> PropLineClientError:
        return PropLineClientError(
            (
                f"PropLine endpoint {endpoint} returned "
                f"status {response.status_code}."
            ),
            endpoint=endpoint,
            status_code=response.status_code,
        )


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        delay = (retry_at - datetime.now(UTC)).total_seconds()
    return max(delay, 0.0)
