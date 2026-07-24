"""Python-version compatibility shims (the package supports 3.9+)."""

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):
        """Backport of enum.StrEnum: members are strings and ``str()``
        yields the plain value."""

        def __str__(self) -> str:
            return str(self.value)


__all__ = ["StrEnum"]
