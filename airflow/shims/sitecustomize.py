from __future__ import annotations

import signal


if not hasattr(signal, "SIGQUIT"):
    signal.SIGQUIT = signal.SIGTERM

if not hasattr(signal, "SIGTTIN"):
    signal.SIGTTIN = signal.SIGTERM

if not hasattr(signal, "SIGTTOU"):
    signal.SIGTTOU = signal.SIGTERM

if not hasattr(signal, "SIGTSTP"):
    signal.SIGTSTP = signal.SIGTERM
