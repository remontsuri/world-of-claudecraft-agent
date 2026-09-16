#!/usr/bin/env python3
"""Fetch MaleCNS v1.0 flat-connectome tables from the public Janelia GS bucket.

No neuPrint account and no API token are required: the flat-connectome exports
are served from a public Google Storage bucket as plain HTTP objects.

    python tools/fetch_malecns.py --out /data/malecns --set circuit
    python tools/fetch_malecns.py --out /data/malecns --set full
    python tools/fetch_malecns.py --out /data/malecns --all

Sets (the names in ``--set`` map 1:1 onto the rows of the download page):
  circuit : body-annotations + body-neurotransmitters + traced-only weights
            -> exactly what fly-woc/build_circuit.py consumes (write the
               project layout with --link-project-names: annotations.feather,
               neurotransmitters.feather, edges-traced.feather)
  full    : connectome-weights (all segments, 1.05 GB) -- the complete graph,
            the file named in the AGENTS.md "never commit 1 GB" rule
  extra   : body-stats, significant-only weights, syn-partners variants
  heavy   : syn-points (13 GB) + tbar-neurotransmitters (2.7 GB)

Properties: resumable (HTTP Range), streaming SHA-256, size + hash check,
never loads a file into RAM, writes a manifest.json next to the data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome"
DATASET = "FlyEM MaleCNS v1.0 (min confidence 0.5), CC BY 4.0"
SOURCE_PAGE = "https://male-cns.janelia.org/download/"

# name -> (bucket file, bytes, project filename or None, sha256 or None)
FILES: dict[str, dict[str, dict]] = {
    "circuit": {
        "annotations": dict(
            remote="body-annotations-male-cns-v1.0-minconf-0.5.feather",
            bytes=14483314, project="annotations.feather",
            # hash published in fly-woc/data/manifest.json (verified against the
            # bucket object on 2026-09-15: identical file)
            sha256="2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2"),
        "neurotransmitters": dict(
            remote="body-neurotransmitters-male-cns-v1.0.feather",
            bytes=43282834, project="neurotransmitters.feather",
            sha256="95c9289220663abeb3409f3ad9e5a7f8a53f8093f5139d15502cd08da8879621"),
        "edges-traced": dict(
            remote="connectome-weights-male-cns-v1.0-minconf-0.5-traced-only.feather",
            bytes=508025642, project="edges-traced.feather",
            sha256="9b3beab17bad5f618be3f2c02d3139a8d07b822565919c013f1e5506d93e604b"),
    },
    "full": {
        "connectome-weights": dict(
            remote="connectome-weights-male-cns-v1.0-minconf-0.5.feather",
            bytes=1051241946, project="connectome-weights.feather", sha256=None),
    },
    "extra": {
        "body-stats": dict(remote="body-stats-male-cns-v1.0-minconf-0.5.feather",
                           bytes=778062826, project=None, sha256=None),
        "edges-significant": dict(
            remote="connectome-weights-male-cns-v1.0-minconf-0.5-significant-only.feather",
            bytes=502169298, project="edges-significant.feather", sha256=None),
        "syn-partners-traced": dict(
            remote="syn-partners-male-cns-v1.0-minconf-0.5-traced-only.feather",
            bytes=2965367002, project=None, sha256=None),
    },
    "heavy": {
        "syn-points": dict(remote="syn-points-male-cns-v1.0-minconf-0.5.feather",
                           bytes=13061489098, project=None, sha256=None),
        "tbar-neurotransmitters": dict(
            remote="tbar-neurotransmitters-male-cns-v1.0.feather",
            bytes=2651680218, project=None, sha256=None),
    },
}
SETS = list(FILES) + ["all"]


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1000
    return f"{n:.1f} TB"


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def head_size(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return int(r.headers["Content-Length"])
    except (urllib.error.URLError, KeyError, ValueError):
        return None


def download(url: str, dest: Path, expect: int | None) -> tuple[str, int]:
    """Resumable download. Returns (sha256, size). Never buffers in RAM."""
    part = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    have = part.stat().st_size if part.exists() else 0
    if dest.exists() and (expect is None or dest.stat().st_size == expect):
        return sha256_file(dest), dest.stat().st_size
    if dest.exists():
        dest.unlink()
    if have:
        with part.open("rb") as fh:            # rehash what we already have
            while block := fh.read(1 << 22):
                h.update(block)
        print(f"    resuming at {human(have)}")
    req = urllib.request.Request(url)
    if have:
        req.add_header("Range", f"bytes={have}-")
    t0, done = time.time(), have
    with urllib.request.urlopen(req, timeout=60) as resp, part.open("ab") as out:
        total = expect or (have + int(resp.headers.get("Content-Length", 0)))
        while block := resp.read(1 << 22):
            out.write(block)
            h.update(block)
            done += len(block)
            if total:
                pct = 100 * done / total
                rate = done / max(time.time() - t0, 1e-9) / 1e6
                print(f"\r    {pct:5.1f}%  {human(done)}/{human(total)}  {rate:6.1f} MB/s",
                      end="", flush=True)
    print()
    part.replace(dest)
    return h.hexdigest(), dest.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path, help="target directory")
    ap.add_argument("--set", dest="sets", action="append", choices=SETS, default=[],
                    help="subset to fetch (repeatable); 'all' = every set")
    ap.add_argument("--all", action="store_true", help="same as --set all")
    ap.add_argument("--link-project-names", action="store_true",
                    help="also hardlink files to the names build_circuit.py expects "
                         "(annotations.feather, neurotransmitters.feather, edges-traced.feather)")
    ap.add_argument("--check-only", action="store_true",
                    help="verify existing files, do not download")
    args = ap.parse_args()

    chosen = list(FILES) if (args.all or "all" in args.sets) else args.sets
    if not chosen and not args.check_only:
        ap.error(f"pick a set: {SETS}")

    args.out.mkdir(parents=True, exist_ok=True)
    entries, failed = {}, []
    for set_name in chosen:
        for key, meta in FILES[set_name].items():
            url = f"{BASE}/{meta['remote']}"
            dest = args.out / meta["remote"]
            print(f"[{set_name}] {key}: {meta['remote']}")
            size = head_size(url)
            if size is not None:
                print(f"    remote size {human(size)}")
            if args.check_only:
                if not dest.exists():
                    print("    MISSING"); failed.append(key); continue
                digest = sha256_file(dest)
                got = dest.stat().st_size
            else:
                digest, got = download(url, dest, size or meta["bytes"])
            ok = (meta["sha256"] is None or digest == meta["sha256"])
            if size is not None and got != size:
                ok = False
            print(f"    {'OK ' if ok else 'FAIL'} {human(got)} sha256={digest[:16]}…")
            if meta["sha256"]:
                print(f"    expected sha256={meta['sha256'][:16]}…  "
                      f"{'match (source identity confirmed)' if ok else 'MISMATCH'}")
            if not ok:
                failed.append(key)
            entries[key] = dict(file=meta["remote"], url=url, bytes=got, sha256=digest,
                                expected_sha256=meta["sha256"], verified=ok,
                                project_name=meta["project"],
                                fetched_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            if args.link_project_names and meta["project"]:
                link = args.out / meta["project"]
                if not link.exists():
                    try:
                        os.link(dest, link)
                    except OSError:
                        link.write_bytes(dest.read_bytes())
                print(f"    -> {meta['project']}")

    man_path = args.out / "fetch-manifest.json"
    previous = json.loads(man_path.read_text()) if man_path.exists() else {}
    previous.update({k: v for k, v in entries.items()})
    man_path.write_text(json.dumps(dict(dataset=DATASET, source_page=SOURCE_PAGE,
                                        base_url=BASE, files=previous), indent=2) + "\n")
    print(f"\nmanifest: {man_path}")
    if failed:
        print(f"FAILED: {failed}", file=sys.stderr)
        return 1
    print("all requested files verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
