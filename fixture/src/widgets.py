"""The fixture's one module: an in-memory widget store behind two gates.

Deliberately trivial. It exists so that a skill under test has real code to
read, a real `dark-ship` gate to point at, and a real place to add a chunk.
The `demo_*` half is what `demo-widget`'s chunk 1 is planned against, and is
intentionally *not* implemented yet: a smoke test of the `build` skill has
something to build.
"""

from __future__ import annotations

_STORE: list[dict[str, str]] = []
_STORE_ENABLED = False


def set_gate(enabled: bool) -> None:
    """Turn the store gate on or off (the `demo-foundation` dark-ship point)."""
    global _STORE_ENABLED
    _STORE_ENABLED = enabled


def store_enabled() -> bool:
    """True when the store may be read or written at all."""
    return _STORE_ENABLED


def add_widget(name: str, owner: str) -> None:
    """Store one widget. The owner is fixed here and never taken later."""
    if not store_enabled():
        return
    _STORE.append({"name": name, "owner": owner})


def list_widgets() -> list[dict[str, str]]:
    """Every stored widget, or nothing at all when the gate is off."""
    if not store_enabled():
        return []
    return list(_STORE)


# demo-widget/1 adds `demo_enabled`, `set_demo` and `demo_list` here.
