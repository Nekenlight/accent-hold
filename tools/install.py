#!/usr/bin/env python3
"""Install only owned files; never change the user's selected input sources."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
FILES = ("run.py", "LICENSE", "accent_hold/__init__.py", "accent_hold/core.py",
         "accent_hold/variants.py", "accent_hold/ibus_engine.py")
INSTALL_DIR = Path("libexec/accent-hold")
COMPONENT = Path("share/ibus/component/accent-hold.xml")
MANIFEST = INSTALL_DIR / "install-manifest.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def payload(prefix):
    files = {INSTALL_DIR / name: (REPO / name).read_bytes() for name in FILES}
    root = ET.Element("component")
    for key, value in {
        "name": "org.freedesktop.IBus.AccentHold", "description": "Press-and-hold Latin accents",
        "exec": shlex.join([sys.executable, str(prefix / INSTALL_DIR / "run.py"), "--ibus"]),
        "version": "0.1.0", "author": "Accent Hold contributors", "license": "MIT",
        "homepage": "", "textdomain": "",
    }.items():
        ET.SubElement(root, key).text = value
    engine = ET.SubElement(ET.SubElement(root, "engines"), "engine")
    for key, value in {
        "name": "accent-hold", "longname": "Accent Hold", "language": "en",
        "description": "Hold a letter to choose an accent", "license": "MIT",
        "author": "Accent Hold contributors", "icon": "input-keyboard", "layout": "default",
    }.items():
        ET.SubElement(engine, key).text = value
    ET.indent(root)
    files[COMPONENT] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return files


def refresh_cache(prefix):
    # IBus does not scan the per-user component directory by default. Include
    # system engines and any caller-specified directories when rebuilding it.
    system_dir = Path("/usr/share/ibus/component")
    pkg_config = subprocess.run(
        ["pkg-config", "--variable=datadir", "ibus-1.0"], capture_output=True, text=True,
        check=False,
    ) if shutil.which("pkg-config") else None
    if pkg_config and pkg_config.returncode == 0 and pkg_config.stdout.strip():
        system_dir = Path(pkg_config.stdout.strip()) / "ibus/component"
    user_dirs = [prefix / "share/ibus/component"]
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    user_dirs.append(data_home / "ibus/component")
    paths = [str(p) for p in user_dirs if p.is_dir()] + [str(system_dir)]
    paths.extend(filter(None, os.environ.get("IBUS_COMPONENT_PATH", "").split(os.pathsep)))
    env = dict(os.environ, IBUS_COMPONENT_PATH=os.pathsep.join(dict.fromkeys(paths)))
    subprocess.run(["ibus", "write-cache"], env=env, check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reversible per-user installation of Accent Hold")
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh-cache", action="store_true", help="Rebuild the user IBus registry cache")
    args = parser.parse_args(argv)
    prefix = args.prefix.expanduser().resolve()
    marker = prefix / MANIFEST
    allowed = {INSTALL_DIR / name for name in FILES} | {COMPONENT}
    if args.action == "install":
        files = payload(prefix)
        # Refuse to overwrite another installation or local edits, including
        # unowned files that happen to contain the same bytes.
        if marker.exists():
            manifest = json.loads(marker.read_text())
            expected = {str(path): digest(data) for path, data in files.items()}
            if manifest != expected or any(
                not (prefix / path).is_file() or (prefix / path).read_bytes() != data
                for path, data in files.items()
            ):
                raise ValueError("Different installation found: uninstall the previous version first.")
            print("Installation is already up to date.")
        else:
            for path in files:
                if (prefix / path).exists() or (prefix / path).is_symlink():
                    raise ValueError(f"Existing unmanaged file: {prefix / path}")
            for path in [*files, MANIFEST]:
                print(f"Install {prefix / path}")
            if not args.dry_run:
                for path, data in files.items():
                    target = prefix / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                marker.write_text(json.dumps({str(p): digest(d) for p, d in files.items()}, indent=2) + "\n")
    else:
        if not marker.is_file():
            raise ValueError(f"No managed installation found in {prefix}")
        manifest = json.loads(marker.read_text())
        if set(manifest) != {str(p) for p in allowed}:
            raise ValueError("Invalid installation manifest.")
        for path, expected in manifest.items():
            target = prefix / path
            if target.is_symlink() or not target.is_file() or digest(target.read_bytes()) != expected:
                raise ValueError(f"Modified or missing file; refusing removal: {target}")
        for path in [*(prefix / p for p in manifest), marker]:
            print(f"Remove {path}")
            if not args.dry_run:
                path.unlink()
        if not args.dry_run:
            # Python may have generated bytecode here; leave untracked files
            # alone rather than recursively deleting the installation directory.
            for directory in (prefix / INSTALL_DIR / "accent_hold", prefix / INSTALL_DIR):
                try:
                    directory.rmdir()
                except OSError:
                    pass
    if args.refresh_cache and not args.dry_run:
        refresh_cache(prefix)
    if args.action == "install":
        if not args.refresh_cache:
            print("To register the engine, run install again with --refresh-cache.")
        print("Log out and back in, then add Accent Hold to the GNOME input sources.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
