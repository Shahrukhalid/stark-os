"""The desktop app's single-instance guard (no window needed)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

APP = Path(__file__).resolve().parents[3] / "desktop" / "stark_desktop.py"


def load():
    spec = importlib.util.spec_from_file_location("stark_desktop", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_second_launch_shows_first_window_instead_of_starting():
    d = load()
    assert d.single_instance_check()


def test_port_used_by_another_program_does_not_block_the_app():
    import socket

    d = load()
    other = socket.socket()
    other.bind(("127.0.0.1", 0))
    other.listen(1)  # something that is not STARK AI: never answers the handshake
    try:
        inst = d.SingleInstance(other.getsockname()[1])
        assert inst.acquire() is True and inst.sock is None
    finally:
        other.close()
