"""The MCP server: exposes tools an AI agent can call."""

import os
import sys
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from .census import GeocodeError, geocode
from .config import API_KEY_VAR, ConfigError, load_api_key
from .va_facilities import FacilitiesError, FacilitySummary, find_facilities

mcp = MCPServer(
    "va-resources",
    instructions="Public VA facility and form data. Never ask users for personal or health information.",
)

MAX_MATCHES = 3  # keep responses small so they don't eat the agent's context
DEFAULT_FACILITY_LIMIT = 5
MAX_FACILITY_LIMIT = 10
NORMAL_STATUS = "NORMAL"


@mcp.tool()
async def geocode_address(address: str) -> str:
    """Convert a U.S. street address into latitude and longitude.

    Use this before searching for nearby VA facilities. Include the city and
    state, e.g. "403 4th St NW, Bemidji, MN 56601".
    """
    if not address.strip():
        return "Please provide a street address including city and state."
    try:
        matches = await geocode(address)
    except GeocodeError as exc:
        return f"Error: {exc}"
    if not matches:
        return (
            f"No match found for '{address}'. Check the spelling, or include the "
            "street number, city, state and ZIP code."
        )
    lines = [
        f"{m.matched_address} -> latitude {m.latitude:.5f}, longitude {m.longitude:.5f}"
        for m in matches[:MAX_MATCHES]
    ]
    return "\n".join(lines)


@mcp.tool()
async def find_va_facilities(
    latitude: Annotated[float, Field(ge=-90, le=90)],
    longitude: Annotated[float, Field(ge=-180, le=180)],
    facility_type: Literal["health", "benefits", "cemetery", "vet_center"] | None = None,
    service: str | None = None,
    radius_miles: Annotated[float, Field(gt=0)] | None = None,
    limit: Annotated[int, Field(ge=1, le=MAX_FACILITY_LIMIT)] = DEFAULT_FACILITY_LIMIT,
) -> str:
    """Find VA facilities near a latitude and longitude, nearest first.

    Call geocode_address first to turn the veteran's address into coordinates.

    Filters (all optional):
    - facility_type: "health" (medical centers and clinics), "benefits" (regional
      benefit offices), "cemetery" (national cemeteries) or "vet_center"
      (readjustment counseling).
    - service: one VA service ID. Common ones: primaryCare, mentalHealth, ptsd,
      urgentCare, emergencyCare, dental, womensHealth, pharmacy, audiology,
      optometry, disabilityClaimAssistance, applyingForBenefits. An unknown ID is
      rejected with a message from the VA API.
    - radius_miles: only return facilities within this many miles.
    - limit: how many facilities to return, 1 to 10 (default 5).

    Distances are in miles. Each result includes the facility ID.
    """
    try:
        facilities = await find_facilities(
            latitude,
            longitude,
            api_key=os.environ[API_KEY_VAR],
            facility_type=facility_type,
            service=service,
            radius_miles=radius_miles,
            limit=limit,
        )
    except FacilitiesError as exc:
        raise ToolError(str(exc)) from exc
    if not facilities:
        return (
            "No VA facilities found for that search. Try a larger radius_miles, "
            "or drop the facility_type or service filter."
        )
    return "\n\n".join(format_facility(f) for f in facilities)


def format_facility(f: FacilitySummary) -> str:
    """One short block of text per facility, skipping fields the API didn't give."""
    heading = f"{f.name} ({f.classification})" if f.classification else f.name
    lines = [heading]
    if f.address:
        lines.append(f.address)
    if f.phone:
        lines.append(f"Phone: {f.phone}")
    if f.distance_miles is not None:
        lines.append(f"Distance: {f.distance_miles:.1f} miles")
    lines.append(f"ID: {f.id}")
    if f.operating_status != NORMAL_STATUS:
        lines.append(f"Status: {f.operating_status}")
    return "\n".join(lines)


def main() -> None:
    # stdout carries the MCP protocol in stdio transport, so startup errors go to stderr.
    try:
        load_api_key()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    mcp.run()  # stdio transport: Claude Desktop / Claude Code launch it as a subprocess


if __name__ == "__main__":
    main()
