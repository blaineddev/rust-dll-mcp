import pytest
from tests.conftest import SAMPLE_CS
from pipeline.parse_cs import parse_cs_file, ParsedType, ParsedMember, extract_hook_calls


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


DOC_COMMENT_CS = """\
namespace Rust
{
	/// <summary>A player on the server.</summary>
	public class BasePlayer
	{
		/// <summary>Kills the player.</summary>
		public void Die()
		{
		}
	}
}
"""


def test_parsed_type_has_doc_comment_field():
	types = parse_cs_file(DOC_COMMENT_CS)
	assert hasattr(types[0], 'doc_comment')


def test_parsed_type_doc_comment_extracted():
	types = parse_cs_file(DOC_COMMENT_CS)
	assert types[0].doc_comment == "A player on the server."


def test_parsed_member_doc_comment_extracted():
	types = parse_cs_file(DOC_COMMENT_CS)
	die_method = next(m for m in types[0].members if m.name == "Die")
	assert die_method.doc_comment == "Kills the player."


def test_parsed_type_doc_comment_is_none_when_absent():
	types = parse_cs_file(SAMPLE_CS)
	assert types[0].doc_comment is None


def test_parsed_type_has_modifier_fields():
	types = parse_cs_file(SAMPLE_CS)
	assert hasattr(types[0], 'is_static')
	assert hasattr(types[0], 'is_abstract')
	assert hasattr(types[0], 'is_sealed')


def test_parsed_member_has_modifier_fields():
	types = parse_cs_file(SAMPLE_CS)
	method = next(m for m in types[0].members if m.kind == 'method')
	assert hasattr(method, 'is_static')
	assert hasattr(method, 'is_abstract')
	assert hasattr(method, 'is_override')
	assert hasattr(method, 'is_virtual')


def test_parsed_type_has_parent_name_field():
	types = parse_cs_file(SAMPLE_CS)
	assert hasattr(types[0], 'parent_name')
	assert types[0].parent_name is None


PROPERTIES_CS = """\
namespace Rust
{
	public class PlayerStats
	{
		private int _health;

		public int Health { get; set; }

		public string Name { get; }

		public bool IsAlive => _health > 0;

		public int Capacity { get; private set; }
	}
}
"""


def test_parse_finds_properties():
	types = parse_cs_file(PROPERTIES_CS)
	properties = [m for m in types[0].members if m.kind == "property"]
	assert len(properties) == 4


def test_parse_property_names():
	types = parse_cs_file(PROPERTIES_CS)
	names = {m.name for m in types[0].members if m.kind == "property"}
	assert names == {"Health", "Name", "IsAlive", "Capacity"}


def test_parse_property_return_type():
	types = parse_cs_file(PROPERTIES_CS)
	health = next(m for m in types[0].members if m.name == "Health")
	assert health.return_type == "int"


def test_parse_property_source_contains_getter():
	types = parse_cs_file(PROPERTIES_CS)
	health = next(m for m in types[0].members if m.name == "Health")
	assert "get" in health.source_code


def test_parse_property_does_not_duplicate_as_field():
	types = parse_cs_file(PROPERTIES_CS)
	field_names = {m.name for m in types[0].members if m.kind == "field"}
	assert "Health" not in field_names


ENUM_VALUES_CS = """\
namespace Rust
{
	public enum HitArea
	{
		Head = 1,
		Body = 2,
		Hand = 4,
		Foot,
	}
}
"""


def test_parse_enum_values_count():
	types = parse_cs_file(ENUM_VALUES_CS)
	values = [m for m in types[0].members if m.kind == "enum_value"]
	assert len(values) == 4


def test_parse_enum_value_names():
	types = parse_cs_file(ENUM_VALUES_CS)
	names = {m.name for m in types[0].members if m.kind == "enum_value"}
	assert names == {"Head", "Body", "Hand", "Foot"}


def test_parse_enum_value_with_explicit_value():
	types = parse_cs_file(ENUM_VALUES_CS)
	head = next(m for m in types[0].members if m.name == "Head")
	assert head.return_type == "1"


def test_parse_enum_value_without_explicit_value():
	types = parse_cs_file(ENUM_VALUES_CS)
	foot = next(m for m in types[0].members if m.name == "Foot")
	assert foot.return_type == ""


MODIFIERS_CS = """\
namespace Rust
{
	public abstract class BaseEntity
	{
		public static BaseEntity CreateEntity()
		{
			return null;
		}

		public abstract void Kill();

		public virtual void OnDestroy()
		{
		}
	}
}
"""

SEALED_CS = """\
namespace Rust
{
	public sealed class FinalClass
	{
	}
}
"""


def test_type_is_abstract():
	types = parse_cs_file(MODIFIERS_CS)
	assert types[0].is_abstract is True


def test_type_is_not_static():
	types = parse_cs_file(MODIFIERS_CS)
	assert types[0].is_static is False


def test_type_is_sealed():
	types = parse_cs_file(SEALED_CS)
	assert types[0].is_sealed is True


def test_member_is_static():
	types = parse_cs_file(MODIFIERS_CS)
	create = next(m for m in types[0].members if m.name == "CreateEntity")
	assert create.is_static is True


def test_member_is_abstract():
	types = parse_cs_file(MODIFIERS_CS)
	kill = next(m for m in types[0].members if m.name == "Kill")
	assert kill.is_abstract is True


def test_member_is_virtual():
	types = parse_cs_file(MODIFIERS_CS)
	on_destroy = next(m for m in types[0].members if m.name == "OnDestroy")
	assert on_destroy.is_virtual is True


NESTED_CS = """\
namespace Rust
{
	public class BasePlayer
	{
		public class PlayerFlags
		{
			public bool IsAdmin;
		}

		public void Die()
		{
		}
	}
}
"""


def test_nested_type_is_extracted():
	types = parse_cs_file(NESTED_CS)
	names = {t.name for t in types}
	assert "PlayerFlags" in names


def test_nested_type_count():
	types = parse_cs_file(NESTED_CS)
	assert len(types) == 2


def test_nested_type_parent_name():
	types = parse_cs_file(NESTED_CS)
	flags = next(t for t in types if t.name == "PlayerFlags")
	assert flags.parent_name == "Rust.BasePlayer"


def test_nested_type_fqn():
	types = parse_cs_file(NESTED_CS)
	flags = next(t for t in types if t.name == "PlayerFlags")
	assert flags.fully_qualified_name == "Rust.BasePlayer.PlayerFlags"


def test_parent_type_does_not_include_nested_as_member():
	types = parse_cs_file(NESTED_CS)
	base_player = next(t for t in types if t.name == "BasePlayer")
	member_names = {m.name for m in base_player.members}
	assert "PlayerFlags" not in member_names


def test_parent_type_still_has_own_methods():
	types = parse_cs_file(NESTED_CS)
	base_player = next(t for t in types if t.name == "BasePlayer")
	member_names = {m.name for m in base_player.members}
	assert "Die" in member_names


HOOK_CALLS_CS = """\
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
			object result = Interface.Call("OnPlayerRespawn", this);
		}

		public void DoNothing()
		{
			int x = 1;
		}
	}
}
"""


def test_extract_hook_calls_finds_callhook():
	types = parse_cs_file(HOOK_CALLS_CS)
	hooks = extract_hook_calls(types)
	names = {h.hook_name for h in hooks}
	assert "OnPlayerDeath" in names


def test_extract_hook_calls_finds_plain_call():
	types = parse_cs_file(HOOK_CALLS_CS)
	hooks = extract_hook_calls(types)
	names = {h.hook_name for h in hooks}
	assert "OnPlayerRespawn" in names


def test_extract_hook_calls_records_calling_method():
	types = parse_cs_file(HOOK_CALLS_CS)
	hooks = extract_hook_calls(types)
	death = next(h for h in hooks if h.hook_name == "OnPlayerDeath")
	assert death.calling_method == "Die"
	assert death.calling_type_fqn == "Rust.BasePlayer"


def test_extract_hook_calls_captures_args_without_leading_comma():
	types = parse_cs_file(HOOK_CALLS_CS)
	hooks = extract_hook_calls(types)
	death = next(h for h in hooks if h.hook_name == "OnPlayerDeath")
	assert not death.args_snippet.startswith(",")
	assert "this" in death.args_snippet
	assert "info" in death.args_snippet


def test_extract_hook_calls_dedupes_same_site():
	duplicate_cs = """\
namespace Rust
{
	public class Foo
	{
		public void Bar()
		{
			Interface.CallHook("OnThing", 1);
			Interface.CallHook("OnThing", 2);
		}
	}
}
"""
	types = parse_cs_file(duplicate_cs)
	hooks = extract_hook_calls(types)
	on_thing = [h for h in hooks if h.hook_name == "OnThing"]
	assert len(on_thing) == 1


def test_extract_hook_calls_ignores_methods_without_hooks():
	types = parse_cs_file(HOOK_CALLS_CS)
	hooks = extract_hook_calls(types)
	assert not any(h.calling_method == "DoNothing" for h in hooks)


NO_ACCESS_FIELD_CS = """\
namespace Rust
{
	public class Foo
	{
		static int counter;
		readonly string label = "x";
		const int MaxValue = 100;

		public void DoWork()
		{
		}
	}
}
"""


def test_parse_field_without_access_modifier_detected():
	types = parse_cs_file(NO_ACCESS_FIELD_CS)
	field_names = {m.name for m in types[0].members if m.kind == "field"}
	assert "counter" in field_names
	assert "label" in field_names
	assert "MaxValue" in field_names


def test_parse_field_without_access_modifier_defaults_to_internal():
	types = parse_cs_file(NO_ACCESS_FIELD_CS)
	counter = next(m for m in types[0].members if m.name == "counter")
	assert counter.access_modifier == "internal"


def test_parse_field_without_access_modifier_does_not_override_method():
	types = parse_cs_file(NO_ACCESS_FIELD_CS)
	field_names = {m.name for m in types[0].members if m.kind == "field"}
	assert "DoWork" not in field_names


MULTI_NAMESPACE_CS = """\
namespace System.Runtime.CompilerServices
{
	internal sealed class NullableContextAttribute : Attribute
	{
	}
}

namespace Rust
{
	public class BaseEntity
	{
		public int health;
	}

	public class BasePlayer : BaseEntity
	{
	}
}

namespace Oxide.Game.Rust
{
	public class RustCore
	{
	}
}
"""


def test_multi_namespace_types_attributed_correctly():
	types = parse_cs_file(MULTI_NAMESPACE_CS)
	by_name = {t.name: t for t in types}
	assert by_name["NullableContextAttribute"].namespace == "System.Runtime.CompilerServices"
	assert by_name["BaseEntity"].namespace == "Rust"
	assert by_name["BasePlayer"].namespace == "Rust"
	assert by_name["RustCore"].namespace == "Oxide.Game.Rust"


def test_multi_namespace_fqns_correct():
	types = parse_cs_file(MULTI_NAMESPACE_CS)
	fqns = {t.fully_qualified_name for t in types}
	assert "Rust.BaseEntity" in fqns
	assert "Rust.BasePlayer" in fqns
	assert "Oxide.Game.Rust.RustCore" in fqns
	assert "System.Runtime.CompilerServices.NullableContextAttribute" in fqns


NESTED_NAMESPACE_CS = """\
namespace Outer
{
	public class AtOuter
	{
	}

	namespace Inner
	{
		public class AtInner
		{
		}
	}
}
"""


def test_nested_namespace_types_attributed_correctly():
	types = parse_cs_file(NESTED_NAMESPACE_CS)
	by_name = {t.name: t for t in types}
	assert by_name["AtOuter"].namespace == "Outer"
	assert by_name["AtInner"].namespace == "Outer.Inner"
	assert by_name["AtOuter"].fully_qualified_name == "Outer.AtOuter"
	assert by_name["AtInner"].fully_qualified_name == "Outer.Inner.AtInner"


GLOBAL_SCOPE_CS = """\
public class NoNamespace
{
	public int value;
}

namespace Rust
{
	public class InNamespace
	{
	}
}
"""


def test_global_scope_type_has_empty_namespace():
	types = parse_cs_file(GLOBAL_SCOPE_CS)
	by_name = {t.name: t for t in types}
	assert by_name["NoNamespace"].namespace == ""
	assert by_name["NoNamespace"].fully_qualified_name == "NoNamespace"
	assert by_name["InNamespace"].namespace == "Rust"
	assert by_name["InNamespace"].fully_qualified_name == "Rust.InNamespace"
