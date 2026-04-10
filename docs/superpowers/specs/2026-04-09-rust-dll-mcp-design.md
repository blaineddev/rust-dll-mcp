# Rust DLL MCP — Design Spec

**Date:** 2026-04-09
**Repo:** https://github.com/blaineddev/rust-dll-mcp

---

## Overview

An MCP server that decompiles Rust game server DLLs monthly (on force wipe) and exposes them as a searchable knowledge base for Oxide/Harmony/Rust development. Everything runs free on GitHub — no paid infrastructure.

Users install via:
```bash
# Windows
winget install astral-sh.uv
claude mcp add --scope user rust-dll-mcp -- uvx rust-dll-mcp

# Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
claude mcp add --scope user rust-dll-mcp -- uvx rust-dll-mcp
```

---

## Architecture

Two independent systems sharing only the SQLite DB file:

**Pipeline** (GitHub Actions, runs monthly):
```
SteamCMD → DLLs → ilspycmd → .cs files → build_index.py → rust_dlls.db → GitHub Release asset
                                                                         → manifest.json commit
```

**MCP Server** (runs locally, stdio transport):
```
startup → fetch manifest.json → compare local DB build ID
        → if stale/missing: stream download release asset → load SQLite
        → register 6 tools → serve via stdio
```

The two systems are fully decoupled — they communicate only through `manifest.json` (in the repo) and the DB release asset.

---

## Repo & Package Structure

```
rust-dll-mcp/
├── .github/
│   └── workflows/
│       └── monthly-wipe-pipeline.yml
├── pipeline/
│   ├── download_dlls.py      # SteamCMD depot pull
│   ├── decompile.py          # ilspycmd → .cs files
│   └── build_index.py        # .cs files → SQLite DB
├── rust_dll_mcp/             # installable Python package
│   ├── __init__.py
│   ├── __main__.py           # entry point: python -m rust_dll_mcp
│   ├── server.py             # MCP server init, tool registration, stdio transport
│   ├── db.py                 # all SQLite queries
│   ├── tools.py              # 6 MCP tool handler functions
│   └── updater.py            # manifest fetch + DB download logic
├── manifest.json             # { "buildId": "...", "wipeDate": "...", "releaseUrl": "..." }
├── pyproject.toml
└── README.md
```

The local DB is stored in `platformdirs.user_cache_dir("rust-dll-mcp")`, not the package install location, so it survives package upgrades.

---

## GitHub Actions Pipeline

**Trigger:** `0 18 1-7 * 4` (first Thursday of month, 18:00 UTC) + manual `workflow_dispatch`.

**Permissions:** `contents: write` (release creation + manifest commit). SteamCMD depot download is anonymous — no Steam credentials required.

**Steps:**

1. **`download_dlls.py`** — installs SteamCMD, runs `+download_depot 258550 258552` anonymously for the managed DLL depot (~500MB). App ID `258550` (RustDedicated), depot ID `258552` (Windows managed DLLs). Outputs to `work/dlls/`.

2. **`decompile.py`** — installs `ilspycmd` via `dotnet tool install`, iterates all `.dll` files in `work/dlls/`, runs `ilspycmd` on each, outputs `.cs` files to `work/source/`. Skips DLLs that fail decompilation (logs warning, continues).

3. **`build_index.py`** — creates fresh SQLite DB, parses all `.cs` files, populates tables, builds FTS5 virtual tables, outputs `rust_dlls.db`.

4. **Release step** (YAML) — creates GitHub Release tagged `wipe-YYYY-MM-DD`, uploads `rust_dlls.db` as asset.

5. **Manifest step** (YAML) — writes `manifest.json`, commits and pushes to main.

**DLLs in scope:**
- `RustDedicated_Data/Managed/` — Assembly-CSharp.dll, Rust.*.dll, etc.
- Oxide/uMod DLLs — Oxide.Core.dll, Oxide.Ext.Rust.dll, etc.
- Harmony/HarmonyX DLLs
- Facepunch SDK DLLs

---

## SQLite Schema

```sql
CREATE TABLE assemblies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT,
    source TEXT -- 'rust', 'oxide', 'harmony', 'facepunch'
);

CREATE TABLE types (
    id INTEGER PRIMARY KEY,
    assembly_id INTEGER REFERENCES assemblies(id),
    namespace TEXT,
    name TEXT NOT NULL,
    fully_qualified_name TEXT NOT NULL,
    kind TEXT, -- 'class', 'struct', 'enum', 'interface', 'delegate'
    access_modifier TEXT,
    source_code TEXT, -- full decompiled source of the type
    base_type TEXT,
    interfaces TEXT -- JSON array
);

CREATE TABLE members (
    id INTEGER PRIMARY KEY,
    type_id INTEGER REFERENCES types(id),
    name TEXT NOT NULL,
    kind TEXT, -- 'method', 'field', 'property', 'event', 'constructor'
    return_type TEXT,
    parameters TEXT, -- JSON array of {name, type}
    access_modifier TEXT,
    attributes TEXT, -- JSON array of attribute names
    source_code TEXT
);

CREATE TABLE wipe_metadata (
    build_id TEXT NOT NULL,
    wipe_date TEXT NOT NULL,
    previous_build_id TEXT,
    indexed_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE types_fts USING fts5(fully_qualified_name, source_code, content='types');
CREATE VIRTUAL TABLE members_fts USING fts5(name, source_code, content='members');
```

---

## MCP Server

### Startup Flow (`server.py`)

1. Check cache dir for `rust_dlls_current.db` + stored build ID
2. Fetch `manifest.json` from `raw.githubusercontent.com/blaineddev/rust-dll-mcp/main/manifest.json`
3. If build IDs match → proceed with existing DB
4. If stale or missing → call `updater.py`: stream download `releaseUrl` with `httpx`, show progress to stderr, save to cache dir
5. Open SQLite connection (`row_factory = sqlite3.Row`), pass to tools
6. Register 6 tools with MCP server
7. Start stdio transport

### The 6 Tools (`tools.py`)

| Tool | Input | Returns | Query strategy |
|---|---|---|---|
| `find_type` | `name: str` | List of matching types (fqn, kind, assembly) | FTS5 on `types_fts`, fallback to `LIKE` on `name`. Top 10 by relevance. |
| `get_type_members` | `fully_qualified_name: str` | All methods/fields/props/events for a type | Join `types` + `members` on `type_id` |
| `get_method_source` | `type: str, method: str` | Decompiled C# source for one method | `members.source_code` where `type_id` matches and `name` matches, `kind = 'method'` |
| `search_usages` | `symbol: str` | All members whose source references the symbol | FTS5 on `members_fts.source_code` |
| `get_hook_signature` | `hook_name: str` | Oxide hook signature + parameters | `members` where `attributes` JSON contains `"HookMethod"` or name matches, filtered to Oxide assemblies |
| `diff_since_last_wipe` | `type: str` | Member additions/removals/changes vs previous wipe | Two DB connections: `rust_dlls_current.db` + `rust_dlls_previous.db` |

### `updater.py`

- Fetches `manifest.json` from GitHub raw URL
- Downloads current DB via `httpx.AsyncClient` with streaming, shows progress to stderr
- Fetches previous release DB on demand (GitHub releases API: get release before latest) for `diff_since_last_wipe`
- Stores both as `rust_dlls_current.db` and `rust_dlls_previous.db` in cache dir

### `__main__.py`

```python
import asyncio
from rust_dll_mcp.server import main

asyncio.run(main())
```

---

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "rust-dll-mcp"
dependencies = [
    "mcp",
    "httpx",
    "platformdirs",
]

[project.scripts]
rust-dll-mcp = "rust_dll_mcp.__main__:main"
```

---

## Tech Stack

- **MCP server:** Python, `mcp` SDK (`mcp.server.stdio` transport)
- **Async:** `asyncio` throughout — MCP SDK is async-first
- **HTTP:** `httpx` (async, streaming download)
- **Database:** SQLite (`sqlite3` stdlib) + FTS5
- **Paths:** `pathlib.Path` throughout
- **Cache dir:** `platformdirs.user_cache_dir("rust-dll-mcp")`
- **Decompiler:** `ilspycmd` (ILSpy CLI, installed via `dotnet tool install`)
- **Pipeline scheduler:** GitHub Actions cron

---

## Coding Conventions

- Single tab indentation
- No abbreviated variable names
- `pathlib.Path` throughout, not `os.path`
- `connection.row_factory = sqlite3.Row` for dict-like row access
