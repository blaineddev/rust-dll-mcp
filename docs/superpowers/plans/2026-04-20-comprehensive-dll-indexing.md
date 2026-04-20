# Comprehensive DLL Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the rust-dll-mcp to parse properties, enum values, nested types, modifiers, and XML doc comments, storing all new data in an extended schema and exposing a new `find_implementations` tool.

**Architecture:** All changes flow through the same pipeline → DB → server stack. Parser changes in `parse_cs.py` extract new data. `build_index.py` writes it. `db.py` defines the schema and queries. `tools.py` and `server.py` expose the new tool.

**Tech Stack:** Python 3.12, SQLite3 + FTS5, pytest

> **Note:** Do not commit between tasks. Commit only at the end (Task 8, final step).

---

## File Map

| File | Change |
|---|---|
| `rust_dll_mcp/db.py` | New columns, 8 indexes, updated FTS tables, `query_find_implementations` |
| `pipeline/parse_cs.py` | Updated dataclasses, `_extract_doc_comment`, `PROPERTY_PATTERN`, `_parse_properties`, `ENUM_VALUE_PATTERN`, `_parse_enum_values`, modifier extraction, `_extract_nested_type_sources`, `_parse_nested_types` |
| `pipeline/build_index.py` | Write all new fields in INSERT, track FQN→id for parent_type_id |
| `rust_dll_mcp/tools.py` | Add `tool_find_implementations` |
| `rust_dll_mcp/server.py` | Register `find_implementations` tool |
| `tests/test_db.py` | Tests for new schema + `query_find_implementations` |
| `tests/test_parse_cs.py` | Tests for all new parser features |
| `tests/test_build_index.py` | Tests for new fields written to DB |
| `tests/test_tools.py` | Tests for `tool_find_implementations` |

---

## Task 1: Update schema in `db.py`

**Files:**
- Modify: `rust_dll_mcp/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Add to the bottom of `tests/test_db.py`:

```python
def test_types_table_has_new_columns(bare_connection):
	create_schema(bare_connection)
	info = bare_connection.execute("PRAGMA table_info(types)").fetchall()
	column_names = {row[1] for row in info}
	assert "parent_type_id" in column_names
	assert "is_static" in column_names
	assert "is_abstract" in column_names
	assert "is_sealed" in column_names
	assert "doc_comment" in column_names


def test_members_table_has_new_columns(bare_connection):
	create_schema(bare_connection)
	info = bare_connection.execute("PRAGMA table_info(members)").fetchall()
	column_names = {row[1] for row in info}
	assert "is_static" in column_names
	assert "is_abstract" in column_names
	assert "is_override" in column_names
	assert "is_virtual" in column_names
	assert "doc_comment" in column_names


def test_schema_creates_indexes(bare_connection):
	create_schema(bare_connection)
	indexes = bare_connection.execute(
		"SELECT name FROM sqlite_master WHERE type='index'"
	).fetchall()
	index_names = {row[0] for row in indexes}
	assert "idx_types_fqn" in index_names
	assert "idx_types_base_type" in index_names
	assert "idx_members_type_id" in index_names


def test_types_fts_has_doc_comment_column(bare_connection):
	create_schema(bare_connection)
	info = bare_connection.execute("PRAGMA table_info(types_fts)").fetchall()
	column_names = {row[1] for row in info}
	assert "doc_comment" in column_names


def test_query_find_implementations_by_base_type(populated_connection):
	from rust_dll_mcp.db import query_find_implementations
	results = query_find_implementations(populated_connection, "BaseEntity")
	assert any(row["fully_qualified_name"] == "Rust.PlayerInventory" for row in results)
	assert any(row["match_reason"] == "base_type" for row in results)


def test_query_find_implementations_returns_empty_for_unknown(populated_connection):
	from rust_dll_mcp.db import query_find_implementations
	results = query_find_implementations(populated_connection, "UnknownXYZ")
	assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python -m pytest tests/test_db.py::test_types_table_has_new_columns tests/test_db.py::test_schema_creates_indexes -v
```

Expected: FAIL

- [ ] **Step 3: Replace `create_schema` in `rust_dll_mcp/db.py`**

Replace the `create_schema` function body with:

```python
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
```

- [ ] **Step 4: Add `query_find_implementations` to `rust_dll_mcp/db.py`**

Append after the existing query functions:

```python
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
```

- [ ] **Step 5: Run all `test_db.py` tests to verify they pass**

```bash
source venv/bin/activate && python -m pytest tests/test_db.py -v
```

Expected: All pass.

---

## Task 2: Update dataclasses + add `_extract_doc_comment`

**Files:**
- Modify: `pipeline/parse_cs.py`
- Test: `tests/test_parse_cs.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_parse_cs.py`:

```python
DOC_COMMENT_CS = """\
namespace Rust
{
	/// <summary>A player on the server.</summary>
	public class BasePlayer
	{
		/// <summary>Kills the player.</summary>
		public void Die()
		{
		}
	}
}
"""


def test_parsed_type_has_doc_comment_field():
	types = parse_cs_file(DOC_COMMENT_CS)
	assert hasattr(types[0], 'doc_comment')


def test_parsed_type_doc_comment_extracted():
	types = parse_cs_file(DOC_COMMENT_CS)
	assert types[0].doc_comment == "A player on the server."


def test_parsed_member_doc_comment_extracted():
	types = parse_cs_file(DOC_COMMENT_CS)
	die_method = next(m for m in types[0].members if m.name == "Die")
	assert die_method.doc_comment == "Kills the player."


def test_parsed_type_doc_comment_is_none_when_absent():
	types = parse_cs_file(SAMPLE_CS)
	assert types[0].doc_comment is None


def test_parsed_type_has_modifier_fields():
	types = parse_cs_file(SAMPLE_CS)
	assert hasattr(types[0], 'is_static')
	assert hasattr(types[0], 'is_abstract')
	assert hasattr(types[0], 'is_sealed')


def test_parsed_member_has_modifier_fields():
	types = parse_cs_file(SAMPLE_CS)
	method = next(m for m in types[0].members if m.kind == 'method')
	assert hasattr(method, 'is_static')
	assert hasattr(method, 'is_abstract')
	assert hasattr(method, 'is_override')
	assert hasattr(method, 'is_virtual')


def test_parsed_type_has_parent_name_field():
	types = parse_cs_file(SAMPLE_CS)
	assert hasattr(types[0], 'parent_name')
	assert types[0].parent_name is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python -m pytest tests/test_parse_cs.py::test_parsed_type_has_doc_comment_field tests/test_parse_cs.py::test_parsed_type_has_modifier_fields -v
```

Expected: FAIL (`ParsedType has no attribute 'doc_comment'`)

- [ ] **Step 3: Replace the two dataclasses in `pipeline/parse_cs.py`**

Replace the existing `ParsedMember` and `ParsedType` dataclasses:

```python
@dataclass
class ParsedMember:
	name: str
	kind: str
	return_type: str
	parameters: list[dict]
	access_modifier: str
	attributes: list[str]
	source_code: str
	is_static: bool = False
	is_abstract: bool = False
	is_override: bool = False
	is_virtual: bool = False
	doc_comment: str | None = None


@dataclass
class ParsedType:
	namespace: str
	name: str
	fully_qualified_name: str
	kind: str
	access_modifier: str
	base_type: str
	interfaces: list[str]
	source_code: str
	members: list[ParsedMember] = dataclass_field(default_factory=list)
	is_static: bool = False
	is_abstract: bool = False
	is_sealed: bool = False
	doc_comment: str | None = None
	parent_name: str | None = None
```

- [ ] **Step 4: Add `_extract_doc_comment` to `pipeline/parse_cs.py`**

Insert this function after the pattern constants and before `_extract_block`:

```python
def _extract_doc_comment(source: str, declaration_start: int) -> str | None:
	"""Extract consecutive /// lines immediately preceding declaration_start, skipping blank lines."""
	preceding = source[:declaration_start]
	lines = preceding.split('\n')
	doc_lines = []
	for line in reversed(lines):
		stripped = line.strip()
		if stripped.startswith('///'):
			doc_lines.insert(0, stripped[3:].strip())
		elif stripped == '':
			continue
		else:
			break
	if not doc_lines:
		return None
	text = ' '.join(doc_lines)
	text = re.sub(r'<[^>]+>', '', text).strip()
	return text or None
```

- [ ] **Step 5: Update `parse_cs_file` to pass `doc_comment` on the `ParsedType` constructor**

In `parse_cs_file`, just before `parsed_types.append(ParsedType(...))`, add:

```python
doc_comment = _extract_doc_comment(source, match.start())
```

Then add `doc_comment=doc_comment` to the `ParsedType(...)` constructor call.

- [ ] **Step 6: Update `_parse_members` method loop to pass `doc_comment` on each `ParsedMember`**

In `_parse_members`, in the `METHOD_PATTERN` `for` loop, add `doc_comment=_extract_doc_comment(type_body, match.start())` to the `ParsedMember(...)` constructor call.

- [ ] **Step 7: Run tests**

```bash
source venv/bin/activate && python -m pytest tests/test_parse_cs.py -v
```

Expected: New tests pass; all prior tests still pass.

---

## Task 3: Add property parsing

**Files:**
- Modify: `pipeline/parse_cs.py`
- Test: `tests/test_parse_cs.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_parse_cs.py`:

```python
PROPERTIES_CS = """\
namespace Rust
{
	public class PlayerStats
	{
		private int _health;

		public int Health { get; set; }

		public string Name { get; }

		public bool IsAlive => _health > 0;

		public int Capacity { get; private set; }
	}
}
"""


def test_parse_finds_properties():
	types = parse_cs_file(PROPERTIES_CS)
	properties = [m for m in types[0].members if m.kind == "property"]
	assert len(properties) == 4


def test_parse_property_names():
	types = parse_cs_file(PROPERTIES_CS)
	names = {m.name for m in types[0].members if m.kind == "property"}
	assert names == {"Health", "Name", "IsAlive", "Capacity"}


def test_parse_property_return_type():
	types = parse_cs_file(PROPERTIES_CS)
	health = next(m for m in types[0].members if m.name == "Health")
	assert health.return_type == "int"


def test_parse_property_source_contains_getter():
	types = parse_cs_file(PROPERTIES_CS)
	health = next(m for m in types[0].members if m.name == "Health")
	assert "get" in health.source_code


def test_parse_property_does_not_duplicate_as_field():
	types = parse_cs_file(PROPERTIES_CS)
	field_names = {m.name for m in types[0].members if m.kind == "field"}
	assert "Health" not in field_names
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python -m pytest tests/test_parse_cs.py::test_parse_finds_properties -v
```

Expected: FAIL

- [ ] **Step 3: Add `PROPERTY_PATTERN` constant to `pipeline/parse_cs.py`**

Insert after `CONSTRUCTOR_PATTERN`:

```python
PROPERTY_PATTERN = re.compile(
	r'(?P<access>public|private|protected internal|protected|internal|private protected)\s+'
	r'(?P<modifiers>(?:(?:static|virtual|abstract|override|sealed|new|unsafe)\s+)*)'
	r'(?P<type>[\w\[\]<>.,\s?\*]+?)\s+'
	r'(?P<name>\w+)\s*'
	r'(?=\s*(?:=>|\{[^(]*(?:get|set|init)))',
	re.MULTILINE,
)
```

- [ ] **Step 4: Add `_parse_properties` function to `pipeline/parse_cs.py`**

Insert before `_parse_members`:

```python
def _parse_properties(type_body: str) -> list[ParsedMember]:
	members = []
	for match in PROPERTY_PATTERN.finditer(type_body):
		name = match.group('name')
		property_type = match.group('type').strip()
		access = match.group('access')
		modifiers_str = match.group('modifiers') or ''

		after = type_body[match.end():]
		if after.lstrip().startswith('=>'):
			semi = after.find(';')
			end_pos = match.end() + semi + 1 if semi != -1 else len(type_body)
		else:
			_, end_pos = _extract_block(type_body, match.end())

		source_code = type_body[match.start():end_pos]

		members.append(ParsedMember(
			name=name,
			kind='property',
			return_type=property_type,
			parameters=[],
			access_modifier=access,
			attributes=[],
			source_code=source_code.strip(),
			is_static='static' in modifiers_str,
			is_abstract='abstract' in modifiers_str,
			is_override='override' in modifiers_str,
			is_virtual='virtual' in modifiers_str,
			doc_comment=_extract_doc_comment(type_body, match.start()),
		))
	return members
```

- [ ] **Step 5: Integrate `_parse_properties` into `_parse_members`**

In `_parse_members`, after the constructor loop and before the field loop, add:

```python
property_members = _parse_properties(type_body)
property_names = {member.name for member in property_members}
members.extend(property_members)
```

Then update the field loop's skip condition from:

```python
if name in method_names:
    continue
```

to:

```python
if name in method_names or name in property_names:
    continue
```

- [ ] **Step 6: Run tests**

```bash
source venv/bin/activate && python -m pytest tests/test_parse_cs.py -v
```

Expected: All tests pass.

---

## Task 4: Add enum value parsing

**Files:**
- Modify: `pipeline/parse_cs.py`
- Test: `tests/test_parse_cs.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_parse_cs.py`:

```python
ENUM_VALUES_CS = """\
namespace Rust
{
	public enum HitArea
	{
		Head = 1,
		Body = 2,
		Hand = 4,
		Foot,
	}
}
"""


def test_parse_enum_values_count():
	types = parse_cs_file(ENUM_VALUES_CS)
	values = [m for m in types[0].members if m.kind == "enum_value"]
	assert len(values) == 4


def test_parse_enum_value_names():
	types = parse_cs_file(ENUM_VALUES_CS)
	names = {m.name for m in types[0].members if m.kind == "enum_value"}
	assert names == {"Head", "Body", "Hand", "Foot"}


def test_parse_enum_value_with_explicit_value():
	types = parse_cs_file(ENUM_VALUES_CS)
	head = next(m for m in types[0].members if m.name == "Head")
	assert head.return_type == "1"


def test_parse_enum_value_without_explicit_value():
	types = parse_cs_file(ENUM_VALUES_CS)
	foot = next(m for m in types[0].members if m.name == "Foot")
	assert foot.return_type == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python -m pytest tests/test_parse_cs.py::test_parse_enum_values_count -v
```

Expected: FAIL (enum currently returns `[]` members)

- [ ] **Step 3: Add `ENUM_VALUE_PATTERN`, `_ENUM_RESERVED`, and `_parse_enum_values` to `pipeline/parse_cs.py`**

Insert after `PROPERTY_PATTERN`:

```python
ENUM_VALUE_PATTERN = re.compile(
	r'^\s*(?P<name>[A-Za-z_]\w*)\s*(?:=\s*(?P<value>[^,\n}]+))?\s*[,\n}]',
	re.MULTILINE,
)

_ENUM_RESERVED = frozenset({
	'get', 'set', 'public', 'private', 'protected', 'internal',
	'static', 'readonly', 'const', 'abstract', 'sealed', 'override',
})


def _parse_enum_values(body: str) -> list[ParsedMember]:
	members = []
	for match in ENUM_VALUE_PATTERN.finditer(body):
		name = match.group('name')
		if name in _ENUM_RESERVED:
			continue
		value = (match.group('value') or '').strip()
		members.append(ParsedMember(
			name=name,
			kind='enum_value',
			return_type=value,
			parameters=[],
			access_modifier='public',
			attributes=[],
			source_code=match.group(0).strip(),
		))
	return members
```

- [ ] **Step 4: Update `parse_cs_file` to call `_parse_enum_values` for enums**

In `parse_cs_file`, change:

```python
members = _parse_members(body) if kind != 'enum' else []
```

to:

```python
members = _parse_members(body) if kind != 'enum' else _parse_enum_values(body)
```

- [ ] **Step 5: Run tests**

```bash
source venv/bin/activate && python -m pytest tests/test_parse_cs.py -v
```

Expected: All tests pass.

---

## Task 5: Add modifier extraction

**Files:**
- Modify: `pipeline/parse_cs.py`
- Test: `tests/test_parse_cs.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_parse_cs.py`:

```python
MODIFIERS_CS = """\
namespace Rust
{
	public abstract class BaseEntity
	{
		public static BaseEntity CreateEntity()
		{
			return null;
		}

		public abstract void Kill();

		public virtual void OnDestroy()
		{
		}
	}
}
"""

SEALED_CS = """\
namespace Rust
{
	public sealed class FinalClass
	{
	}
}
"""


def test_type_is_abstract():
	types = parse_cs_file(MODIFIERS_CS)
	assert types[0].is_abstract is True


def test_type_is_not_static():
	types = parse_cs_file(MODIFIERS_CS)
	assert types[0].is_static is False


def test_type_is_sealed():
	types = parse_cs_file(SEALED_CS)
	assert types[0].is_sealed is True


def test_member_is_static():
	types = parse_cs_file(MODIFIERS_CS)
	create = next(m for m in types[0].members if m.name == "CreateEntity")
	assert create.is_static is True


def test_member_is_abstract():
	types = parse_cs_file(MODIFIERS_CS)
	kill = next(m for m in types[0].members if m.name == "Kill")
	assert kill.is_abstract is True


def test_member_is_virtual():
	types = parse_cs_file(MODIFIERS_CS)
	on_destroy = next(m for m in types[0].members if m.name == "OnDestroy")
	assert on_destroy.is_virtual is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python -m pytest tests/test_parse_cs.py::test_type_is_abstract tests/test_parse_cs.py::test_member_is_static -v
```

Expected: FAIL

- [ ] **Step 3: Update `TYPE_DECLARATION_PATTERN` to capture a `modifiers` group**

Replace the current `TYPE_DECLARATION_PATTERN` with:

```python
TYPE_DECLARATION_PATTERN = re.compile(
	r'(?P<access>public|internal|private|protected)?\s*'
	r'(?P<modifiers>(?:(?:abstract|sealed|static|partial|readonly)\s+)*)'
	r'(?P<kind>class|struct|enum|interface|delegate)\s+'
	r'(?P<name>\w+)'
	r'(?:\s*<[^>]+>)?'
	r'(?:\s*:\s*(?P<inheritance>[^{]+))?',
	re.MULTILINE,
)
```

- [ ] **Step 4: Update `parse_cs_file` to use the `modifiers` group for type modifier flags**

In `parse_cs_file`, after `access_modifier = match.group('access') or 'internal'`, add:

```python
modifiers_str = match.group('modifiers') or ''
```

Update the `ParsedType(...)` constructor to include:

```python
is_static='static' in modifiers_str,
is_abstract='abstract' in modifiers_str,
is_sealed='sealed' in modifiers_str,
```

- [ ] **Step 5: Update `_parse_members` method loop to set member modifier flags**

In `_parse_members`, in the `METHOD_PATTERN` `for` loop, before creating `ParsedMember`, add:

```python
method_modifiers = match.group('modifiers') or ''
```

Then update the `ParsedMember(...)` constructor to include:

```python
is_static='static' in method_modifiers,
is_abstract='abstract' in method_modifiers,
is_override='override' in method_modifiers,
is_virtual='virtual' in method_modifiers,
```

- [ ] **Step 6: Run tests**

```bash
source venv/bin/activate && python -m pytest tests/test_parse_cs.py -v
```

Expected: All tests pass.

---

## Task 6: Add nested type tracking

**Files:**
- Modify: `pipeline/parse_cs.py`
- Test: `tests/test_parse_cs.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_parse_cs.py`:

```python
NESTED_CS = """\
namespace Rust
{
	public class BasePlayer
	{
		public class PlayerFlags
		{
			public bool IsAdmin;
		}

		public void Die()
		{
		}
	}
}
"""


def test_nested_type_is_extracted():
	types = parse_cs_file(NESTED_CS)
	names = {t.name for t in types}
	assert "PlayerFlags" in names


def test_nested_type_count():
	types = parse_cs_file(NESTED_CS)
	assert len(types) == 2


def test_nested_type_parent_name():
	types = parse_cs_file(NESTED_CS)
	flags = next(t for t in types if t.name == "PlayerFlags")
	assert flags.parent_name == "Rust.BasePlayer"


def test_nested_type_fqn():
	types = parse_cs_file(NESTED_CS)
	flags = next(t for t in types if t.name == "PlayerFlags")
	assert flags.fully_qualified_name == "Rust.BasePlayer.PlayerFlags"


def test_parent_type_does_not_include_nested_as_member():
	types = parse_cs_file(NESTED_CS)
	base_player = next(t for t in types if t.name == "BasePlayer")
	member_names = {m.name for m in base_player.members}
	assert "PlayerFlags" not in member_names


def test_parent_type_still_has_own_methods():
	types = parse_cs_file(NESTED_CS)
	base_player = next(t for t in types if t.name == "BasePlayer")
	member_names = {m.name for m in base_player.members}
	assert "Die" in member_names
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python -m pytest tests/test_parse_cs.py::test_nested_type_is_extracted tests/test_parse_cs.py::test_nested_type_parent_name -v
```

Expected: FAIL

- [ ] **Step 3: Replace `_strip_nested_types` with `_extract_nested_type_sources` in `pipeline/parse_cs.py`**

Replace the `_strip_nested_types` function with:

```python
def _extract_nested_type_sources(body: str) -> tuple[str, list[str]]:
	"""Strip nested type declarations from body, returning (cleaned_body, list_of_nested_sources)."""
	result = []
	nested_sources = []
	search_start = 0
	while True:
		match = TYPE_DECLARATION_PATTERN.search(body, search_start)
		if not match:
			result.append(body[search_start:])
			break
		result.append(body[search_start:match.start()])
		_, end_position = _extract_block(body, match.end())
		nested_sources.append(body[match.start():end_position])
		search_start = end_position
	return ''.join(result), nested_sources
```

- [ ] **Step 4: Add `_parse_nested_types` function to `pipeline/parse_cs.py`**

Insert after `_extract_nested_type_sources`:

```python
def _parse_nested_types(nested_sources: list[str], parent_fqn: str, namespace: str) -> list[ParsedType]:
	parsed = []
	for source in nested_sources:
		match = TYPE_DECLARATION_PATTERN.search(source)
		if not match:
			continue
		kind = match.group('kind')
		name = match.group('name')
		access_modifier = match.group('access') or 'private'
		modifiers_str = match.group('modifiers') or ''
		inheritance_str = (match.group('inheritance') or '').strip()
		base_type, interfaces = _parse_inheritance(inheritance_str)
		fully_qualified_name = f"{parent_fqn}.{name}"

		body, end_position = _extract_block(source, match.end())
		clean_body, further_nested = _extract_nested_type_sources(body)

		members = _parse_members(clean_body) if kind != 'enum' else _parse_enum_values(clean_body)
		doc_comment = _extract_doc_comment(source, match.start())

		parsed.append(ParsedType(
			namespace=namespace,
			name=name,
			fully_qualified_name=fully_qualified_name,
			kind=kind,
			access_modifier=access_modifier,
			base_type=base_type,
			interfaces=interfaces,
			source_code=source[:end_position],
			members=members,
			is_static='static' in modifiers_str,
			is_abstract='abstract' in modifiers_str,
			is_sealed='sealed' in modifiers_str,
			doc_comment=doc_comment,
			parent_name=parent_fqn,
		))

		parsed.extend(_parse_nested_types(further_nested, fully_qualified_name, namespace))
	return parsed
```

- [ ] **Step 5: Update `_parse_members` to use `_extract_nested_type_sources`**

In `_parse_members`, replace:

```python
type_body = _strip_nested_types(type_body)
```

with:

```python
type_body, _ = _extract_nested_type_sources(type_body)
```

- [ ] **Step 6: Update `parse_cs_file` to collect nested types**

In `parse_cs_file`, replace:

```python
body, end_position = _extract_block(source, match.end())
type_source = source[match.start():end_position]

members = _parse_members(body) if kind != 'enum' else _parse_enum_values(body)
```

with:

```python
body, end_position = _extract_block(source, match.end())
type_source = source[match.start():end_position]

clean_body, nested_sources = _extract_nested_type_sources(body)
members = _parse_members(clean_body) if kind != 'enum' else _parse_enum_values(clean_body)
```

After `parsed_types.append(ParsedType(...))`, add:

```python
parsed_types.extend(_parse_nested_types(nested_sources, fully_qualified_name, namespace))
```

- [ ] **Step 7: Run tests**

```bash
source venv/bin/activate && python -m pytest tests/test_parse_cs.py -v
```

Expected: All tests pass.

---

## Task 7: Update `build_index.py` to write all new fields

**Files:**
- Modify: `pipeline/build_index.py`
- Test: `tests/test_build_index.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_build_index.py`:

```python
EXTENDED_CS = """\
namespace Rust
{
	/// <summary>A player entity.</summary>
	public abstract class PlayerBase : BaseEntity
	{
		/// <summary>Player health value.</summary>
		public int Health { get; set; }

		public static PlayerBase CreatePlayer()
		{
			return null;
		}

		public abstract void Kill();

		public class PlayerFlags
		{
			public bool IsAdmin;
		}
	}

	public enum DamageType
	{
		Generic = 0,
		Bullet = 1,
	}
}
"""


@pytest.fixture
def extended_connection(tmp_path):
	cs_file = tmp_path / "Assembly-CSharp.cs"
	cs_file.write_text(EXTENDED_CS)
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	index_cs_file(connection, cs_file, source="rust")
	populate_fts(connection)
	yield connection
	connection.close()


def test_type_doc_comment_stored(extended_connection):
	row = extended_connection.execute(
		"SELECT doc_comment FROM types WHERE name = 'PlayerBase'"
	).fetchone()
	assert row is not None
	assert "A player entity" in row["doc_comment"]


def test_member_doc_comment_stored(extended_connection):
	row = extended_connection.execute(
		"SELECT doc_comment FROM members WHERE name = 'Health'"
	).fetchone()
	assert row is not None
	assert "Player health value" in row["doc_comment"]


def test_type_is_abstract_stored(extended_connection):
	row = extended_connection.execute(
		"SELECT is_abstract FROM types WHERE name = 'PlayerBase'"
	).fetchone()
	assert row["is_abstract"] == 1


def test_member_is_static_stored(extended_connection):
	row = extended_connection.execute(
		"SELECT is_static FROM members WHERE name = 'CreatePlayer'"
	).fetchone()
	assert row["is_static"] == 1


def test_member_is_abstract_stored(extended_connection):
	row = extended_connection.execute(
		"SELECT is_abstract FROM members WHERE name = 'Kill'"
	).fetchone()
	assert row["is_abstract"] == 1


def test_property_stored_as_member_kind(extended_connection):
	row = extended_connection.execute(
		"SELECT kind FROM members WHERE name = 'Health'"
	).fetchone()
	assert row["kind"] == "property"


def test_enum_values_stored(extended_connection):
	rows = extended_connection.execute(
		"SELECT name FROM members WHERE kind = 'enum_value'"
	).fetchall()
	names = {row["name"] for row in rows}
	assert "Generic" in names
	assert "Bullet" in names


def test_nested_type_stored_with_parent_id(extended_connection):
	parent = extended_connection.execute(
		"SELECT id FROM types WHERE name = 'PlayerBase'"
	).fetchone()
	child = extended_connection.execute(
		"SELECT parent_type_id FROM types WHERE name = 'PlayerFlags'"
	).fetchone()
	assert child is not None
	assert child["parent_type_id"] == parent["id"]


def test_fts_finds_type_by_doc_comment(extended_connection):
	rows = extended_connection.execute(
		"SELECT * FROM types_fts WHERE types_fts MATCH 'player entity'"
	).fetchall()
	assert len(rows) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python -m pytest tests/test_build_index.py::test_type_doc_comment_stored tests/test_build_index.py::test_nested_type_stored_with_parent_id -v
```

Expected: FAIL

- [ ] **Step 3: Replace `index_cs_file` in `pipeline/build_index.py`**

Replace the entire `index_cs_file` function:

```python
def index_cs_file(
	connection: sqlite3.Connection,
	cs_file: Path,
	source: str | None = None,
) -> int:
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

	connection.commit()
	return assembly_id
```

- [ ] **Step 4: Run all tests**

```bash
source venv/bin/activate && python -m pytest -v
```

Expected: All tests pass.

---

## Task 8: Add `tool_find_implementations` and register in `server.py`

**Files:**
- Modify: `rust_dll_mcp/tools.py`
- Modify: `rust_dll_mcp/server.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tools.py`:

```python
from rust_dll_mcp.tools import tool_find_implementations  # add to existing import block


IMPLEMENTATIONS_CS = """\
namespace Rust
{
	public class BaseEntity
	{
	}

	public class BasePlayer : BaseEntity
	{
	}

	public class BaseVehicle : BaseEntity
	{
	}
}
"""


@pytest.fixture
def implementations_connection(tmp_path):
	cs_file = tmp_path / "Assembly-CSharp.cs"
	cs_file.write_text(IMPLEMENTATIONS_CS)
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	index_cs_file(connection, cs_file, source="rust")
	populate_fts(connection)
	return connection


@pytest.mark.asyncio
async def test_find_implementations_returns_subclasses(implementations_connection):
	result = await tool_find_implementations(implementations_connection, None, "BaseEntity")
	fqns = {r["fully_qualified_name"] for r in result}
	assert "Rust.BasePlayer" in fqns
	assert "Rust.BaseVehicle" in fqns


@pytest.mark.asyncio
async def test_find_implementations_returns_empty_for_unknown(implementations_connection):
	result = await tool_find_implementations(implementations_connection, None, "NoSuchType")
	assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source venv/bin/activate && python -m pytest tests/test_tools.py::test_find_implementations_returns_subclasses -v
```

Expected: FAIL (`cannot import name 'tool_find_implementations'`)

- [ ] **Step 3: Add `query_find_implementations` to the import in `rust_dll_mcp/tools.py`**

Update the `from rust_dll_mcp.db import ...` block to include `query_find_implementations`.

- [ ] **Step 4: Add `tool_find_implementations` to `rust_dll_mcp/tools.py`**

Append:

```python
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
```

- [ ] **Step 5: Register `find_implementations` in `rust_dll_mcp/server.py`**

Add `tool_find_implementations` to the import from `rust_dll_mcp.tools`.

Add to `list_tools()` return list:

```python
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
```

Add to `call_tool()` dispatch:

```python
elif name == "find_implementations":
	result = await tool_find_implementations(current_connection, previous_connection, arguments["type_name"])
```

- [ ] **Step 6: Run full test suite**

```bash
source venv/bin/activate && python -m pytest -v
```

Expected: All tests pass.

- [ ] **Step 7: Commit everything**

```bash
git add rust_dll_mcp/db.py pipeline/parse_cs.py pipeline/build_index.py rust_dll_mcp/tools.py rust_dll_mcp/server.py tests/test_db.py tests/test_parse_cs.py tests/test_build_index.py tests/test_tools.py docs/superpowers/specs/2026-04-20-comprehensive-dll-indexing-design.md docs/superpowers/plans/2026-04-20-comprehensive-dll-indexing.md
git commit -m "feat: comprehensive DLL indexing — properties, enum values, nested types, modifiers, doc comments, find_implementations, DB indexes"
```
