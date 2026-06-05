from datetime import date
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.seats_aero import SeatsAeroApiError, SeatsAeroClient, SeatsAeroResult


Cabin = Literal["economy", "premium", "business", "first"]
Region = Literal["North America", "South America", "Africa", "Asia", "Europe", "Oceania"]


class LiveSearchRequest(BaseModel):
    origin_airport: str
    destination_airport: str
    departure_date: date
    source: str
    disable_filters: bool = False
    show_dynamic_pricing: bool = False
    seat_count: int = Field(1, ge=1, le=9)


app = FastAPI(
    title="Seats.aero Search API",
    version="0.1.0",
    description="A thin Python API wrapper around the Seats.aero Partner API.",
)


def get_client(settings: Settings = Depends(get_settings)) -> SeatsAeroClient:
    return SeatsAeroClient(
        api_key=settings.seats_aero_api_key,
        base_url=settings.seats_aero_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    )


def _json_response(result: SeatsAeroResult) -> JSONResponse:
    headers = {}
    remaining = result.headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        headers["X-SeatsAero-RateLimit-Remaining"] = remaining
    return JSONResponse(content=result.data, headers=headers)


async def _proxy(client: SeatsAeroClient, method: str, path: str, **kwargs: object) -> JSONResponse:
    try:
        return _json_response(await client.request(method, path, **kwargs))
    except SeatsAeroApiError as exc:
        headers = {}
        remaining = exc.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            headers["X-SeatsAero-RateLimit-Remaining"] = remaining
        raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers) from exc


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/search")
async def cached_search(
    origin_airport: str = Query(..., description="Comma-delimited origin airport codes, such as SFO,LAX."),
    destination_airport: str = Query(..., description="Comma-delimited destination airport codes, such as FRA,LHR."),
    start_date: Optional[date] = Query(None, description="Earliest departure date in YYYY-MM-DD format."),
    end_date: Optional[date] = Query(None, description="Latest departure date in YYYY-MM-DD format."),
    cursor: Optional[int] = Query(None, ge=0),
    take: int = Query(500, ge=10, le=1000),
    order_by: Optional[Literal["lowest_mileage"]] = Query(None),
    skip: Optional[int] = Query(None, ge=0),
    include_trips: bool = Query(False),
    only_direct_flights: bool = Query(False),
    carriers: Optional[str] = Query(None, description="Comma-delimited carrier codes, such as DL,AA."),
    include_filtered: bool = Query(False),
    sources: Optional[str] = Query(None, description="Comma-delimited mileage programs, such as aeroplan,united."),
    minify_trips: bool = Query(False),
    cabins: Optional[str] = Query(None, description="Comma-delimited cabins, such as economy,business."),
    client: SeatsAeroClient = Depends(get_client),
) -> JSONResponse:
    params = locals()
    params.pop("client")
    return await _proxy(client, "GET", "/partnerapi/search", params=params)


@app.get("/availability")
async def bulk_availability(
    source: str = Query(..., description="Mileage program to retrieve availability from."),
    cabin: Optional[Cabin] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    origin_region: Optional[Region] = Query(None),
    destination_region: Optional[Region] = Query(None),
    take: int = Query(500, ge=10, le=1000),
    cursor: Optional[int] = Query(None, ge=0),
    skip: int = Query(0, ge=0),
    include_filtered: bool = Query(False),
    client: SeatsAeroClient = Depends(get_client),
) -> JSONResponse:
    params = locals()
    params.pop("client")
    return await _proxy(client, "GET", "/partnerapi/availability", params=params)


@app.get("/trips/{availability_id}")
async def get_trips(
    availability_id: str,
    include_filtered: bool = Query(False),
    client: SeatsAeroClient = Depends(get_client),
) -> JSONResponse:
    return await _proxy(
        client,
        "GET",
        f"/partnerapi/trips/{availability_id}",
        params={"include_filtered": include_filtered},
    )


@app.get("/routes")
async def get_routes(
    source: str = Query(..., description="Mileage program source."),
    client: SeatsAeroClient = Depends(get_client),
) -> JSONResponse:
    return await _proxy(client, "GET", "/partnerapi/routes", params={"source": source})


@app.post("/live")
async def live_search(
    request: LiveSearchRequest,
    settings: Settings = Depends(get_settings),
    client: SeatsAeroClient = Depends(get_client),
) -> JSONResponse:
    if not settings.enable_live_search:
        raise HTTPException(
            status_code=403,
            detail="Live Search is disabled locally. Seats.aero documents this endpoint as commercial-partner-only.",
        )

    return await _proxy(client, "POST", "/partnerapi/live", json_body=request.model_dump())
