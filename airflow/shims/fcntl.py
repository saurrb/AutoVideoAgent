from __future__ import annotations

FD_CLOEXEC = 1
F_GETFD = 1
F_SETFD = 2
F_GETFL = 3
F_SETFL = 4


def fcntl(_fd, _cmd, _arg=0):
    return 0
