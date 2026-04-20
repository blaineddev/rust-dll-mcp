# Comprehensive DLL Indexing — Design Spec

**Date:** 2026-04-20

---

## Overview

Five targeted improvements to make the MCP server's knowledge of Rust DLLs more complete: property and enum value parsing, nested type tracking, queryable modifier columns, XML doc comment capture, a new `find_implementations` tool, and DB indexes for query performance.

---

## Schema Changes (`db.py`)

### `types` table — new columns

| Column | Type | Description |
|---|---|---|
| `parent_type_id` | `INTEGER REFERENCES types(id)` | null for top-level types; set for nested types |
| `is_static` | `INTEGER` | 0/1 |
| `is_abstract` | `INTEGER` | 0/1 |
| `is_sealed` | `INTEGER` | 0/1 |
| `doc_comment` | `TEXT` | extracted `/// <summary>` text |

### `members` table — new columns

| Column | Type | Description |
|---|---|---|
| `is_static` | `INTEGER` | 0/1 |
| `is_abstract` | `INTEGER` | 0/1 |
| `is_override` | `INTEGER` | 0/1 |
| `is_virtual` | `INTEGER` | 0/1 |
| `doc_comment` | `TEXT` | extracted `/// <summary>` text |

### New `members.kind` values

- `'property'` — C# property (auto, read-only, or full get/set)
- `'enum_value'` — member of an enum type

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_types_fqn        ON types(fully_qualified_name);
CREATE INDEX IF NOT EXISTS idx_types_name        ON types(name);
CREATE INDEX IF NOT EXISTS idx_types_base_type   ON types(base_type);
CREATE INDEX IF NOT EXISTS idx_types_parent      ON types(parent_type_id);
CREATE INDEX IF NOT EXISTS idx_types_assembly    ON types(assembly_id);
CREATE INDEX IF NOT EXISTS idx_members_type_id   ON members(type_id);
CREATE INDEX IF NOT EXISTS idx_members_name      ON members(name);
CREATE INDEX IF NOT EXISTS idx_assemblies_source ON assemblies(source);
```

### FTS5 tables — add `doc_comment`

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS types_fts USING fts5(
    fully_qualified_name, source_code, doc_comment,
    content='types'
);

CREATE VIRTUAL TABLE IF NOT EXISTS members_fts USING fts5(
    name, source_code, doc_comment,
    content='members'
);
```

No changes to FTS query logic — `MATCH` searches all indexed columns by default.

---

## Parser Changes (`pipeline/parse_cs.py`)

### Properties

Add `PROPERTY_PATTERN` to capture all property forms:
- Auto-property: `public int Health { get; set; }`
- Read-only: `public string Name { get; }`
- Expression-bodied: `public bool IsAlive => health > 0;`
- Full get/set with bodies

Stored as `kind = 'property'`, `return_type` = property type, `parameters = []`. Body (if any) captured as `source_code`.

### Enum values

When `kind == 'enum'`, parse the enum body for `NAME` and `NAME = value` entries instead of returning `[]`. Stored as `kind = 'enum_value'`, `name` = identifier, `return_type` = explicit value string if present (e.g. `"42"`), otherwise `''`.

### Nested types

`ParsedType` gains an optional `parent_name: str` field. Instead of stripping nested type declarations with `_strip_nested_types`, parse them recursively and attach to the parent. In `build_index.py`, nested types are inserted after the parent with `parent_type_id` set. The parent's `source_code` still has nested bodies stripped to keep it readable.

### XML doc comments

Before each type and member declaration, scan backward for consecutive `/// ` lines and extract the text content. Strip XML tags (`<summary>`, `<param>`, `<returns>`) and store the plain text in `doc_comment`. If no doc comment exists, store `None`.

### Modifier extraction

`METHOD_PATTERN` already captures a `modifiers` group. Parse it to populate `is_static`, `is_abstract`, `is_virtual`, `is_override` on members. For types, extract modifiers from the type declaration match to populate `is_static`, `is_abstract`, `is_sealed`.

---

## Pipeline Changes (`pipeline/build_index.py`)

- Pass new modifier and `doc_comment` fields on `INSERT INTO types`
- Pass new modifier and `doc_comment` fields on `INSERT INTO members`
- After inserting a parent type, recursively insert its nested types with `parent_type_id` set
- Pass `return_type` for enum values (the explicit value string)

---

## New Tool: `find_implementations`

### Query (`db.py` — `query_find_implementations`)

**Input:** `type_name: str` — name or FQN of a base class or interface

**Logic:**
1. Match types where `base_type` = `type_name` (case-insensitive, partial FQN aware) using `idx_types_base_type`
2. Match types where `interfaces` JSON column contains `type_name` via `LIKE`
3. Union results, tag each with `match_reason` (`'base_type'` or `'interface'`)

**Returns per row:** `fully_qualified_name, kind, assembly_name, match_reason`

### Tool handler (`tools.py`)

Tool name: `find_implementations`
Input schema: `{ "type_name": { "type": "string" } }`
Returns formatted list of matching types grouped by `match_reason`.

### Registration (`server.py`)

Register `find_implementations` alongside the existing 6 tools (making 7 total).

---

## File Change Summary

| File | Change |
|---|---|
| `rust_dll_mcp/db.py` | New columns, 8 indexes, updated FTS tables, `query_find_implementations` |
| `pipeline/parse_cs.py` | Property, enum value, doc comment, modifier, nested type parsing |
| `pipeline/build_index.py` | Insert new fields, handle nested type parent linkage |
| `rust_dll_mcp/tools.py` | `find_implementations` handler |
| `rust_dll_mcp/server.py` | Register `find_implementations` tool |

---

## Coding Conventions (unchanged)

- Single tab indentation
- No abbreviated variable names
- `pathlib.Path` throughout
- `connection.row_factory = sqlite3.Row`
