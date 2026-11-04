"""Client for the U.S. Census Bureau Geocoder (free, no API key).

Docs: https://geocoding.geo.census.gov/geocoder/
"""

from dataclasses import dataclass

import httpx

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
TIMEOUT_SECONDS = 10.0


@dataclass
class GeocodeMatch:
    matched_address: str
    latitude: float
    longitude: float


class GeocodeError(Exception):
    """Raised when the Census service can't be reached or answers badly."""


async def geocode(address: str, client: httpx.AsyncClient | None = None) -> list[GeocodeMatch]:
    """Turn a one-line U.S. address into coordinates.

    Returns an empty list when Census finds no match, so callers can tell
    "no such address" apart from "the service is down" (which raises).
    """
    params = {"address": address, "benchmark": "Public_AR_Current", "format": "json"}
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_SECONDS)
    try:
        response = await client.get(CENSUS_URL, params=params)
        response.raise_for_status()
        data = response.json()
    except httpx.TimeoutException as exc:
        raise GeocodeError("The Census geocoder timed out. Try again in a moment.") from exc
    except httpx.HTTPStatusError as exc:
        raise GeocodeError(
            f"The Census geocoder returned HTTP {exc.response.status_code}."
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise GeocodeError(
            "The Census geocoder could not be reached or sent invalid data."
        ) from exc
    finally:
        if owns_client:
            await client.aclose()

    matches = data.get("result", {}).get("addressMatches", [])
    # Census puts longitude in "x" and latitude in "y".
    return [
        GeocodeMatch(
            matched_address=m["matchedAddress"],
            latitude=m["coordinates"]["y"],
            longitude=m["coordinates"]["x"],
        )
        for m in matches
    ]
