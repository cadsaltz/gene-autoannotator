"""Deprecated compatibility package; import from :mod:`backend` instead."""

import importlib
import sys


_MODULES = (
    "annotation_store",
    "api",
    "batch_store",
    "job_store",
    "profile_store",
    "regex_gen",
    "runner",
    "schemas",
    "worker_registry",
)

for _name in _MODULES:
    _module = importlib.import_module(f"backend.{_name}")
    globals()[_name] = _module
    sys.modules[f"{__name__}.{_name}"] = _module

del _module
del _name
