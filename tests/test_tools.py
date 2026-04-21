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
	tool_find_implementations,
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
	names = [member["name"] for member in result]
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
	assert "not available" in result.lower()


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


HOOK_CALLSITE_CS = """\
namespace Rust
{
	public class BasePlayer
	{
		public void Die()
		{
			Interface.CallHook("OnPlayerDeath", this, "with \\"quoted\\" arg");
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
	return connection


@pytest.mark.asyncio
async def test_tool_get_hook_signature_returns_callsite_source(hook_callsite_connection):
	result = await tool_get_hook_signature(hook_callsite_connection, None, "OnPlayerDeath")
	assert len(result) >= 1
	assert result[0]["source"] == "call_site"
	assert result[0]["parameters"][0]["call_site"] == "Rust.BasePlayer.Die"


@pytest.mark.asyncio
async def test_tool_get_hook_signature_handles_quoted_args(hook_callsite_connection):
	"""Quoted strings in hook args must not break JSON decoding downstream."""
	result = await tool_get_hook_signature(hook_callsite_connection, None, "OnPlayerDeath")
	# If json.dumps/json.loads round-trip is wrong, the tool would raise
	assert isinstance(result[0]["parameters"], list)


@pytest.mark.asyncio
async def test_tool_get_hook_signature_unknown_returns_message(populated_connection):
	result = await tool_get_hook_signature(populated_connection, None, "NoSuchHook")
	assert "not found" in result[0]["message"].lower()
