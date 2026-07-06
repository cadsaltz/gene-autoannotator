from autoannotation import organisms
from autoannotation.consensus import FieldSpec, field_specs_from_profile


def test_field_specs_from_profile_includes_identity_and_llm_fields():
    profile = organisms.resolve_profile('mtb-h37rv')
    specs = field_specs_from_profile(field_defs_profile=profile)
    keys = [spec.key for spec in specs]
    assert keys[:2] == ['gene_id', 'name']
    assert specs[0].kind == 'identity'
    assert specs[1].kind == 'identity'
    assert 'function' in keys
    assert 'functional_category' in keys
    assert 'essential_in_vitro' in keys
    function_spec = next(spec for spec in specs if spec.key == 'function')
    assert function_spec.kind == 'string'
    category_spec = next(spec for spec in specs if spec.key == 'functional_category')
    assert category_spec.kind == 'array'
