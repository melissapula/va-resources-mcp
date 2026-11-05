"""Unit tests for the VA Facilities client, using a fake transport instead of the network."""

import logging
from contextlib import suppress

import httpx
import pytest

from va_resources_mcp.va_facilities import TIMEOUT_SECONDS, FacilitiesError, find_facilities

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


@pytest.mark.parametrize(
    "client_kwargs",
    [{"body": {"message": "Bad Request"}}, {"body": {"errors": []}}, {"text": "not json"}],
    ids=["no-errors-key", "empty-errors", "not-json"],
)
async def test_400_without_api_detail_raises_generic_bad_request(client_kwargs):
    with pytest.raises(FacilitiesError, match="rejected the request as a bad request"):
        await search(client_returning(400, **client_kwargs))


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


async def test_skips_a_malformed_facility_logs_it_and_returns_the_rest(caplog):
    broken = facility("vha_bad", "Broken Clinic")
    del broken["attributes"]["operatingStatus"]
    body = {"data": [broken, *BEMIDJI_RESPONSE["data"]], "meta": BEMIDJI_RESPONSE["meta"]}

    with caplog.at_level(logging.WARNING, logger="va_resources_mcp.va_facilities"):
        results = await search(client_returning(200, body))

    assert [f.id for f in results] == ["vha_437GE", "vha_656GA"]
    (record,) = caplog.records
    assert "vha_bad" in record.getMessage()
    assert API_KEY not in caplog.text


def _with_physical(**physical_overrides) -> dict:
    physical = {"address1": "705 5th Street NW", "city": "Bemidji", "state": "MN"}
    physical.update(physical_overrides)
    return {"address": {"physical": physical}}


@pytest.mark.parametrize(
    ("overrides", "field", "expected"),
    [
        ({"phone": "218-555-1212"}, "phone", None),
        ({"phone": {"main": 2187556360}}, "phone", None),
        ({"classification": 7}, "classification", None),
        ({"address": "705 5th Street NW"}, "address", None),
        ({"address": {"physical": ["705 5th Street NW"]}}, "address", None),
        # A numeric ZIP is dropped rather than str()-ed, because str() would lose leading zeros.
        (_with_physical(zip=56601), "address", "705 5th Street NW, Bemidji, MN"),
        (_with_physical(address2=12), "address", "705 5th Street NW, Bemidji, MN"),
    ],
    ids=[
        "phone-string",
        "phone-main-number",
        "classification-number",
        "address-string",
        "physical-list",
        "zip-number",
        "address2-number",
    ],
)
async def test_malformed_optional_field_only_blanks_that_field(overrides, field, expected):
    body = {"data": [facility("vha_437GE", "Bemidji VA Clinic", **overrides)], "meta": {}}

    (result,) = await search(client_returning(200, body))

    assert getattr(result, field) == expected
    assert result.name == "Bemidji VA Clinic"


@pytest.mark.parametrize(
    ("record_id", "overrides"),
    [
        ("vha_bad", {"name": None}),
        ("vha_bad", {"name": ""}),
        ("vha_bad", {"name": 5}),
        ("vha_bad", {"facilityType": None}),
        ("vha_bad", {"operatingStatus": {"code": None}}),
        (5, {}),
        (None, {}),
    ],
    ids=[
        "name-null",
        "name-empty",
        "name-number",
        "type-null",
        "status-code-null",
        "id-number",
        "id-null",
    ],
)
async def test_skips_a_record_whose_required_field_is_not_a_string(record_id, overrides, caplog):
    broken = facility(record_id, "Broken Clinic")
    broken["attributes"].update(overrides)  # not via facility(): "name" would collide with its arg
    body = {"data": [broken, *BEMIDJI_RESPONSE["data"]], "meta": BEMIDJI_RESPONSE["meta"]}

    with caplog.at_level(logging.WARNING, logger="va_resources_mcp.va_facilities"):
        results = await search(client_returning(200, body))

    assert [f.id for f in results] == ["vha_437GE", "vha_656GA"]
    assert len(caplog.records) == 1


@pytest.mark.parametrize(
    "bad_entry",
    [{"id": "vha_656GA"}, None, {"id": "vha_656GA", "distance": "far"}, {"distance": 1.0}],
    ids=["missing-distance", "null-entry", "string-distance", "missing-id"],
)
async def test_malformed_distance_entry_only_blanks_that_distance(bad_entry, caplog):
    meta = {"distances": [{"id": "vha_437GE", "distance": 2.54}, bad_entry]}
    body = {"data": BEMIDJI_RESPONSE["data"], "meta": meta}

    with caplog.at_level(logging.WARNING, logger="va_resources_mcp.va_facilities"):
        results = await search(client_returning(200, body))

    assert [(f.id, f.distance_miles) for f in results] == [
        ("vha_437GE", 2.54),
        ("vha_656GA", None),
    ]
    assert len(caplog.records) == 1


@pytest.mark.parametrize(
    "bad_key",
    [
        "s3cret-tokén",
        "s3cret-token\n",
        "s3cret-token\r",
        " s3cret-token",
        "s3cret-token ",
        "s3cret\x00",
    ],
    ids=["non-ascii", "trailing-newline", "trailing-cr", "leading-space", "trailing-space", "nul"],
)
async def test_unsendable_api_key_raises_error_pointing_at_the_key_without_sending(bad_key):
    requests: list[httpx.Request] = []

    with pytest.raises(FacilitiesError, match="VA_API_KEY") as excinfo:
        await find_facilities(
            *BEMIDJI, api_key=bad_key, client=client_returning(200, {}, requests=requests)
        )

    assert "s3cret" not in str(excinfo.value)
    assert requests == []


async def test_json_that_is_not_an_object_raises_facilities_error():
    with pytest.raises(FacilitiesError, match="unexpected response"):
        await search(client_returning(200, ["not", "an", "object"]))


@pytest.mark.parametrize(
    ("status", "body"), [(200, BEMIDJI_RESPONSE), (503, {})], ids=["success", "error"]
)
async def test_closes_the_client_it_creates_on_success_and_error(monkeypatch, status, body):
    real_async_client = httpx.AsyncClient
    created: list[httpx.AsyncClient] = []

    def make_client(**kwargs) -> httpx.AsyncClient:
        assert kwargs == {"timeout": TIMEOUT_SECONDS}
        transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))
        created.append(real_async_client(transport=transport, **kwargs))
        return created[-1]

    monkeypatch.setattr(httpx, "AsyncClient", make_client)

    with suppress(FacilitiesError):  # the 503 case raises; this test is about cleanup
        await find_facilities(*BEMIDJI, api_key=API_KEY)

    (client,) = created
    assert client.is_closed


async def test_does_not_send_the_key_on_a_redirect_even_if_the_client_follows_them():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://elsewhere.example/collect"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)

    with pytest.raises(FacilitiesError, match="HTTP 302"):
        await search(client)

    assert [r.url.host for r in requests] == ["sandbox-api.va.gov"]
