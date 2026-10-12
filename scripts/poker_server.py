"""Launch the existing server against an isolated database, optionally changing one description.

Run with poker-analytics' interpreter, since its installed MCP SDK can differ from the client.
"""

import argparse
import json
from pathlib import Path

from poker_analytics import mcp_server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--description", type=Path)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("database must be an existing isolated fixture copy")
    mcp_server.DB_PATH = args.database.resolve()
    if args.description:
        override = json.loads(args.description.read_text())
        tool = mcp_server.mcp._tool_manager.get_tool(override["tool"])
        if tool is None:
            parser.error("description override targets an unknown tool")
        tool.description = override["description"]
    if args.transport == "stdio":
        mcp_server.mcp.run(transport="stdio")
    else:
        mcp_server.mcp.run(transport="streamable-http", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
