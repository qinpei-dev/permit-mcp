"""A separate, deterministic, read-only MCP server used as the upstream."""

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("PermitMCP sample upstream")
SAMPLES = {"greeting": "Hello from upstream MCP", "farewell": "Goodbye from upstream MCP"}


@mcp.tool()
def read_sample(sample_id: str) -> str:
    """Read one fixed sample by its identifier."""
    return SAMPLES[sample_id]


if __name__ == "__main__":
    mcp.run(transport="stdio")
