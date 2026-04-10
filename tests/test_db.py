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

	current_connection = sqlite3.connect(":memory:")
	current_connection.row_factory = sqlite3.Row
	create_schema(current_connection)
	index_cs_file(current_connection, new_file, source="rust")
	populate_fts(current_connection)

	previous_connection = sqlite3.connect(":memory:")
	previous_connection.row_factory = sqlite3.Row
	create_schema(previous_connection)
	index_cs_file(previous_connection, old_file, source="rust")
	populate_fts(previous_connection)

	diff = query_diff_since_last_wipe(current_connection, previous_connection, "Rust.Foo")
	assert "NewMethod" in [member["name"] for member in diff["added"]]
	assert len(diff["removed"]) == 0

	current_connection.close()
	previous_connection.close()
