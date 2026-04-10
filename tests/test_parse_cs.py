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
	methods = [member for member in types[0].members if member.kind == "method"]
	assert len(methods) == 3


def test_parse_type_has_two_fields():
	types = parse_cs_file(SAMPLE_CS)
	fields = [member for member in types[0].members if member.kind == "field"]
	assert len(fields) == 2


def test_parse_method_name():
	types = parse_cs_file(SAMPLE_CS)
	method_names = [member.name for member in types[0].members if member.kind == "method"]
	assert "GiveItem" in method_names


def test_parse_method_return_type():
	types = parse_cs_file(SAMPLE_CS)
	give_item = next(member for member in types[0].members if member.name == "GiveItem")
	assert give_item.return_type == "void"


def test_parse_method_parameters():
	types = parse_cs_file(SAMPLE_CS)
	give_item = next(member for member in types[0].members if member.name == "GiveItem")
	assert len(give_item.parameters) == 2
	assert give_item.parameters[0]["name"] == "item"
	assert give_item.parameters[0]["type"] == "Item"


def test_parse_method_source_contains_body():
	types = parse_cs_file(SAMPLE_CS)
	give_item = next(member for member in types[0].members if member.name == "GiveItem")
	assert "containerMain.AddItem" in give_item.source_code


def test_parse_field_name():
	types = parse_cs_file(SAMPLE_CS)
	field_names = [member.name for member in types[0].members if member.kind == "field"]
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
