# rust-dll-mcp Improvements — Design

**Date:** 2026-06-08
**Status:** Approved design, pending implementation plan

## Motivation

Three concrete failures motivated this work, all observed while querying the
indexed Rust server DLLs:

1. **Inheritance was invisible.** Querying `CuiRectTransformComponent` via
   `get_type_members` returned only that type's own members with no signal that
   a base class existed, so a partial member list read as complete. The single
   biggest missing signal was a one-line "this type has a base type."
2. **No source-text search.** A search for `localEulerAngles` returned zero CUI
   hits and that was read as confirmation it wasn't used — but the relevant code
   is `rt.rotation = Quaternion.Euler(...)` and the JSON key is the string
   literal `"rotation"`. `search_usages` matches indexed symbol references, not
   string literals or arbitrary source text, so it could never have surfaced
   these.
3. **Client-side code was absent.** The code that actually parses CUI JSON keys
   (including `"rotation"`) lives in the Rust *client*, in the public
   `Facepunch/Rust.Community` repo — `CommunityEntity.UI.cs:507` literally does
   `if ( ShouldUpdateField( "rotation" ) ) rt.rotation = Quaternion.Euler(...)`.
   The indexed server depot does not contain it.

## Constraints and ground truth

- All four changes run against the **existing DB schema** — no migration. The
  columns needed (`types.base_type`, `types.interfaces`, `members.is_override`,
  `assemblies.source`) already exist.
- The server-side tool changes (items 1, 2, 4) work against today's shipped DBs
  immediately. Item 3 adds rows on the next monthly pipeline build.
- Measured worst case on the real 590 MB current DB: a fully flattened
  `BasePlayer` is **1,669 members ≈ 88,600 tokens**; `BaseEntity` alone is 458
  members (~25k tokens) and is a near-universal ancestor, so naively flattening
  any game entity would cost ~35k+ tokens per call. This directly shaped the
  item-1 design: **no full-flatten path exists.**

## Item 1 — `get_type_members`: own members + quantified inheritance signal

### Behavior

`get_type_members(fully_qualified_name, assembly_name=None)` — **no
`include_inherited` parameter.** There is intentionally no way to fetch an
entire flattened inheritance chain in a single call; that path is too expensive
(see measured numbers above).

Every call returns:

- The type's **own members in full** (unchanged set, current query).
- `base_type` and `interfaces`, **always emitted** — the one-line "a base
  exists" signal whose absence caused the original failure.
- `inherited_summary`: the resolved ancestor chain, each entry quantified so the
  model knows *how much* is hidden and *where*, without paying for the bodies.
- `unresolved_bases`: ancestor names that could not be resolved in the DB
  (external Unity types like `MonoBehaviour`, generics like `List<T>`); the walk
  stops at the first unresolved link.
- `hint`: a one-line instruction on how to go deeper.

### Response shape

This changes the response from a bare member list to an envelope (breaking
change; tests updated):

```json
{
  "fully_qualified_name": "BasePlayer",
  "base_type": "BaseCombatEntity",
  "interfaces": ["..."],
  "members": [ /* BasePlayer's own members, full detail */ ],
  "inherited_summary": [
    { "declaring_type": "BaseCombatEntity",  "source": "rust", "member_count": 109 },
    { "declaring_type": "BaseEntity",        "source": "rust", "member_count": 458 },
    { "declaring_type": "BaseNetworkable",   "source": "rust", "member_count": 147 },
    { "declaring_type": "BaseMonoBehaviour", "source": "rust", "member_count": 8 },
    { "declaring_type": "FacepunchBehaviour","source": "rust", "member_count": 16 }
  ],
  "unresolved_bases": ["MonoBehaviour"],
  "hint": "638 inherited members across 5 base types not shown. Call get_type_members on a specific base type (e.g. BaseEntity) to see its members."
}
```

The `inherited_summary` costs ~50 tokens regardless of chain size.

### Going deeper = manual recursion

The only way to see an ancestor's members is to call `get_type_members` on that
ancestor's FQN, which returns *its* own members and *its* own
`inherited_summary`. Each step is single-level, cheap, and deliberate; the model
pays only for the levels it chooses to open.

### Base-chain resolution

`base_type` is stored as a string. Resolution order: exact `fully_qualified_name`
match → simple-name (`types.name`) match preferring the same assembly → same
`source` → first match. Cycle guard via a visited set. Unresolved or empty base
ends the walk and is recorded in `unresolved_bases`.

### Partial classes

`CommunityEntity` is a partial class split across ~8 files (one `types` row
each). Own members already aggregate across partial rows via the FQN join.
`base_type` is taken from whichever partial declares one (only
`CommunityEntity.cs` declares `: PointEntity`); the rest contribute members
only. Member-count queries for the summary aggregate the same way.

### Simplification

Because member sets are never merged across the chain, there is **no override/
shadow dedup** to implement — that complexity disappears with the no-flatten
decision.

## Item 2 — new `search_source` tool (grep over decompiled bodies)

A regex search over decompiled source, returning grep-style per-line snippets.

### Signature

- `pattern` (string, required): a Python regular expression.
- `source` (string, optional): restrict to one source bucket (`rust`, `oxide`,
  `facepunch`, `community`).
- `limit` (int, optional): default 50, max 200.

### Behavior

- Scans `members.source_code` across all members (methods, properties,
  constructors, fields, enum values). Member bodies are where both `rt.rotation`
  and the `"rotation"` literal live, so this is the unit that mirrors grep over
  method source.
- Compiles `pattern` with Python `re`; an invalid pattern returns a friendly
  error string rather than raising.
- For each member whose source matches, emits one result **per matching line**
  up to `limit`, then stops.

### Result shape

```json
[
  {
    "type_fqn": "CommunityEntity",
    "member_name": "AddUI",
    "kind": "method",
    "source": "community",
    "line_number": 508,
    "line": "rt.rotation = Quaternion.Euler( 0, 0, obj.GetFloat(\"rotation\", 0) );"
  }
]
```

`line_number` is 1-based within the member's stored source (file-level line
numbers are not stored).

### Performance

A full compiled-regex scan over `members.source_code` for one wipe DB is
acceptable; the result `limit` short-circuits the scan once enough hits are
collected. No premature pre-filtering; this characteristic is documented rather
than optimized away.

## Item 3 — index `Facepunch/Rust.Community` as `source="community"`

### Source

The public `Facepunch/Rust.Community` repository — 11 hand-written `.cs` files at
the repo root (`CommunityEntity*.cs`, `Icons.cs`, etc.). These are the
client-side CUI implementation and contain the JSON-key parsing absent from the
server depot.

### Ingestion

- `index_cs_file` already accepts a `source` override. Add a small `build_index`
  entry point (and CLI flag) to index a directory of `.cs` files with an
  explicit `source` tag, so the community files are tagged `community` rather
  than going through `_assembly_source` name heuristics.
- The monthly pipeline workflow (`.github/workflows/monthly-wipe-pipeline.yml`)
  gets a step: shallow-clone `Rust.Community`, then index its `.cs` files as
  `community`. Refreshes monthly alongside the wipe build.

### Parsing notes

The files are hand-written, not ILSpy output, but standard C#. `build_index`
already wraps each file in try/except, so a stray parse miss degrades
gracefully. Most files have no namespace, yielding FQNs like `CommunityEntity`,
`cui`, and `Rust.UI.Icons`.

## Item 4 — source label + filter across tools

- `find_type`: add `source` to each result; add an optional `source` filter
  parameter.
- `search_usages`: add `source` to each result; add an optional `source` filter
  parameter.
- `get_type_members`: members and `inherited_summary` entries already carry
  `source` (item 1).
- `search_source`: `source` filter and label built in (item 2).

This lets a query be scoped to client-only vs server-only and makes every
result's origin explicit — directly killing the "looked complete" failure mode.

## Testing

- **Item 1:** inherited-summary chain resolution with counts; `base_type`/
  `interfaces` always emitted; `unresolved_bases` populated for external bases;
  partial-class aggregation; envelope shape. Update the existing
  `test_get_type_members_returns_list` for the new envelope shape.
- **Item 2:** regex match returns per-line snippets; `limit` bounds results;
  invalid regex returns an error string; `source` filter scopes results.
- **Item 3:** index the real `CommunityEntity.UI.cs` and assert the `"rotation"`
  line is findable via `search_source` and tagged `source="community"`.
- **Item 4:** `source` present on `find_type`/`search_usages` results; filter
  scopes correctly.

## Out of scope

- No schema migration.
- No depth cap parameter (there is no flatten path to cap).
- No decompilation of client DLLs — only the public `Rust.Community` source.
- No changes to `get_method_source`, `get_hook_signature`,
  `diff_since_last_wipe`, or `find_implementations` beyond what falls out of the
  shared query helpers.
