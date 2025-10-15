"""Minimal subset of distutils.version needed for Django on Python 3.12."""
from __future__ import annotations

import re
from functools import total_ordering
from itertools import zip_longest

_component_re = re.compile(r"(\d+|[a-zA-Z]+)")


def _normalize(value):
    """Return either an int or lower-cased string for comparison."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        try:
            return int(value)
        except ValueError:
            return value.lower()
    return str(value).lower()


@total_ordering
class LooseVersion:
    """Approximation of distutils' LooseVersion for compatibility."""

    def __init__(self, version: str):
        self.vstring = str(version)
        self.components = self._parse(self.vstring)
        self.version = list(self.components)

    def _parse(self, version: str):
        parts = []
        for match in _component_re.findall(version):
            if match.isdigit():
                parts.append(int(match))
            else:
                parts.append(match.lower())
        return parts

    def _compare(self, other: "LooseVersion | str") -> int:
        if not isinstance(other, LooseVersion):
            other = LooseVersion(other)
        for left, right in zip_longest(self.components, other.components, fillvalue=0):
            left_norm = _normalize(left)
            right_norm = _normalize(right)
            if left_norm == right_norm:
                continue
            return -1 if left_norm < right_norm else 1
        return 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, (LooseVersion, str)):
            return NotImplemented
        return self._compare(other) == 0

    def __lt__(self, other: "LooseVersion | str") -> bool:
        return self._compare(other) < 0

    def __repr__(self) -> str:
        return f"LooseVersion('{self.vstring}')"


class StrictVersion(LooseVersion):
    """Placeholder implementation for compatibility."""

    def __init__(self, version: str):
        super().__init__(version)

