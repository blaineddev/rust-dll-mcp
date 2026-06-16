import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import platformdirs
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from rust_dll_mcp.updater import sync_databases, CURRENT_DB_FILE, PREVIOUS_DB_FILE
from rust_dll_mcp.serialize import compact_json
from rust_dll_mcp.tools import (
	tool_find_type,
	tool_get_type_members,
	tool_get_method_source,
	tool_search_usages,
	tool_search_source,
	tool_get_hook_signature,
	tool_diff_since_last_wipe,
	tool_find_implementations,
)


def _open_connection(db_path: Path) -> sqlite3.Connection:
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	return connection


class DbState:
	"""Holds the live database connections, swapped in once the background load finishes."""

	def __init__(self) -> None:
		self.current: sqlite3.Connection | None = None
		self.previous: sqlite3.Connection | None = None
		self.status = "updating"
		self.message = "rust-dll-mcp is downloading the latest wipe database; please retry in a moment."


async def _load_databases(state: DbState, cache_dir: Path) -> None:
	"""Sync and open the databases, then publish them on the shared state."""
	try:
		current_path, previous_path = await sync_databases(cache_dir)
	except Exception as error:
		# Network/manifest failure: fall back to a cached DB if one exists, rather
		# than leaving the server permanently unusable when GitHub is unreachable.
		cached_current = cache_dir / CURRENT_DB_FILE
		if cached_current.exists():
			print(f"rust-dll-mcp: update check failed ({error}); using cached database.", file=sys.stderr, flush=True)
			current_path = cached_current
			cached_previous = cache_dir / PREVIOUS_DB_FILE
			previous_path = cached_previous if cached_previous.exists() else None
		else:
			state.status = "error"
			state.message = f"rust-dll-mcp: database unavailable ({error})."
			print(state.message, file=sys.stderr, flush=True)
			return

	state.previous = _open_connection(previous_path) if previous_path else None
	state.current = _open_connection(current_path)
	state.status = "ready"
	print("rust-dll-mcp: database ready.", file=sys.stderr, flush=True)


async def run() -> None:
	cache_dir = Path(platformdirs.user_cache_dir("rust-dll-mcp"))
	state = DbState()

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
						"source": {"type": "string", "description": "Optional source filter: rust, oxide, facepunch, or community"},
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
						"assembly_name": {"type": "string", "description": "Filter by assembly name, e.g. Assembly-CSharp.decompiled. Use when find_type returns multiple matches with the same name."},
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
						"source": {"type": "string", "description": "Optional source filter: rust, oxide, facepunch, or community"},
					},
					"required": ["symbol"],
				},
			),
			types.Tool(
				name="search_source",
				description="Regex search over decompiled source bodies. Returns grep-style per-line matches. Use for string literals (e.g. JSON keys) and arbitrary text that search_usages (symbol-only) misses.",
				inputSchema={
					"type": "object",
					"properties": {
						"pattern": {"type": "string", "description": "Python regular expression to match against source lines"},
						"source": {"type": "string", "description": "Optional source filter: rust, oxide, facepunch, or community"},
						"limit": {"type": "integer", "description": "Max matching lines to return (default 50, max 200)"},
					},
					"required": ["pattern"],
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
		if state.current is None:
			return [types.TextContent(type="text", text=compact_json({"status": state.status, "message": state.message}))]

		current_connection = state.current
		previous_connection = state.previous

		match name:
			case "find_type":
				result = await tool_find_type(current_connection, previous_connection, arguments["name"], arguments.get("source"))
			case "get_type_members":
				result = await tool_get_type_members(current_connection, previous_connection, arguments["fully_qualified_name"], arguments.get("assembly_name"))
			case "get_method_source":
				result = await tool_get_method_source(current_connection, previous_connection, arguments["type"], arguments["method"])
			case "search_usages":
				result = await tool_search_usages(current_connection, previous_connection, arguments["symbol"], arguments.get("source"))
			case "search_source":
				result = await tool_search_source(current_connection, previous_connection, arguments["pattern"], arguments.get("source"), arguments.get("limit", 50))
			case "get_hook_signature":
				result = await tool_get_hook_signature(current_connection, previous_connection, arguments["hook_name"])
			case "diff_since_last_wipe":
				result = await tool_diff_since_last_wipe(current_connection, previous_connection, arguments["type"])
			case "find_implementations":
				result = await tool_find_implementations(current_connection, previous_connection, arguments["type_name"])
			case _:
				result = f"Unknown tool: {name}"

		return [types.TextContent(type="text", text=result if isinstance(result, str) else compact_json(result))]

	print("rust-dll-mcp: starting; database loads in the background...", file=sys.stderr, flush=True)
	loader = asyncio.create_task(_load_databases(state, cache_dir))
	try:
		async with stdio_server() as (read_stream, write_stream):
			await app.run(read_stream, write_stream, app.create_initialization_options())
	finally:
		loader.cancel()
		if state.current:
			state.current.close()
		if state.previous:
			state.previous.close()
