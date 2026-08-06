from typing import Any, Callable


class _Mark:
    def skipif(self, condition: bool, *, reason: str) -> Callable[[Any], Any]: ...


mark: _Mark
