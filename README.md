# mikrotik-mirror

A local mirror for **MikroTik RouterOS** downloads. This tool pulls every package, install image, tool, and SHA256 checksum from `download.mikrotik.com` and keeps them in sync on a schedule.

Why run your own mirror? If you manage dozens (or hundreds) of MikroTik devices, downloading updates from the official server for each one wastes bandwidth and time. A local mirror lets you point all your routers at one internal source. It also helps in air-gapped networks or regions with slow international links.

## What gets mirrored

| Category | Examples |
|----------|----------|
| System packages | `routeros-7.20.8-arm64.npk` |
| Install images | `.iso`, `.zip` (IMG) |
| Extra packages | container, dude, iot, wireless, zerotier, and more |
| All-in-one bundles | `all_packages-arm64-7.20.8.zip` |
| CHR images | RAW disk, OVA, VDI, VHD, VHDX, VMDK (x86 + arm64) |
| WinBox | macOS, Linux, Windows (v4.0.1) |
| Tools | Netinstall (Win64/Win32/Linux), The Dude, Bandwidth Test, FlashFig |
| Checksums | `.sha256` for every file above |

**Architectures:** `arm64` `arm` `mipsbe` `mmips` `ppc` `smips` `tile` `x86`

**Versions:** Auto-discovered from mikrotik.com, or use the built-in list (currently 7.20.8, 7.20.7, 6.49.19, 6.49.18, 6.49.13, 6.49.10).

## Quick start

```bash
git clone https://github.com/Definisi/mikrotik-mirror.git
cd mikrotik-mirror
python mirror.py
```

That downloads everything with 4 parallel workers. Files already on disk are skipped, so re-running the same command is safe and fast.

> [!NOTE]
> Requires **Python 3.10+** with no external dependencies. The script uses only the standard library.

## Usage

```bash
# Download all versions, all architectures
python mirror.py

# Only a specific version and architecture
python mirror.py -v 7.20.8 -a arm64

# Auto-discover the latest versions from mikrotik.com
python mirror.py --auto-discover

# Preview what would be downloaded without writing anything
python mirror.py --dry-run

# Download, verify checksums, and retry corrupt files up to 3 times
python mirror.py --verify --retry 3

# Generate an index.json manifest of all mirrored files
python mirror.py --generate-index

# Only grab tools (Netinstall, Dude, etc.)
python mirror.py --tools-only

# Only grab packages, skip tools
python mirror.py --no-tools
```

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `-o, --output DIR` | Output directory | `./downloads` |
| `-v, --version VER` | Download a specific version (repeatable) | all known |
| `-a, --arch ARCH` | Download a specific architecture (repeatable) | all 8 |
| `-w, --workers N` | Number of parallel download threads | `4` |
| `--auto-discover` | Scrape mikrotik.com for the current version list | off |
| `--dry-run` | Show what would be downloaded, download nothing | off |
| `--verify` | Verify SHA256 checksums after downloading | off |
| `--retry N` | Re-download corrupt files up to N times | `0` |
| `--generate-index` | Write `downloads/index.json` with file sizes | off |
| `--tools-only` | Only download tools (Netinstall, Dude, etc.) | off |
| `--no-tools` | Skip tools, download packages only | off |
| `--no-chr` | Skip CHR virtual machine images | off |
| `--no-winbox` | Skip WinBox downloads | off |

## Automated sync with GitHub Actions

The included workflow (`.github/workflows/sync.yml`) runs **every 6 hours**. Each run:

1. Auto-discovers the latest versions from mikrotik.com
2. Downloads new or updated files with 8 workers
3. Verifies all SHA256 checksums (retries corrupt files up to 3 times)
4. Generates `index.json`
5. Commits and pushes any changes

You can also trigger a sync manually from the **Actions** tab. Optional inputs let you limit the run to a specific version or architecture.

> [!IMPORTANT]
> The full mirror is around **2.6 GB**. Make sure your GitHub plan has enough storage, or adjust the versions and architectures to fit your needs.

## Directory layout

```
downloads/
  routeros/
    7.20.8/
      routeros-7.20.8-arm64.npk
      routeros-7.20.8-arm64.npk.sha256
      mikrotik-7.20.8-arm64.iso
      container-7.20.8-arm64.npk
      wireless-7.20.8-arm64.npk
      all_packages-arm64-7.20.8.zip
      chr-7.20.8.img.zip              # CHR images
      chr-7.20.8.ova
      chr-7.20.8.vmdk.zip
      chr-7.20.8-arm64.img.zip
      netinstall64-7.20.8.zip
      dude-install-7.20.8.exe
      btest.exe
      ...
    7.20.7/
      ...
  winbox/
    4.0.1/
      WinBox.dmg
      WinBox_Linux.zip
      WinBox_Windows.zip
  index.json          # generated with --generate-index
```

Files are organized by version. Each version directory contains all architectures and tools together, matching the structure on `download.mikrotik.com`.

## How it works

1. **Build a file list.** For each version and architecture, the script constructs the expected filenames using known URL patterns from MikroTik's download server.
2. **Download in parallel.** Files are fetched with multiple threads. Existing files are skipped. HTTP 404 responses are silently ignored because not every package exists for every architecture.
3. **Verify integrity.** When `--verify` is set, the script reads each `.sha256` file and compares it against the actual file hash. Corrupt files can be automatically re-downloaded with `--retry`.
4. **Version discovery.** The `--auto-discover` flag scrapes the MikroTik download page to find all currently listed versions, so you never need to update the script when MikroTik releases a new version.

## Pointing your routers at the mirror

Once you have a local mirror, serve the `downloads/routeros/` directory over HTTP (nginx, caddy, python -m http.server, etc.) and configure your routers to use it:

```
/system upgrade set update-channel=long-term
/system upgrade set package-source=http://your-mirror:8080/routeros
```

See the [MikroTik upgrade documentation](https://help.mikrotik.com/docs/display/ROS/Upgrading+and+installation) for details.

## Contributing

Found a missing package or architecture? Open an issue or submit a pull request. The package lists are defined at the top of `mirror.py` and are easy to extend.

## License

MIT
