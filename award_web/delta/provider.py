from __future__ import annotations

import base64
import json
import re
import shutil
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


def _stage_path(path: Path, stage: str) -> Path:
    return path.with_name(f"{path.stem}_{stage}{path.suffix}")


def _safe_screenshot(page: Any, path: Path, timeout_ms: int = 15000) -> str:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True, timeout=timeout_ms)
    except Exception:
        return ""
    return str(path) if path.exists() and path.stat().st_size > 0 else ""


def _capture_page_snapshot(page: Any, *, stage: str, html_path: Path, screenshot_path: Path) -> dict[str, Any]:
    body_text = page.locator("body").inner_text(timeout=10000)
    html = page.content()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    screenshot = _safe_screenshot(page, screenshot_path)
    status, status_message = page_status(body_text)
    return {
        "stage": stage,
        "url": page.url,
        "status": status,
        "status_message": status_message,
        "body_text": body_text,
        "evidence": {
            "html": str(html_path),
            "screenshot": screenshot,
        },
    }


def _copy_snapshot_evidence(snapshot: dict[str, Any], *, html_path: Path, screenshot_path: Path) -> dict[str, Any]:
    evidence = snapshot.get("evidence") if isinstance(snapshot.get("evidence"), dict) else {}
    copied_evidence = {"html": "", "screenshot": ""}
    source_html = str(evidence.get("html") or "")
    if source_html:
        html_source = Path(source_html)
        if html_source.exists():
            html_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(html_source, html_path)
            copied_evidence["html"] = str(html_path)
    source_screenshot = str(evidence.get("screenshot") or "")
    if source_screenshot:
        screenshot_source = Path(source_screenshot)
        if screenshot_source.exists() and screenshot_source.stat().st_size > 0:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(screenshot_source, screenshot_path)
            copied_evidence["screenshot"] = str(screenshot_path)
    return {**snapshot, "evidence": copied_evidence}


def _write_browser_capture_html(snapshot: dict[str, Any], html_path: Path) -> str:
    html = snapshot.get("html_content")
    if html is None:
        html = snapshot.get("html")
    if isinstance(html, str) and html:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html, encoding="utf-8")
        return str(html_path)

    evidence = snapshot.get("evidence") if isinstance(snapshot.get("evidence"), dict) else {}
    source_html = str(snapshot.get("html_path") or evidence.get("html") or "")
    if source_html:
        source = Path(source_html)
        if source.exists():
            html_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, html_path)
            return str(html_path)
    return ""


def _write_browser_capture_screenshot(snapshot: dict[str, Any], screenshot_path: Path) -> str:
    screenshot_base64 = snapshot.get("screenshot_base64")
    if isinstance(screenshot_base64, str) and screenshot_base64:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(base64.b64decode(screenshot_base64))
        return str(screenshot_path) if screenshot_path.stat().st_size > 0 else ""

    evidence = snapshot.get("evidence") if isinstance(snapshot.get("evidence"), dict) else {}
    source_screenshot = str(snapshot.get("screenshot_path") or evidence.get("screenshot") or "")
    if source_screenshot:
        source = Path(source_screenshot)
        if source.exists() and source.stat().st_size > 0:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, screenshot_path)
            return str(screenshot_path)
    return ""


def _browser_capture_stage_paths(
    *,
    stage: str,
    index: int,
    total: int,
    html_path: Path,
    screenshot_path: Path,
) -> tuple[Path, Path]:
    normalized_stage = stage.lower()
    if total == 1 or normalized_stage in {"return", "final"}:
        return html_path, screenshot_path
    if normalized_stage:
        return _stage_path(html_path, normalized_stage), _stage_path(screenshot_path, normalized_stage)
    return _stage_path(html_path, f"snapshot_{index + 1}"), _stage_path(screenshot_path, f"snapshot_{index + 1}")


def _normalize_browser_capture_snapshot(
    snapshot: dict[str, Any],
    *,
    stage: str,
    index: int,
    total: int,
    html_path: Path,
    screenshot_path: Path,
) -> dict[str, Any]:
    target_html, target_screenshot = _browser_capture_stage_paths(
        stage=stage,
        index=index,
        total=total,
        html_path=html_path,
        screenshot_path=screenshot_path,
    )
    body_text = str(snapshot.get("body_text") or snapshot.get("text") or "")
    status, status_message = page_status(body_text)
    return {
        "stage": stage,
        "url": str(snapshot.get("url") or ""),
        "status": str(snapshot.get("status") or status),
        "status_message": str(snapshot.get("status_message") or status_message),
        "body_text": body_text,
        "evidence": {
            "html": _write_browser_capture_html(snapshot, target_html),
            "screenshot": _write_browser_capture_screenshot(snapshot, target_screenshot),
        },
    }


def import_delta_browser_capture(
    capture_path: Path,
    request: AwardWebSearchRequest,
    *,
    html_path: Path,
    screenshot_path: Path,
) -> dict[str, Any]:
    with capture_path.open(encoding="utf-8") as handle:
        capture = json.load(handle)
    if not isinstance(capture, dict):
        raise DeltaProviderError(f"{capture_path} must contain a JSON object")

    raw_snapshots = capture.get("snapshots")
    if isinstance(raw_snapshots, list) and raw_snapshots:
        snapshots = [snapshot for snapshot in raw_snapshots if isinstance(snapshot, dict)]
    else:
        snapshots = [capture]
    if not snapshots:
        raise DeltaProviderError(f"{capture_path} did not contain any browser snapshots")

    normalized_snapshots = [
        _normalize_browser_capture_snapshot(
            snapshot,
            stage=str(snapshot.get("stage") or ("outbound" if index == 0 else "return")),
            index=index,
            total=len(snapshots),
            html_path=html_path,
            screenshot_path=screenshot_path,
        )
        for index, snapshot in enumerate(snapshots)
    ]
    final_snapshot = normalized_snapshots[-1]
    return {
        "provider": "delta",
        "capture_source": "browser_session",
        "created_at": str(capture.get("created_at") or datetime.now(UTC).isoformat()),
        "request": request.as_provider_request(),
        "status": final_snapshot["status"],
        "status_message": final_snapshot["status_message"],
        "url": final_snapshot["url"],
        "body_text": final_snapshot["body_text"],
        "evidence": final_snapshot["evidence"],
        "snapshots": normalized_snapshots,
    }


def _looks_like_return_selection(text: str, request: AwardWebSearchRequest) -> bool:
    normalized = "\n".join(line.strip().lower() for line in text.splitlines() if line.strip())
    route_tokens = [
        "return",
        (request.return_origin or "").lower(),
        (request.return_destination or "").lower(),
    ]
    return all(token in normalized for token in route_tokens if token)


def _select_first_outbound_fare(page: Any) -> bool:
    fare_text = re.compile(r"Delta\s+Main.*?(?:Actual Fare|From).*?miles", re.IGNORECASE | re.DOTALL)
    candidates = [
        page.get_by_role("button").filter(has_text=fare_text),
        page.locator("[role='button']").filter(has_text=fare_text),
        page.locator("button, [role='button'], a").filter(has_text=fare_text),
    ]
    for locator in candidates:
        try:
            count = min(locator.count(), 8)
        except Exception:
            continue
        for index in range(count):
            try:
                locator.nth(index).click(timeout=6000)
                return True
            except Exception:
                continue
    return False


def _wait_for_return_selection(page: Any, request: AwardWebSearchRequest, timeout_ms: int) -> bool:
    page.wait_for_timeout(4000)
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    deadline = max(1, timeout_ms // 1000)
    for _ in range(deadline):
        try:
            if _looks_like_return_selection(page.locator("body").inner_text(timeout=2000), request):
                return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return False


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
            snapshots = []
            if request.trip_type == "round-trip":
                return_captured = False
                outbound_snapshot = _capture_page_snapshot(
                    page,
                    stage="outbound",
                    html_path=_stage_path(html_path, "outbound"),
                    screenshot_path=_stage_path(screenshot_path, "outbound"),
                )
                snapshots.append(outbound_snapshot)
                if _select_first_outbound_fare(page) and _wait_for_return_selection(page, request, timeout_ms):
                    snapshots.append(
                        _capture_page_snapshot(
                            page,
                            stage="return",
                            html_path=html_path,
                            screenshot_path=screenshot_path,
                        )
                    )
                    return_captured = True
                if not return_captured:
                    snapshots[0] = _copy_snapshot_evidence(
                        outbound_snapshot,
                        html_path=html_path,
                        screenshot_path=screenshot_path,
                    )
            if not snapshots:
                snapshots.append(
                    _capture_page_snapshot(
                        page,
                        stage="outbound" if request.trip_type == "round-trip" else "one-way",
                        html_path=html_path,
                        screenshot_path=screenshot_path,
                    )
                )
            final_snapshot = snapshots[-1]
            return {
                "provider": "delta",
                "created_at": created_at,
                "request": request.as_provider_request(),
                "status": final_snapshot["status"],
                "status_message": final_snapshot["status_message"],
                "url": final_snapshot["url"],
                "body_text": final_snapshot["body_text"],
                "evidence": {
                    "html": final_snapshot["evidence"]["html"],
                    "screenshot": final_snapshot["evidence"]["screenshot"],
                },
                "snapshots": snapshots,
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
