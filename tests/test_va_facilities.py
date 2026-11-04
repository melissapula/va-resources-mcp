"""Unit tests for the VA Facilities client, using a fake transport instead of the network."""

import httpx
import pytest

from va_resources_mcp.va_facilities import FacilitiesError, find_facilities

API_KEY = "test-key-should-never-leak"
BEMIDJI = (47.47, -94.88)


def facility(fid: str, name: str, **attribute_overrides) -> dict:
    attributes = {
        "name": name,
        "facilityType": "va_health_facility",
        "classification": "Primary Care CBOC",
        "address": {
            "physical": {
                "address1": "705 5th Street NW",
                "address2": None,
                "address3": None,
                "city": "Bemidji",
                "state": "MN",
                "zip": "56601-2851",
            }
        },
        "phone": {"main": "218-755-6360"},
        "operatingStatus": {"code": "NORMAL"},
        "lat": 47.47,
        "long": -94.88,
    }
    attributes.update(attribute_overrides)
    return {"id": fid, "type": "va_facilities", "attributes": attributes}


# Trimmed from a real sandbox response near Bemidji, MN. The distances are listed in the
# opposite order to `data` on purpose, so matching by position instead of by ID fails.
BEMIDJI_RESPONSE = {
    "data": [
        facility("vha_437GE", "Bemidji VA Clinic"),
        facility(
            "vha_656GA",
            "Brainerd VA Clinic",
            address={
                "physical": {
                    "address1": "722 NW 7th Street",
                    "city": "Brainerd",
                    "state": "MN",
                    "zip": "56401",
                }
            },
            phone={"main": "218-855-1115"},
        ),
    ],
    "meta": {
        "distances": [
            {"id": "vha_656GA", "distance": 82.78},
            {"id": "vha_437GE", "distance": 2.54},
        ]
    },
}


def client_returning(
    status: int,
    body=None,
    exc: Exception | None = None,
    requests: list[httpx.Request] | None = None,
    text: str | None = None,
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if exc:
            raise exc
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def search(client: httpx.AsyncClient, **kwargs):
    return await find_facilities(*BEMIDJI, api_key=API_KEY, client=client, **kwargs)


async def test_returns_facilities_in_api_order_with_distances_matched_by_id():
    results = await search(client_returning(200, BEMIDJI_RESPONSE))

    assert [f.id for f in results] == ["vha_437GE", "vha_656GA"]
    assert [f.distance_miles for f in results] == [2.54, 82.78]
    first = results[0]
    assert first.name == "Bemidji VA Clinic"
    assert first.facility_type == "va_health_facility"
    assert first.classification == "Primary Care CBOC"
    assert first.address == "705 5th Street NW, Bemidji, MN 56601-2851"
    assert first.phone == "218-755-6360"
    assert first.operating_status == "NORMAL"


async def test_sends_api_key_header_and_coordinates():
    requests: list[httpx.Request] = []
    await search(client_returning(200, BEMIDJI_RESPONSE, requests=requests), limit=3)

    (request,) = requests
    assert request.headers["apikey"] == API_KEY
    assert request.url.params["lat"] == "47.47"
    assert request.url.params["long"] == "-94.88"
    assert request.url.params["per_page"] == "3"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, {}),
        (
            {"facility_type": "health", "service": "primaryCare", "radius_miles": 50},
            {"type": "health", "services[]": "primaryCare", "radius": "50"},
        ),
    ],
)
async def test_sends_type_service_and_radius_only_when_given(kwargs, expected):
    requests: list[httpx.Request] = []
    await search(client_returning(200, BEMIDJI_RESPONSE, requests=requests), **kwargs)

    params = requests[0].url.params
    for name in ("type", "services[]", "radius"):
        assert params.get(name) == expected.get(name)


async def test_no_facilities_returns_empty_list():
    body = {"data": [], "meta": {"distances": []}}
    assert await search(client_returning(200, body)) == []


async def test_missing_optional_fields_become_none():
    bare = facility("vha_999", "Bare Clinic")
    for optional in ("classification", "address", "phone"):
        del bare["attributes"][optional]
    body = {"data": [bare], "meta": {}}

    (result,) = await search(client_returning(200, body))

    assert result.classification is None
    assert result.address is None
    assert result.phone is None
    assert result.distance_miles is None


async def test_invalid_service_400_passes_api_detail_through():
    detail = "'notAService' is not a valid value for 'services'"
    body = {"errors": [{"title": "Invalid field value", "detail": detail, "status": "400"}]}

    with pytest.raises(FacilitiesError, match=detail):
        await search(client_returning(400, body), service="notAService")


@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_key_raises_error_that_does_not_contain_the_key(status):
    with pytest.raises(FacilitiesError, match="VA_API_KEY") as excinfo:
        await search(client_returning(status, {"message": "Unauthorized"}))

    assert API_KEY not in str(excinfo.value)


async def test_rate_limit_429_raises_friendly_error():
    with pytest.raises(FacilitiesError, match="rate limit"):
        await search(client_returning(429, {"message": "API rate limit exceeded"}))


async def test_other_http_error_reports_status():
    with pytest.raises(FacilitiesError, match="HTTP 503"):
        await search(client_returning(503, {}))


async def test_timeout_raises_friendly_error():
    with pytest.raises(FacilitiesError, match="timed out"):
        await search(client_returning(0, exc=httpx.ReadTimeout("slow")))


async def test_unreachable_host_raises_friendly_error():
    with pytest.raises(FacilitiesError, match="could not be reached"):
        await search(client_returning(0, exc=httpx.ConnectError("no route")))


@pytest.mark.parametrize(
    "client_kwargs",
    [
        {"body": {"data": [{"id": "vha_1", "attributes": {"facilityType": "x"}}], "meta": {}}},
        {"text": "<html>not json</html>"},
    ],
    ids=["missing-name", "not-json"],
)
async def test_malformed_body_raises_facilities_error(client_kwargs):
    with pytest.raises(FacilitiesError):
        await search(client_returning(200, **client_kwargs))


async def test_json_that_is_not_an_object_raises_facilities_error():
    with pytest.raises(FacilitiesError, match="unexpected response"):
        await search(client_returning(200, ["not", "an", "object"]))
