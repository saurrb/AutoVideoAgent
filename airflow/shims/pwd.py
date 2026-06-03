from __future__ import annotations

from collections import namedtuple
from getpass import getuser

struct_passwd = namedtuple(
    "struct_passwd",
    ["pw_name", "pw_passwd", "pw_uid", "pw_gid", "pw_gecos", "pw_dir", "pw_shell"],
)


def getpwuid(uid: int) -> struct_passwd:
    username = getuser() or "airflow"
    return struct_passwd(
        pw_name=username,
        pw_passwd="x",
        pw_uid=int(uid),
        pw_gid=int(uid),
        pw_gecos=username,
        pw_dir="C:\\",
        pw_shell="cmd.exe",
    )
