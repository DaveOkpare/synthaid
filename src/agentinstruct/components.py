"""Explicit, lazy component lookup without plugin discovery or construction at load."""

import importlib
import inspect
import re
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from agentinstruct.plans import EnvironmentPlan

type ComponentKind = Literal["agent", "environment", "tool", "reviewer", "verifier"]

# None denotes a component built with lifecycle-owned dependencies, or an existing
# injected-factory placeholder. Merely importing this registry imports no adapters.
BUILTIN_COMPONENTS: Mapping[ComponentKind, Mapping[str, str | None]] = MappingProxyType(
    {
        "agent": MappingProxyType(
            {"scripted": "agentinstruct.execution:ScriptedAgent", "model": None}
        ),
        "environment": MappingProxyType(
            {
                "single": "agentinstruct.execution:SingleAgentEnvironment",
                "dialogue": "agentinstruct.execution:DialogueEnvironment",
            }
        ),
        "tool": MappingProxyType({"custom": None, "function": None, "agent": None}),
        "reviewer": MappingProxyType(
            {
                "deterministic": "agentinstruct.review:DeterministicReviewer",
                "model": None,
                "custom": None,
            }
        ),
        "verifier": MappingProxyType(
            {
                "deterministic": "agentinstruct.verification:DeterministicVerifier",
                "model": None,
                "custom": None,
            }
        ),
    }
)
_REFERENCE = re.compile(
    r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", re.ASCII
)
_METHODS: Mapping[ComponentKind, Mapping[str, int]] = {
    "agent": {"generate": 1},
    "environment": {"setup": 1, "run": 2},
    "tool": {"call": 2},
    "reviewer": {"review": 1},
    "verifier": {"verify": 1},
}


class ComponentError(ValueError):
    def __init__(self, kind: str, reference: str, problem: str) -> None:
        self.kind, self.reference = kind, reference
        super().__init__(f"{kind} component {reference!r}: {problem}")


def component_selector(kind: ComponentKind, value: str) -> str:
    if value not in BUILTIN_COMPONENTS[kind] and _REFERENCE.fullmatch(value) is None:
        raise ComponentError(
            kind, value, "expected a built-in identifier or module:Class reference"
        )
    return value


def import_reference(kind: str, reference: str) -> object:
    if _REFERENCE.fullmatch(reference) is None:
        raise ComponentError(
            kind, reference, "expected an explicit module:attribute reference"
        )
    module_name, attribute = reference.split(":")
    try:
        target: object = importlib.import_module(module_name)
        for part in attribute.split("."):
            target = getattr(target, part)
        return target
    except Exception as exc:
        raise ComponentError(
            kind, reference, f"lookup failed ({type(exc).__name__})"
        ) from None


def _signature(
    kind: str, reference: str, target: object, count: int, label: str
) -> None:
    try:
        if not callable(target):
            raise TypeError
        inspect.signature(target).bind(*([None] * count))
    except (TypeError, ValueError):
        raise ComponentError(
            kind, reference, f"{label} must accept {count} positional arguments"
        ) from None


def validate_component(
    kind: ComponentKind, component: object, reference: str, *, definition: bool = False
) -> None:
    methods = dict(_METHODS[kind])
    if kind == "environment" and hasattr(component, "finalize"):
        methods["finalize"] = 2
    for name, count in methods.items():
        method = getattr(component, name, None)
        if not inspect.iscoroutinefunction(method):
            raise ComponentError(kind, reference, f"requires async {name}")
        # Class lookup binds classmethods, and staticmethods never receive self.
        # Only an ordinary instance method needs the receiver supplied here.
        unbound = definition and not isinstance(
            inspect.getattr_static(component, name), (staticmethod, classmethod)
        )
        _signature(kind, reference, method, count + int(unbound), name)
    if kind == "tool" and not definition:
        for attribute in (
            "id",
            "description",
            "input_schema",
            "output_schema",
            "execution_errors",
        ):
            if not hasattr(component, attribute):
                raise ComponentError(kind, reference, f"requires {attribute}")


def resolve_component(kind: ComponentKind, selector: str) -> type[object] | None:
    """Resolve and check only the requested class, without constructing it."""
    component_selector(kind, selector)
    reference = BUILTIN_COMPONENTS[kind].get(selector, selector)
    if reference is None:
        return None
    target = import_reference(kind, reference)
    if not inspect.isclass(target):
        raise ComponentError(kind, selector, "expected a component class")
    validate_component(kind, target, selector, definition=True)
    _signature(kind, selector, target, 0 if kind == "environment" else 1, "constructor")
    return target


def construct_component(kind: ComponentKind, selector: str, plan: object) -> object:
    cls = resolve_component(kind, selector)
    if cls is None:
        raise ComponentError(
            kind, selector, "requires a Runner-managed component or injected factory"
        )
    constructor = cast(Callable[..., object], cls)
    try:
        if kind == "environment":
            component = (
                constructor(cast("EnvironmentPlan", plan).initiator)
                if selector == "dialogue"
                else constructor()
            )
        else:
            component = constructor(plan)
    except Exception as exc:
        raise ComponentError(
            kind, selector, f"construction failed ({type(exc).__name__})"
        ) from None
    validate_component(kind, component, selector)
    return component


def resolve_callable(
    kind: str, reference: str, count: int, *, asynchronous: bool
) -> Callable[..., object]:
    target = import_reference(kind, reference)
    if not callable(target) or inspect.iscoroutinefunction(target) != asynchronous:
        expected = "async function" if asynchronous else "synchronous factory"
        raise ComponentError(kind, reference, f"expected a {expected}")
    _signature(kind, reference, target, count, "callable")
    if kind == "AgentTool factory" and inspect.isclass(target):
        validate_component("agent", target, reference, definition=True)
    return target
