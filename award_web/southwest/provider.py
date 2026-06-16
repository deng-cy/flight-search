from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ..models import AwardWebSearchRequest
from .normalization import page_status


SOUTHWEST_BOOK_URL = "https://www.southwest.com/air/booking/"


class SouthwestProviderError(RuntimeError):
    pass


def _date_mmdd(value: str) -> str:
    _year, month, day = value.split("-", 2)
    return f"{month}/{day}"


def _booking_query_url(request: AwardWebSearchRequest) -> str:
    params = {
        "adultPassengersCount": request.adults,
        "adultsCount": request.adults,
        "departureDate": request.departure_date,
        "departureTimeOfDay": "ALL_DAY",
        "destinationAirportCode": request.destination,
        "fareType": "POINTS",
        "originationAirportCode": request.origin,
        "passengerType": "ADULT",
        "promoCode": "",
        "returnDate": "",
        "returnTimeOfDay": "ALL_DAY",
        "tripType": "oneway",
        "validate": "true",
    }
    return f"{SOUTHWEST_BOOK_URL}?{urlencode(params)}"


def _import_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise SouthwestProviderError(
            "Playwright is required for live Southwest web searches. "
            "Install award_web/requirements.txt and run `python -m playwright install chromium`."
        ) from exc
    return sync_playwright


def _safe_click(locator: Any, timeout_ms: int = 2500) -> bool:
    try:
        if locator.count():
            locator.first.click(timeout=timeout_ms)
            return True
    except Exception:
        return False
    return False


def _select_one_way(page: Any) -> None:
    trigger = page.locator('[role="combobox"][aria-label="Trip type options"]')
    try:
        trigger.first.wait_for(state="visible", timeout=15000)
        trigger.first.click(timeout=10000)
        page.get_by_text("One-way", exact=True).click(timeout=10000)
        return
    except Exception:
        pass
    if "one-way" not in page.locator("body").inner_text(timeout=5000).lower():
        raise SouthwestProviderError("Southwest trip type selector was not found")


def _set_airport(page: Any, selector: str, code: str) -> None:
    field = page.locator(selector)
    if field.count() != 1:
        raise SouthwestProviderError(f"Southwest airport field {selector} was not found")
    field.fill(code, timeout=10000)
    page.keyboard.press("Tab")


def _set_date(page: Any, request: AwardWebSearchRequest) -> None:
    field = page.locator("#departureDate")
    if field.count() != 1:
        raise SouthwestProviderError("Southwest departure date field was not found")
    field.fill(_date_mmdd(request.departure_date), timeout=10000)
    page.keyboard.press("Tab")


def _set_passengers(page: Any, adults: int) -> None:
    field = page.locator('input[name="adultPassengersCount"]')
    if field.count() == 1 and adults != 1:
        field.fill(str(adults), timeout=10000)
        page.keyboard.press("Tab")


def _select_points(page: Any) -> None:
    if _safe_click(page.get_by_text("Points", exact=True), timeout_ms=10000):
        return
    radio = page.locator('input[name="fareType"][value="POINTS"]')
    if radio.count() != 1:
        raise SouthwestProviderError("Southwest points fare selector was not found")
    radio.evaluate(
        """(el) => {
            el.checked = true;
            el.setAttribute("aria-checked", "true");
            el.dispatchEvent(new Event("input", { bubbles: true }));
            el.dispatchEvent(new Event("change", { bubbles: true }));
        }"""
    )


def _fill_search_form(page: Any, request: AwardWebSearchRequest) -> None:
    _safe_click(page.get_by_text("Dismiss", exact=True), timeout_ms=3000)
    _select_one_way(page)
    _set_airport(page, "#originationAirportCode", request.origin)
    _set_airport(page, "#destinationAirportCode", request.destination)
    _set_date(page, request)
    _set_passengers(page, request.adults)
    _select_points(page)


def _submit_search(page: Any, timeout_ms: int) -> None:
    submit = page.locator("#flightBookingSubmit")
    if submit.count() != 1:
        raise SouthwestProviderError("Southwest Search flights button was not found")
    submit.click(timeout=10000)
    page.wait_for_timeout(8000)
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def search_southwest_public(
    request: AwardWebSearchRequest,
    *,
    html_path: Path,
    screenshot_path: Path,
    headless: bool = True,
    timeout_ms: int = 45000,
) -> dict[str, Any]:
    if request.trip_type != "one-way" or request.return_date:
        raise SouthwestProviderError("Southwest award web searches must be run as one-way searches and summed later.")

    sync_playwright = _import_playwright()
    created_at = datetime.now(UTC).isoformat()
    with sync_playwright() as playwright:
        browser = None
        context = None
        page = None
        network_errors: list[dict[str, Any]] = []
        try:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1365, "height": 900})
            page = context.new_page()

            def capture_response(response: Any) -> None:
                url = response.url
                if "/api/air-booking/" not in url and "/air/booking/select" not in url:
                    return
                if response.status >= 400:
                    network_errors.append({"status": response.status, "url": url})

            page.on("response", capture_response)
            page.goto(SOUTHWEST_BOOK_URL, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.locator("#flightBookingSubmit").wait_for(state="visible", timeout=timeout_ms)
            except Exception:
                pass
            _fill_search_form(page, request)
            _submit_search(page, timeout_ms)

            body_text = page.locator("body").inner_text(timeout=10000)
            if page_status(body_text)[0] == "search_not_completed":
                page.goto(_booking_query_url(request), wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(5000)
                body_text = page.locator("body").inner_text(timeout=10000)

            html = page.content()
            html_path.parent.mkdir(parents=True, exist_ok=True)
            html_path.write_text(html, encoding="utf-8")
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_path), full_page=True, timeout=15000)
            status, status_message = page_status(body_text)
            if status == "search_not_completed" and network_errors:
                first_error = network_errors[0]
                status = "provider_error"
                status_message = f"Southwest network request returned HTTP {first_error['status']}: {first_error['url']}"
            return {
                "provider": "southwest",
                "created_at": created_at,
                "request": request.as_provider_request(),
                "status": status,
                "status_message": status_message,
                "url": page.url,
                "body_text": body_text,
                "network_errors": network_errors,
                "evidence": {
                    "html": str(html_path),
                    "screenshot": str(screenshot_path),
                },
            }
        except Exception as exc:
            body_text = ""
            html = ""
            url = page.url if page is not None else SOUTHWEST_BOOK_URL
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
            if detected_status in {"unknown", "search_not_completed"}:
                detected_status = "provider_error"
                detected_message = str(exc)
            return {
                "provider": "southwest",
                "created_at": created_at,
                "request": request.as_provider_request(),
                "status": detected_status,
                "status_message": detected_message,
                "url": url,
                "body_text": body_text,
                "network_errors": network_errors,
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
