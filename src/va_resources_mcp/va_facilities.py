"""Client for the VA Lighthouse Facilities API (sandbox).

Docs: https://developer.va.gov/explore/api/va-facilities/docs
The API key goes in the `apikey` request header.
"""

import logging
from dataclasses import dataclass

import httpx

from .config import is_sendable_api_key

logger = logging.getLogger(__name__)

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
    # An unsendable key would surface as a misleading "could not be reached" error instead of
    # pointing at the key. load_api_key checks this at startup too; this covers other callers.
    if not is_sendable_api_key(api_key):
        raise FacilitiesError(
            "The VA API key contains spaces or characters that aren't allowed. "
            "Check VA_API_KEY in .env."
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
    distances = _distances_by_id(body.get("meta"))
    items = body["data"]
    summaries = [s for s in (_try_summary(item, distances) for item in items) if s is not None]
    # Every record failing means the response shape changed, not that nothing is nearby.
    if items and not summaries:
        raise FacilitiesError("The VA Facilities API sent an unexpected response.")
    return summaries


def _distances_by_id(meta: object) -> dict[str, float]:
    """Distances aren't inside each facility; the API lists them in meta, keyed by ID.

    A malformed entry is skipped, so that facility just has no distance instead of the whole
    search failing.
    """
    entries = meta.get("distances") if isinstance(meta, dict) else None
    distances: dict[str, float] = {}
    for entry in entries if isinstance(entries, list) else []:
        entry_id, distance = (
            (entry.get("id"), entry.get("distance")) if isinstance(entry, dict) else (None, None)
        )
        # bool is a subclass of int, so exclude it explicitly.
        is_number = isinstance(distance, (int, float)) and not isinstance(distance, bool)
        if isinstance(entry_id, str) and is_number:
            distances[entry_id] = float(distance)
        else:
            logger.warning("Ignoring malformed VA facility distance entry: %r", entry)
    return distances


def _try_summary(item: dict, distances: dict[str, float]) -> FacilitySummary | None:
    """Summarize one record, or None if it's malformed, so one bad record doesn't hide the rest."""
    try:
        return _to_summary(item, distances.get(item["id"]))
    except (KeyError, TypeError, AttributeError) as exc:
        # Logged so a partial result can be traced; the record holds no request data or key.
        record_id = item.get("id") if isinstance(item, dict) else None
        logger.warning("Skipping malformed VA facility record %r: %r", record_id, exc)
        return None


def _to_summary(item: dict, distance: float | None) -> FacilitySummary:
    """A bad required field raises (so the record is skipped); a bad optional one becomes None."""
    attributes = item["attributes"]
    return FacilitySummary(
        id=_required_str(item["id"], "id"),
        name=_required_str(attributes["name"], "name"),
        facility_type=_required_str(attributes["facilityType"], "facilityType"),
        classification=_optional_str(attributes.get("classification")),
        address=_one_line_address(attributes.get("address")),
        phone=_optional_str(_dict_or_empty(attributes.get("phone")).get("main")),
        distance_miles=distance,
        operating_status=_required_str(attributes["operatingStatus"]["code"], "operatingStatus"),
    )


def _required_str(value: object, field: str) -> str:
    # The message names the field only, never the value, so the log line stays small and safe.
    if not isinstance(value, str) or not value:
        raise TypeError(f"{field} is not a non-empty string")
    return value


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _dict_or_empty(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _one_line_address(address: object) -> str | None:
    """Join the physical address parts that exist, e.g. "705 5th St NW, Bemidji, MN 56601".

    A part that isn't a string is left out rather than converted, since str() of a numeric ZIP
    would drop its leading zeros.
    """
    physical = _dict_or_empty(_dict_or_empty(address).get("physical"))

    def part(key: str) -> str | None:
        return _optional_str(physical.get(key))

    street = ", ".join(p for p in (part("address1"), part("address2"), part("address3")) if p)
    state_zip = " ".join(p for p in (part("state"), part("zip")) if p)
    parts = [p for p in (street, part("city"), state_zip) if p]
    return ", ".join(parts) or None
