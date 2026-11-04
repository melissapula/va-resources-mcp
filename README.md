# VA Resources MCP Server

An [MCP](https://modelcontextprotocol.io) server that lets AI agents help veterans find VA facilities and forms using public federal data.

## Tools

| Tool | What it does | Data source |
| --- | --- | --- |
| `geocode_address` | Address to latitude/longitude | U.S. Census Geocoder (no key) |
| `find_va_facilities` | *(planned)* Nearby VA facilities by service | VA Lighthouse Facilities API |
| `get_facility_details` | *(planned)* Hours, phone, services, wait times | VA Lighthouse Facilities API |
| `search_va_forms` | *(planned)* Find a VA form and its current version | VA Lighthouse Forms API |

This server handles public data only. It never asks for or stores veterans' personal information.

## Run it

```
uv sync
uv run pytest
uv run va-resources-mcp
```

## Connect it to Claude Code

From this folder:

```
claude mcp add va-resources -- uv --directory C:\Users\missa\repositories\va-resources-mcp run va-resources-mcp
```

Then ask Claude: "Geocode 403 4th St NW, Bemidji, MN 56601."
