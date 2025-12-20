"""
Lightweight fallback for the removed stdlib ``distutils`` package.

Only the pieces needed by Django (``distutils.version``) are implemented.
This keeps management commands working in restricted environments where
``distutils`` cannot be installed system-wide.
"""

from .version import LooseVersion, StrictVersion  # noqa: F401

__all__ = ["LooseVersion", "StrictVersion"]
