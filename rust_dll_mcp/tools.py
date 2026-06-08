import json
import re
import sqlite3
from pathlib import Path

from rust_dll_mcp.db import (
	query_find_type,
	query_get_type_members,
	query_type_header,
	query_inheritance_summary,
	query_member_sources,
	query_get_method_source,
	query_search_usages,
	query_get_hook_signature,
	query_diff_since_last_wipe,
	query_find_implementations,
)
from rust_dll_mcp.serialize import slim_member


async def tool_find_type(
	connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection | None,
	name: str,
	source: str | None = None,
) -> list[dict]:
	rows = query_find_type(connection, name, source)
	return [
		{
			"fully_qualified_name": row["fully_qualified_name"],
			"name": row["name"],
			"kind": row["kind"],
			"assembly": row["assembly_name"],
			"source": row["source"],
		}
		for row in rows
	]


async def tool_get_type_members(
	connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection | None,
	fully_qualified_name: str,
	assembly_name: str | None = None,
) -> dict:
	rows = query_get_type_members(connection, fully_qualified_name, assembly_name)
	base_type, interfaces, source = query_type_header(connection, fully_qualified_name, assembly_name)
	summary, unresolved = query_inheritance_summary(connection, fully_qualified_name)

	result: dict = {"fully_qualified_name": fully_qualified_name}
	if base_type:
		result["base_type"] = base_type
	if interfaces:
		result["interfaces"] = interfaces
	if source:
		result["source"] = source
	result["members"] = [slim_member(row) for row in rows]
	if summary:
		total = sum(entry["member_count"] for entry in summary)
		result["inherited_summary"] = summary
		result["hint"] = (
			f"{total} inherited members across {len(summary)} base types not shown. "
			f"Call get_type_members on a specific base type "
			f"(e.g. {summary[0]['declaring_type']}) to see its members."
		)
	if unresolved:
		result["unresolved_bases"] = unresolved
	return result


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
	source: str | None = None,
) -> list[dict]:
	rows = query_search_usages(connection, symbol, source)
	return [
		{
			"type_fqn": row["type_fqn"],
			"member_name": row["name"],
			"kind": row["kind"],
			"source": row["source"],
		}
		for row in rows
	]


async def tool_search_source(
	connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection | None,
	pattern: str,
	source: str | None = None,
	limit: int = 50,
) -> list[dict] | str:
	try:
		compiled = re.compile(pattern)
	except re.error as error:
		return f"Invalid regex pattern: {error}"

	limit = max(1, min(int(limit), 200))
	results: list[dict] = []
	for row in query_member_sources(connection, source):
		code = row["source_code"] or ""
		if not compiled.search(code):
			continue
		for line_number, line in enumerate(code.split("\n"), start=1):
			if compiled.search(line):
				results.append({
					"type_fqn": row["type_fqn"],
					"member_name": row["name"],
					"kind": row["kind"],
					"source": row["source"],
					"line_number": line_number,
					"line": line.strip(),
				})
				if len(results) >= limit:
					return results
	return results


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
