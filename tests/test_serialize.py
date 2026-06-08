import json
import sqlite3
import pytest
from rust_dll_mcp.serialize import (
	compact_json,
	param_signature,
	slim_member,
	member_signature,
)


def _row(**kwargs):
	"""Build a sqlite3.Row with the member columns slim_member/member_signature read."""
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	cols = ["name", "kind", "return_type", "parameters", "access_modifier", "attributes"]
	defaults = {"name": "x", "kind": "method", "return_type": "", "parameters": "[]",
	            "access_modifier": "public", "attributes": "[]"}
	defaults.update(kwargs)
	placeholders = ",".join("?" for _ in cols)
	connection.execute(f"CREATE TABLE m ({','.join(cols)})")
	connection.execute(f"INSERT INTO m VALUES ({placeholders})", [defaults[c] for c in cols])
	return connection.execute("SELECT * FROM m").fetchone()


def test_compact_json_has_no_whitespace():
	assert compact_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'


def test_param_signature_joins_type_and_name():
	params = [{"type": "Item", "name": "item"}, {"type": "int", "name": "amount"}]
	assert param_signature(params) == "Item item, int amount"


def test_slim_member_omits_empty_and_default_fields():
	row = _row(name="capacity", kind="field", return_type="int")
	assert slim_member(row) == {"name": "capacity", "kind": "field", "return_type": "int"}


def test_slim_member_renders_params_and_keeps_non_public():
	row = _row(name="Give", kind="method", return_type="bool",
	           parameters='[{"type":"Item","name":"i"}]', access_modifier="private",
	           attributes='["Obsolete"]')
	assert slim_member(row) == {
		"name": "Give", "kind": "method", "return_type": "bool",
		"params": "Item i", "access_modifier": "private", "attributes": ["Obsolete"],
	}


def test_member_signature_method_and_field():
	method = _row(name="Give", kind="method", return_type="bool",
	              parameters='[{"type":"Item","name":"i"}]')
	assert member_signature(method) == "bool Give(Item i)"
	field = _row(name="capacity", kind="field", return_type="int")
	assert member_signature(field) == "int capacity"
