from __future__ import annotations

RLIMIT_CORE = 4
RLIMIT_NOFILE = 7
RLIM_INFINITY = -1


def getrlimit(_limit: int):
    return (RLIM_INFINITY, RLIM_INFINITY)


def setrlimit(_limit: int, _value) -> None:
    return None
