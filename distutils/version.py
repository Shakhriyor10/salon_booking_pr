"""
Minimal drop-in replacement for :mod:`distutils.version`.

This module provides ``LooseVersion``/``StrictVersion`` APIs that wrap
``packaging.version.Version`` so Django can perform version comparisons
without the deprecated stdlib package.
"""

from packaging.version import InvalidVersion, Version


class LooseVersion:
    def __init__(self, vstring=None):
        self.vstring = "" if vstring is None else str(vstring)
        try:
            self._version = Version(self.vstring) if vstring is not None else None
        except InvalidVersion:
            self._version = None
        if self._version is not None:
            components = list(self._version.release)
            if self._version.pre:
                components.extend(self._version.pre)
            self.version = components
        else:
            self.version = []

    def _coerce(self, other):
        other_string = "" if other is None else str(other)
        try:
            other_version = Version(other_string)
        except InvalidVersion:
            other_version = None
        return other_string, other_version

    def __repr__(self):
        return f"LooseVersion('{self.vstring}')"

    def __str__(self):
        return self.vstring

    def __eq__(self, other):
        other_string, other_version = self._coerce(other)
        if self._version is None or other_version is None:
            return self.vstring == other_string
        return self._version == other_version

    def __lt__(self, other):
        other_string, other_version = self._coerce(other)
        if self._version is None or other_version is None:
            return self.vstring < other_string
        return self._version < other_version

    def __le__(self, other):
        return self == other or self < other

    def __gt__(self, other):
        return not self.__le__(other)

    def __ge__(self, other):
        return not self.__lt__(other)


class StrictVersion(LooseVersion):
    """Alias kept for API compatibility."""


__all__ = ["LooseVersion", "StrictVersion"]