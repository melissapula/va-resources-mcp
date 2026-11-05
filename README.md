# VA Resources MCP Server

An [MCP](https://modelcontextprotocol.io) server that lets AI agents help veterans find VA facilities and forms using public federal data.

![Demo: geocoding a Bemidji, MN address in the MCP Inspector, then listing the five closest VA health facilities with mental health care, nearest first](docs/demo.gif)

## Tools

| Tool | What it does | Data source |
| --- | --- | --- |
| `geocode_address` | Address to latitude/longitude | U.S. Census Geocoder (no key) |
| `find_va_facilities` | Nearby VA facilities by type or service, nearest first | VA Lighthouse Facilities API (sandbox, key required) |
| `get_facility_details` | *(planned)* Hours, phone, services, wait times | VA Lighthouse Facilities API |
| `search_va_forms` | *(planned)* Find a VA form and its current version | VA Lighthouse Forms API |

This server handles public data only. It never asks for or stores veterans' personal information.

## Set up your API key

The server needs a VA Lighthouse sandbox key and won't start without one.

1. Request a free sandbox key for the VA Facilities API at developer.va.gov.
2. Copy `.env.example` to `.env` in this folder and put the key after `VA_API_KEY=`.

`.env` is git-ignored. A `VA_API_KEY` already set in the environment (for example in an MCP client's `env` config) takes priority over `.env`.

## Run it

```
uv sync
uv run pytest
uv run va-resources-mcp
```

To try the tools by hand in a browser, use the MCP Inspector:

```
npx @modelcontextprotocol/inspector uv run va-resources-mcp
```

## Connect it to Claude Code

From this folder:

```
claude mcp add va-resources -- uv --directory C:\Users\missa\repositories\va-resources-mcp run va-resources-mcp
```

Then ask Claude: "Geocode 403 4th St NW, Bemidji, MN 56601."

Or chain both tools: "Find VA clinics with mental health care within 50 miles of 403 4th St NW, Bemidji, MN 56601." Claude geocodes the address, then calls `find_va_facilities` with the coordinates.
