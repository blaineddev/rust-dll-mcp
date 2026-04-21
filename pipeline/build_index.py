import sqlite3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline.parse_cs import parse_cs_file, extract_hook_calls


# Namespaces that appear in decompiled output as transitive dependencies.
# These pollute find_type results and are never useful for Rust game modding.
EXCLUDED_NAMESPACE_PREFIXES = (
	"Microsoft.CodeAnalysis",
	"System.Runtime.CompilerServices",
	"System.Reflection",
	"System.Diagnostics.CodeAnalysis",
	"System.ComponentModel",
	"<PrivateImplementationDetails>",
	"Internal.Runtime",
	"System.Numerics",
	"System.Buffers",
	"System.Memory",
	"System.Threading.Tasks.Sources",
)


def _is_excluded_type(parsed_type) -> bool:
	"""Return True if a parsed type belongs to a noise namespace."""
	ns = parsed_type.namespace
	fqn = parsed_type.fully_qualified_name
	if any(ns.startswith(prefix) or fqn.startswith(prefix) for prefix in EXCLUDED_NAMESPACE_PREFIXES):
		return True
	# Compiler-generated types
	if "<PrivateImplementationDetails>" in fqn or fqn.startswith("<"):
		return True
	return False


def _assembly_source(assembly_name: str) -> str:
	name_lower = assembly_name.lower()
	if name_lower.startswith("oxide"):
		return "oxide"
	if name_lower.startswith("harmony") or name_lower.startswith("0harmony"):
		return "harmony"
	if name_lower.startswith("facepunch") or name_lower.startswith("rust."):
		return "facepunch"
	return "rust"


def index_cs_file(
	connection: sqlite3.Connection,
	cs_file: Path,
	source: str | None = None,
) -> int:
	"""Parse a .cs file and insert all types and members. Returns the assembly row id."""
	assembly_name = cs_file.stem
	resolved_source = source or _assembly_source(assembly_name)

	cursor = connection.execute(
		"INSERT INTO assemblies (name, source) VALUES (?, ?)",
		(assembly_name, resolved_source),
	)
	assembly_id = cursor.lastrowid

	source_text = cs_file.read_text(encoding="utf-8", errors="replace")
	parsed_types = parse_cs_file(source_text)

	fqn_to_id: dict[str, int] = {}

	# Filter out noise namespaces (Microsoft.CodeAnalysis, compiler internals, etc.)
	parsed_types = [t for t in parsed_types if not _is_excluded_type(t)]

	for parsed_type in parsed_types:
		parent_id = fqn_to_id.get(parsed_type.parent_name) if parsed_type.parent_name else None

		cursor = connection.execute(
			"""
			INSERT INTO types (
				assembly_id, namespace, name, fully_qualified_name,
				kind, access_modifier, source_code, base_type, interfaces,
				parent_type_id, is_static, is_abstract, is_sealed, doc_comment
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			""",
			(
				assembly_id,
				parsed_type.namespace,
				parsed_type.name,
				parsed_type.fully_qualified_name,
				parsed_type.kind,
				parsed_type.access_modifier,
				parsed_type.source_code,
				parsed_type.base_type,
				json.dumps(parsed_type.interfaces),
				parent_id,
				int(parsed_type.is_static),
				int(parsed_type.is_abstract),
				int(parsed_type.is_sealed),
				parsed_type.doc_comment,
			),
		)
		type_id = cursor.lastrowid
		fqn_to_id[parsed_type.fully_qualified_name] = type_id

		for member in parsed_type.members:
			connection.execute(
				"""
				INSERT INTO members (
					type_id, name, kind, return_type, parameters,
					access_modifier, attributes, source_code,
					is_static, is_abstract, is_override, is_virtual, doc_comment
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				""",
				(
					type_id,
					member.name,
					member.kind,
					member.return_type,
					json.dumps(member.parameters),
					member.access_modifier,
					json.dumps(member.attributes),
					member.source_code,
					int(member.is_static),
					int(member.is_abstract),
					int(member.is_override),
					int(member.is_virtual),
					member.doc_comment,
				),
			)

	# Extract Interface.CallHook/Call patterns and store in hooks table
	hook_calls = extract_hook_calls(parsed_types)
	for hook in hook_calls:
		connection.execute(
			"""
			INSERT INTO hooks (name, calling_type_fqn, calling_method, parameters, source_context, assembly_id)
			VALUES (?, ?, ?, ?, ?, ?)
			""",
			(
				hook.hook_name,
				hook.calling_type_fqn,
				hook.calling_method,
				hook.args_snippet,
				None,
				assembly_id,
			),
		)

	connection.commit()
	return assembly_id


def populate_fts(connection: sqlite3.Connection) -> None:
	"""Rebuild FTS5 virtual tables from the main tables."""
	connection.execute("INSERT INTO types_fts(types_fts) VALUES('rebuild')")
	connection.execute("INSERT INTO members_fts(members_fts) VALUES('rebuild')")
	connection.commit()


def write_wipe_metadata(
	connection: sqlite3.Connection,
	build_id: str,
	wipe_date: str,
	previous_build_id: str | None = None,
) -> None:
	connection.execute("DELETE FROM wipe_metadata")
	connection.execute(
		"INSERT INTO wipe_metadata (build_id, wipe_date, previous_build_id, indexed_at) VALUES (?, ?, ?, ?)",
		(build_id, wipe_date, previous_build_id, datetime.now(timezone.utc).isoformat()),
	)
	connection.commit()


def build_index(
	source_dir: Path,
	db_path: Path,
	build_id: str,
	wipe_date: str,
	previous_build_id: str | None = None,
) -> None:
	"""Full pipeline: walk source_dir .cs files → populate db_path."""
	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row

	from rust_dll_mcp.db import create_schema
	create_schema(connection)

	cs_files = list(source_dir.rglob("*.cs"))
	print(f"Indexing {len(cs_files)} .cs files into {db_path}", flush=True)

	for cs_file in cs_files:
		try:
			index_cs_file(connection, cs_file)
			print(f"  indexed {cs_file.name}", flush=True)
		except Exception as error:
			print(f"  WARNING: failed to index {cs_file.name}: {error}", file=sys.stderr, flush=True)

	populate_fts(connection)
	write_wipe_metadata(connection, build_id, wipe_date, previous_build_id)
	connection.close()
	print(f"Done. Database written to {db_path}", flush=True)


if __name__ == "__main__":
	import argparse

	argument_parser = argparse.ArgumentParser(description="Build SQLite index from decompiled .cs files")
	argument_parser.add_argument("source_dir", type=Path)
	argument_parser.add_argument("db_path", type=Path)
	argument_parser.add_argument("--build-id", required=True)
	argument_parser.add_argument("--wipe-date", required=True)
	argument_parser.add_argument("--previous-build-id")
	args = argument_parser.parse_args()

	build_index(args.source_dir, args.db_path, args.build_id, args.wipe_date, args.previous_build_id)
