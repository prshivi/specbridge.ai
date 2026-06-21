from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(slots=True)
class APIError(Exception):
    message: str
    status_code: int | None = None

    def __str__(self) -> str:
        return self.message


class SpecBridgeAPI:
    """Small, testable HTTP client for the Streamlit workspace."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: int = 120,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("API_BASE_URL", "http://localhost:8000")
        ).rstrip("/")
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        return self.get("/health", timeout=5)

    def upload(self, uploaded_file: Any) -> dict[str, Any]:
        try:
            response = requests.post(
                f"{self.base_url}/upload",
                files={
                    "file": (
                        uploaded_file.name,
                        uploaded_file.getvalue(),
                        uploaded_file.type,
                    )
                },
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise self._connection_error(error) from error
        return self._decode(response)

    def get(
        self,
        path: str,
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        try:
            response = requests.get(
                f"{self.base_url}{path}",
                timeout=timeout or self.timeout,
            )
        except requests.RequestException as error:
            raise self._connection_error(error) from error
        return self._decode(response)

    def post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = requests.post(
                f"{self.base_url}{path}",
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise self._connection_error(error) from error
        return self._decode(response)

    def patch(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.patch(
                f"{self.base_url}{path}",
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise self._connection_error(error) from error
        return self._decode(response)

    def download(self, path: str) -> bytes:
        try:
            response = requests.get(
                f"{self.base_url}{path}",
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise self._connection_error(error) from error
        if not response.ok:
            self._raise(response)
        return response.content

    def _connection_error(self, error: requests.RequestException) -> APIError:
        return APIError(
            f"Cannot connect to the SpecBridge API at {self.base_url}. "
            "Start the FastAPI backend and try again."
        )

    @staticmethod
    def _decode(response: requests.Response) -> dict[str, Any]:
        if not response.ok:
            SpecBridgeAPI._raise(response)
        try:
            return response.json()
        except ValueError as error:
            raise APIError(
                "The API returned an invalid response.",
                response.status_code,
            ) from error

    @staticmethod
    def _raise(response: requests.Response) -> None:
        try:
            payload = response.json()
            detail = payload.get("detail", response.text)
            if isinstance(detail, list):
                detail = "; ".join(
                    str(item.get("msg", item)) if isinstance(item, dict) else str(item)
                    for item in detail
                )
        except ValueError:
            detail = response.text
        message = str(detail).strip() or f"API request failed ({response.status_code})."
        raise APIError(message, response.status_code)
