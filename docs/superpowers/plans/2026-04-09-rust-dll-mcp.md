# Rust DLL MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python MCP server that decompiles Rust game server DLLs monthly via GitHub Actions and exposes them as a searchable SQLite knowledge base, installable with `uvx rust-dll-mcp`.

**Architecture:** A GitHub Actions pipeline downloads depot 258552 via SteamCMD, decompiles all DLLs with ilspycmd, and indexes everything into a SQLite DB uploaded as a release asset. The local MCP server fetches a `manifest.json` on startup, auto-downloads the DB if stale, and exposes 6 query tools over stdio transport.

**Tech Stack:** Python 3.11+, `mcp` SDK, `httpx`, `platformdirs`, `sqlite3` (stdlib), `pytest`, `respx`, GitHub Actions, SteamCMD, ilspycmd (.NET tool), `uv`/`uvx` for distribution.

---

## File Map

```
rust-dll-mcp/
├── .github/workflows/monthly-wipe-pipeline.yml
├── pipeline/
│   ├── __init__.py
│   ├── parse_cs.py          # C# source parser → ParsedType / ParsedMember dataclasses
│   ├── build_index.py       # walks decompiled .cs files → populates SQLite
│   ├── download_dlls.py     # SteamCMD depot 258552 pull
│   └── decompile.py         # ilspycmd invocation over all DLLs
├── rust_dll_mcp/
│   ├── __init__.py
│   ├── __main__.py          # main() entry point, asyncio.run(run())
│   ├── server.py            # startup flow + MCP wiring
│   ├── db.py                # schema creation + all 6 query functions
│   ├── tools.py             # 6 async tool handler functions
│   └── updater.py           # manifest fetch + streaming DB download
├── tests/
│   ├── conftest.py          # shared fixtures: in-memory DB, sample C# content
│   ├── test_parse_cs.py
│   ├── test_build_index.py
│   ├── test_db.py
│   ├── test_updater.py
│   └── test_tools.py
├── manifest.json
└── pyproject.toml
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `rust_dll_mcp/__init__.py`
- Create: `rust_dll_mcp/__main__.py`
- Create: `pipeline/__init__.py`
- Create: `tests/conftest.py`
- Create: `manifest.json`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "rust-dll-mcp"
version = "0.1.0"
description = "MCP server exposing Rust game server DLLs as a searchable knowledge base"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
	"mcp>=1.0.0",
	"httpx>=0.27.0",
	"platformdirs>=4.0.0",
]

[project.scripts]
rust-dll-mcp = "rust_dll_mcp.__main__:main"

[dependency-groups]
dev = [
	"pytest>=8.0.0",
	"pytest-asyncio>=0.23.0",
	"respx>=0.21.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create empty package init files**

`rust_dll_mcp/__init__.py` — empty file.
`pipeline/__init__.py` — empty file.

- [ ] **Step 3: Create stub `rust_dll_mcp/__main__.py`**

```python
import asyncio


def main() -> None:
	asyncio.run(_run())


async def _run() -> None:
	pass


if __name__ == "__main__":
	main()
```

- [ ] **Step 4: Create `tests/conftest.py`**

```python
import sqlite3
import pytest
from rust_dll_mcp.db import create_schema


@pytest.fixture
def db_connection():
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	yield connection
	connection.close()


SAMPLE_CS = """\
using System;
using System.Collections.Generic;

namespace Rust
{
	public class PlayerInventory : BaseEntity
	{
		public ItemContainer containerMain;
		public int capacity = 24;

		public void GiveItem(Item item, int amount = 1)
		{
			containerMain.AddItem(item, amount);
		}

		public bool HasItem(int itemID)
		{
			return containerMain.FindItemByItemID(itemID) != null;
		}

		public int GetAmount(int itemID)
		{
			return containerMain.GetAmount(itemID, false);
		}
	}
}
"""
```

- [ ] **Step 5: Create placeholder `manifest.json`**

```json
{
	"buildId": "",
	"wipeDate": "",
	"releaseUrl": "",
	"previousReleaseUrl": ""
}
```

- [ ] **Step 6: Install dependencies and verify**

Run: `uv sync --dev`
Expected: dependencies installed, no errors.

Run: `python -c "import rust_dll_mcp"`
Expected: no output, no errors.

- [ ] **Step 7: Commit**

```bash
git init
git add pyproject.toml rust_dll_mcp/ pipeline/ tests/ manifest.json
git commit -m "feat: project scaffold"
```

---

## Task 2: SQLite Schema

**Files:**
- Create: `rust_dll_mcp/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

`tests/test_db.py`:
```python
import sqlite3
import pytest
from rust_dll_mcp.db import create_schema


@pytest.fixture
def bare_connection():
	connection = sqlite3.connect(":memory:")
	yield connection
	connection.close()


def test_schema_creates_assemblies_table(bare_connection):
	create_schema(bare_connection)
	cursor = bare_connection.execute(
		"SELECT name FROM sqlite_master WHERE type='table' AND name='assemblies'"
	)
	assert cursor.fetchone() is not None


def test_schema_creates_types_table(bare_connection):
	create_schema(bare_connection)
	cursor = bare_connection.execute(
		"SELECT name FROM sqlite_master WHERE type='table' AND name='types'"
	)
	assert cursor.fetchone() is not None


def test_schema_creates_members_table(bare_connection):
	create_schema(bare_connection)
	cursor = bare_connection.execute(
		"SELECT name FROM sqlite_master WHERE type='table' AND name='members'"
	)
	assert cursor.fetchone() is not None


def test_schema_creates_wipe_metadata_table(bare_connection):
	create_schema(bare_connection)
	cursor = bare_connection.execute(
		"SELECT name FROM sqlite_master WHERE type='table' AND name='wipe_metadata'"
	)
	assert cursor.fetchone() is not None


def test_schema_creates_types_fts_table(bare_connection):
	create_schema(bare_connection)
	cursor = bare_connection.execute(
		"SELECT name FROM sqlite_master WHERE type='table' AND name='types_fts'"
	)
	assert cursor.fetchone() is not None


def test_schema_creates_members_fts_table(bare_connection):
	create_schema(bare_connection)
	cursor = bare_connection.execute(
		"SELECT name FROM sqlite_master WHERE type='table' AND name='members_fts'"
	)
	assert cursor.fetchone() is not None


def test_schema_is_idempotent(bare_connection):
	create_schema(bare_connection)
	create_schema(bare_connection)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'create_schema'`

- [ ] **Step 3: Implement `rust_dll_mcp/db.py`**

```python
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
			interfaces TEXT
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
			source_code TEXT
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
			content='types'
		);

		CREATE VIRTUAL TABLE IF NOT EXISTS members_fts USING fts5(
			name,
			source_code,
			content='members'
		);
	""")
	connection.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add rust_dll_mcp/db.py tests/test_db.py
git commit -m "feat: sqlite schema"
```

---

## Task 3: C# Source Parser

**Files:**
- Create: `pipeline/parse_cs.py`
- Create: `tests/test_parse_cs.py`

- [ ] **Step 1: Write failing tests**

`tests/test_parse_cs.py`:
```python
import pytest
from tests.conftest import SAMPLE_CS
from pipeline.parse_cs import parse_cs_file, ParsedType, ParsedMember


def test_parse_finds_one_type():
	types = parse_cs_file(SAMPLE_CS)
	assert len(types) == 1


def test_parse_type_name():
	types = parse_cs_file(SAMPLE_CS)
	assert types[0].name == "PlayerInventory"


def test_parse_type_namespace():
	types = parse_cs_file(SAMPLE_CS)
	assert types[0].namespace == "Rust"


def test_parse_type_fully_qualified_name():
	types = parse_cs_file(SAMPLE_CS)
	assert types[0].fully_qualified_name == "Rust.PlayerInventory"


def test_parse_type_kind():
	types = parse_cs_file(SAMPLE_CS)
	assert types[0].kind == "class"


def test_parse_type_access_modifier():
	types = parse_cs_file(SAMPLE_CS)
	assert types[0].access_modifier == "public"


def test_parse_type_base_type():
	types = parse_cs_file(SAMPLE_CS)
	assert types[0].base_type == "BaseEntity"


def test_parse_type_has_three_methods():
	types = parse_cs_file(SAMPLE_CS)
	methods = [m for m in types[0].members if m.kind == "method"]
	assert len(methods) == 3


def test_parse_type_has_two_fields():
	types = parse_cs_file(SAMPLE_CS)
	fields = [m for m in types[0].members if m.kind == "field"]
	assert len(fields) == 2


def test_parse_method_name():
	types = parse_cs_file(SAMPLE_CS)
	method_names = [m.name for m in types[0].members if m.kind == "method"]
	assert "GiveItem" in method_names


def test_parse_method_return_type():
	types = parse_cs_file(SAMPLE_CS)
	give_item = next(m for m in types[0].members if m.name == "GiveItem")
	assert give_item.return_type == "void"


def test_parse_method_parameters():
	types = parse_cs_file(SAMPLE_CS)
	give_item = next(m for m in types[0].members if m.name == "GiveItem")
	assert len(give_item.parameters) == 2
	assert give_item.parameters[0]["name"] == "item"
	assert give_item.parameters[0]["type"] == "Item"


def test_parse_method_source_contains_body():
	types = parse_cs_file(SAMPLE_CS)
	give_item = next(m for m in types[0].members if m.name == "GiveItem")
	assert "containerMain.AddItem" in give_item.source_code


def test_parse_field_name():
	types = parse_cs_file(SAMPLE_CS)
	field_names = [m.name for m in types[0].members if m.kind == "field"]
	assert "containerMain" in field_names


def test_parse_enum():
	enum_cs = """\
namespace Rust
{
	public enum HitArea
	{
		Head = 1,
		Body = 2,
		Hand = 4,
	}
}
"""
	types = parse_cs_file(enum_cs)
	assert len(types) == 1
	assert types[0].kind == "enum"
	assert types[0].name == "HitArea"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_parse_cs.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_cs_file'`

- [ ] **Step 3: Implement `pipeline/parse_cs.py`**

```python
import re
import json
from dataclasses import dataclass, field as dataclass_field


@dataclass
class ParsedMember:
	name: str
	kind: str
	return_type: str
	parameters: list[dict]
	access_modifier: str
	attributes: list[str]
	source_code: str


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


NAMESPACE_PATTERN = re.compile(r'\bnamespace\s+([\w.]+)')

TYPE_DECLARATION_PATTERN = re.compile(
	r'(?P<access>public|internal|private|protected)?\s*'
	r'(?:abstract|sealed|static|partial|readonly|\s)*'
	r'(?P<kind>class|struct|enum|interface|delegate)\s+'
	r'(?P<name>\w+)'
	r'(?:\s*<[^>]+>)?'
	r'(?:\s*:\s*(?P<inheritance>[^{]+))?',
	re.MULTILINE,
)

ATTRIBUTE_PATTERN = re.compile(r'\[(\w+(?:\([^)]*\))?)\]')

METHOD_PATTERN = re.compile(
	r'(?P<attributes>(?:\[[\w\s,.()"\']+\]\s*)*)'
	r'(?P<access>public|private|protected internal|protected|internal|private protected)\s+'
	r'(?P<modifiers>(?:(?:static|virtual|abstract|override|sealed|async|extern|new|unsafe|partial)\s+)*)'
	r'(?P<return_type>[\w\[\]<>.,\s?\*]+?)\s+'
	r'(?P<name>\w+)\s*'
	r'(?:<[^>]+>)?\s*'
	r'\((?P<params>[^)]*)\)',
	re.MULTILINE,
)

FIELD_PATTERN = re.compile(
	r'(?P<access>public|private|protected internal|protected|internal|private protected)\s+'
	r'(?P<modifiers>(?:(?:static|readonly|const|volatile)\s+)*)'
	r'(?P<type>[\w\[\]<>.,\s?\*]+?)\s+'
	r'(?P<name>\w+)\s*[;=]',
	re.MULTILINE,
)


def _extract_block(source: str, start: int) -> tuple[str, int]:
	"""Extract content from the first '{' at/after start through its matching '}'."""
	brace_start = source.find('{', start)
	if brace_start == -1:
		return '', len(source)

	depth = 0
	in_string = False
	in_verbatim = False
	in_char = False
	i = brace_start

	while i < len(source):
		char = source[i]
		if in_verbatim:
			if char == '"' and i + 1 < len(source) and source[i + 1] == '"':
				i += 2
				continue
			elif char == '"':
				in_verbatim = False
		elif in_string:
			if char == '\\':
				i += 2
				continue
			elif char == '"':
				in_string = False
		elif in_char:
			if char == '\\':
				i += 2
				continue
			elif char == "'":
				in_char = False
		else:
			if char == '@' and i + 1 < len(source) and source[i + 1] == '"':
				in_verbatim = True
				i += 2
				continue
			elif char == '"':
				in_string = True
			elif char == "'":
				in_char = True
			elif char == '{':
				depth += 1
			elif char == '}':
				depth -= 1
				if depth == 0:
					return source[brace_start:i + 1], i + 1
		i += 1

	return source[brace_start:], len(source)


def _parse_parameters(params_str: str) -> list[dict]:
	if not params_str.strip():
		return []
	parameters = []
	for param in params_str.split(','):
		param = param.strip()
		# strip default values
		param = param.split('=')[0].strip()
		# strip attributes like [In], out/ref/params keywords
		param = re.sub(r'\[[\w\s]+\]', '', param).strip()
		param = re.sub(r'\b(out|ref|in|params)\b\s*', '', param).strip()
		parts = param.rsplit(None, 1)
		if len(parts) == 2:
			parameters.append({"type": parts[0].strip(), "name": parts[1].strip()})
	return parameters


def _parse_inheritance(inheritance_str: str) -> tuple[str, list[str]]:
	"""Split 'BaseClass, IInterface1, IInterface2' into (base_type, interfaces)."""
	if not inheritance_str:
		return '', []
	parts = [part.strip() for part in inheritance_str.split(',')]
	# Heuristic: first entry starting with uppercase non-I or known base = base class
	# Simple rule: first entry is base_type if it doesn't start with 'I' followed by uppercase
	base_type = ''
	interfaces = []
	for i, part in enumerate(parts):
		if i == 0 and not re.match(r'^I[A-Z]', part):
			base_type = part
		else:
			interfaces.append(part)
	return base_type, interfaces


def _parse_members(type_body: str) -> list[ParsedMember]:
	members = []
	seen_names_kinds = set()

	# Extract method members
	for match in METHOD_PATTERN.finditer(type_body):
		name = match.group('name')
		kind = 'constructor' if match.group('return_type').strip() == name else 'method'
		return_type = match.group('return_type').strip()
		if kind == 'constructor':
			return_type = ''

		key = (name, kind)
		if key in seen_names_kinds:
			continue
		seen_names_kinds.add(key)

		# Extract the method body
		body, _ = _extract_block(type_body, match.end())
		source_code = type_body[match.start():match.start() + (match.end() - match.start()) + len(body)]

		attributes_str = match.group('attributes') or ''
		attributes = ATTRIBUTE_PATTERN.findall(attributes_str)

		members.append(ParsedMember(
			name=name,
			kind=kind,
			return_type=return_type,
			parameters=_parse_parameters(match.group('params')),
			access_modifier=match.group('access'),
			attributes=attributes,
			source_code=source_code.strip(),
		))

	# Extract field members (only those not already captured as methods)
	method_names = {m.name for m in members}
	for match in FIELD_PATTERN.finditer(type_body):
		name = match.group('name')
		if name in method_names:
			continue
		key = (name, 'field')
		if key in seen_names_kinds:
			continue
		seen_names_kinds.add(key)

		members.append(ParsedMember(
			name=name,
			kind='field',
			return_type=match.group('type').strip(),
			parameters=[],
			access_modifier=match.group('access'),
			attributes=[],
			source_code=match.group(0).strip(),
		))

	return members


def parse_cs_file(source: str) -> list[ParsedType]:
	"""Parse a decompiled C# source string and return a list of ParsedType objects."""
	namespace_match = NAMESPACE_PATTERN.search(source)
	namespace = namespace_match.group(1) if namespace_match else ''

	parsed_types = []
	search_start = 0

	while True:
		match = TYPE_DECLARATION_PATTERN.search(source, search_start)
		if not match:
			break

		kind = match.group('kind')
		name = match.group('name')
		access_modifier = match.group('access') or 'internal'
		inheritance_str = (match.group('inheritance') or '').strip()
		base_type, interfaces = _parse_inheritance(inheritance_str)
		fully_qualified_name = f"{namespace}.{name}" if namespace else name

		body, end_pos = _extract_block(source, match.end())
		type_source = source[match.start():end_pos]

		members = _parse_members(body) if kind != 'enum' else []

		parsed_types.append(ParsedType(
			namespace=namespace,
			name=name,
			fully_qualified_name=fully_qualified_name,
			kind=kind,
			access_modifier=access_modifier,
			base_type=base_type,
			interfaces=interfaces,
			source_code=type_source,
			members=members,
		))

		search_start = end_pos

	return parsed_types
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_parse_cs.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/parse_cs.py tests/test_parse_cs.py tests/conftest.py
git commit -m "feat: c# source parser"
```

---

## Task 4: Database Indexer

**Files:**
- Create: `pipeline/build_index.py`
- Create: `tests/test_build_index.py`

- [ ] **Step 1: Write failing tests**

`tests/test_build_index.py`:
```python
import sqlite3
import json
import pytest
from pathlib import Path
from tests.conftest import SAMPLE_CS
from pipeline.build_index import index_cs_file, populate_fts, write_wipe_metadata
from rust_dll_mcp.db import create_schema


@pytest.fixture
def indexed_connection(tmp_path):
	cs_file = tmp_path / "Assembly-CSharp.cs"
	cs_file.write_text(SAMPLE_CS)

	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)

	assembly_id = index_cs_file(connection, cs_file, source="rust")
	populate_fts(connection)
	yield connection, assembly_id
	connection.close()


def test_index_creates_assembly(indexed_connection):
	connection, assembly_id = indexed_connection
	row = connection.execute(
		"SELECT * FROM assemblies WHERE id = ?", (assembly_id,)
	).fetchone()
	assert row is not None
	assert row["name"] == "Assembly-CSharp"
	assert row["source"] == "rust"


def test_index_creates_type(indexed_connection):
	connection, _ = indexed_connection
	row = connection.execute(
		"SELECT * FROM types WHERE name = 'PlayerInventory'"
	).fetchone()
	assert row is not None
	assert row["fully_qualified_name"] == "Rust.PlayerInventory"
	assert row["kind"] == "class"


def test_index_creates_members(indexed_connection):
	connection, _ = indexed_connection
	rows = connection.execute(
		"SELECT * FROM members WHERE name = 'GiveItem'"
	).fetchall()
	assert len(rows) == 1


def test_index_member_parameters_json(indexed_connection):
	connection, _ = indexed_connection
	row = connection.execute(
		"SELECT parameters FROM members WHERE name = 'GiveItem'"
	).fetchone()
	params = json.loads(row["parameters"])
	assert params[0]["name"] == "item"


def test_fts_finds_type_by_name(indexed_connection):
	connection, _ = indexed_connection
	rows = connection.execute(
		"SELECT * FROM types_fts WHERE types_fts MATCH 'PlayerInventory'"
	).fetchall()
	assert len(rows) >= 1


def test_fts_finds_member_by_name(indexed_connection):
	connection, _ = indexed_connection
	rows = connection.execute(
		"SELECT * FROM members_fts WHERE members_fts MATCH 'GiveItem'"
	).fetchall()
	assert len(rows) >= 1


def test_write_wipe_metadata(indexed_connection):
	connection, _ = indexed_connection
	write_wipe_metadata(connection, build_id="12345", wipe_date="2026-04-03", previous_build_id="12000")
	row = connection.execute("SELECT * FROM wipe_metadata").fetchone()
	assert row["build_id"] == "12345"
	assert row["previous_build_id"] == "12000"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_build_index.py -v`
Expected: FAIL — `ImportError: cannot import name 'index_cs_file'`

- [ ] **Step 3: Implement `pipeline/build_index.py`**

```python
import sqlite3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline.parse_cs import parse_cs_file


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

	for parsed_type in parsed_types:
		cursor = connection.execute(
			"""
			INSERT INTO types (
				assembly_id, namespace, name, fully_qualified_name,
				kind, access_modifier, source_code, base_type, interfaces
			) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
			),
		)
		type_id = cursor.lastrowid

		for member in parsed_type.members:
			connection.execute(
				"""
				INSERT INTO members (
					type_id, name, kind, return_type, parameters,
					access_modifier, attributes, source_code
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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

	parser = argparse.ArgumentParser(description="Build SQLite index from decompiled .cs files")
	parser.add_argument("source_dir", type=Path)
	parser.add_argument("db_path", type=Path)
	parser.add_argument("--build-id", required=True)
	parser.add_argument("--wipe-date", required=True)
	parser.add_argument("--previous-build-id")
	args = parser.parse_args()

	build_index(args.source_dir, args.db_path, args.build_id, args.wipe_date, args.previous_build_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_build_index.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/build_index.py tests/test_build_index.py
git commit -m "feat: database indexer"
```

---

## Task 5: DLL Downloader

**Files:**
- Create: `pipeline/download_dlls.py`

No unit tests — this script requires SteamCMD and network access. It is validated by the GitHub Actions run.

- [ ] **Step 1: Implement `pipeline/download_dlls.py`**

```python
"""
Download the RustDedicated managed DLL depot via SteamCMD.

App ID:   258550 (RustDedicated)
Depot ID: 258552 (Windows managed DLLs)

Usage:
	python pipeline/download_dlls.py --output-dir work/dlls
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


STEAM_APP_ID = "258550"
STEAM_DEPOT_ID = "258552"
STEAMCMD_URL_LINUX = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"
STEAMCMD_URL_WINDOWS = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"


def install_steamcmd(install_dir: Path) -> Path:
	install_dir.mkdir(parents=True, exist_ok=True)
	system = platform.system()

	if system == "Linux":
		archive = install_dir / "steamcmd_linux.tar.gz"
		subprocess.run(
			["curl", "-sSL", "-o", str(archive), STEAMCMD_URL_LINUX],
			check=True,
		)
		subprocess.run(["tar", "-xzf", str(archive), "-C", str(install_dir)], check=True)
		steamcmd_executable = install_dir / "steamcmd.sh"
	elif system == "Windows":
		archive = install_dir / "steamcmd.zip"
		subprocess.run(
			["curl", "-sSL", "-o", str(archive), STEAMCMD_URL_WINDOWS],
			check=True,
		)
		shutil.unpack_archive(str(archive), str(install_dir))
		steamcmd_executable = install_dir / "steamcmd.exe"
	else:
		print(f"Unsupported platform: {system}", file=sys.stderr)
		sys.exit(1)

	return steamcmd_executable


def download_depot(steamcmd_executable: Path, output_dir: Path) -> None:
	output_dir.mkdir(parents=True, exist_ok=True)
	subprocess.run(
		[
			str(steamcmd_executable),
			"+@NoPromptForPassword", "1",
			"+login", "anonymous",
			"+download_depot", STEAM_APP_ID, STEAM_DEPOT_ID,
			"+quit",
		],
		check=True,
	)

	# SteamCMD downloads to a fixed path; copy to output_dir
	steam_download_path = Path.home() / ".steam" / "steamapps" / "content" / f"app_{STEAM_APP_ID}" / f"depot_{STEAM_DEPOT_ID}"
	if not steam_download_path.exists():
		# Fallback Windows path
		steam_download_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Steam" / "steamapps" / "content" / f"app_{STEAM_APP_ID}" / f"depot_{STEAM_DEPOT_ID}"

	if not steam_download_path.exists():
		print(f"ERROR: Could not find downloaded depot at {steam_download_path}", file=sys.stderr)
		sys.exit(1)

	dll_files = list(steam_download_path.rglob("*.dll"))
	print(f"Copying {len(dll_files)} DLLs to {output_dir}", flush=True)
	for dll_file in dll_files:
		shutil.copy2(dll_file, output_dir / dll_file.name)

	print(f"Done. {len(dll_files)} DLLs in {output_dir}", flush=True)


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Download RustDedicated managed DLLs via SteamCMD")
	parser.add_argument("--output-dir", type=Path, default=Path("work/dlls"))
	parser.add_argument("--steamcmd-dir", type=Path, default=Path("work/steamcmd"))
	args = parser.parse_args()

	steamcmd_executable = install_steamcmd(args.steamcmd_dir)
	download_depot(steamcmd_executable, args.output_dir)
```

- [ ] **Step 2: Commit**

```bash
git add pipeline/download_dlls.py
git commit -m "feat: steamcmd dll downloader"
```

---

## Task 6: DLL Decompiler

**Files:**
- Create: `pipeline/decompile.py`

No unit tests — requires .NET runtime and actual DLL files. Validated by GitHub Actions.

- [ ] **Step 1: Implement `pipeline/decompile.py`**

```python
"""
Decompile all .dll files in a directory to .cs source files using ilspycmd.

Usage:
	python pipeline/decompile.py --dlls-dir work/dlls --output-dir work/source
"""
import argparse
import subprocess
import sys
from pathlib import Path


def install_ilspycmd() -> None:
	result = subprocess.run(
		["dotnet", "tool", "install", "--global", "ilspycmd"],
		capture_output=True,
		text=True,
	)
	# exit code 1 with "already installed" message is acceptable
	if result.returncode != 0 and "already installed" not in result.stderr:
		print(result.stderr, file=sys.stderr)
		sys.exit(1)
	print("ilspycmd ready", flush=True)


def decompile_dll(dll_path: Path, output_dir: Path) -> bool:
	"""Decompile a single DLL to a .cs file. Returns True on success."""
	output_file = output_dir / f"{dll_path.stem}.cs"
	result = subprocess.run(
		["ilspycmd", "--outputdir", str(output_dir), str(dll_path)],
		capture_output=True,
		text=True,
		timeout=120,
	)
	if result.returncode != 0:
		print(f"  WARNING: failed to decompile {dll_path.name}: {result.stderr[:200]}", file=sys.stderr, flush=True)
		return False
	return True


def decompile_all(dlls_dir: Path, output_dir: Path) -> None:
	output_dir.mkdir(parents=True, exist_ok=True)
	dll_files = list(dlls_dir.glob("*.dll"))
	print(f"Decompiling {len(dll_files)} DLLs", flush=True)

	success_count = 0
	fail_count = 0

	for dll_file in dll_files:
		if decompile_dll(dll_file, output_dir):
			success_count += 1
		else:
			fail_count += 1

	print(f"Done. {success_count} succeeded, {fail_count} failed.", flush=True)


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="Decompile DLLs to C# source using ilspycmd")
	parser.add_argument("--dlls-dir", type=Path, default=Path("work/dlls"))
	parser.add_argument("--output-dir", type=Path, default=Path("work/source"))
	parser.add_argument("--skip-install", action="store_true")
	args = parser.parse_args()

	if not args.skip_install:
		install_ilspycmd()

	decompile_all(args.dlls_dir, args.output_dir)
```

- [ ] **Step 2: Commit**

```bash
git add pipeline/decompile.py
git commit -m "feat: ilspycmd decompiler script"
```

---

## Task 7: GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/monthly-wipe-pipeline.yml`

- [ ] **Step 1: Create `.github/workflows/monthly-wipe-pipeline.yml`**

```yaml
name: Monthly Wipe Pipeline

on:
  schedule:
    # First Thursday of each month at 18:00 UTC
    - cron: '0 18 1-7 * 4'
  workflow_dispatch:
    inputs:
      build_id:
        description: 'Steam build ID (leave blank to auto-detect)'
        required: false

permissions:
  contents: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Set up .NET (for ilspycmd)
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '8.0.x'

      - name: Install Python dependencies
        run: pip install httpx

      - name: Download managed DLLs via SteamCMD
        run: python pipeline/download_dlls.py --output-dir work/dlls

      - name: Decompile DLLs to C# source
        run: python pipeline/decompile.py --dlls-dir work/dlls --output-dir work/source

      - name: Determine wipe date and build ID
        id: wipe_info
        run: |
          WIPE_DATE=$(date -u +%Y-%m-%d)
          BUILD_ID="${{ github.event.inputs.build_id }}"
          if [ -z "$BUILD_ID" ]; then
            BUILD_ID=$(date -u +%Y%m%d%H%M)
          fi
          echo "wipe_date=$WIPE_DATE" >> "$GITHUB_OUTPUT"
          echo "build_id=$BUILD_ID" >> "$GITHUB_OUTPUT"

      - name: Get previous build ID from manifest
        id: prev_build
        run: |
          PREV_BUILD_ID=$(python -c "import json; data=json.load(open('manifest.json')); print(data.get('buildId',''))")
          echo "previous_build_id=$PREV_BUILD_ID" >> "$GITHUB_OUTPUT"

      - name: Build SQLite index
        run: |
          python pipeline/build_index.py \
            work/source \
            rust_dlls.db \
            --build-id "${{ steps.wipe_info.outputs.build_id }}" \
            --wipe-date "${{ steps.wipe_info.outputs.wipe_date }}" \
            --previous-build-id "${{ steps.prev_build.outputs.previous_build_id }}"

      - name: Create GitHub Release and upload DB
        id: create_release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          TAG="wipe-${{ steps.wipe_info.outputs.wipe_date }}"
          gh release create "$TAG" rust_dlls.db \
            --title "Wipe ${{ steps.wipe_info.outputs.wipe_date }}" \
            --notes "Automated decompilation for wipe ${{ steps.wipe_info.outputs.wipe_date }}. Build ID: ${{ steps.wipe_info.outputs.build_id }}"
          RELEASE_URL=$(gh release view "$TAG" --json assets --jq '.assets[0].url')
          echo "release_url=$RELEASE_URL" >> "$GITHUB_OUTPUT"

      - name: Get previous release URL
        id: prev_release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          PREV_URL=$(gh release list --limit 2 --json tagName,assets \
            | python -c "
          import json, sys
          releases = json.load(sys.stdin)
          if len(releases) >= 2:
              assets = releases[1].get('assets', [])
              print(assets[0]['url'] if assets else '')
          else:
              print('')
          ")
          echo "previous_release_url=$PREV_URL" >> "$GITHUB_OUTPUT"

      - name: Update manifest.json and commit
        run: |
          python -c "
          import json
          manifest = {
              'buildId': '${{ steps.wipe_info.outputs.build_id }}',
              'wipeDate': '${{ steps.wipe_info.outputs.wipe_date }}',
              'releaseUrl': '${{ steps.create_release.outputs.release_url }}',
              'previousReleaseUrl': '${{ steps.prev_release.outputs.previous_release_url }}'
          }
          with open('manifest.json', 'w') as f:
              json.dump(manifest, f, indent='\t')
              f.write('\n')
          "
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add manifest.json
          git commit -m "chore: update manifest for wipe ${{ steps.wipe_info.outputs.wipe_date }}"
          git push
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/monthly-wipe-pipeline.yml
git commit -m "feat: github actions monthly wipe pipeline"
```

---

## Task 8: Updater

**Files:**
- Create: `rust_dll_mcp/updater.py`
- Create: `tests/test_updater.py`

- [ ] **Step 1: Write failing tests**

`tests/test_updater.py`:
```python
import json
import pytest
import respx
import httpx
from pathlib import Path
from rust_dll_mcp.updater import fetch_manifest, download_file, get_current_build_id, save_build_id

MANIFEST_URL = "https://raw.githubusercontent.com/blaineddev/rust-dll-mcp/main/manifest.json"
FAKE_MANIFEST = {
	"buildId": "20260403120000",
	"wipeDate": "2026-04-03",
	"releaseUrl": "https://github.com/blaineddev/rust-dll-mcp/releases/download/wipe-2026-04-03/rust_dlls.db",
	"previousReleaseUrl": "https://github.com/blaineddev/rust-dll-mcp/releases/download/wipe-2026-03-06/rust_dlls.db",
}


@pytest.mark.asyncio
async def test_fetch_manifest_returns_dict():
	with respx.mock:
		respx.get(MANIFEST_URL).mock(return_value=httpx.Response(200, json=FAKE_MANIFEST))
		manifest = await fetch_manifest()
	assert manifest["buildId"] == "20260403120000"
	assert manifest["wipeDate"] == "2026-04-03"


@pytest.mark.asyncio
async def test_fetch_manifest_raises_on_error():
	with respx.mock:
		respx.get(MANIFEST_URL).mock(return_value=httpx.Response(404))
		with pytest.raises(RuntimeError, match="Failed to fetch manifest"):
			await fetch_manifest()


@pytest.mark.asyncio
async def test_download_file_writes_content(tmp_path):
	destination = tmp_path / "test.db"
	with respx.mock:
		respx.get("https://example.com/test.db").mock(
			return_value=httpx.Response(200, content=b"fake db content")
		)
		await download_file("https://example.com/test.db", destination)
	assert destination.read_bytes() == b"fake db content"


def test_save_and_get_build_id(tmp_path):
	save_build_id(tmp_path, "20260403120000")
	assert get_current_build_id(tmp_path) == "20260403120000"


def test_get_build_id_returns_empty_when_missing(tmp_path):
	assert get_current_build_id(tmp_path) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_updater.py -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_manifest'`

- [ ] **Step 3: Implement `rust_dll_mcp/updater.py`**

```python
import sys
from pathlib import Path

import httpx


MANIFEST_URL = "https://raw.githubusercontent.com/blaineddev/rust-dll-mcp/main/manifest.json"
BUILD_ID_FILE = "build_id.txt"
CURRENT_DB_FILE = "rust_dlls_current.db"
PREVIOUS_DB_FILE = "rust_dlls_previous.db"


async def fetch_manifest() -> dict:
	async with httpx.AsyncClient() as client:
		response = await client.get(MANIFEST_URL)
	if response.status_code != 200:
		raise RuntimeError(f"Failed to fetch manifest: HTTP {response.status_code}")
	return response.json()


async def download_file(url: str, destination: Path) -> None:
	"""Stream-download url to destination, printing progress to stderr."""
	destination.parent.mkdir(parents=True, exist_ok=True)
	print(f"Downloading {url} ...", file=sys.stderr, flush=True)
	async with httpx.AsyncClient(follow_redirects=True) as client:
		async with client.stream("GET", url) as response:
			response.raise_for_status()
			total = int(response.headers.get("content-length", 0))
			downloaded = 0
			with destination.open("wb") as file_handle:
				async for chunk in response.aiter_bytes(chunk_size=65536):
					file_handle.write(chunk)
					downloaded += len(chunk)
					if total:
						percent = downloaded * 100 // total
						print(f"\r  {percent}% ({downloaded}/{total} bytes)", file=sys.stderr, end="", flush=True)
	print(file=sys.stderr, flush=True)


def get_current_build_id(cache_dir: Path) -> str:
	build_id_path = cache_dir / BUILD_ID_FILE
	if build_id_path.exists():
		return build_id_path.read_text().strip()
	return ""


def save_build_id(cache_dir: Path, build_id: str) -> None:
	cache_dir.mkdir(parents=True, exist_ok=True)
	(cache_dir / BUILD_ID_FILE).write_text(build_id)


async def ensure_current_db(cache_dir: Path) -> Path:
	"""Return path to current DB, downloading if stale or missing."""
	manifest = await fetch_manifest()
	remote_build_id = manifest["buildId"]
	local_build_id = get_current_build_id(cache_dir)
	db_path = cache_dir / CURRENT_DB_FILE

	if local_build_id == remote_build_id and db_path.exists():
		print("Local DB is up to date.", file=sys.stderr, flush=True)
		return db_path

	print(f"Updating DB (local={local_build_id!r}, remote={remote_build_id!r})", file=sys.stderr, flush=True)
	await download_file(manifest["releaseUrl"], db_path)
	save_build_id(cache_dir, remote_build_id)
	return db_path


async def ensure_previous_db(cache_dir: Path) -> Path | None:
	"""Return path to previous wipe DB, downloading on demand. Returns None if unavailable."""
	manifest = await fetch_manifest()
	previous_url = manifest.get("previousReleaseUrl", "")
	if not previous_url:
		return None

	db_path = cache_dir / PREVIOUS_DB_FILE
	if not db_path.exists():
		await download_file(previous_url, db_path)
	return db_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_updater.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add rust_dll_mcp/updater.py tests/test_updater.py
git commit -m "feat: manifest fetcher and db updater"
```

---

## Task 9: DB Query Functions

**Files:**
- Modify: `rust_dll_mcp/db.py` (append query functions)
- Modify: `tests/test_db.py` (append query tests)

- [ ] **Step 1: Write failing query tests — append to `tests/test_db.py`**

```python
import json
from pipeline.build_index import index_cs_file, populate_fts
from tests.conftest import SAMPLE_CS
from rust_dll_mcp.db import (
	query_find_type,
	query_get_type_members,
	query_get_method_source,
	query_search_usages,
	query_get_hook_signature,
	query_diff_since_last_wipe,
)


@pytest.fixture
def populated_connection(tmp_path):
	cs_file = tmp_path / "Assembly-CSharp.cs"
	cs_file.write_text(SAMPLE_CS)
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	index_cs_file(connection, cs_file, source="rust")
	populate_fts(connection)
	yield connection
	connection.close()


@pytest.fixture
def oxide_connection(tmp_path):
	oxide_cs = """\
namespace Oxide.Game.Rust.Libraries
{
	public class RustLibrary
	{
		[HookMethod("OnPlayerDeath")]
		public object OnPlayerDeath(BasePlayer player, HitInfo info)
		{
			return null;
		}
	}
}
"""
	cs_file = tmp_path / "Oxide.Game.Rust.cs"
	cs_file.write_text(oxide_cs)
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	index_cs_file(connection, cs_file, source="oxide")
	populate_fts(connection)
	yield connection
	connection.close()


def test_find_type_returns_match(populated_connection):
	results = query_find_type(populated_connection, "PlayerInventory")
	assert len(results) >= 1
	assert any(row["name"] == "PlayerInventory" for row in results)


def test_find_type_fuzzy_match(populated_connection):
	results = query_find_type(populated_connection, "Player")
	assert len(results) >= 1


def test_find_type_returns_empty_for_unknown(populated_connection):
	results = query_find_type(populated_connection, "XyzUnknownType99999")
	assert len(results) == 0


def test_get_type_members_returns_members(populated_connection):
	members = query_get_type_members(populated_connection, "Rust.PlayerInventory")
	assert len(members) > 0
	names = [row["name"] for row in members]
	assert "GiveItem" in names


def test_get_type_members_returns_empty_for_unknown(populated_connection):
	members = query_get_type_members(populated_connection, "Unknown.Type")
	assert len(members) == 0


def test_get_method_source_returns_source(populated_connection):
	source = query_get_method_source(populated_connection, "Rust.PlayerInventory", "GiveItem")
	assert source is not None
	assert "containerMain" in source


def test_get_method_source_returns_none_for_unknown(populated_connection):
	source = query_get_method_source(populated_connection, "Rust.PlayerInventory", "NonExistentMethod")
	assert source is None


def test_search_usages_finds_symbol(populated_connection):
	results = query_search_usages(populated_connection, "containerMain")
	assert len(results) >= 1


def test_get_hook_signature_finds_hook(oxide_connection):
	results = query_get_hook_signature(oxide_connection, "OnPlayerDeath")
	assert len(results) >= 1
	assert results[0]["name"] == "OnPlayerDeath"


def test_diff_since_last_wipe_detects_added_member(tmp_path):
	old_cs = """\
namespace Rust
{
	public class Foo
	{
		public void OldMethod() { }
	}
}
"""
	new_cs = """\
namespace Rust
{
	public class Foo
	{
		public void OldMethod() { }
		public void NewMethod() { }
	}
}
"""
	old_file = tmp_path / "old.cs"
	new_file = tmp_path / "new.cs"
	old_file.write_text(old_cs)
	new_file.write_text(new_cs)

	current_conn = sqlite3.connect(":memory:")
	current_conn.row_factory = sqlite3.Row
	create_schema(current_conn)
	index_cs_file(current_conn, new_file, source="rust")
	populate_fts(current_conn)

	previous_conn = sqlite3.connect(":memory:")
	previous_conn.row_factory = sqlite3.Row
	create_schema(previous_conn)
	index_cs_file(previous_conn, old_file, source="rust")
	populate_fts(previous_conn)

	diff = query_diff_since_last_wipe(current_conn, previous_conn, "Rust.Foo")
	assert "NewMethod" in [m["name"] for m in diff["added"]]
	assert len(diff["removed"]) == 0

	current_conn.close()
	previous_conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -v -k "query"`
Expected: FAIL — `ImportError: cannot import name 'query_find_type'`

- [ ] **Step 3: Append query functions to `rust_dll_mcp/db.py`**

```python
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


def query_get_type_members(connection: sqlite3.Connection, fully_qualified_name: str) -> list[sqlite3.Row]:
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
	# Search members whose attributes contain the hook name or whose name matches directly
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add rust_dll_mcp/db.py tests/test_db.py
git commit -m "feat: db query functions"
```

---

## Task 10: MCP Tool Handlers

**Files:**
- Create: `rust_dll_mcp/tools.py`
- Create: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

`tests/test_tools.py`:
```python
import json
import sqlite3
import pytest
from pathlib import Path
from tests.conftest import SAMPLE_CS
from pipeline.build_index import index_cs_file, populate_fts
from rust_dll_mcp.db import create_schema
from rust_dll_mcp.tools import (
	tool_find_type,
	tool_get_type_members,
	tool_get_method_source,
	tool_search_usages,
	tool_get_hook_signature,
	tool_diff_since_last_wipe,
)


@pytest.fixture
def populated_connection(tmp_path):
	cs_file = tmp_path / "Assembly-CSharp.cs"
	cs_file.write_text(SAMPLE_CS)
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	index_cs_file(connection, cs_file, source="rust")
	populate_fts(connection)
	return connection


@pytest.mark.asyncio
async def test_find_type_returns_list(populated_connection):
	result = await tool_find_type(populated_connection, None, "PlayerInventory")
	assert isinstance(result, list)
	assert len(result) >= 1
	assert result[0]["fully_qualified_name"] == "Rust.PlayerInventory"


@pytest.mark.asyncio
async def test_get_type_members_returns_list(populated_connection):
	result = await tool_get_type_members(populated_connection, None, "Rust.PlayerInventory")
	names = [m["name"] for m in result]
	assert "GiveItem" in names


@pytest.mark.asyncio
async def test_get_method_source_returns_string(populated_connection):
	result = await tool_get_method_source(populated_connection, None, "Rust.PlayerInventory", "GiveItem")
	assert isinstance(result, str)
	assert "containerMain" in result


@pytest.mark.asyncio
async def test_get_method_source_unknown_returns_message(populated_connection):
	result = await tool_get_method_source(populated_connection, None, "Rust.PlayerInventory", "NoSuchMethod")
	assert "not found" in result.lower()


@pytest.mark.asyncio
async def test_search_usages_returns_list(populated_connection):
	result = await tool_search_usages(populated_connection, None, "containerMain")
	assert isinstance(result, list)
	assert len(result) >= 1


@pytest.mark.asyncio
async def test_diff_no_previous_db_returns_message(populated_connection):
	result = await tool_diff_since_last_wipe(populated_connection, None, "Rust.PlayerInventory")
	assert "not available" in result.lower() or isinstance(result, dict)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL — `ImportError: cannot import name 'tool_find_type'`

- [ ] **Step 3: Implement `rust_dll_mcp/tools.py`**

```python
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
)


async def tool_find_type(
	connection: sqlite3.Connection,
	_previous_connection: sqlite3.Connection | None,
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
	_previous_connection: sqlite3.Connection | None,
	fully_qualified_name: str,
) -> list[dict]:
	rows = query_get_type_members(connection, fully_qualified_name)
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
	_previous_connection: sqlite3.Connection | None,
	type_fqn: str,
	method: str,
) -> str:
	source = query_get_method_source(connection, type_fqn, method)
	if source is None:
		return f"Method '{method}' not found on type '{type_fqn}'."
	return source


async def tool_search_usages(
	connection: sqlite3.Connection,
	_previous_connection: sqlite3.Connection | None,
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
	_previous_connection: sqlite3.Connection | None,
	hook_name: str,
) -> list[dict]:
	rows = query_get_hook_signature(connection, hook_name)
	if not rows:
		return [{"message": f"Hook '{hook_name}' not found in Oxide assemblies."}]
	return [
		{
			"name": row["name"],
			"return_type": row["return_type"],
			"parameters": json.loads(row["parameters"] or "[]"),
			"type_fqn": row["type_fqn"],
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add rust_dll_mcp/tools.py tests/test_tools.py
git commit -m "feat: mcp tool handlers"
```

---

## Task 11: MCP Server

**Files:**
- Create: `rust_dll_mcp/server.py`

- [ ] **Step 1: Implement `rust_dll_mcp/server.py`**

```python
import json
import sqlite3
import sys
from pathlib import Path

import platformdirs
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from rust_dll_mcp.db import create_schema
from rust_dll_mcp.updater import ensure_current_db, ensure_previous_db
from rust_dll_mcp.tools import (
	tool_find_type,
	tool_get_type_members,
	tool_get_method_source,
	tool_search_usages,
	tool_get_hook_signature,
	tool_diff_since_last_wipe,
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
		else:
			result = f"Unknown tool: {name}"

		return [types.TextContent(type="text", text=json.dumps(result, indent=2) if not isinstance(result, str) else result)]

	print("rust-dll-mcp: ready.", file=sys.stderr, flush=True)
	async with stdio_server() as (read_stream, write_stream):
		await app.run(read_stream, write_stream, app.create_initialization_options())

	current_connection.close()
	if previous_connection:
		previous_connection.close()
```

- [ ] **Step 2: Run the full test suite to verify nothing broken**

Run: `uv run pytest -v`
Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add rust_dll_mcp/server.py
git commit -m "feat: mcp server wiring"
```

---

## Task 12: Entry Point + Packaging Verification

**Files:**
- Modify: `rust_dll_mcp/__main__.py`

- [ ] **Step 1: Complete `rust_dll_mcp/__main__.py`**

```python
import asyncio

from rust_dll_mcp.server import run


def main() -> None:
	asyncio.run(run())


if __name__ == "__main__":
	main()
```

- [ ] **Step 2: Verify the package entry point is wired correctly**

Run: `uv run python -c "from rust_dll_mcp.__main__ import main; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Build the package and verify it's installable**

Run: `uv build`
Expected: `dist/rust_dll_mcp-0.1.0-py3-none-any.whl` created.

Run: `uvx --from dist/rust_dll_mcp-0.1.0-py3-none-any.whl rust-dll-mcp --help 2>&1 || true`
Expected: server starts (will fail on manifest fetch without network — that's fine), no import errors.

- [ ] **Step 4: Run the full test suite one final time**

Run: `uv run pytest -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add rust_dll_mcp/__main__.py
git commit -m "feat: entry point and packaging"
```

---

## Install Instructions (for README)

**Windows:**
```powershell
winget install astral-sh.uv
claude mcp add --scope user rust-dll-mcp -- uvx rust-dll-mcp
```

**Linux/macOS:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
claude mcp add --scope user rust-dll-mcp -- uvx rust-dll-mcp
```

On first use, the server auto-downloads the latest wipe database (~varies by wipe). Subsequent starts check `manifest.json` and only re-download when a new wipe has occurred.
