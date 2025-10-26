"""Utilities for replacing OneShot examples in prompts."""
from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = (
    "ConfigError",
    "MarkdownDocument",
    "ReplacementPlan",
    "replace_oneshots",
)


def __getattr__(name: str) -> Any:  # pragma: no cover - simple lazy import
    if name in __all__:
        module = import_module(".replacer", __name__)
        return getattr(module, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
