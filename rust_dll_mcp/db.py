import sqlite3


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


def query_find_type(connection: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
	"""Fuzzy search for types by name. FTS5 first, LIKE fallback."""
	fts_rows = connection.execute(
		"""
		SELECT t.id, t.name, t.fully_qualified_name, t.kind, t.namespace, a.name AS assembly_name
		FROM types_fts
		JOIN types t ON types_fts.rowid = t.id
		LEFT JOIN assemblies a ON t.assembly_id = a.id
		WHERE types_fts MATCH ?
		LIMIT 10
		""",
		(name,),
	).fetchall()

	if fts_rows:
		return fts_rows

	return connection.execute(
		"""
		SELECT t.id, t.name, t.fully_qualified_name, t.kind, t.namespace, a.name AS assembly_name
		FROM types t
		LEFT JOIN assemblies a ON t.assembly_id = a.id
		WHERE t.name LIKE ?
		LIMIT 10
		""",
		(f"%{name}%",),
	).fetchall()


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


def query_search_usages(connection: sqlite3.Connection, symbol: str) -> list[sqlite3.Row]:
	return connection.execute(
		"""
		SELECT m.id, m.name, m.kind, t.fully_qualified_name AS type_fqn
		FROM members_fts
		JOIN members m ON members_fts.rowid = m.id
		JOIN types t ON m.type_id = t.id
		WHERE members_fts MATCH ?
		LIMIT 50
		""",
		(symbol,),
	).fetchall()


def query_get_hook_signature(connection: sqlite3.Connection, hook_name: str) -> list[sqlite3.Row]:
	return connection.execute(
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

	added = [dict(row) for name, row in current_members.items() if name not in previous_members]
	removed = [dict(row) for name, row in previous_members.items() if name not in current_members]
	changed = [
		{"name": name, "current": dict(current_members[name]), "previous": dict(previous_members[name])}
		for name in current_members
		if name in previous_members
		and current_members[name]["source_code"] != previous_members[name]["source_code"]
	]

	return {"added": added, "removed": removed, "changed": changed}
