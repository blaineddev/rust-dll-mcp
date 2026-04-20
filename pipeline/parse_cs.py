import re
from dataclasses import dataclass, field as dataclass_field


@dataclass
class ParsedMember:
	name: str
	kind: str
	return_type: str
	parameters: list[dict]
	access_modifier: str
	attributes: list[str]
	source_code: str
	is_static: bool = False
	is_abstract: bool = False
	is_override: bool = False
	is_virtual: bool = False
	doc_comment: str | None = None


@dataclass
class ParsedType:
	namespace: str
	name: str
	fully_qualified_name: str
	kind: str
	access_modifier: str
	base_type: str
	interfaces: list[str]
	source_code: str
	members: list[ParsedMember] = dataclass_field(default_factory=list)
	is_static: bool = False
	is_abstract: bool = False
	is_sealed: bool = False
	doc_comment: str | None = None
	parent_name: str | None = None


NAMESPACE_PATTERN = re.compile(r'\bnamespace\s+([\w.]+)')

TYPE_DECLARATION_PATTERN = re.compile(
	r'(?P<access>public|internal|private|protected)?\s*'
	r'(?P<modifiers>(?:(?:abstract|sealed|static|partial|readonly)\s+)*)'
	r'(?P<kind>class|struct|enum|interface|delegate)\s+'
	r'(?P<name>\w+)'
	r'(?:\s*<[^>]+>)?'
	r'(?:\s*:\s*(?P<inheritance>[^{]+))?',
	re.MULTILINE,
)

ATTRIBUTE_PATTERN = re.compile(r'\[(\w+(?:\([^)]*\))?)\]')

METHOD_PATTERN = re.compile(
	r'(?P<attributes>(?:\[[\w\s,.()"\']+\]\s*)*)'
	r'(?P<access>public|private|protected internal|protected|internal|private protected)\s+'
	r'(?P<modifiers>(?:(?:static|virtual|abstract|override|sealed|async|extern|new|unsafe|partial)\s+)*)'
	r'(?P<return_type>[\w\[\]<>.,\s?\*]+?)\s+'
	r'(?P<name>\w+)\s*'
	r'(?:<[^>]+>)?\s*'
	r'\((?P<params>[^)]*)\)',
	re.MULTILINE,
)

FIELD_PATTERN = re.compile(
	r'(?P<access>public|private|protected internal|protected|internal|private protected)\s+'
	r'(?P<modifiers>(?:(?:static|readonly|const|volatile)\s+)*)'
	r'(?P<type>[\w\[\]<>.,\s?\*]+?)\s+'
	r'(?P<name>\w+)\s*[;=]',
	re.MULTILINE,
)

CONSTRUCTOR_PATTERN = re.compile(
	r'(?P<access>public|private|protected internal|protected|internal|private protected)\s+'
	r'(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*[:{]',
	re.MULTILINE,
)

ENUM_VALUE_PATTERN = re.compile(
	r'^\s*(?P<name>[A-Za-z_]\w*)\s*(?:=\s*(?P<value>[^,\n}]+))?\s*[,\n}]',
	re.MULTILINE,
)

_ENUM_RESERVED = frozenset({
	'get', 'set', 'public', 'private', 'protected', 'internal',
	'static', 'readonly', 'const', 'abstract', 'sealed', 'override',
})

PROPERTY_PATTERN = re.compile(
	r'(?P<access>public|private|protected internal|protected|internal|private protected)\s+'
	r'(?P<modifiers>(?:(?:static|virtual|abstract|override|sealed|new|unsafe)\s+)*)'
	r'(?P<type>[\w\[\]<>.,\s?\*]+?)\s+'
	r'(?P<name>\w+)\s*'
	r'(?=\s*(?:=>|\{[^(]*(?:get|set|init)))',
	re.MULTILINE,
)


def _extract_doc_comment(source: str, declaration_start: int) -> str | None:
	"""Extract consecutive /// lines immediately preceding declaration_start, skipping blank lines."""
	preceding = source[:declaration_start]
	lines = preceding.split('\n')
	doc_lines = []
	for line in reversed(lines):
		stripped = line.strip()
		if stripped.startswith('///'):
			doc_lines.insert(0, stripped[3:].strip())
		elif stripped == '':
			continue
		else:
			break
	if not doc_lines:
		return None
	text = ' '.join(doc_lines)
	text = re.sub(r'<[^>]+>', '', text).strip()
	return text or None


def _extract_block(source: str, start: int) -> tuple[str, int]:
	"""Extract content from the first '{' at/after start through its matching '}'."""
	brace_start = source.find('{', start)
	if brace_start == -1:
		return '', len(source)

	depth = 0
	in_string = False
	in_verbatim = False
	in_char = False
	index = brace_start

	while index < len(source):
		char = source[index]
		if in_verbatim:
			if char == '"' and index + 1 < len(source) and source[index + 1] == '"':
				index += 2
				continue
			elif char == '"':
				in_verbatim = False
		elif in_string:
			if char == '\\':
				index += 2
				continue
			elif char == '"':
				in_string = False
		elif in_char:
			if char == '\\':
				index += 2
				continue
			elif char == "'":
				in_char = False
		else:
			if char == '@' and index + 1 < len(source) and source[index + 1] == '"':
				in_verbatim = True
				index += 2
				continue
			elif char == '"':
				in_string = True
			elif char == "'":
				in_char = True
			elif char == '{':
				depth += 1
			elif char == '}':
				depth -= 1
				if depth == 0:
					return source[brace_start:index + 1], index + 1
		index += 1

	return source[brace_start:], len(source)


def _split_parameters(params_str: str) -> list[str]:
	"""Split parameter string on commas, ignoring commas inside angle brackets."""
	parts = []
	depth = 0
	current = []
	for char in params_str:
		if char == '<':
			depth += 1
			current.append(char)
		elif char == '>':
			depth -= 1
			current.append(char)
		elif char == ',' and depth == 0:
			parts.append(''.join(current).strip())
			current = []
		else:
			current.append(char)
	if current:
		parts.append(''.join(current).strip())
	return [part for part in parts if part]


def _parse_parameters(params_str: str) -> list[dict]:
	if not params_str.strip():
		return []
	parameters = []
	for param in _split_parameters(params_str):
		param = param.strip()
		param = param.split('=')[0].strip()
		param = re.sub(r'\[[\w\s]+\]', '', param).strip()
		param = re.sub(r'\b(out|ref|in|params)\b\s*', '', param).strip()
		parts = param.rsplit(None, 1)
		if len(parts) == 2:
			parameters.append({"type": parts[0].strip(), "name": parts[1].strip()})
	return parameters


def _parse_inheritance(inheritance_str: str) -> tuple[str, list[str]]:
	if not inheritance_str:
		return '', []
	parts = [part.strip() for part in inheritance_str.split(',')]
	base_type = ''
	interfaces = []
	for index, part in enumerate(parts):
		if index == 0 and not re.match(r'^I[A-Z]', part):
			base_type = part
		else:
			interfaces.append(part)
	return base_type, interfaces


def _extract_nested_type_sources(body: str) -> tuple[str, list[str]]:
	"""Strip nested type declarations from body, returning (cleaned_body, list_of_nested_sources)."""
	result = []
	nested_sources = []
	search_start = 0
	while True:
		match = TYPE_DECLARATION_PATTERN.search(body, search_start)
		if not match:
			result.append(body[search_start:])
			break
		result.append(body[search_start:match.start()])
		_, end_position = _extract_block(body, match.end())
		nested_sources.append(body[match.start():end_position])
		search_start = end_position
	return ''.join(result), nested_sources


def _parse_nested_types(nested_sources: list[str], parent_fqn: str, namespace: str) -> list[ParsedType]:
	parsed = []
	for source in nested_sources:
		match = TYPE_DECLARATION_PATTERN.search(source)
		if not match:
			continue
		kind = match.group('kind')
		name = match.group('name')
		access_modifier = match.group('access') or 'private'
		modifiers_str = match.group('modifiers') or ''
		inheritance_str = (match.group('inheritance') or '').strip()
		base_type, interfaces = _parse_inheritance(inheritance_str)
		fully_qualified_name = f"{parent_fqn}.{name}"

		body, end_position = _extract_block(source, match.end())
		clean_body, further_nested = _extract_nested_type_sources(body)

		members = _parse_members(clean_body) if kind != 'enum' else _parse_enum_values(clean_body)
		doc_comment = _extract_doc_comment(source, match.start())

		parsed.append(ParsedType(
			namespace=namespace,
			name=name,
			fully_qualified_name=fully_qualified_name,
			kind=kind,
			access_modifier=access_modifier,
			base_type=base_type,
			interfaces=interfaces,
			source_code=source[:end_position],
			members=members,
			is_static='static' in modifiers_str,
			is_abstract='abstract' in modifiers_str,
			is_sealed='sealed' in modifiers_str,
			doc_comment=doc_comment,
			parent_name=parent_fqn,
		))

		parsed.extend(_parse_nested_types(further_nested, fully_qualified_name, namespace))
	return parsed


def _parse_enum_values(body: str) -> list[ParsedMember]:
	members = []
	for match in ENUM_VALUE_PATTERN.finditer(body):
		name = match.group('name')
		if name in _ENUM_RESERVED:
			continue
		value = (match.group('value') or '').strip()
		members.append(ParsedMember(
			name=name,
			kind='enum_value',
			return_type=value,
			parameters=[],
			access_modifier='public',
			attributes=[],
			source_code=match.group(0).strip(),
		))
	return members


def _parse_properties(type_body: str) -> list[ParsedMember]:
	members = []
	for match in PROPERTY_PATTERN.finditer(type_body):
		name = match.group('name')
		property_type = match.group('type').strip()
		access = match.group('access')
		modifiers_str = match.group('modifiers') or ''

		after = type_body[match.end():]
		if after.lstrip().startswith('=>'):
			semi = after.find(';')
			end_pos = match.end() + semi + 1 if semi != -1 else len(type_body)
		else:
			_, end_pos = _extract_block(type_body, match.end())

		source_code = type_body[match.start():end_pos]

		members.append(ParsedMember(
			name=name,
			kind='property',
			return_type=property_type,
			parameters=[],
			access_modifier=access,
			attributes=[],
			source_code=source_code.strip(),
			is_static='static' in modifiers_str,
			is_abstract='abstract' in modifiers_str,
			is_override='override' in modifiers_str,
			is_virtual='virtual' in modifiers_str,
			doc_comment=_extract_doc_comment(type_body, match.start()),
		))
	return members


def _parse_members(type_body: str) -> list[ParsedMember]:
	members = []

	type_body, _ = _extract_nested_type_sources(type_body)

	for match in METHOD_PATTERN.finditer(type_body):
		name = match.group('name')
		return_type = match.group('return_type').strip()
		kind = 'constructor' if return_type == name else 'method'
		if kind == 'constructor':
			return_type = ''

		body, end_position = _extract_block(type_body, match.end())
		source_code = type_body[match.start():end_position]

		attributes_str = match.group('attributes') or ''
		attributes = ATTRIBUTE_PATTERN.findall(attributes_str)
		method_modifiers = match.group('modifiers') or ''

		members.append(ParsedMember(
			name=name,
			kind=kind,
			return_type=return_type,
			parameters=_parse_parameters(match.group('params')),
			access_modifier=match.group('access'),
			attributes=attributes,
			source_code=source_code.strip(),
			is_static='static' in method_modifiers,
			is_abstract='abstract' in method_modifiers,
			is_override='override' in method_modifiers,
			is_virtual='virtual' in method_modifiers,
			doc_comment=_extract_doc_comment(type_body, match.start()),
		))

	method_names = {member.name for member in members}
	for match in CONSTRUCTOR_PATTERN.finditer(type_body):
		name = match.group('name')
		# Skip if already captured as a method, or if it's a keyword (lowercase)
		if name in method_names or name[0].islower():
			continue
		# Skip common false positives
		if name in {'if', 'while', 'foreach', 'switch', 'for', 'using', 'lock', 'catch', 'return'}:
			continue

		body, end_position = _extract_block(type_body, match.end() - 1)  # -1 because pattern consumed the '{'
		source_code = type_body[match.start():end_position]

		members.append(ParsedMember(
			name=name,
			kind='constructor',
			return_type='',
			parameters=_parse_parameters(match.group('params')),
			access_modifier=match.group('access'),
			attributes=[],
			source_code=source_code.strip(),
		))
		method_names.add(name)

	property_members = _parse_properties(type_body)
	property_names = {member.name for member in property_members}
	members.extend(property_members)

	seen_field_names = set()
	for match in FIELD_PATTERN.finditer(type_body):
		name = match.group('name')
		if name in method_names or name in property_names:
			continue
		if name in seen_field_names:
			continue
		seen_field_names.add(name)

		members.append(ParsedMember(
			name=name,
			kind='field',
			return_type=match.group('type').strip(),
			parameters=[],
			access_modifier=match.group('access'),
			attributes=[],
			source_code=match.group(0).strip(),
		))

	return members


def parse_cs_file(source: str) -> list[ParsedType]:
	"""Parse a decompiled C# source string and return a list of ParsedType objects."""
	namespace_match = NAMESPACE_PATTERN.search(source)
	namespace = namespace_match.group(1) if namespace_match else ''

	parsed_types = []
	search_start = 0

	while True:
		match = TYPE_DECLARATION_PATTERN.search(source, search_start)
		if not match:
			break

		kind = match.group('kind')
		name = match.group('name')
		access_modifier = match.group('access') or 'internal'
		modifiers_str = match.group('modifiers') or ''
		inheritance_str = (match.group('inheritance') or '').strip()
		base_type, interfaces = _parse_inheritance(inheritance_str)
		fully_qualified_name = f"{namespace}.{name}" if namespace else name

		body, end_position = _extract_block(source, match.end())
		type_source = source[match.start():end_position]

		clean_body, nested_sources = _extract_nested_type_sources(body)
		members = _parse_members(clean_body) if kind != 'enum' else _parse_enum_values(clean_body)

		doc_comment = _extract_doc_comment(source, match.start())

		parsed_types.append(ParsedType(
			namespace=namespace,
			name=name,
			fully_qualified_name=fully_qualified_name,
			kind=kind,
			access_modifier=access_modifier,
			base_type=base_type,
			interfaces=interfaces,
			source_code=type_source,
			members=members,
			is_static='static' in modifiers_str,
			is_abstract='abstract' in modifiers_str,
			is_sealed='sealed' in modifiers_str,
			doc_comment=doc_comment,
		))

		parsed_types.extend(_parse_nested_types(nested_sources, fully_qualified_name, namespace))

		search_start = end_position

	return parsed_types
