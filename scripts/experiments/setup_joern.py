"""Explicit, project-local setup for the pinned Joern experiment. No global install."""

import argparse
import hashlib
import inspect
import json
from pathlib import Path
import platform
import shutil
import tarfile
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

VERSION = "4.0.666"
PACKAGES = {
    "joern": {
        "url": "https://github.com/joernio/joern/releases/download/v4.0.666/joern-cli-macos-arm64.zip",
        "sha256": "d4a45bd07b670bf70aefb99c9203173874804d0811ef72ea6d6b87f88f54743e",
        "name": "joern-cli-macos-arm64.zip",
        "size": 1756903260,
    },
    "jdk": {
        "url": "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.13_9.tar.gz",
        "sha256": "bf036b35b071bfb2f54f2c0af8ee8d88afa95ee6eb3dce02c0f94cfc2524d04a",
        "name": "OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.13_9.tar.gz",
        "size": 199754598,
    },
}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download(package, directory):
    target = directory / package["name"]
    if target.is_file() and digest(target) == package["sha256"]:
        return target
    partial = target.with_suffix(target.suffix + ".part")
    parts = directory / (package["name"] + ".parts")
    parts.mkdir(exist_ok=True)
    width = 64 * 1024 * 1024
    # Reuse complete segments from an interrupted sequential download.
    if partial.exists():
        with partial.open("rb") as stream:
            for number in range(partial.stat().st_size // width):
                segment = parts / str(number)
                block = stream.read(width)
                if not segment.exists():
                    segment.write_bytes(block)
    def segment(number):
        start, stop = number * width, min((number + 1) * width, package["size"]) - 1
        path = parts / str(number)
        if path.exists() and path.stat().st_size == stop - start + 1:
            return path
        for attempt in range(3):
            try:
                req = urllib.request.Request(package["url"], headers={"User-Agent": "CodeStrata-Joern-Evaluation", "Range": f"bytes={start}-{stop}"})
                with urllib.request.urlopen(req, timeout=60) as response, path.with_suffix(".part").open("wb") as out:
                    if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-{stop}/"):
                        raise ValueError("Server did not honor byte range")
                    shutil.copyfileobj(response, out, 1024 * 1024)
                path.with_suffix(".part").replace(path)
                if path.stat().st_size != stop-start+1:
                    raise ValueError("Truncated segment")
                print(json.dumps({"download": target.name, "segment": number, "MiB": (stop-start+1)//1048576}), flush=True)
                return path
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2)
    count = (package["size"] + width - 1) // width
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(segment, range(count)))
    with partial.open("wb") as out:
        for path in paths:
            with path.open("rb") as stream:
                shutil.copyfileobj(stream, out, 8 * 1024 * 1024)
    if digest(partial) != package["sha256"]:
        raise ValueError("SHA-256 mismatch: " + target.name)
    partial.replace(target)
    shutil.rmtree(parts)
    return target


def extract(archive, directory):
    directory.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            for entry in z.infolist():
                path = (directory / entry.filename).resolve()
                if not path.is_relative_to(directory.resolve()):
                    raise ValueError("Unsafe archive path")
                # The pinned distribution contains regular files/directories only.
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Unexpected symlink in zip")
                z.extract(entry, directory)
                mode = (entry.external_attr >> 16) & 0o777
                if mode and not entry.is_dir():
                    path.chmod(mode)
    else:
        with tarfile.open(archive) as tar:
            for member in tar.getmembers():
                if member.isdev() or member.isfifo():
                    raise ValueError("Unexpected special file in archive")
                path = (directory / member.name).resolve()
                if not path.is_relative_to(directory.resolve()):
                    raise ValueError("Unsafe archive path")
                if member.issym() or member.islnk():
                    base = path.parent if member.issym() else directory
                    if not (base / member.linkname).resolve().is_relative_to(directory.resolve()):
                        raise ValueError("Unsafe archive link")
            if 'filter' in inspect.signature(tar.extractall).parameters:
                tar.extractall(directory, filter="data")
            else:
                # Python 3.10 before extraction-filter backports: paths, links
                # and special-file types have already been checked above.
                tar.extractall(directory)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", required=True, type=Path)
    cli.add_argument("--only", choices=PACKAGES, help="Prepare one package independently")
    args = cli.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        cli.error("This pinned setup supports macOS arm64 only; the probe accepts explicit tools elsewhere.")
    root = args.output.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    archives = root / "downloads"
    archives.mkdir(exist_ok=True)
    for name, package in PACKAGES.items():
        if args.only and name != args.only:
            continue
        archive = download(package, archives)
        dest = root / name
        marker = dest / ".verified-sha256"
        if not marker.is_file() or marker.read_text() != package["sha256"]:
            if dest.exists():
                shutil.rmtree(dest)
            extract(archive, dest)
            marker.write_text(package["sha256"])
        print(json.dumps({"ready": name, "path": str(dest)}), flush=True)
    if not all((root / name / ".verified-sha256").exists() for name in PACKAGES):
        return
    manifest = {"joernVersion": VERSION, "jdkVersion": "21.0.13+9", "packages": PACKAGES}
    manifest["joern"] = str(next((root / "joern").rglob("joern-cli/joern")))
    manifest["java"] = str(next((root / "jdk").rglob("Contents/Home/bin/java")))
    (root / "tools.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
