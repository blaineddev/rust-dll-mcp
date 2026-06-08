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
	tool_search_source,
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
	results = await tool_search_source(community_connection, None, r"rt\.rotation")
	assert any(r["member_name"] == "UpdateRectTransform" for r in results)
	hit = next(r for r in results if "rt.rotation" in r["line"])
	assert hit["source"] == "community"
	assert hit["line"] == 'rt.rotation = Quaternion.Euler( 0, 0, obj.GetFloat("rotation", 0) );'


@pytest.mark.asyncio
async def test_search_source_finds_json_string_literal(community_connection):
	results = await tool_search_source(community_connection, None, r'"rotation"')
	assert len(results) >= 1


@pytest.mark.asyncio
async def test_search_source_source_filter_scopes(community_connection):
	assert await tool_search_source(community_connection, None, r"rt\.rotation", source="rust") == []
	assert len(await tool_search_source(community_connection, None, r"rt\.rotation", source="community")) >= 1


@pytest.mark.asyncio
async def test_search_source_invalid_regex_returns_message(community_connection):
	result = await tool_search_source(community_connection, None, r"(unclosed")
	assert isinstance(result, str)
	assert "invalid regex" in result.lower()


@pytest.mark.asyncio
async def test_search_source_respects_limit(community_connection):
	results = await tool_search_source(community_connection, None, r"rotation", limit=1)
	assert len(results) == 1


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
