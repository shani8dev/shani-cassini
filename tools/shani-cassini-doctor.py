#!/usr/bin/env python3
"""shani-cassini-doctor — self-check the tools shani-cassini needs.

For every feature, lists the external binaries it calls, marks each
present/missing, and prints the distro install command for anything missing.

Modelled on `voltkit doctor` and `shani-doctor`.

Exit 0 if every needed tool is present, 1 otherwise.
"""
from __future__ import annotations

import os
import shutil
import sys

FEATURES = [
    ("System & hardware", ["lsblk", "lspci", "lsmod", "smartctl", "btrfs"],
     "util-linux pciutils kmod smartmontools btrfs-progs",
     "util-linux pciutils kmod smartmontools btrfs-progs"),
    ("Firmware", ["fwupdmgr"],
     "fwupd", "fwupd"),
    ("Secure Boot / MOK", ["mokutil", "sbctl"],
     "mokutil sbctl", "mokutil sbctl"),
    ("Security keys", ["ykman"],
     "yubikey-manager", "yubikey-manager"),
    ("Bluetooth", ["bluetoothctl"],
     "bluez-utils", "bluez-utils"),
    ("Audio", ["systemctl"],
     "systemd", "systemd"),
    ("Containers", ["systemctl"],
     "systemd", "systemd"),
    ("Virtualization", ["systemctl"],
     "systemd", "systemd"),
    ("Backup", ["restic"],
     "restic", "restic"),
    ("Caddy", ["caddy"],
     "caddy", "caddy"),
    ("Cloudflared", ["cloudflared"],
     "cloudflared", "cloudflared"),
    ("Chronoa (AI assistant)", ["python3", "shani-chronoa"],
     "python shani-chronoa", "python3 shani-chronoa"),
    ("Notifications", ["notify-send"],
     "libnotify", "libnotify-bin"),
    ("Shell settings (gsettings)", ["gsettings"],
     "glib2", "libglib2.0-bin"),
    ("Privilege escalation", ["pkexec", "systemctl"],
     "polkit systemd", "policykit-1 systemd"),
    ("Debugging", ["coredumpctl"],
     "systemd-coredump", "systemd-coredump"),
    ("Whisper (speech)", ["whisper-cli"],
     "whisper-cpp", "whisper-cpp"),
    ("Ollama (LLM)", ["ollama"],
     "ollama", "ollama"),
]


def distro_id():
    try:
        with open("/etc/os-release") as f:
            info = {}
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    info[k.strip()] = v.strip().strip('"')
            return info.get("ID", "").lower()
    except OSError:
        return ""


def install_cmd(distro, arch_pkg, deb_pkg):
    arch_family = {"arch", "endeavouros", "manjaro"}
    deb_family = {"ubuntu", "debian", "linuxmint", "pop", "zorin", "raspbian"}
    if distro in arch_family:
        return "sudo pacman -S " + arch_pkg
    if distro in deb_family:
        return "sudo apt install " + deb_pkg
    return "install " + arch_pkg


def main():
    distro = distro_id()
    missing_any = False
    print("shani-cassini-doctor: tools shani-cassini needs")
    print("=" * 56)
    for name, tools, arch_pkg, deb_pkg in FEATURES:
        print("\n" + name)
        feature_missing = False
        for tool in tools:
            present = shutil.which(tool) is not None
            if not present:
                missing_any = True
                feature_missing = True
            print("  [{}] {}".format("OK " if present else "MISSING", tool))
        if feature_missing:
            print("    -> {}".format(install_cmd(distro, arch_pkg, deb_pkg)))
    print()
    if missing_any:
        print("Some tools are missing. Install them, then restart shani-cassini.")
        return 1
    print("All checked tools are present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())