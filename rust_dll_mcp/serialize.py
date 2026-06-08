import json


def compact_json(obj) -> str:
	"""Serialize without indentation — the global token-saving encoding."""
	return json.dumps(obj, separators=(",", ":"))


def param_signature(parameters: list[dict]) -> str:
	"""Render parsed parameters as a compact signature string, e.g. 'Item item, int amount'."""
	parts = []
	for parameter in parameters:
		type_text = (parameter.get("type") or "").strip()
		name_text = (parameter.get("name") or "").strip()
		parts.append(f"{type_text} {name_text}".strip())
	return ", ".join(parts)


def slim_member(row) -> dict:
	"""Token-optimized member dict from a members row.

	Omits empty/default fields (absent == empty); params rendered as a signature string.
	"""
	parameters = json.loads(row["parameters"] or "[]")
	attributes = json.loads(row["attributes"] or "[]")
	member = {"name": row["name"], "kind": row["kind"]}
	if row["return_type"]:
		member["return_type"] = row["return_type"]
	if parameters:
		member["params"] = param_signature(parameters)
	if row["access_modifier"] and row["access_modifier"] != "public":
		member["access_modifier"] = row["access_modifier"]
	if attributes:
		member["attributes"] = attributes
	return member


def member_signature(row) -> str:
	"""Single-line signature for diff output, e.g. 'bool Give(Item i)' or 'int capacity'."""
	parameters = json.loads(row["parameters"] or "[]")
	return_type = row["return_type"] or ""
	if row["kind"] in ("method", "constructor"):
		call = f"{row['name']}({param_signature(parameters)})"
		return f"{return_type} {call}".strip()
	return f"{return_type} {row['name']}".strip()
