# rust-dll-mcp Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `get_type_members` expose a quantified inheritance signal without ever flattening, add a regex source-search tool, index the Facepunch/Rust.Community client code, label/filter results by source, and cut token usage across every tool.

**Architecture:** A new `rust_dll_mcp/serialize.py` holds shared token-optimized serialization helpers (compact JSON, slim member dicts, signature strings). Query logic stays in `rust_dll_mcp/db.py`; tool response shaping stays in `rust_dll_mcp/tools.py`; tool registration and the global serializer live in `rust_dll_mcp/server.py`. The indexing pipeline gains a community-source ingestion path.

**Tech Stack:** Python 3.11, `sqlite3` (FTS5), `mcp` server SDK, `pytest`/`pytest-asyncio`. Tests run with `PYTHONPATH=. pytest`.

**Spec:** `docs/superpowers/specs/2026-06-08-dll-mcp-improvements-design.md`

---

## File Structure

- Create: `rust_dll_mcp/serialize.py` — `compact_json`, `param_signature`, `slim_member`, `member_signature`. One responsibility: turning DB rows and Python objects into token-optimized output.
- Modify: `rust_dll_mcp/db.py` — new query helpers for the inheritance summary, member-source iteration, source filtering, and slim diff; `source` added to `find_type`/`search_usages` selects; `namespace` dropped from `find_type`.
- Modify: `rust_dll_mcp/tools.py` — `tool_get_type_members` returns the envelope; new `tool_search_source`; `source` plumbed through `tool_find_type`/`tool_search_usages`; diff returns slim rows.
- Modify: `rust_dll_mcp/server.py` — register `search_source`; add `source`/`limit` params; switch global serialization to `compact_json`.
- Modify: `pipeline/build_index.py` — `build_index` gains `community_dir`; CLI gains `--community-dir`.
- Modify: `.github/workflows/monthly-wipe-pipeline.yml` — clone `Rust.Community`, pass `--community-dir`.
- Test: `tests/test_serialize.py` (new), `tests/test_tools.py`, `tests/test_db.py`, `tests/test_build_index.py`.

---

## Task 1: Serialization helpers

**Files:**
- Create: `rust_dll_mcp/serialize.py`
- Test: `tests/test_serialize.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_serialize.py
import json
import sqlite3
import pytest
from rust_dll_mcp.serialize import (
	compact_json,
	param_signature,
	slim_member,
	member_signature,
)


def _row(**kwargs):
	"""Build a sqlite3.Row with the member columns slim_member/member_signature read."""
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	cols = ["name", "kind", "return_type", "parameters", "access_modifier", "attributes"]
	defaults = {"name": "x", "kind": "method", "return_type": "", "parameters": "[]",
	            "access_modifier": "public", "attributes": "[]"}
	defaults.update(kwargs)
	placeholders = ",".join("?" for _ in cols)
	connection.execute(f"CREATE TABLE m ({','.join(cols)})")
	connection.execute(f"INSERT INTO m VALUES ({placeholders})", [defaults[c] for c in cols])
	return connection.execute("SELECT * FROM m").fetchone()


def test_compact_json_has_no_whitespace():
	assert compact_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'


def test_param_signature_joins_type_and_name():
	params = [{"type": "Item", "name": "item"}, {"type": "int", "name": "amount"}]
	assert param_signature(params) == "Item item, int amount"


def test_slim_member_omits_empty_and_default_fields():
	row = _row(name="capacity", kind="field", return_type="int")
	assert slim_member(row) == {"name": "capacity", "kind": "field", "return_type": "int"}


def test_slim_member_renders_params_and_keeps_non_public():
	row = _row(name="Give", kind="method", return_type="bool",
	           parameters='[{"type":"Item","name":"i"}]', access_modifier="private",
	           attributes='["Obsolete"]')
	assert slim_member(row) == {
		"name": "Give", "kind": "method", "return_type": "bool",
		"params": "Item i", "access_modifier": "private", "attributes": ["Obsolete"],
	}


def test_member_signature_method_and_field():
	method = _row(name="Give", kind="method", return_type="bool",
	              parameters='[{"type":"Item","name":"i"}]')
	assert member_signature(method) == "bool Give(Item i)"
	field = _row(name="capacity", kind="field", return_type="int")
	assert member_signature(field) == "int capacity"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/test_serialize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rust_dll_mcp.serialize'`

- [ ] **Step 3: Write the implementation**

```python
# rust_dll_mcp/serialize.py
import json


def compact_json(obj) -> str:
	"""Serialize without indentation — the global token-saving encoding."""
	return json.dumps(obj, separators=(",", ":"))


def param_signature(parameters: list[dict]) -> str:
	"""Render parsed parameters as a compact signature string, e.g. 'Item item, int amount'."""
	parts = []
	for parameter in parameters:
		type_text = (parameter.get("type") or "").strip()
		name_text = (parameter.get("name") or "").strip()
		parts.append(f"{type_text} {name_text}".strip())
	return ", ".join(parts)


def slim_member(row) -> dict:
	"""Token-optimized member dict from a members row.

	Omits empty/default fields (absent == empty); params rendered as a signature string.
	"""
	parameters = json.loads(row["parameters"] or "[]")
	attributes = json.loads(row["attributes"] or "[]")
	member = {"name": row["name"], "kind": row["kind"]}
	if row["return_type"]:
		member["return_type"] = row["return_type"]
	if parameters:
		member["params"] = param_signature(parameters)
	if row["access_modifier"] and row["access_modifier"] != "public":
		member["access_modifier"] = row["access_modifier"]
	if attributes:
		member["attributes"] = attributes
	return member


def member_signature(row) -> str:
	"""Single-line signature for diff output, e.g. 'bool Give(Item i)' or 'int capacity'."""
	parameters = json.loads(row["parameters"] or "[]")
	return_type = row["return_type"] or ""
	if row["kind"] in ("method", "constructor"):
		call = f"{row['name']}({param_signature(parameters)})"
		return f"{return_type} {call}".strip()
	return f"{return_type} {row['name']}".strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/test_serialize.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add rust_dll_mcp/serialize.py tests/test_serialize.py
git commit -m "feat: add token-optimized serialization helpers"
```

---

## Task 2: Compact JSON in the server

**Files:**
- Modify: `rust_dll_mcp/server.py:147` (serialization), imports near top

- [ ] **Step 1: Add the import**

Add to the import block in `rust_dll_mcp/server.py` (alongside the other `from rust_dll_mcp...` imports):

```python
from rust_dll_mcp.serialize import compact_json
```

- [ ] **Step 2: Switch the serializer**

Replace the return line in `call_tool` (currently `rust_dll_mcp/server.py:147`):

```python
		return [types.TextContent(type="text", text=json.dumps(result, indent=2) if not isinstance(result, str) else result)]
```

with:

```python
		return [types.TextContent(type="text", text=result if isinstance(result, str) else compact_json(result))]
```

- [ ] **Step 3: Verify nothing references the old behavior**

Run: `PYTHONPATH=. pytest tests/ -v`
Expected: PASS for all existing tests except `tests/test_tools.py::test_get_type_members_returns_list` (that test is updated in Task 3; it may fail or pass depending on order — that is expected and resolved in Task 3).

- [ ] **Step 4: Commit**

```bash
git add rust_dll_mcp/server.py
git commit -m "perf: serialize tool responses as compact JSON"
```

---

## Task 3: get_type_members envelope + inheritance summary

**Files:**
- Modify: `rust_dll_mcp/db.py` (add resolution + summary helpers)
- Modify: `rust_dll_mcp/tools.py:34-51` (`tool_get_type_members`)
- Test: `tests/test_db.py`, `tests/test_tools.py`

- [ ] **Step 1: Write failing DB tests**

Add to `tests/test_db.py` (top imports already include `create_schema`; add the new ones):

```python
# add to imports in tests/test_db.py
from rust_dll_mcp.db import query_type_header, query_inheritance_summary
from pipeline.build_index import index_cs_file, populate_fts

INHERIT_CS = """\
namespace Game
{
	public class Animal
	{
		public void Eat() { }
		public int legs;
	}
	public class Dog : Animal
	{
		public void Bark() { }
	}
}
"""


def _inherit_connection():
	import sqlite3, tempfile, pathlib
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	tmp = pathlib.Path(tempfile.mkdtemp()) / "Game.cs"
	tmp.write_text(INHERIT_CS)
	index_cs_file(connection, tmp, source="rust")
	populate_fts(connection)
	return connection


def test_query_type_header_returns_base_and_source():
	connection = _inherit_connection()
	base_type, interfaces, source = query_type_header(connection, "Game.Dog")
	assert base_type == "Animal"
	assert source == "rust"


def test_inheritance_summary_resolves_and_counts():
	connection = _inherit_connection()
	summary, unresolved = query_inheritance_summary(connection, "Game.Dog")
	assert summary == [{"declaring_type": "Game.Animal", "source": "rust", "member_count": 2}]
	assert unresolved == []


def test_inheritance_summary_reports_unresolved_external_base():
	connection = _inherit_connection()
	summary, unresolved = query_inheritance_summary(connection, "Game.Animal")
	assert summary == []
	assert unresolved == []  # Animal has no base
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. pytest tests/test_db.py -k "type_header or inheritance" -v`
Expected: FAIL with `ImportError: cannot import name 'query_type_header'`

- [ ] **Step 3: Implement DB helpers**

Add to `rust_dll_mcp/db.py` (after `query_get_type_members`):

```python
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
```

- [ ] **Step 4: Run DB tests to verify pass**

Run: `PYTHONPATH=. pytest tests/test_db.py -k "type_header or inheritance" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Write failing tool tests**

Replace `test_get_type_members_returns_list` in `tests/test_tools.py` with the following tests (all use the existing `populated_connection` fixture — no new fixture needed):

```python
# replace test_get_type_members_returns_list with:
@pytest.mark.asyncio
async def test_get_type_members_envelope_shape(populated_connection):
	result = await tool_get_type_members(populated_connection, None, "Rust.PlayerInventory")
	assert result["fully_qualified_name"] == "Rust.PlayerInventory"
	assert result["base_type"] == "BaseEntity"
	names = [member["name"] for member in result["members"]]
	assert "GiveItem" in names


@pytest.mark.asyncio
async def test_get_type_members_unresolved_base(populated_connection):
	# SAMPLE_CS's PlayerInventory extends BaseEntity, which is not in the sample DB.
	result = await tool_get_type_members(populated_connection, None, "Rust.PlayerInventory")
	assert result["unresolved_bases"] == ["BaseEntity"]
	assert "inherited_summary" not in result


@pytest.mark.asyncio
async def test_get_type_members_omits_empty_member_fields(populated_connection):
	result = await tool_get_type_members(populated_connection, None, "Rust.PlayerInventory")
	by_name = {member["name"]: member for member in result["members"]}
	# A field has no params/attributes -> those keys are absent.
	assert "params" not in by_name["capacity"]
	assert "attributes" not in by_name["capacity"]
	# A method with parameters renders a signature string.
	assert by_name["GiveItem"]["params"] == "Item item, int amount"
```

- [ ] **Step 6: Run to verify failure**

Run: `PYTHONPATH=. pytest tests/test_tools.py -k "get_type_members" -v`
Expected: FAIL — `tool_get_type_members` still returns a list, so `result["fully_qualified_name"]` raises `TypeError`.

- [ ] **Step 7: Implement the envelope**

Replace `tool_get_type_members` in `rust_dll_mcp/tools.py`. Update the `from rust_dll_mcp.db import (...)` block to add `query_type_header` and `query_inheritance_summary`, add `from rust_dll_mcp.serialize import slim_member`, then:

```python
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
```

- [ ] **Step 8: Run tool tests to verify pass**

Run: `PYTHONPATH=. pytest tests/test_tools.py -k "get_type_members" -v`
Expected: PASS (3 passed)

- [ ] **Step 9: Commit**

```bash
git add rust_dll_mcp/db.py rust_dll_mcp/tools.py tests/test_db.py tests/test_tools.py
git commit -m "feat: get_type_members returns envelope with inheritance summary"
```

---

## Task 4: search_source regex tool

**Files:**
- Modify: `rust_dll_mcp/db.py` (add `query_member_sources`)
- Modify: `rust_dll_mcp/tools.py` (add `tool_search_source`)
- Modify: `rust_dll_mcp/server.py` (register tool + dispatch)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tools.py`:

```python
CUI_CS = """\
public partial class CommunityEntity
{
	public void UpdateRectTransform(RectTransform rt, JSON.Object obj)
	{
		if ( ShouldUpdateField( "rotation" ) )
			rt.rotation = Quaternion.Euler( 0, 0, obj.GetFloat("rotation", 0) );
	}
}
"""


@pytest.fixture
def community_connection(tmp_path):
	import sqlite3
	from rust_dll_mcp.db import create_schema
	cs_file = tmp_path / "CommunityEntity.UI.cs"
	cs_file.write_text(CUI_CS)
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	index_cs_file(connection, cs_file, source="community")
	populate_fts(connection)
	return connection


@pytest.mark.asyncio
async def test_search_source_finds_member_reference(community_connection):
	from rust_dll_mcp.tools import tool_search_source
	results = await tool_search_source(community_connection, None, r"rt\.rotation")
	assert any(r["member_name"] == "UpdateRectTransform" for r in results)
	hit = next(r for r in results if "rt.rotation" in r["line"])
	assert hit["source"] == "community"
	assert hit["line"] == 'rt.rotation = Quaternion.Euler( 0, 0, obj.GetFloat("rotation", 0) );'


@pytest.mark.asyncio
async def test_search_source_finds_json_string_literal(community_connection):
	from rust_dll_mcp.tools import tool_search_source
	results = await tool_search_source(community_connection, None, r'"rotation"')
	assert len(results) >= 1


@pytest.mark.asyncio
async def test_search_source_source_filter_scopes(community_connection):
	from rust_dll_mcp.tools import tool_search_source
	assert await tool_search_source(community_connection, None, r"rt\.rotation", source="rust") == []
	assert len(await tool_search_source(community_connection, None, r"rt\.rotation", source="community")) >= 1


@pytest.mark.asyncio
async def test_search_source_invalid_regex_returns_message(community_connection):
	from rust_dll_mcp.tools import tool_search_source
	result = await tool_search_source(community_connection, None, r"(unclosed")
	assert isinstance(result, str)
	assert "invalid regex" in result.lower()


@pytest.mark.asyncio
async def test_search_source_respects_limit(community_connection):
	from rust_dll_mcp.tools import tool_search_source
	results = await tool_search_source(community_connection, None, r"rotation", limit=1)
	assert len(results) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. pytest tests/test_tools.py -k "search_source" -v`
Expected: FAIL with `ImportError: cannot import name 'tool_search_source'`

- [ ] **Step 3: Implement the DB iterator**

Add to `rust_dll_mcp/db.py`:

```python
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
```

- [ ] **Step 4: Implement the tool**

Add to `rust_dll_mcp/tools.py` (add `import re` at top, and `query_member_sources` to the db import block):

```python
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
```

- [ ] **Step 5: Run tool tests to verify pass**

Run: `PYTHONPATH=. pytest tests/test_tools.py -k "search_source" -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Register the tool in the server**

In `rust_dll_mcp/server.py`, add `tool_search_source` to the `from rust_dll_mcp.tools import (...)` block. Add this `types.Tool(...)` entry to the list returned by `list_tools` (after the `search_usages` entry):

```python
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
```

Add this dispatch branch to `call_tool` (after the `search_usages` branch):

```python
		elif name == "search_source":
			result = await tool_search_source(
				current_connection, previous_connection,
				arguments["pattern"], arguments.get("source"), arguments.get("limit", 50),
			)
```

- [ ] **Step 7: Run the full suite**

Run: `PYTHONPATH=. pytest tests/ -v`
Expected: PASS (no regressions)

- [ ] **Step 8: Commit**

```bash
git add rust_dll_mcp/db.py rust_dll_mcp/tools.py rust_dll_mcp/server.py tests/test_tools.py
git commit -m "feat: add search_source regex tool over decompiled bodies"
```

---

## Task 5: Source label + filter on find_type and search_usages

**Files:**
- Modify: `rust_dll_mcp/db.py` (`query_find_type`, `query_search_usages`)
- Modify: `rust_dll_mcp/tools.py` (`tool_find_type`, `tool_search_usages`)
- Modify: `rust_dll_mcp/server.py` (schemas + dispatch)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tools.py`:

```python
@pytest.mark.asyncio
async def test_find_type_labels_source_and_drops_namespace(populated_connection):
	result = await tool_find_type(populated_connection, None, "PlayerInventory")
	assert result[0]["source"] == "rust"
	assert "namespace" not in result[0]


@pytest.mark.asyncio
async def test_find_type_source_filter(populated_connection):
	assert await tool_find_type(populated_connection, None, "PlayerInventory", source="community") == []
	assert len(await tool_find_type(populated_connection, None, "PlayerInventory", source="rust")) >= 1


@pytest.mark.asyncio
async def test_search_usages_labels_source(populated_connection):
	result = await tool_search_usages(populated_connection, None, "containerMain")
	assert all(hit["source"] == "rust" for hit in result)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. pytest tests/test_tools.py -k "labels_source or source_filter" -v`
Expected: FAIL — `tool_find_type` has no `source` parameter / results lack `source` key.

- [ ] **Step 3: Update db queries**

Replace `query_find_type` in `rust_dll_mcp/db.py`:

```python
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
```

Replace `query_search_usages` in `rust_dll_mcp/db.py`:

```python
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
```

- [ ] **Step 4: Update tools**

Replace `tool_find_type` in `rust_dll_mcp/tools.py`:

```python
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
```

Replace `tool_search_usages` in `rust_dll_mcp/tools.py`:

```python
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
```

- [ ] **Step 5: Run tool tests to verify pass**

Run: `PYTHONPATH=. pytest tests/test_tools.py -k "labels_source or source_filter or returns_list or search_usages" -v`
Expected: PASS

- [ ] **Step 6: Wire source params into the server**

In `rust_dll_mcp/server.py`, add a `source` property to the `find_type` and `search_usages` `inputSchema` `properties` (do not add to `required`):

```python
						"source": {"type": "string", "description": "Optional source filter: rust, oxide, facepunch, or community"},
```

Update the two dispatch branches in `call_tool`:

```python
		if name == "find_type":
			result = await tool_find_type(current_connection, previous_connection, arguments["name"], arguments.get("source"))
		...
		elif name == "search_usages":
			result = await tool_search_usages(current_connection, previous_connection, arguments["symbol"], arguments.get("source"))
```

- [ ] **Step 7: Run the full suite**

Run: `PYTHONPATH=. pytest tests/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add rust_dll_mcp/db.py rust_dll_mcp/tools.py rust_dll_mcp/server.py tests/test_tools.py
git commit -m "feat: label and filter find_type/search_usages results by source"
```

---

## Task 6: Slim diff_since_last_wipe

**Files:**
- Modify: `rust_dll_mcp/db.py` (`query_diff_since_last_wipe`)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_tools.py`:

```python
CHANGED_CS_OLD = """\
namespace Rust
{
	public class Door
	{
		public void Open() { return; }
	}
}
"""
CHANGED_CS_NEW = """\
namespace Rust
{
	public class Door
	{
		public void Open() { Lock(); return; }
		public void Slam() { }
	}
}
"""


@pytest.mark.asyncio
async def test_diff_returns_slim_signatures(tmp_path):
	import sqlite3
	from rust_dll_mcp.db import create_schema
	def build(text):
		f = tmp_path / f"Assembly-{abs(hash(text))}.cs"
		f.write_text(text)
		c = sqlite3.connect(":memory:")
		c.row_factory = sqlite3.Row
		create_schema(c)
		index_cs_file(c, f, source="rust")
		populate_fts(c)
		return c
	current = build(CHANGED_CS_NEW)
	previous = build(CHANGED_CS_OLD)
	result = await tool_diff_since_last_wipe(current, previous, "Rust.Door")
	assert {entry["name"] for entry in result["added"]} == {"Slam"}
	assert result["added"][0]["signature"] == "void Slam()"
	changed_names = {entry["name"] for entry in result["changed"]}
	assert "Open" in changed_names
	open_entry = next(e for e in result["changed"] if e["name"] == "Open")
	assert open_entry["source_changed"] is True
	# No full source bodies inlined anywhere.
	for bucket in ("added", "removed", "changed"):
		for entry in result[bucket]:
			assert "source_code" not in entry
			assert "current" not in entry and "previous" not in entry
```

(Note: the parser keeps `void` as the return type for void methods — only constructors get a blank return type — and `member_signature` strips surrounding whitespace, so `Slam`'s signature is exactly `"void Slam()"`.)

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. pytest tests/test_tools.py -k "diff_returns_slim" -v`
Expected: FAIL — current diff returns full `dict(row)` with `source_code`, no `signature` key.

- [ ] **Step 3: Implement slim diff**

Replace `query_diff_since_last_wipe` in `rust_dll_mcp/db.py` (add `from rust_dll_mcp.serialize import member_signature` to the top of `db.py`):

```python
def query_diff_since_last_wipe(
	current_connection: sqlite3.Connection,
	previous_connection: sqlite3.Connection,
	type_fqn: str,
) -> dict:
	"""Compare members of a type between two DBs. Returns slim {added, removed, changed}."""
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
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=. pytest tests/test_tools.py -k "diff" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add rust_dll_mcp/db.py tests/test_tools.py
git commit -m "perf: slim diff_since_last_wipe to signatures + change flags"
```

---

## Task 7: Index the Rust.Community client source

**Files:**
- Modify: `pipeline/build_index.py` (`build_index` + CLI)
- Test: `tests/test_build_index.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_build_index.py`:

```python
def test_build_index_indexes_community_dir(tmp_path):
	import sqlite3
	from pipeline.build_index import build_index
	server_dir = tmp_path / "source"
	server_dir.mkdir()
	(server_dir / "Assembly-CSharp.cs").write_text(
		"namespace Rust { public class Foo { public void Bar() { } } }"
	)
	community_dir = tmp_path / "community"
	community_dir.mkdir()
	(community_dir / "CommunityEntity.UI.cs").write_text(
		'public partial class CommunityEntity { public void Add() { ShouldUpdateField("rotation"); } }'
	)
	db_path = tmp_path / "out.db"
	build_index(server_dir, db_path, build_id="b1", wipe_date="2026-06-08", community_dir=community_dir)

	connection = sqlite3.connect(db_path)
	connection.row_factory = sqlite3.Row
	row = connection.execute(
		"""
		SELECT a.source FROM types t JOIN assemblies a ON t.assembly_id = a.id
		WHERE t.fully_qualified_name = 'CommunityEntity' LIMIT 1
		"""
	).fetchone()
	assert row["source"] == "community"
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=. pytest tests/test_build_index.py -k "community" -v`
Expected: FAIL — `build_index()` got an unexpected keyword argument `community_dir`.

- [ ] **Step 3: Implement community ingestion**

In `pipeline/build_index.py`, change the `build_index` signature and body. Replace the signature line and add the community loop after the `for cs_file in cs_files:` block (before `populate_fts`):

```python
def build_index(
	source_dir: Path,
	db_path: Path,
	build_id: str,
	wipe_date: str,
	previous_build_id: str | None = None,
	community_dir: Path | None = None,
) -> None:
```

Add after the existing server-source indexing loop, before `populate_fts(connection)`:

```python
	if community_dir is not None:
		community_files = list(Path(community_dir).rglob("*.cs"))
		print(f"Indexing {len(community_files)} community .cs files", flush=True)
		for cs_file in community_files:
			try:
				index_cs_file(connection, cs_file, source="community")
				print(f"  indexed (community) {cs_file.name}", flush=True)
			except Exception as error:
				print(f"  WARNING: failed to index {cs_file.name}: {error}", file=sys.stderr, flush=True)
```

Add the CLI argument in the `__main__` block (after the `--previous-build-id` argument):

```python
	argument_parser.add_argument("--community-dir", type=Path, default=None)
```

And update the `build_index(...)` call at the bottom to pass it:

```python
	build_index(
		args.source_dir, args.db_path, args.build_id, args.wipe_date,
		args.previous_build_id, args.community_dir,
	)
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=. pytest tests/test_build_index.py -k "community" -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `PYTHONPATH=. pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/build_index.py tests/test_build_index.py
git commit -m "feat: index Rust.Community client source as source=community"
```

---

## Task 8: Wire Rust.Community into the monthly pipeline

**Files:**
- Modify: `.github/workflows/monthly-wipe-pipeline.yml`

- [ ] **Step 1: Add the clone step**

In `.github/workflows/monthly-wipe-pipeline.yml`, add a step immediately before the `Build SQLite index` step:

```yaml
      - name: Clone Rust.Community client source
        run: git clone --depth 1 https://github.com/Facepunch/Rust.Community.git work/community
```

- [ ] **Step 2: Pass --community-dir to the build**

Edit the `Build SQLite index` step's `run:` block to add the new flag:

```yaml
      - name: Build SQLite index
        run: |
          python pipeline/build_index.py \
            work/source \
            rust_dlls.db \
            --build-id "${{ steps.wipe_info.outputs.build_id }}" \
            --wipe-date "${{ steps.wipe_info.outputs.wipe_date }}" \
            --previous-build-id "${{ steps.prev_build.outputs.previous_build_id }}" \
            --community-dir work/community
```

- [ ] **Step 3: Validate YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/monthly-wipe-pipeline.yml'))"`
Expected: no output (valid YAML). If `yaml` is unavailable, run `python -c "import json,sys; print('skip')"` and visually confirm indentation matches the surrounding steps (6-space step indent, 8-space keys).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/monthly-wipe-pipeline.yml
git commit -m "ci: clone and index Rust.Community in monthly pipeline"
```

---

## Task 9: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `PYTHONPATH=. pytest tests/ -v`
Expected: PASS (all tests, no skips of the new ones)

- [ ] **Step 2: Smoke-test compact output against the real cached DB (if present)**

Run:
```bash
PYTHONPATH=. python -c "
import asyncio, sqlite3
from pathlib import Path
import platformdirs
from rust_dll_mcp.tools import tool_get_type_members, tool_search_source
from rust_dll_mcp.serialize import compact_json
p = Path(platformdirs.user_cache_dir('rust-dll-mcp')) / 'rust_dlls_current.db'
if not p.exists():
    print('no cached DB; skipping smoke test'); raise SystemExit
c = sqlite3.connect(p); c.row_factory = sqlite3.Row
async def main():
    r = await tool_get_type_members(c, None, 'BasePlayer')
    out = compact_json(r)
    assert 'inherited_summary' in r and 'base_type' in r
    assert '\n' not in out  # compact, no indentation
    print('get_type_members BasePlayer envelope OK, members:', len(r['members']))
    hits = await tool_search_source(c, None, r'rt\\.rotation', limit=5)
    print('search_source rt.rotation hits:', len(hits))
asyncio.run(main())
"
```
Expected: prints the envelope member count and a search hit count without assertion errors (or "no cached DB; skipping" if the 590 MB DB is absent).

- [ ] **Step 3: Confirm the spec is fully covered**

Re-read `docs/superpowers/specs/2026-06-08-dll-mcp-improvements-design.md` and confirm each of Items 1–5 maps to a completed task (Item 1 → Task 3; Item 2 → Task 4; Item 3 → Tasks 7–8; Item 4 → Task 5; Item 5 → Tasks 1, 2, 3, 5, 6). No code changes in this task.
