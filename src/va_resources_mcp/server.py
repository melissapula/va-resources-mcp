"""The MCP server: exposes tools an AI agent can call."""

from mcp.server.mcpserver import MCPServer

from .census import GeocodeError, geocode

mcp = MCPServer(
    "va-resources",
    instructions="Public VA facility and form data. Never ask users for personal or health information.",
)

MAX_MATCHES = 3  # keep responses small so they don't eat the agent's context


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


def main() -> None:
    mcp.run()  # stdio transport: Claude Desktop / Claude Code launch it as a subprocess


if __name__ == "__main__":
    main()
