"""Unit tests for the Census client, using a fake transport instead of the network."""

import httpx
import pytest

from va_resources_mcp.census import GeocodeError, geocode

MATCH_RESPONSE = {
    "result": {
        "addressMatches": [
            {
                "matchedAddress": "403 4TH ST NW, BEMIDJI, MN, 56601",
                "coordinates": {"x": -94.88, "y": 47.47},
            }
        ]
    }
}


def client_returning(status: int, body=None, exc: Exception | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if exc:
            raise exc
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_returns_coordinates_with_lat_lon_in_right_order():
    matches = await geocode("403 4th St NW, Bemidji, MN", client_returning(200, MATCH_RESPONSE))
    assert len(matches) == 1
    assert matches[0].latitude == 47.47
    assert matches[0].longitude == -94.88


async def test_no_match_returns_empty_list():
    matches = await geocode("nowhere", client_returning(200, {"result": {"addressMatches": []}}))
    assert matches == []


async def test_server_error_raises_geocode_error():
    with pytest.raises(GeocodeError, match="HTTP 503"):
        await geocode("anything", client_returning(503, {}))


async def test_timeout_raises_friendly_error():
    with pytest.raises(GeocodeError, match="timed out"):
        await geocode("anything", client_returning(0, exc=httpx.ReadTimeout("slow")))
