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
