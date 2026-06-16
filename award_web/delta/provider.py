from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..models import AwardWebSearchRequest
from .normalization import page_status


DELTA_BOOK_URL = "https://www.delta.com/flightsearch/book-a-flight"


class DeltaProviderError(RuntimeError):
    pass


def _date_id(value: str) -> str:
    year, month, day = value.split("-", 2)
    return f"{month}-{day}-{year}"


def _trip_label(trip_type: str) -> str:
    return "One Way" if trip_type == "one-way" else "Round Trip"


def _import_playwright() -> Any:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise DeltaProviderError(
            "Playwright is required for live Delta web searches. "
            "Install award_web/requirements.txt and run `python -m playwright install chromium`."
        ) from exc
    return sync_playwright, PlaywrightError, PlaywrightTimeoutError


def _safe_click(locator: Any, timeout_ms: int = 2500) -> bool:
    try:
        if locator.count() == 1:
            locator.click(timeout=timeout_ms)
            return True
    except Exception:
        return False
    return False


def _set_checkbox(page: Any, selector: str, checked: bool) -> None:
    locator = page.locator(selector)
    if locator.count() != 1:
        return
    try:
        locator.set_checked(checked, timeout=5000)
    except Exception:
        current = bool(locator.is_checked())
        if current != checked:
            locator.click(timeout=5000)


def _select_trip_type(page: Any, trip_type: str) -> None:
    current = page.locator("#trip-type-field")
    if current.count() != 1:
        raise DeltaProviderError("Delta trip type selector was not found")
    current.click(timeout=10000)
    page.get_by_role("option", name=_trip_label(trip_type), exact=True).click(timeout=10000)


def _set_airport(page: Any, kind: str, code: str) -> None:
    prefix = "Origin Airport or City" if kind == "origin" else "Destination Airport or City"
    page.locator(f'[role="button"][aria-label^="{prefix}"]').click(timeout=10000)
    search = page.locator('input[id^="predictive_search_"]')
    search.fill(code, timeout=10000)
    page.get_by_role("option", name=f"{code} ", exact=False).click(timeout=15000)


def _select_date(page: Any, iso_date: str) -> None:
    target_selector = f'[id="{_date_id(iso_date)}"]'
    for _ in range(18):
        target = page.locator(target_selector)
        if target.count() == 1:
            target.click(timeout=10000)
            return
        page.locator("#date_picker_next").click(timeout=10000)
        page.wait_for_timeout(250)
    raise DeltaProviderError(f"Delta date picker could not reach {iso_date}")


def _open_date_picker(page: Any) -> None:
    trigger = page.locator(".aura-date-picker__trigger")
    if trigger.count() != 1:
        raise DeltaProviderError("Delta date picker trigger was not found")
    trigger.click(timeout=10000)


def _complete_dates(page: Any, request: AwardWebSearchRequest) -> None:
    _open_date_picker(page)
    _safe_click(page.get_by_role("button", name="Clear", exact=True))
    _select_date(page, request.departure_date)
    if request.trip_type == "round-trip" and request.return_date:
        _select_date(page, request.return_date)
    page.locator("#date_picker_done").click(timeout=10000)


def _fill_search_form(page: Any, request: AwardWebSearchRequest, *, flexible_dates: bool) -> None:
    _safe_click(page.locator("#onetrust-accept-btn-handler"))
    _select_trip_type(page, request.trip_type)
    _set_airport(page, "origin", request.origin)
    _set_airport(page, "destination", request.destination)
    _complete_dates(page, request)
    _set_checkbox(page, "#shopWithMiles", True)
    _set_checkbox(page, "#flexibleDate", flexible_dates)


def _submit_search(page: Any, timeout_ms: int) -> None:
    find_flights = page.get_by_role("button", name="Find Flights", exact=True)
    if find_flights.count() != 1:
        raise DeltaProviderError("Delta Find Flights button was not found")
    find_flights.click(timeout=10000)
    page.wait_for_timeout(6000)
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def search_delta_public(
    request: AwardWebSearchRequest,
    *,
    html_path: Path,
    screenshot_path: Path,
    headless: bool = True,
    flexible_dates: bool = False,
    timeout_ms: int = 45000,
) -> dict[str, Any]:
    sync_playwright, _playwright_error, _playwright_timeout_error = _import_playwright()
    created_at = datetime.now(UTC).isoformat()
    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None
        try:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1365, "height": 900})
            page = context.new_page()
            page.goto(DELTA_BOOK_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            _fill_search_form(page, request, flexible_dates=flexible_dates)
            _submit_search(page, timeout_ms)
            body_text = page.locator("body").inner_text(timeout=10000)
            html = page.content()
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html, encoding="utf-8")
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_path), full_page=True, timeout=15000)
            status, status_message = page_status(body_text)
            return {
                "provider": "delta",
                "created_at": created_at,
                "request": request.as_provider_request(),
                "status": status,
                "status_message": status_message,
                "url": page.url,
                "body_text": body_text,
                "evidence": {
                    "html": str(html_path),
                    "screenshot": str(screenshot_path),
                },
            }
        except Exception as exc:
            body_text = ""
            html = ""
            url = page.url if page is not None else DELTA_BOOK_URL
            if page is not None:
                try:
                    body_text = page.locator("body").inner_text(timeout=5000)
                    html = page.content()
                except Exception:
                    pass
            if html:
                html_path.parent.mkdir(parents=True, exist_ok=True)
                html_path.write_text(html, encoding="utf-8")
            if page is not None:
                try:
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshot_path), full_page=True, timeout=10000)
                except Exception:
                    pass
            detected_status, detected_message = page_status(body_text)
            if detected_status == "unknown":
                detected_status = "provider_error"
                detected_message = str(exc)
            return {
                "provider": "delta",
                "created_at": created_at,
                "request": request.as_provider_request(),
                "status": detected_status,
                "status_message": detected_message,
                "url": url,
                "body_text": body_text,
                "evidence": {
                    "html": str(html_path) if html else "",
                    "screenshot": str(screenshot_path) if screenshot_path.exists() else "",
                },
            }
        finally:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
