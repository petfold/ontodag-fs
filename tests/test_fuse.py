"""The FUSE mount (``odag-fs mount``), through the kernel.

Marker ``fuse`` — deselected by default (pyproject addopts); run with
``pytest -m fuse``. Skips, naming the missing piece, without fusepy,
libfuse 2, ``/dev/fuse`` or ``fusermount``. Mounts the offline zoo view
via ``swarmfs.fuse.mount(fs=...)`` — the same call ``cmd_mount`` makes —
and checks what a shell user sees: the lattice as directories, bytes,
read-only modes, and refused writes as EROFS rather than fsspec's raw
wrapper's EINVAL-with-traceback (the comparison that motivated the
switch, 2026-09-11).
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import subprocess
import time

import pytest

from conftest import build_zoo


def _fuse_unavailable() -> str | None:
    try:
        import fuse  # noqa: F401
    except ImportError:
        return "fusepy not installed (pip install 'swarmfs[fuse]')"
    except OSError as e:  # fusepy: EnvironmentError('Unable to find libfuse')
        return f"libfuse 2 not available: {e}"
    if not os.path.exists("/dev/fuse") or not os.access("/dev/fuse", os.R_OK | os.W_OK):
        return "/dev/fuse missing or not accessible"
    if not (shutil.which("fusermount") or shutil.which("fusermount3")):
        return "fusermount not on PATH"
    return None


def _unmount(mountpoint: str) -> None:
    for cmd in (["fusermount", "-u"], ["fusermount3", "-u"], ["umount"]):
        if shutil.which(cmd[0]):
            if subprocess.run([*cmd, mountpoint], capture_output=True).returncode == 0:
                return
    raise RuntimeError(f"could not unmount {mountpoint}")


@pytest.mark.fuse
@pytest.mark.parametrize("backend", ["memory", "ontodag"])
def test_mounted_view_through_the_kernel(backend, tmp_path):
    reason = _fuse_unavailable()
    if reason:
        pytest.skip(reason)
    from swarmfs.fuse import mount

    zoo = build_zoo(backend)
    mp = tmp_path / "mnt"
    mp.mkdir()
    th = mount("/", str(mp), fs=zoo.fs, fsname="odag-fs", foreground=False,
               ready_file=True)
    try:
        deadline = time.monotonic() + 15
        while not os.path.exists(mp / ".fuse_ready"):
            assert th.is_alive(), "FUSE thread died before the mount was ready"
            assert time.monotonic() < deadline, "mount did not become ready"
            time.sleep(0.05)

        # the lattice as directories, reserved namespaces included
        top = set(os.listdir(mp))
        assert {"animal", "document", ".swarm", ".unfiled", ".all"} <= top  # pet is under animal
        assert set(os.listdir(mp / "pet" / "dog")) == {"rex.jpg", "notes.txt", ".all"}
        assert (mp / "pet" / "dog" / "rex.jpg").read_bytes() == b"rex the dog"
        assert (mp / "pet" / "mammal" / "dog" / "rex.jpg").read_bytes() == b"rex the dog"
        with open(mp / "pet" / "dog" / "rex.jpg", "rb") as f:
            f.seek(4)
            assert f.read(3) == b"the"

        # honest attributes: real size, read-only modes, stable timestamps
        st = os.stat(mp / "pet" / "dog" / "rex.jpg")
        assert st.st_size == len(b"rex the dog")
        assert stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o444
        assert stat.S_IMODE(os.stat(mp / "pet").st_mode) == 0o555
        time.sleep(0.05)
        assert os.stat(mp / "pet" / "dog" / "rex.jpg").st_mtime == st.st_mtime

        # errno, not EINVAL: unknown concept is ENOENT, writes are EROFS
        with pytest.raises(FileNotFoundError):
            os.listdir(mp / "unicorn")
        for attempt in (
            lambda: open(mp / "pet" / "dog" / "new.txt", "wb"),
            lambda: os.unlink(mp / "pet" / "dog" / "rex.jpg"),
            lambda: os.mkdir(mp / "pet" / "hamster"),
            lambda: os.rename(mp / "pet" / "dog" / "rex.jpg", mp / "pet" / "cat" / "rex.jpg"),
        ):
            with pytest.raises(OSError) as e:
                attempt()
            assert e.value.errno in (errno.EROFS, errno.EACCES, errno.EPERM), e.value
    finally:
        _unmount(str(mp))
        th.join(timeout=10)
    assert not th.is_alive()
