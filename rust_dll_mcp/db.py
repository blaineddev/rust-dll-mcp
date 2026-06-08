import json
import sqlite3

from rust_dll_mcp.serialize import member_signature

# Noise namespaces filtered out of find_type results at query time.
# Mirrors the exclusion list in pipeline/build_index.py for existing DBs.
_EXCLUDED_FQN_PREFIXES = (
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


def _filter_noise_types(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
	"""Remove types from noise namespaces."""
	return [
		row for row in rows
		if not any(row["fully_qualified_name"].startswith(p) for p in _EXCLUDED_FQN_PREFIXES)
	]


def create_schema(connection: sqlite3.Connection) -> None:
	connection.executescript("""
		CREATE TABLE IF NOT EXISTS assemblies (
			id INTEGER PRIMARY KEY,
			name TEXT NOT NULL,
			version TEXT,
			source TEXT
		);

		CREATE TABLE IF NOT EXISTS types (
			id INTEGER PRIMARY KEY,
			assembly_id INTEGER REFERENCES assemblies(id),
			namespace TEXT,
			name TEXT NOT NULL,
			fully_qualified_name TEXT NOT NULL,
			kind TEXT,
			access_modifier TEXT,
			source_code TEXT,
			base_type TEXT,
			interfaces TEXT,
			parent_type_id INTEGER REFERENCES types(id),
			is_static INTEGER NOT NULL DEFAULT 0,
			is_abstract INTEGER NOT NULL DEFAULT 0,
			is_sealed INTEGER NOT NULL DEFAULT 0,
			doc_comment TEXT
		);

		CREATE TABLE IF NOT EXISTS members (
			id INTEGER PRIMARY KEY,
			type_id INTEGER REFERENCES types(id),
			name TEXT NOT NULL,
			kind TEXT,
			return_type TEXT,
			parameters TEXT,
			access_modifier TEXT,
			attributes TEXT,
			source_code TEXT,
			is_static INTEGER NOT NULL DEFAULT 0,
			is_abstract INTEGER NOT NULL DEFAULT 0,
			is_override INTEGER NOT NULL DEFAULT 0,
			is_virtual INTEGER NOT NULL DEFAULT 0,
			doc_comment TEXT
		);

		CREATE TABLE IF NOT EXISTS hooks (
			id INTEGER PRIMARY KEY,
			name TEXT NOT NULL,
			calling_type_fqn TEXT NOT NULL,
			calling_method TEXT NOT NULL,
			parameters TEXT,
			source_context TEXT,
			assembly_id INTEGER REFERENCES assemblies(id)
		);

		CREATE INDEX IF NOT EXISTS idx_hooks_name ON hooks(name);

		CREATE TABLE IF NOT EXISTS wipe_metadata (
			build_id TEXT NOT NULL,
			wipe_date TEXT NOT NULL,
			previous_build_id TEXT,
			indexed_at TEXT NOT NULL
		);

		CREATE VIRTUAL TABLE IF NOT EXISTS types_fts USING fts5(
			fully_qualified_name,
			source_code,
			doc_comment,
			content='types'
		);

		CREATE VIRTUAL TABLE IF NOT EXISTS members_fts USING fts5(
			name,
			source_code,
			doc_comment,
			content='members'
		);

		CREATE INDEX IF NOT EXISTS idx_types_fqn        ON types(fully_qualified_name);
		CREATE INDEX IF NOT EXISTS idx_types_name        ON types(name);
		CREATE INDEX IF NOT EXISTS idx_types_base_type   ON types(base_type);
		CREATE INDEX IF NOT EXISTS idx_types_parent      ON types(parent_type_id);
		CREATE INDEX IF NOT EXISTS idx_types_assembly    ON types(assembly_id);
		CREATE INDEX IF NOT EXISTS idx_members_type_id   ON members(type_id);
		CREATE INDEX IF NOT EXISTS idx_members_name      ON members(name);
		CREATE INDEX IF NOT EXISTS idx_assemblies_source ON assemblies(source);
	""")
	connection.commit()


def query_find_type(
	connection: sqlite3.Connection,
	name: str,
	source: str | None = None,
) -> list[sqlite3.Row]:
	"""Fuzzy search for types by name. FTS5 first, LIKE fallback. Optional source filter."""
	fts_sql = """
		SELECT t.id, t.name, t.fully_qualified_name, t.kind, a.name AS assembly_name, a.source AS source
		FROM types_fts
		JOIN types t ON types_fts.rowid = t.id
		LEFT JOIN assemblies a ON t.assembly_id = a.id
		WHERE types_fts MATCH ?
	"""
	if source:
		fts_rows = connection.execute(fts_sql + " AND a.source = ? LIMIT 10", (name, source)).fetchall()
	else:
		fts_rows = connection.execute(fts_sql + " LIMIT 10", (name,)).fetchall()
	if fts_rows:
		return _filter_noise_types(fts_rows)

	like_sql = """
		SELECT t.id, t.name, t.fully_qualified_name, t.kind, a.name AS assembly_name, a.source AS source
		FROM types t
		LEFT JOIN assemblies a ON t.assembly_id = a.id
		WHERE t.name LIKE ?
	"""
	if source:
		rows = connection.execute(like_sql + " AND a.source = ? LIMIT 25", (f"%{name}%", source)).fetchall()
	else:
		rows = connection.execute(like_sql + " LIMIT 25", (f"%{name}%",)).fetchall()
	return _filter_noise_types(rows)[:10]


def query_get_type_members(
	connection: sqlite3.Connection,
	fully_qualified_name: str,
	assembly_name: str | None = None,
) -> list[sqlite3.Row]:
	if assembly_name:
		return connection.execute(
			"""
			SELECT m.id, m.name, m.kind, m.return_type, m.parameters, m.access_modifier, m.attributes
			FROM members m
			JOIN types t ON m.type_id = t.id
			JOIN assemblies a ON t.assembly_id = a.id
			WHERE t.fully_qualified_name = ?
			  AND a.name = ?
			ORDER BY m.kind, m.name
			""",
			(fully_qualified_name, assembly_name),
		).fetchall()
	return connection.execute(
		"""
		SELECT m.id, m.name, m.kind, m.return_type, m.parameters, m.access_modifier, m.attributes
		FROM members m
		JOIN types t ON m.type_id = t.id
		WHERE t.fully_qualified_name = ?
		ORDER BY m.kind, m.name
		""",
		(fully_qualified_name,),
	).fetchall()


def _strip_generics(type_name: str) -> str:
	return type_name.split("<", 1)[0].strip()


def _resolve_type_fqn(connection: sqlite3.Connection, name: str) -> str | None:
	row = connection.execute(
		"SELECT fully_qualified_name FROM types WHERE fully_qualified_name = ? LIMIT 1",
		(name,),
	).fetchone()
	if row:
		return row["fully_qualified_name"]
	row = connection.execute(
		"SELECT fully_qualified_name FROM types WHERE name = ? LIMIT 1",
		(name,),
	).fetchone()
	return row["fully_qualified_name"] if row else None


def _type_base(connection: sqlite3.Connection, fully_qualified_name: str) -> str:
	"""Non-empty base_type among partial-class rows for an FQN, or ''."""
	rows = connection.execute(
		"SELECT base_type FROM types WHERE fully_qualified_name = ?",
		(fully_qualified_name,),
	).fetchall()
	for row in rows:
		if row["base_type"]:
			return row["base_type"]
	return ""


def _type_source(connection: sqlite3.Connection, fully_qualified_name: str) -> str | None:
	row = connection.execute(
		"""
		SELECT a.source FROM types t
		LEFT JOIN assemblies a ON t.assembly_id = a.id
		WHERE t.fully_qualified_name = ? LIMIT 1
		""",
		(fully_qualified_name,),
	).fetchone()
	return row["source"] if row and row["source"] else None


def _member_count(connection: sqlite3.Connection, fully_qualified_name: str) -> int:
	row = connection.execute(
		"""
		SELECT COUNT(*) AS n FROM members m
		JOIN types t ON m.type_id = t.id
		WHERE t.fully_qualified_name = ?
		""",
		(fully_qualified_name,),
	).fetchone()
	return row["n"]


def query_type_header(
	connection: sqlite3.Connection,
	fully_qualified_name: str,
	assembly_name: str | None = None,
) -> tuple[str, list[str], str | None]:
	"""Return (base_type, interfaces, source), aggregating partial-class rows."""
	if assembly_name:
		rows = connection.execute(
			"""
			SELECT t.base_type, t.interfaces, a.source FROM types t
			JOIN assemblies a ON t.assembly_id = a.id
			WHERE t.fully_qualified_name = ? AND a.name = ?
			""",
			(fully_qualified_name, assembly_name),
		).fetchall()
	else:
		rows = connection.execute(
			"""
			SELECT t.base_type, t.interfaces, a.source FROM types t
			LEFT JOIN assemblies a ON t.assembly_id = a.id
			WHERE t.fully_qualified_name = ?
			""",
			(fully_qualified_name,),
		).fetchall()
	base_type = ""
	interfaces: list[str] = []
	source: str | None = None
	for row in rows:
		if row["base_type"] and not base_type:
			base_type = row["base_type"]
		for interface in json.loads(row["interfaces"] or "[]"):
			if interface not in interfaces:
				interfaces.append(interface)
		if row["source"] and source is None:
			source = row["source"]
	return base_type, interfaces, source


def query_inheritance_summary(
	connection: sqlite3.Connection,
	fully_qualified_name: str,
) -> tuple[list[dict], list[str]]:
	"""Walk the base chain. Returns (summary, unresolved_bases)."""
	summary: list[dict] = []
	unresolved: list[str] = []
	seen = {fully_qualified_name}
	current_base = _type_base(connection, fully_qualified_name)
	while current_base:
		resolved = _resolve_type_fqn(connection, _strip_generics(current_base))
		if not resolved:
			unresolved.append(current_base)
			break
		if resolved in seen:
			break
		seen.add(resolved)
		summary.append({
			"declaring_type": resolved,
			"source": _type_source(connection, resolved),
			"member_count": _member_count(connection, resolved),
		})
		current_base = _type_base(connection, resolved)
	return summary, unresolved


def query_member_sources(
	connection: sqlite3.Connection,
	source: str | None = None,
):
	"""Iterate (type_fqn, name, kind, source, source_code) over all members, optionally one source."""
	if source:
		return connection.execute(
			"""
			SELECT t.fully_qualified_name AS type_fqn, m.name, m.kind,
			       a.source AS source, m.source_code
			FROM members m
			JOIN types t ON m.type_id = t.id
			LEFT JOIN assemblies a ON t.assembly_id = a.id
			WHERE a.source = ?
			""",
			(source,),
		)
	return connection.execute(
		"""
		SELECT t.fully_qualified_name AS type_fqn, m.name, m.kind,
		       a.source AS source, m.source_code
		FROM members m
		JOIN types t ON m.type_id = t.id
		LEFT JOIN assemblies a ON t.assembly_id = a.id
		"""
	)


def query_get_method_source(
	connection: sqlite3.Connection,
	type_fqn: str,
	method_name: str,
) -> str | None:
	row = connection.execute(
		"""
		SELECT m.source_code
		FROM members m
		JOIN types t ON m.type_id = t.id
		WHERE t.fully_qualified_name = ?
		  AND m.name = ?
		  AND m.kind IN ('method', 'constructor')
		LIMIT 1
		""",
		(type_fqn, method_name),
	).fetchone()
	return row["source_code"] if row else None


def query_search_usages(
	connection: sqlite3.Connection,
	symbol: str,
	source: str | None = None,
) -> list[sqlite3.Row]:
	sql = """
		SELECT m.id, m.name, m.kind, t.fully_qualified_name AS type_fqn, a.source AS source
		FROM members_fts
		JOIN members m ON members_fts.rowid = m.id
		JOIN types t ON m.type_id = t.id
		LEFT JOIN assemblies a ON t.assembly_id = a.id
		WHERE members_fts MATCH ?
	"""
	if source:
		return connection.execute(sql + " AND a.source = ? LIMIT 50", (symbol, source)).fetchall()
	return connection.execute(sql + " LIMIT 50", (symbol,)).fetchall()


def query_get_hook_signature(connection: sqlite3.Connection, hook_name: str) -> list[sqlite3.Row]:
	# First check Oxide assembly members (original approach)
	oxide_rows = connection.execute(
		"""
		SELECT m.name, m.return_type, m.parameters, m.attributes, t.fully_qualified_name AS type_fqn
		FROM members m
		JOIN types t ON m.type_id = t.id
		JOIN assemblies a ON t.assembly_id = a.id
		WHERE a.source = 'oxide'
		  AND (m.name = ? OR m.attributes LIKE ?)
		LIMIT 10
		""",
		(hook_name, f'%"{hook_name}"%'),
	).fetchall()

	# Also check the hooks table for Interface.CallHook/Call sites
	hook_rows = []
	try:
		hook_rows = connection.execute(
			"""
			SELECT h.name, h.calling_type_fqn, h.calling_method, h.parameters AS call_args
			FROM hooks h
			WHERE h.name = ?
			LIMIT 10
			""",
			(hook_name,),
		).fetchall()
	except sqlite3.OperationalError:
		# hooks table may not exist in older DBs
		pass

	if oxide_rows or hook_rows:
		results = list(oxide_rows)
		# Convert hook call-site rows into a compatible format
		for row in hook_rows:
			parameters_payload = [{
				"call_site": f'{row["calling_type_fqn"]}.{row["calling_method"]}',
				"args": row["call_args"] or "",
			}]
			results.append({
				"name": row["name"],
				"return_type": "object",
				"parameters": json.dumps(parameters_payload),
				"type_fqn": row["calling_type_fqn"],
			})
		return results

	return []


def query_find_implementations(connection: sqlite3.Connection, type_name: str) -> list[sqlite3.Row]:
	base_rows = connection.execute(
		"""
		SELECT t.fully_qualified_name, t.kind, a.name AS assembly_name, 'base_type' AS match_reason
		FROM types t
		LEFT JOIN assemblies a ON t.assembly_id = a.id
		WHERE t.base_type = ? OR t.base_type LIKE ?
		""",
		(type_name, f'%.{type_name}'),
	).fetchall()

	interface_rows = connection.execute(
		"""
		SELECT t.fully_qualified_name, t.kind, a.name AS assembly_name, 'interface' AS match_reason
		FROM types t
		LEFT JOIN assemblies a ON t.assembly_id = a.id
		WHERE t.interfaces LIKE ?
		""",
		(f'%"{type_name}"%',),
	).fetchall()

	seen = {}
	for row in base_rows + interface_rows:
		fqn = row['fully_qualified_name']
		if fqn not in seen:
			seen[fqn] = row
	return list(seen.values())


def query_diff_since_last_wipe(
	current_connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection,
	type_fqn: str,
) -> dict:
	"""Compare members of a type between two DB connections. Returns {added, removed, changed}."""
	def get_members(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
		rows = connection.execute(
			"""
			SELECT m.name, m.kind, m.return_type, m.parameters, m.source_code
			FROM members m
			JOIN types t ON m.type_id = t.id
			WHERE t.fully_qualified_name = ?
			""",
			(type_fqn,),
		).fetchall()
		return {row["name"]: row for row in rows}

	current_members = get_members(current_connection)
	previous_members = get_members(previous_connection)

	added = [
		{"name": row["name"], "kind": row["kind"], "signature": member_signature(row)}
		for name, row in current_members.items()
		if name not in previous_members
	]
	removed = [
		{"name": row["name"], "kind": row["kind"], "signature": member_signature(row)}
		for name, row in previous_members.items()
		if name not in current_members
	]
	changed = [
		{
			"name": name,
			"kind": current_members[name]["kind"],
			"signature": member_signature(current_members[name]),
			"source_changed": True,
		}
		for name in current_members
		if name in previous_members
		and current_members[name]["source_code"] != previous_members[name]["source_code"]
	]

	return {"added": added, "removed": removed, "changed": changed}
