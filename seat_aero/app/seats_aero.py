from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Optional

import httpx


@dataclass
class SeatsAeroResult:
    data: Any
    headers: Mapping[str, str]


class SeatsAeroApiError(Exception):
    def __init__(self, status_code: int, detail: Any, headers: Mapping[str, str]) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    return value


def _clean_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: cleaned for key, value in values.items() if (cleaned := _clean_value(value)) is not None}


class SeatsAeroClient:
    def __init__(self, api_key: str, base_url: str = "https://seats.aero", timeout_seconds: float = 30) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
    ) -> SeatsAeroResult:
        headers = {
            "Accept": "application/json",
            "Partner-Authorization": self.api_key,
        }

        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = await client.request(
                method,
                path,
                headers=headers,
                params=_clean_mapping(params or {}),
                json=_clean_mapping(json_body or {}) if json_body is not None else None,
            )

        try:
            data = response.json()
        except ValueError:
            data = {"message": response.text}

        if response.status_code >= 400:
            raise SeatsAeroApiError(response.status_code, data, response.headers)

        return SeatsAeroResult(data=data, headers=response.headers)
