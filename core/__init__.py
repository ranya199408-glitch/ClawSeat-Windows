# core/ package marker — makes `from core.resolve import ...` work
# after `pip install -e .` or when CLAWSEAT_ROOT is on PYTHONPATH.
#
# `__all__` pins the intended public surface. Anything not listed here
# is considered internal and may change without notice; see audit L3
# for the motivation (shells/ and adapters/ were importing ad-hoc and
# there was no way to tell which symbols counted as contract vs
# implementation detail).

__all__ = [
    "resolve",
    "harness_adapter",
    "bootstrap_receipt",
    "preflight",
    "skill_registry",
    # Namespaced subpackages with their own public surfaces:
    "adapter",     # ClawseatAdapter + AdapterResult types
    "engine",      # seat instantiation
    "transport",   # transport_router
    "migration",   # dynamic-roster migration scripts
]
