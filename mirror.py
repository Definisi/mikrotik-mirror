#!/usr/bin/env python3
"""
MikroTik RouterOS Download Mirror

Downloads all RouterOS packages, install images, tools, and SHA256 checksums
from download.mikrotik.com for specified versions and architectures.

Usage:
    python mirror.py                    # download all configured versions/archs
    python mirror.py --version 7.20.8   # specific version only
    python mirror.py --arch arm64       # specific architecture only
    python mirror.py --dry-run          # show what would be downloaded
    python mirror.py --verify           # verify SHA256 after download
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

BASE_URL = "https://download.mikrotik.com/routeros"

ARCHITECTURES = ["arm64", "arm", "mipsbe", "mmips", "ppc", "smips", "tile", "x86"]

VERSIONS = [
    "7.20.8",
    "7.20.7",
    "6.49.19",
    "6.49.18",
    "6.49.13",
    "6.49.10",
]

# Extra packages available per RouterOS version family
# Not all packages exist for all architectures — 404s are silently skipped
PACKAGES_V7 = [
    "calea",
    "container",
    "dude",
    "extra-nic",
    "gps",
    "iot",
    "iot-bt-extra",
    "openflow",
    "rose-storage",
    "switch-marvell",
    "tr069-client",
    "ups",
    "user-manager",
    "wifi-qcom",
    "wireless",
    "zerotier",
]

PACKAGES_V6 = [
    "advanced-tools",
    "calea",
    "dhcp",
    "dude",
    "gps",
    "hotspot",
    "iot",
    "ipv6",
    "kvm",
    "lcd",
    "lora",
    "mpls",
    "multicast",
    "ntp",
    "openflow",
    "ppp",
    "routing",
    "security",
    "system",
    "tr069-client",
    "ups",
    "user-manager",
    "wireless",
    "zerotier",
]

# CHR (Cloud Hosted Router) virtual machine images
CHR_IMAGES_V7 = [
    "chr-{version}.img.zip",           # RAW disk (x86)
    "chr-{version}.ova",               # OVA (VMware/VirtualBox)
    "chr-{version}.vdi.zip",           # VDI (VirtualBox)
    "chr-{version}.vhd.zip",           # VHD (Hyper-V/VirtualPC)
    "chr-{version}.vhdx.zip",          # VHDX (Hyper-V)
    "chr-{version}.vmdk.zip",          # VMDK (VMware)
    "chr-{version}-arm64.img.zip",     # RAW disk (arm64)
    "chr-{version}-arm64.vdi.zip",     # VDI (arm64)
]

# SwitchOS firmware — two variants: SwitchOS (swos/) and SwitchOS Lite (swoslite/)
# Each entry: (base_path, board_slug, version, extension)
SWITCHOS_FIRMWARE = [
    # SwitchOS (original) — /swos/
    ("swos", "rb250",     "1.17", "lzb"),   # RB250GS
    ("swos", "rb260",     "1.17", "lzb"),   # RB260GS, RB260GSP
    ("swos", "css106",    "2.18", "bin"),   # new RB260GS(CSS106-5G-1S), new RB260GSP(CSS106-1G-4P-1S)
    ("swos", "css305",    "2.18", "bin"),   # CRS305-1G-4S+
    ("swos", "css305r2",  "2.18", "bin"),   # CRS305-1G-4S+OUT
    ("swos", "css309",    "2.18", "bin"),   # CRS309-1G-8S+
    ("swos", "css310",    "2.18", "bin"),   # CRS310-1G-5S-4S+IN, CRS310-1G-5S-4S+OUT
    ("swos", "css310g",   "2.18", "bin"),   # CRS310-8G+2S+IN
    ("swos", "css312",    "2.18", "bin"),   # CRS312-4C+8XG
    ("swos", "css317",    "2.18", "bin"),   # CRS317-1G-16S+
    ("swos", "css318fi",  "2.18", "bin"),   # CRS318-1Fi-15Fr-2S
    ("swos", "css318g",   "2.18", "bin"),   # CSS318-16G-2S+IN
    ("swos", "css318p",   "2.18", "bin"),   # CRS318-16P-2S+
    ("swos", "css320p",   "2.18", "bin"),   # CRS320-8P-8B-4S+RM
    ("swos", "css326",    "2.18", "bin"),   # CRS326-24G-2S+, CSS326-24G-2S+
    ("swos", "css326q",   "2.18", "bin"),   # CRS326-24S+2Q+
    ("swos", "css326xg",  "2.18", "bin"),   # CRS326-4C+20G+2Q+RM
    ("swos", "css328",    "2.18", "bin"),   # CRS328-4C-20S-4S+
    ("swos", "css328p",   "2.18", "bin"),   # CRS328-24P-4S+
    ("swos", "css354",    "2.18", "bin"),   # CRS354-48G-4S+2Q+, CRS354-48P-4S+2Q+
    # SwitchOS Lite — /swoslite/
    ("swoslite", "css606",    "2.21", "bin"),   # CSS606-1G-2Gi-3S+OUT
    ("swoslite", "css610",    "2.21", "bin"),   # netPower Lite 7R (CSS610-1Gi-7R-2S+)
    ("swoslite", "css610g",   "2.21", "bin"),   # CSS610-8G-2S+
    ("swoslite", "css610out", "2.21", "bin"),   # CSS610-8P-2S+OUT
    ("swoslite", "css610pi",  "2.21", "bin"),   # CSS610-8P-2S+IN
    ("swoslite", "gpen21",    "2.21", "bin"),   # GPEN21
    ("swoslite", "ftc11xg",   "2.21", "bin"),   # FTC11XG
    ("swoslite", "ftc21",     "2.21", "bin"),   # FTC21
    ("swoslite", "gper14i",   "2.21", "bin"),   # GPER14i
]

# WinBox management tool (separate versioning)
WINBOX_VERSION = "4.0.1"
WINBOX_FILES = [
    "WinBox.dmg",
    "WinBox_Linux.zip",
    "WinBox_Windows.zip",
]

# Tools that are version-specific but architecture-independent
TOOLS_VERSIONED = [
    "netinstall64-{version}.zip",
    "netinstall-{version}.zip",
    "netinstall-{version}.tar.gz",
    "dude-install-{version}.exe",
]

# Tools that are static per version
TOOLS_STATIC = [
    "btest.exe",
    "flashfig.exe",
    "mikrotik.mib",
]

# ── Version Discovery ────────────────────────────────────────────────────────

MIKROTIK_DOWNLOAD_PAGE = "https://mikrotik.com/download/routeros"


def discover_versions() -> list[str]:
    """Scrape the MikroTik download page to find all available versions."""
    try:
        req = urllib.request.Request(
            MIKROTIK_DOWNLOAD_PAGE,
            headers={"User-Agent": "MikroTik-Mirror/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Extract versions from <option> tags in the version dropdown
        # Pattern: <option value="7.20.8" ...>7.20.8</option>
        # or wire:model based options
        found = re.findall(r'<option[^>]*>\s*([\d]+\.[\d]+\.[\d]+)\s*</option>', html)
        if not found:
            # Fallback: look for version patterns in wire:snapshot or JS data
            found = re.findall(r'"((?:6|7)\.\d+\.\d+)"', html)

        # Deduplicate and sort (newest first)
        versions = sorted(set(found), key=lambda v: list(map(int, v.split("."))), reverse=True)
        return versions
    except Exception as e:
        print(f"WARNING: Failed to discover versions: {e}")
        print(f"         Falling back to hardcoded list")
        return VERSIONS


# ── Helpers ──────────────────────────────────────────────────────────────────

def is_v7(version: str) -> bool:
    return version.startswith("7.")


def arch_suffix(arch: str) -> str:
    """Return filename arch suffix. x86 has no suffix in MikroTik naming."""
    return "" if arch == "x86" else f"-{arch}"


def build_file_list(version: str, arch: str) -> list[str]:
    """Build list of filenames to download for a given version+arch combo."""
    sfx = arch_suffix(arch)
    files = []

    # Main RouterOS package
    files.append(f"routeros-{version}{sfx}.npk")

    # Install images
    if arch == "x86":
        files.append(f"install-image-{version}.zip")
        files.append(f"mikrotik-{version}.iso")
    else:
        files.append(f"mikrotik-{version}{sfx}.iso")

    # Extra packages
    packages = PACKAGES_V7 if is_v7(version) else PACKAGES_V6
    for pkg in packages:
        files.append(f"{pkg}-{version}{sfx}.npk")

    # All packages bundle
    files.append(f"all_packages-{arch}-{version}.zip")

    # Add SHA256 for each file
    files_with_sha = []
    for f in files:
        files_with_sha.append(f)
        files_with_sha.append(f"{f}.sha256")

    return files_with_sha


def build_tools_list(version: str) -> list[str]:
    """Build list of tool filenames (arch-independent, per version)."""
    files = []
    for tmpl in TOOLS_VERSIONED:
        files.append(tmpl.format(version=version))
    files.extend(TOOLS_STATIC)

    files_with_sha = []
    for f in files:
        files_with_sha.append(f)
        files_with_sha.append(f"{f}.sha256")

    return files_with_sha


def build_chr_list(version: str) -> list[str]:
    """Build list of CHR image filenames for a given version."""
    templates = CHR_IMAGES_V7 if is_v7(version) else []
    files = [t.format(version=version) for t in templates]

    files_with_sha = []
    for f in files:
        files_with_sha.append(f)
        files_with_sha.append(f"{f}.sha256")

    return files_with_sha


def build_winbox_list() -> list[str]:
    """Build list of WinBox filenames."""
    files_with_sha = []
    for f in WINBOX_FILES:
        files_with_sha.append(f)
        files_with_sha.append(f"{f}.sha256")

    return files_with_sha


def build_switchos_queue(output_dir: Path) -> list[tuple[str, Path]]:
    """Build download queue for all SwitchOS firmware files."""
    base = "https://download.mikrotik.com"
    queue = []
    for base_path, slug, version, ext in SWITCHOS_FIRMWARE:
        filename = f"swos-{slug}-{version}.{ext}"
        url = f"{base}/{base_path}/{version}/{filename}"
        dest = output_dir / base_path / version / filename
        queue.append((url, dest))
    return queue


def download_file(url: str, dest: Path, dry_run: bool = False) -> tuple[str, bool, str]:
    """Download a single file. Returns (url, success, message)."""
    if dest.exists():
        return (url, True, "exists")

    if dry_run:
        return (url, True, "dry-run")

    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MikroTik-Mirror/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
        return (url, True, "ok")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return (url, False, "404")
        return (url, False, f"HTTP {e.code}")
    except Exception as e:
        # Clean up partial download
        if dest.exists():
            dest.unlink()
        return (url, False, str(e))


def verify_sha256(version_dir: Path) -> list[tuple[str, bool, str]]:
    """Verify SHA256 checksums for all files in a version directory."""
    results = []
    for sha_file in sorted(version_dir.glob("*.sha256")):
        target_name = sha_file.stem  # remove .sha256
        target_path = version_dir / target_name

        if not target_path.exists():
            continue

        expected = sha_file.read_text().strip().split()[0].lower()
        actual = hashlib.sha256(target_path.read_bytes()).hexdigest().lower()

        if actual == expected:
            results.append((target_name, True, "ok"))
        else:
            results.append((target_name, False, f"expected {expected[:16]}... got {actual[:16]}..."))

    return results


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MikroTik RouterOS Download Mirror")
    parser.add_argument("--output", "-o", default="./downloads", help="Output directory (default: ./downloads)")
    parser.add_argument("--version", "-v", action="append", help="Specific version(s) to download (repeatable)")
    parser.add_argument("--arch", "-a", action="append", help="Specific architecture(s) to download (repeatable)")
    parser.add_argument("--workers", "-w", type=int, default=4, help="Parallel download workers (default: 4)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be downloaded")
    parser.add_argument("--verify", action="store_true", help="Verify SHA256 checksums after download")
    parser.add_argument("--tools-only", action="store_true", help="Only download tools (netinstall, dude, etc.)")
    parser.add_argument("--no-tools", action="store_true", help="Skip tools, only download packages")
    parser.add_argument("--no-chr", action="store_true", help="Skip CHR virtual machine images")
    parser.add_argument("--no-winbox", action="store_true", help="Skip WinBox downloads")
    parser.add_argument("--no-switchos", action="store_true", help="Skip SwitchOS firmware downloads")
    parser.add_argument("--generate-index", action="store_true", help="Generate index.json manifest")
    parser.add_argument("--auto-discover", action="store_true", help="Auto-discover versions from mikrotik.com")
    parser.add_argument("--retry", type=int, default=0, help="Retry failed/corrupt downloads N times")
    args = parser.parse_args()

    if args.auto_discover:
        print("Discovering versions from mikrotik.com...")
        discovered = discover_versions()
        if discovered:
            print(f"  Found: {', '.join(discovered)}")
        versions = args.version or discovered or VERSIONS
    else:
        versions = args.version or VERSIONS
    archs = args.arch or ARCHITECTURES
    output_dir = Path(args.output)

    # Validate inputs
    for v in versions:
        if v not in VERSIONS:
            print(f"WARNING: version {v} not in known list, proceeding anyway")
    for a in archs:
        if a not in ARCHITECTURES:
            print(f"ERROR: unknown architecture '{a}'. Valid: {', '.join(ARCHITECTURES)}")
            sys.exit(1)

    # Build download queue: list of (url, dest_path)
    queue = []

    if not args.tools_only:
        for version in versions:
            for arch in archs:
                files = build_file_list(version, arch)
                for filename in files:
                    url = f"{BASE_URL}/{version}/{filename}"
                    dest = output_dir / "routeros" / version / filename
                    queue.append((url, dest))

    if not args.no_tools:
        # Tools are arch-independent, download once per version
        seen_tools = set()
        for version in versions:
            tools = build_tools_list(version)
            for filename in tools:
                if filename not in seen_tools:
                    seen_tools.add(filename)
                    url = f"{BASE_URL}/{version}/{filename}"
                    dest = output_dir / "routeros" / version / filename
                    queue.append((url, dest))

    if not args.no_chr:
        # CHR images per version
        for version in versions:
            chr_files = build_chr_list(version)
            for filename in chr_files:
                url = f"{BASE_URL}/{version}/{filename}"
                dest = output_dir / "routeros" / version / filename
                queue.append((url, dest))

    if not args.no_winbox:
        # WinBox (separate version path)
        winbox_files = build_winbox_list()
        for filename in winbox_files:
            url = f"{BASE_URL}/winbox/{WINBOX_VERSION}/{filename}"
            dest = output_dir / "winbox" / WINBOX_VERSION / filename
            queue.append((url, dest))

    if not args.no_switchos:
        # SwitchOS firmware (separate base URLs per variant)
        queue.extend(build_switchos_queue(output_dir))

    total = len(queue)
    print(f"MikroTik RouterOS Mirror")
    print(f"  Versions:       {', '.join(versions)}")
    print(f"  Architectures:  {', '.join(archs)}")
    print(f"  Output:         {output_dir.resolve()}")
    print(f"  Files to check: {total}")
    if args.dry_run:
        print(f"  Mode:           DRY RUN")
    print()

    # Download
    downloaded = 0
    skipped = 0
    failed = 0
    not_found = 0
    errors = []

    start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(download_file, url, dest, args.dry_run): (url, dest)
            for url, dest in queue
        }

        for i, future in enumerate(as_completed(futures), 1):
            url, success, msg = future.result()
            filename = url.split("/")[-1]
            version = url.split("/")[-2]

            if success:
                if msg == "exists":
                    skipped += 1
                    status = "SKIP"
                elif msg == "dry-run":
                    downloaded += 1
                    status = "WOULD"
                else:
                    downloaded += 1
                    status = "OK"
            else:
                if msg == "404":
                    not_found += 1
                    status = "N/A"
                else:
                    failed += 1
                    status = "FAIL"
                    errors.append((url, msg))

            # Progress line
            if msg != "404":  # Don't spam 404s
                print(f"  [{i:4d}/{total}] {status:5s}  {version}/{filename}")

    elapsed = time.time() - start

    print()
    print(f"Done in {elapsed:.1f}s")
    print(f"  Downloaded: {downloaded}")
    print(f"  Skipped:    {skipped} (already exist)")
    print(f"  Not found:  {not_found} (expected, not all packages exist for all archs)")
    print(f"  Failed:     {failed}")

    if errors:
        print()
        print("Errors:")
        for url, msg in errors:
            print(f"  {url}: {msg}")

    # Verify checksums (with retry support)
    if args.verify and not args.dry_run:
        for attempt in range(1 + args.retry):
            print()
            if attempt > 0:
                print(f"Retry attempt {attempt}/{args.retry}...")
            print("Verifying SHA256 checksums...")
            verify_errors = []
            for version in versions:
                vdir = output_dir / "routeros" / version
                if vdir.exists():
                    results = verify_sha256(vdir)
                    for name, ok, msg in results:
                        if not ok:
                            verify_errors.append((version, name, msg))
                            print(f"  FAIL  {version}/{name}: {msg}")

            if not verify_errors:
                count = sum(1 for v in versions if (output_dir / "routeros" / v).exists())
                print(f"  All checksums verified across {count} version(s)")
                break

            if attempt < args.retry:
                print(f"\n{len(verify_errors)} checksum failure(s). Re-downloading corrupt files...")
                for version, name, _ in verify_errors:
                    corrupt = output_dir / "routeros" / version / name
                    if corrupt.exists():
                        corrupt.unlink()
                        url = f"{BASE_URL}/{version}/{name}"
                        result = download_file(url, corrupt)
                        print(f"  Re-downloaded: {version}/{name} -> {result[2]}")
            else:
                print(f"\n{len(verify_errors)} checksum verification(s) failed after {args.retry} retries!")
                sys.exit(1)

    # Generate index
    if args.generate_index:
        index = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "versions": {}}
        for version in versions:
            vdir = output_dir / "routeros" / version
            if vdir.exists():
                files = {}
                for f in sorted(vdir.iterdir()):
                    if f.is_file() and not f.name.endswith(".sha256"):
                        files[f.name] = {"size": f.stat().st_size}
                index["versions"][version] = {"files": files, "architectures": archs}

        index_path = output_dir / "index.json"
        index_path.write_text(json.dumps(index, indent=2))
        print(f"\nIndex written to {index_path}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
