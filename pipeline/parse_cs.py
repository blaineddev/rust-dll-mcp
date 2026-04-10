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


NAMESPACE_PATTERN = re.compile(r'\bnamespace\s+([\w.]+)')

TYPE_DECLARATION_PATTERN = re.compile(
	r'(?P<access>public|internal|private|protected)?\s*'
	r'(?:abstract|sealed|static|partial|readonly|\s)*'
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


def _strip_nested_types(body: str) -> str:
	"""Remove nested type declarations and their bodies from a type body string."""
	result = []
	search_start = 0
	while True:
		match = TYPE_DECLARATION_PATTERN.search(body, search_start)
		if not match:
			result.append(body[search_start:])
			break
		result.append(body[search_start:match.start()])
		_, end_position = _extract_block(body, match.end())
		search_start = end_position
	return ''.join(result)


def _parse_members(type_body: str) -> list[ParsedMember]:
	members = []

	type_body = _strip_nested_types(type_body)

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

		members.append(ParsedMember(
			name=name,
			kind=kind,
			return_type=return_type,
			parameters=_parse_parameters(match.group('params')),
			access_modifier=match.group('access'),
			attributes=attributes,
			source_code=source_code.strip(),
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

	seen_field_names = set()
	for match in FIELD_PATTERN.finditer(type_body):
		name = match.group('name')
		if name in method_names:
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
		inheritance_str = (match.group('inheritance') or '').strip()
		base_type, interfaces = _parse_inheritance(inheritance_str)
		fully_qualified_name = f"{namespace}.{name}" if namespace else name

		body, end_position = _extract_block(source, match.end())
		type_source = source[match.start():end_position]

		members = _parse_members(body) if kind != 'enum' else []

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
		))

		search_start = end_position

	return parsed_types
