import sqlite3
import json
import pytest
from pathlib import Path
from tests.conftest import SAMPLE_CS
from pipeline.build_index import index_cs_file, populate_fts, write_wipe_metadata, build_index
from rust_dll_mcp.db import create_schema


def test_build_index_indexes_community_dir(tmp_path):
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


HOOK_CALLSITE_CS = """\
namespace Rust
{
	public class BasePlayer
	{
		public void Die(HitInfo info)
		{
			Interface.CallHook("OnPlayerDeath", this, info);
		}

		public void Respawn()
		{
			Interface.Call("OnPlayerRespawn", this);
		}
	}
}
"""


@pytest.fixture
def hook_callsite_connection(tmp_path):
	cs_file = tmp_path / "Assembly-CSharp.cs"
	cs_file.write_text(HOOK_CALLSITE_CS)
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	index_cs_file(connection, cs_file, source="rust")
	populate_fts(connection)
	yield connection
	connection.close()


def test_hooks_table_populated_from_callhook(hook_callsite_connection):
	rows = hook_callsite_connection.execute(
		"SELECT name FROM hooks"
	).fetchall()
	names = {row["name"] for row in rows}
	assert "OnPlayerDeath" in names
	assert "OnPlayerRespawn" in names


def test_hooks_table_records_calling_method(hook_callsite_connection):
	row = hook_callsite_connection.execute(
		"SELECT calling_method, calling_type_fqn FROM hooks WHERE name = 'OnPlayerDeath'"
	).fetchone()
	assert row["calling_method"] == "Die"
	assert row["calling_type_fqn"] == "Rust.BasePlayer"


NOISE_CS = """\
namespace Microsoft.CodeAnalysis.EmbeddedAttribute
{
	public class EmbeddedAttribute
	{
	}
}
"""

REAL_CS = """\
namespace Rust
{
	public class RealType
	{
	}
}
"""


@pytest.fixture
def noise_filtered_connection(tmp_path):
	noise_file = tmp_path / "NoiseAssembly.cs"
	noise_file.write_text(NOISE_CS)
	real_file = tmp_path / "Assembly-CSharp.cs"
	real_file.write_text(REAL_CS)
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	index_cs_file(connection, noise_file, source="rust")
	index_cs_file(connection, real_file, source="rust")
	populate_fts(connection)
	yield connection
	connection.close()


def test_noise_namespace_excluded_from_index(noise_filtered_connection):
	rows = noise_filtered_connection.execute("SELECT fully_qualified_name FROM types").fetchall()
	fqns = {row["fully_qualified_name"] for row in rows}
	assert not any(fqn.startswith("Microsoft.CodeAnalysis") for fqn in fqns)


def test_real_type_survives_noise_filter(noise_filtered_connection):
	rows = noise_filtered_connection.execute("SELECT fully_qualified_name FROM types").fetchall()
	fqns = {row["fully_qualified_name"] for row in rows}
	assert "Rust.RealType" in fqns
