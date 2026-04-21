import json
import sqlite3
from pathlib import Path

from rust_dll_mcp.db import (
	query_find_type,
	query_get_type_members,
	query_get_method_source,
	query_search_usages,
	query_get_hook_signature,
	query_diff_since_last_wipe,
	query_find_implementations,
)


async def tool_find_type(
	connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection | None,
	name: str,
) -> list[dict]:
	rows = query_find_type(connection, name)
	return [
		{
			"fully_qualified_name": row["fully_qualified_name"],
			"name": row["name"],
			"kind": row["kind"],
			"namespace": row["namespace"],
			"assembly": row["assembly_name"],
		}
		for row in rows
	]


async def tool_get_type_members(
	connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection | None,
	fully_qualified_name: str,
	assembly_name: str | None = None,
) -> list[dict]:
	rows = query_get_type_members(connection, fully_qualified_name, assembly_name)
	return [
		{
			"name": row["name"],
			"kind": row["kind"],
			"return_type": row["return_type"],
			"parameters": json.loads(row["parameters"] or "[]"),
			"access_modifier": row["access_modifier"],
			"attributes": json.loads(row["attributes"] or "[]"),
		}
		for row in rows
	]


async def tool_get_method_source(
	connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection | None,
	type_fqn: str,
	method: str,
) -> str:
	source = query_get_method_source(connection, type_fqn, method)
	if source is None:
		return f"Method '{method}' not found on type '{type_fqn}'."
	return source


async def tool_search_usages(
	connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection | None,
	symbol: str,
) -> list[dict]:
	rows = query_search_usages(connection, symbol)
	return [
		{
			"type_fqn": row["type_fqn"],
			"member_name": row["name"],
			"kind": row["kind"],
		}
		for row in rows
	]


async def tool_get_hook_signature(
	connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection | None,
	hook_name: str,
) -> list[dict]:
	rows = query_get_hook_signature(connection, hook_name)
	if not rows:
		return [{"message": f"Hook '{hook_name}' not found in Oxide assemblies or game call sites."}]
	results = []
	for row in rows:
		# row may be a sqlite3.Row or a plain dict (from hook call-site conversion)
		if isinstance(row, dict):
			results.append({
				"name": row["name"],
				"return_type": row["return_type"],
				"parameters": json.loads(row["parameters"] or "[]"),
				"type_fqn": row["type_fqn"],
				"source": "call_site",
			})
		else:
			results.append({
				"name": row["name"],
				"return_type": row["return_type"],
				"parameters": json.loads(row["parameters"] or "[]"),
				"type_fqn": row["type_fqn"],
				"source": "oxide",
			})
	return results


async def tool_find_implementations(
	connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection | None,
	type_name: str,
) -> list[dict]:
	rows = query_find_implementations(connection, type_name)
	return [
		{
			"fully_qualified_name": row["fully_qualified_name"],
			"kind": row["kind"],
			"assembly_name": row["assembly_name"],
			"match_reason": row["match_reason"],
		}
		for row in rows
	]


async def tool_diff_since_last_wipe(
	connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection | None,
	type_fqn: str,
) -> dict | str:
	if previous_connection is None:
		return "Previous wipe database not available."
	return query_diff_since_last_wipe(connection, previous_connection, type_fqn)
