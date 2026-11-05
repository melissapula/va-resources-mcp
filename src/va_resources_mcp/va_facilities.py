"""Client for the VA Lighthouse Facilities API (sandbox).

Docs: https://developer.va.gov/explore/api/va-facilities/docs
The API key goes in the `apikey` request header.
"""

from dataclasses import dataclass

import httpx

FACILITIES_URL = "https://sandbox-api.va.gov/services/va_facilities/v1/facilities"
TIMEOUT_SECONDS = 10.0
API_KEY_HEADER = "apikey"


@dataclass(frozen=True)
class FacilitySummary:
    id: str
    name: str
    facility_type: str
    classification: str | None
    address: str | None
    phone: str | None
    distance_miles: float | None
    operating_status: str


class FacilitiesError(Exception):
    """Raised when the Facilities API can't be reached or answers badly.

    Messages are built from the status code and the API's error detail only, never from
    the request, so the API key can't end up in them.
    """


async def find_facilities(
    latitude: float,
    longitude: float,
    *,
    api_key: str,
    facility_type: str | None = None,
    service: str | None = None,
    radius_miles: float | None = None,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
) -> list[FacilitySummary]:
    """Find VA facilities near a point, nearest first.

    Returns an empty list when nothing matches, so callers can tell "nothing nearby"
    apart from "the service is down" (which raises).
    """
    # httpx can only encode ASCII header values; anything else would surface as a misleading
    # "could not be reached" error instead of pointing at the key.
    if not api_key.isascii():
        raise FacilitiesError(
            "The VA API key contains characters that aren't allowed. Check VA_API_KEY in .env."
        )

    params: dict[str, str | int | float] = {"lat": latitude, "long": longitude, "per_page": limit}
    if facility_type:
        params["type"] = facility_type
    if service:
        params["services[]"] = service
    if radius_miles is not None:
        params["radius"] = radius_miles

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
    try:
        # Never follow redirects, even on a caller's client: httpx strips only `Authorization`
        # on a cross-host redirect, so the `apikey` header would go to the new host.
        response = await client.get(
            FACILITIES_URL,
            params=params,
            headers={API_KEY_HEADER: api_key},
            follow_redirects=False,
        )
        response.raise_for_status()
        body = response.json()
    except httpx.TimeoutException as exc:
        raise FacilitiesError("The VA Facilities API timed out. Try again in a moment.") from exc
    except httpx.HTTPStatusError as exc:
        raise FacilitiesError(_status_message(exc.response)) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise FacilitiesError(
            "The VA Facilities API could not be reached or sent invalid data."
        ) from exc
    finally:
        if owns_client:
            await client.aclose()

    try:
        return _parse_facilities(body)
    except (KeyError, TypeError, AttributeError) as exc:
        raise FacilitiesError("The VA Facilities API sent an unexpected response.") from exc


def _status_message(response: httpx.Response) -> str:
    status = response.status_code
    if status in (401, 403):
        return "The VA API key is missing or was rejected. Check VA_API_KEY in .env."
    if status == 400:
        detail = _error_detail(response)
        if detail:
            return f"The VA Facilities API rejected the request: {detail}"
        return "The VA Facilities API rejected the request as a bad request."
    if status == 429:
        return (
            "The VA Facilities API rate limit was reached (60 requests per minute). "
            "Try again in a minute."
        )
    return f"The VA Facilities API returned HTTP {status}."


def _error_detail(response: httpx.Response) -> str | None:
    """The first `errors[].detail` the API sent, such as an invalid service ID."""
    try:
        return response.json()["errors"][0]["detail"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def _parse_facilities(body: dict) -> list[FacilitySummary]:
    # Distances aren't inside each facility; the API lists them in meta, keyed by ID.
    meta = body.get("meta") or {}
    distances = {d["id"]: d["distance"] for d in meta.get("distances") or []}
    items = body["data"]
    summaries = [s for s in (_try_summary(item, distances) for item in items) if s is not None]
    # Every record failing means the response shape changed, not that nothing is nearby.
    if items and not summaries:
        raise FacilitiesError("The VA Facilities API sent an unexpected response.")
    return summaries


def _try_summary(item: dict, distances: dict[str, float]) -> FacilitySummary | None:
    """Summarize one record, or None if it's malformed, so one bad record doesn't hide the rest."""
    try:
        return _to_summary(item, distances.get(item["id"]))
    except (KeyError, TypeError, AttributeError):
        return None


def _to_summary(item: dict, distance: float | None) -> FacilitySummary:
    attributes = item["attributes"]
    return FacilitySummary(
        id=item["id"],
        name=attributes["name"],
        facility_type=attributes["facilityType"],
        classification=attributes.get("classification"),
        address=_one_line_address(attributes.get("address")),
        phone=(attributes.get("phone") or {}).get("main"),
        distance_miles=distance,
        operating_status=attributes["operatingStatus"]["code"],
    )


def _one_line_address(address: dict | None) -> str | None:
    """Join the physical address parts that exist, e.g. "705 5th St NW, Bemidji, MN 56601"."""
    physical = (address or {}).get("physical") or {}
    street = ", ".join(
        part for part in (physical.get(k) for k in ("address1", "address2", "address3")) if part
    )
    state_zip = " ".join(part for part in (physical.get("state"), physical.get("zip")) if part)
    parts = [part for part in (street, physical.get("city"), state_zip) if part]
    return ", ".join(parts) or None
