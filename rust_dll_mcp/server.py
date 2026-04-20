import json
import sqlite3
import sys
from pathlib import Path

import platformdirs
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from rust_dll_mcp.updater import ensure_current_db, ensure_previous_db
from rust_dll_mcp.tools import (
	tool_find_type,
	tool_get_type_members,
	tool_get_method_source,
	tool_search_usages,
	tool_get_hook_signature,
	tool_diff_since_last_wipe,
	tool_find_implementations,
)


def _open_connection(db_path: Path) -> sqlite3.Connection:
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	return connection


async def run() -> None:
	cache_dir = Path(platformdirs.user_cache_dir("rust-dll-mcp"))

	print("rust-dll-mcp: checking for updates...", file=sys.stderr, flush=True)
	current_db_path = await ensure_current_db(cache_dir)
	current_connection = _open_connection(current_db_path)

	previous_db_path = await ensure_previous_db(cache_dir)
	previous_connection = _open_connection(previous_db_path) if previous_db_path else None

	app = Server("rust-dll-mcp")

	@app.list_tools()
	async def list_tools() -> list[types.Tool]:
		return [
			types.Tool(
				name="find_type",
				description="Fuzzy search for a class, struct, or enum by name across all Rust DLLs.",
				inputSchema={
					"type": "object",
					"properties": {
						"name": {"type": "string", "description": "Type name to search for"},
					},
					"required": ["name"],
				},
			),
			types.Tool(
				name="get_type_members",
				description="List all methods, fields, properties, and events for a type.",
				inputSchema={
					"type": "object",
					"properties": {
						"fully_qualified_name": {"type": "string", "description": "Fully qualified type name, e.g. Rust.PlayerInventory"},
					},
					"required": ["fully_qualified_name"],
				},
			),
			types.Tool(
				name="get_method_source",
				description="Return the decompiled C# source for a specific method.",
				inputSchema={
					"type": "object",
					"properties": {
						"type": {"type": "string", "description": "Fully qualified type name"},
						"method": {"type": "string", "description": "Method name"},
					},
					"required": ["type", "method"],
				},
			),
			types.Tool(
				name="search_usages",
				description="Find all members whose decompiled source references a given symbol.",
				inputSchema={
					"type": "object",
					"properties": {
						"symbol": {"type": "string", "description": "Symbol name to search for"},
					},
					"required": ["symbol"],
				},
			),
			types.Tool(
				name="get_hook_signature",
				description="Return the Oxide hook method signature and parameters for a named hook.",
				inputSchema={
					"type": "object",
					"properties": {
						"hook_name": {"type": "string", "description": "Oxide hook name, e.g. OnPlayerDeath"},
					},
					"required": ["hook_name"],
				},
			),
			types.Tool(
				name="diff_since_last_wipe",
				description="Compare a type's members between the current and previous wipe database.",
				inputSchema={
					"type": "object",
					"properties": {
						"type": {"type": "string", "description": "Fully qualified type name"},
					},
					"required": ["type"],
				},
			),
			types.Tool(
				name="find_implementations",
				description="Find all types that extend a base class or implement an interface.",
				inputSchema={
					"type": "object",
					"properties": {
						"type_name": {
							"type": "string",
							"description": "Base class or interface name, e.g. BaseEntity or IPlayer",
						},
					},
					"required": ["type_name"],
				},
			),
		]

	@app.call_tool()
	async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
		if name == "find_type":
			result = await tool_find_type(current_connection, previous_connection, arguments["name"])
		elif name == "get_type_members":
			result = await tool_get_type_members(current_connection, previous_connection, arguments["fully_qualified_name"])
		elif name == "get_method_source":
			result = await tool_get_method_source(current_connection, previous_connection, arguments["type"], arguments["method"])
		elif name == "search_usages":
			result = await tool_search_usages(current_connection, previous_connection, arguments["symbol"])
		elif name == "get_hook_signature":
			result = await tool_get_hook_signature(current_connection, previous_connection, arguments["hook_name"])
		elif name == "diff_since_last_wipe":
			result = await tool_diff_since_last_wipe(current_connection, previous_connection, arguments["type"])
		elif name == "find_implementations":
			result = await tool_find_implementations(current_connection, previous_connection, arguments["type_name"])
		else:
			result = f"Unknown tool: {name}"

		return [types.TextContent(type="text", text=json.dumps(result, indent=2) if not isinstance(result, str) else result)]

	print("rust-dll-mcp: ready.", file=sys.stderr, flush=True)
	async with stdio_server() as (read_stream, write_stream):
		await app.run(read_stream, write_stream, app.create_initialization_options())

	current_connection.close()
	if previous_connection:
		previous_connection.close()
