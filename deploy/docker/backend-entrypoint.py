#!/usr/local/bin/python
"""Backend container entrypoint: fix data-dir ownership, then drop root.

Existing volumes may hold root-owned files, so a root start chowns
APP_DATA_DIRS to APP_UID:APP_GID and execs the command as that user. A
non-root start only checks the dirs are writable.
"""

import os
import sys


def _data_dirs():
    raw = os.environ.get("APP_DATA_DIRS", "")
    return [path for path in raw.split(":") if path]


def _chown_entry(name, uid, gid, dir_fd=None):
    try:
        stat = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return 0
    if stat.st_uid == uid and stat.st_gid == gid:
        return 0
    os.chown(name, uid, gid, dir_fd=dir_fd, follow_symlinks=False)
    return 1


def _chown_tree(root, uid, gid):
    # Every entry is chowned once, relative to its parent's fd, so a symlink
    # swapped into the tree mid-walk can never redirect a chown outside it.
    changed = _chown_entry(root, uid, gid)
    for _dirpath, dirnames, filenames, dir_fd in os.fwalk(root, follow_symlinks=False):
        for name in dirnames + filenames:
            changed += _chown_entry(name, uid, gid, dir_fd=dir_fd)
    return changed


def _drop_privileges(uid, gid):
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)


def _check_writable(dirs):
    bad = [path for path in dirs if os.path.isdir(path) and not os.access(path, os.W_OK | os.X_OK)]
    if bad:
        sys.stderr.write(
            f"error: uid {os.getuid()} cannot write {', '.join(bad)}. Start the container "
            "as root once so the entrypoint can chown them, or run: "
            f"chown -R {os.getuid()}:{os.getgid()} <dir> on the volume.\n"
        )
        sys.exit(1)


def main(argv):
    if not argv:
        sys.stderr.write("usage: backend-entrypoint.py COMMAND [ARGS...]\n")
        return 2
    dirs = _data_dirs()
    if os.getuid() == 0:
        uid = int(os.environ.get("APP_UID", "10001"))
        gid = int(os.environ.get("APP_GID", "10001"))
        for path in dirs:
            os.makedirs(path, exist_ok=True)
            changed = _chown_tree(path, uid, gid)
            if changed:
                print(f"entrypoint: chowned {changed} path(s) under {path} to {uid}:{gid}", flush=True)
        _drop_privileges(uid, gid)
        os.environ["HOME"] = os.environ.get("APP_HOME", "/home/app")
    _check_writable(dirs)
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
