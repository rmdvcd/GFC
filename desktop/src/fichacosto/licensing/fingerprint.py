"""Privacy-conscious device fingerprint used for offline license binding.

The digest is SHA-256 over a versioned, unit-separator-delimited tuple. Raw hardware
identifiers are never returned or persisted by this module. It intentionally avoids
IMEI, serial numbers, usernames, and files containing personal data.
"""
from __future__ import annotations

import hashlib
import platform
import re
import subprocess
import unicodedata
import uuid
from pathlib import Path


def _stable_platform_id() -> str:
    system = platform.system().lower()
    if system == "windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                return str(value).strip()
        except (ImportError, OSError, ValueError):
            return ""
    if system == "linux":
        for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
            try:
                value = path.read_text(encoding="ascii").strip()
                if value:
                    return value
            except OSError:
                pass
        return ""
    if system == "darwin":
        try:
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                check=True, capture_output=True, text=True, timeout=3,
            )
            match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', result.stdout)
            return match.group(1).strip() if match else ""
        except (OSError, subprocess.SubprocessError):
            return ""
    return ""


def _fingerprint_components() -> tuple[str, ...]:
    # Include an explicit version tag and stable fields in a fixed order. A separator
    # prevents ambiguous concatenations (e.g. "ab"+"c" versus "a"+"bc").
    mac = uuid.getnode()
    return (
        "FichaCostoDeviceV1",
        platform.system().strip(),
        platform.node().strip(),
        f"{mac:012x}",
        platform.machine().strip(),
        _stable_platform_id(),
    )


def get_device_fingerprint() -> str:
    normalized = [unicodedata.normalize("NFC", part) for part in _fingerprint_components()]
    canonical = "\x1f".join(normalized).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
