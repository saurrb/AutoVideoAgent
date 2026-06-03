from __future__ import annotations

from collections import namedtuple
from getpass import getuser

struct_group = namedtuple("struct_group", ["gr_name", "gr_passwd", "gr_gid", "gr_mem"])


def getgrnam(name: str) -> struct_group:
    group_name = name or getuser() or "airflow"
    return struct_group(gr_name=group_name, gr_passwd="x", gr_gid=1000, gr_mem=[])
