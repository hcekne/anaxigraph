from __future__ import annotations

from anaxigraph.pattern_targets import (
    area_target,
    module_target,
    repository_target,
    subsystem_target,
    symbol_target,
    target_key,
)


def test_target_hierarchy_uses_portable_structural_identities():
    repository = repository_target("Sample")
    area = area_target("core services", "Core services", source="semantic")
    subsystem = subsystem_target(
        "billing/api",
        "Billing API",
        area_key=area.key,
        source="semantic",
    )
    module = module_target("./src\\billing/provider.py", subsystem_key=subsystem.key)
    type_target = symbol_target(
        module.path,
        "src.billing.provider.Provider",
        "class",
        parent_key=module.key,
        label="Provider",
    )
    method = symbol_target(
        module.path,
        "src.billing.provider.Provider.complete",
        "method",
        parent_key=type_target.key,
        label="complete",
    )

    assert repository.key == "repository:root"
    assert area.parent_key == repository.key
    assert area.key == "area:core%20services"
    assert subsystem.parent_key == area.key
    assert subsystem.key == "subsystem:billing%2Fapi"
    assert module.parent_key == subsystem.key
    assert module.key == "module:src/billing/provider.py"
    assert type_target.level == "type"
    assert method.level == "symbol"
    assert method.parent_key == type_target.key


def test_symbol_identity_does_not_depend_on_transient_rows_or_source_lines():
    first = target_key(
        "symbol",
        path="src/parser.py",
        identity="src.parser.parse#fragment",
    )
    second = target_key(
        "symbol",
        path="./src/parser.py",
        identity="src.parser.parse#fragment",
    )

    assert first == second
    assert first.endswith("src.parser.parse%23fragment")
