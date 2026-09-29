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


def _chown_tree(root, uid, gid):
    changed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # Real subdirs are chowned when walked as dirpath; walk skips dir symlinks.
        links = [name for name in dirnames if os.path.islink(os.path.join(dirpath, name))]
        for path in [dirpath, *(os.path.join(dirpath, name) for name in links + filenames)]:
            try:
                stat = os.lstat(path)
            except FileNotFoundError:
                continue
            if stat.st_uid != uid or stat.st_gid != gid:
                os.lchown(path, uid, gid)
                changed += 1
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
