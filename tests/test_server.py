"""Tests for the find_va_facilities tool, called through the MCP server so argument
validation runs. The Facilities client is replaced with a fake; nothing touches the network."""

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from va_resources_mcp import server
from va_resources_mcp.va_facilities import FacilitiesError, FacilitySummary

FAKE_KEY = "fake-key"
BEMIDJI = {"latitude": 47.47, "longitude": -94.88}


def summary(fid: str, name: str, distance: float | None, status: str = "NORMAL") -> FacilitySummary:
    return FacilitySummary(
        id=fid,
        name=name,
        facility_type="va_health_facility",
        classification="Primary Care CBOC",
        address="705 5th Street NW, Bemidji, MN 56601-2851",
        phone="218-755-6360",
        distance_miles=distance,
        operating_status=status,
    )


BEMIDJI_CLINIC = summary("vha_437GE", "Bemidji VA Clinic", 2.54)
BRAINERD_CLINIC = summary("vha_656GA", "Brainerd VA Clinic", 82.78)


class FakeFindFacilities:
    """Stands in for va_facilities.find_facilities and records how it was called."""

    def __init__(self, result: list[FacilitySummary] | None = None, error: Exception | None = None):
        self.result = result or []
        self.error = error
        self.calls: list[dict] = []

    async def __call__(self, latitude: float, longitude: float, **kwargs) -> list[FacilitySummary]:
        self.calls.append({"latitude": latitude, "longitude": longitude, **kwargs})
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def fake_find(monkeypatch):
    monkeypatch.setenv("VA_API_KEY", FAKE_KEY)

    def install(**kwargs) -> FakeFindFacilities:
        fake = FakeFindFacilities(**kwargs)
        monkeypatch.setattr(server, "find_facilities", fake)
        return fake

    return install


async def call_find(**arguments) -> str:
    result = await server.mcp.call_tool("find_va_facilities", arguments)
    return result.content[0].text


async def test_formats_facilities_nearest_first_with_distance_and_id(fake_find):
    fake_find(result=[BEMIDJI_CLINIC, BRAINERD_CLINIC])

    text = await call_find(**BEMIDJI)

    assert text.index("Bemidji VA Clinic") < text.index("Brainerd VA Clinic")
    for expected in [
        "Primary Care CBOC",
        "705 5th Street NW, Bemidji, MN 56601-2851",
        "218-755-6360",
        "2.5 miles",
        "82.8 miles",
        "ID: vha_437GE",
        "ID: vha_656GA",
    ]:
        assert expected in text


async def test_shows_status_only_when_not_normal(fake_find):
    fake_find(result=[BEMIDJI_CLINIC, summary("vha_656GA", "Brainerd VA Clinic", 82.78, "LIMITED")])

    text = await call_find(**BEMIDJI)

    assert "Status: LIMITED" in text
    assert text.count("Status:") == 1


async def test_no_results_returns_widen_search_hint(fake_find):
    fake_find(result=[])

    text = await call_find(**BEMIDJI)

    assert "No VA facilities found" in text
    assert "radius" in text


async def test_facilities_error_becomes_tool_error(fake_find):
    fake_find(error=FacilitiesError("The VA Facilities API rate limit was reached."))

    with pytest.raises(ToolError, match="rate limit was reached"):
        await call_find(**BEMIDJI)


@pytest.mark.parametrize("latitude", [91, -91], ids=["above", "below"])
async def test_latitude_out_of_range_is_rejected_before_calling_api(fake_find, latitude):
    fake = fake_find(result=[BEMIDJI_CLINIC])

    with pytest.raises(ToolError):
        await call_find(latitude=latitude, longitude=-94.88)
    assert fake.calls == []


@pytest.mark.parametrize("longitude", [181, -181], ids=["above", "below"])
async def test_longitude_out_of_range_is_rejected_before_calling_api(fake_find, longitude):
    fake = fake_find(result=[BEMIDJI_CLINIC])

    with pytest.raises(ToolError):
        await call_find(latitude=47.47, longitude=longitude)
    assert fake.calls == []


@pytest.mark.parametrize(
    "radius_miles",
    [0, -5, float("inf"), float("nan")],
    ids=["zero", "negative", "infinite", "nan"],
)
async def test_radius_that_is_not_a_positive_finite_number_is_rejected(fake_find, radius_miles):
    fake = fake_find(result=[BEMIDJI_CLINIC])

    with pytest.raises(ToolError):
        await call_find(**BEMIDJI, radius_miles=radius_miles)
    assert fake.calls == []


async def test_missing_key_becomes_tool_error_without_calling_api(fake_find, monkeypatch):
    fake = fake_find(result=[BEMIDJI_CLINIC])

    def missing_key() -> str:
        raise server.ConfigError("VA_API_KEY is not set. Copy .env.example to .env.")

    # Patched rather than unsetting the variable, so the developer's real .env isn't read.
    monkeypatch.setattr(server, "load_api_key", missing_key)

    with pytest.raises(ToolError, match="VA_API_KEY is not set"):
        await call_find(**BEMIDJI)
    assert fake.calls == []


async def test_unknown_facility_type_is_rejected(fake_find):
    fake = fake_find(result=[BEMIDJI_CLINIC])

    with pytest.raises(ToolError):
        await call_find(**BEMIDJI, facility_type="hospital")
    assert fake.calls == []


async def test_limit_above_max_is_rejected(fake_find):
    fake = fake_find(result=[BEMIDJI_CLINIC])

    with pytest.raises(ToolError):
        await call_find(**BEMIDJI, limit=server.MAX_FACILITY_LIMIT + 1)
    assert fake.calls == []


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            {"facility_type": "health", "service": "mentalHealth", "radius_miles": 25, "limit": 3},
            {"facility_type": "health", "service": "mentalHealth", "radius_miles": 25, "limit": 3},
        ),
        (
            {},
            {"facility_type": None, "service": None, "radius_miles": None, "limit": 5},
        ),
    ],
    ids=["with-filters", "defaults"],
)
async def test_passes_filters_through_to_client(fake_find, arguments, expected):
    fake = fake_find(result=[BEMIDJI_CLINIC])

    await call_find(**BEMIDJI, **arguments)

    assert fake.calls == [{**BEMIDJI, "api_key": FAKE_KEY, **expected}]


async def test_tool_is_listed_with_docstring():
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}

    tool = tools["find_va_facilities"]
    assert "geocode_address" in tool.description
    assert "mentalHealth" in tool.description
    properties = tool.input_schema["properties"]
    assert {"latitude", "longitude", "facility_type", "service", "radius_miles", "limit"} <= set(
        properties
    )


def test_main_exits_with_stderr_message_and_no_stdout_when_key_missing(monkeypatch, capsys):
    def missing_key() -> str:
        raise server.ConfigError("VA_API_KEY is not set. Copy .env.example to .env.")

    def run_must_not_be_called() -> None:
        raise AssertionError("server started without a key")

    monkeypatch.setattr(server, "load_api_key", missing_key)
    monkeypatch.setattr(server.mcp, "run", run_must_not_be_called)

    with pytest.raises(SystemExit) as exit_info:
        server.main()

    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert "VA_API_KEY is not set" in captured.err
    assert captured.out == ""
