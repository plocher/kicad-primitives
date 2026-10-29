"""Opt-in footprint-library gates on explicit ``.pretty`` paths; originals are never written.

Run with --help. Normal unittest discovery does not depend on local installations.
The output directory must not exist; every edit and every KiCad invocation uses a
disposable copy beneath it. With ``--kicad-cli`` the copy is rendered with
``kicad-cli fp export svg`` after the edits, which proves KiCad 10 still loads
every edited, created, copied, and renamed footprint.
"""

import argparse
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from kicad_primitives.footprints import FootprintLibrary


@dataclass(frozen=True)
class LibraryResult:
    """Measured facts and input identity, not a general compatibility claim."""

    input_path: str
    sha256: str
    footprints: int
    failures: int
    no_op_bytes: int
    edited: str | None
    exact_delta: bool | None
    created: str
    copied: str | None
    renamed: str | None
    svg_count: int | None


def _tree_digest(library: Path) -> str:
    digest = sha256()
    for path in sorted(library.glob("*.kicad_mod")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _only_delta(before: bytes, after: bytes, old: bytes, new: bytes) -> bool:
    start = before.find(old)
    while start != -1:
        if after == before[:start] + new + before[start + len(old) :]:
            return True
        start = before.find(old, start + 1)
    return False


def _export(cli: Path, library: Path, output: Path) -> int:
    output.mkdir()
    subprocess.run(
        [str(cli), "fp", "export", "svg", "--output", str(output), str(library)],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return len(list(output.glob("*.svg")))


def _verify(path: Path, output: Path, cli: Path | None) -> LibraryResult:
    digest = _tree_digest(path)
    output.mkdir()
    copy = output / path.name
    shutil.copytree(path, copy)
    library = FootprintLibrary.open(copy)
    no_op = 0
    for summary in library.summaries:
        footprint = library.footprint(summary.name)
        assert footprint.to_bytes() == summary.path.read_bytes(), "No-op byte mismatch"
        no_op += 1
        footprint.close()
    assert not library.is_modified
    target = next(
        (s for s in library.summaries if s.version == 20260206),
        None,
    )
    edited: str | None = None
    exact: bool | None = None
    if target is not None:
        footprint = library.footprint(target.name)
        before = footprint.to_bytes()
        old = footprint.attribute("Value").value
        new = old + ' [slice proof: "quoted" café \\ path]'
        footprint.set_attribute("Value", new)
        footprint.add_attribute("kicad_primitives_probe", "added")
        footprint.delete_attribute("kicad_primitives_probe")
        after = footprint.to_bytes()
        exact = _only_delta(
            before,
            after,
            json.dumps(old, ensure_ascii=False).encode("utf-8"),
            json.dumps(new, ensure_ascii=False).encode("utf-8"),
        )
        assert exact, "Unexpected source delta"
        assert target.path.read_bytes() == before, "Editing implicitly wrote to disk"
        footprint.validate()
        footprint.save()
        assert target.path.read_bytes() == after, "Save changed preview bytes"
        assert not footprint.is_modified
        edited = target.name
        footprint.close()
    created = "kicad_primitives_created"
    library.create(created)
    copied: str | None = None
    renamed: str | None = None
    if target is not None:
        copied = f"{target.name}_copy"
        library.copy(target.name, copied)
        renamed = f"{target.name}_renamed"
        library.rename(copied, renamed)
    library.refresh()
    names = {s.name for s in library.summaries}
    assert created in names and (renamed is None or renamed in names), (
        "Directory ops lost"
    )
    assert copied is None or copied not in names, "Rename left the old file behind"
    library.close()
    final = FootprintLibrary.open(copy)
    failures = len(final.failures)
    svg_count: int | None = None
    if cli is not None:
        for failure in final.failures:
            failure.path.unlink()  # KiCad refuses a library with unreadable files
        final.refresh()
        svg_count = _export(cli, copy, output / "svg")
        assert svg_count == len(final.summaries), "KiCad did not render every footprint"
    footprints = len(final.summaries)
    final.close()
    assert _tree_digest(path) == digest, "Original changed during verification"
    return LibraryResult(
        str(path),
        digest,
        footprints,
        failures,
        no_op,
        edited,
        exact,
        created,
        copied,
        renamed,
        svg_count,
    )


def main() -> None:
    """Verify explicit library paths, producing a JSON record and disposable copies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("libraries", nargs="+", type=Path)
    parser.add_argument(
        "--output", required=True, type=Path, help="New output directory"
    )
    parser.add_argument(
        "--kicad-cli", type=Path, help="Optional explicit KiCad CLI path"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    records = []
    for i, path in enumerate(args.libraries):
        record = _verify(path.absolute(), args.output / f"library-{i}", args.kicad_cli)
        records.append(asdict(record))
        (args.output / "results.json").write_text(json.dumps(records, indent=2) + "\n")
        print(
            f"{path.name}: {record.footprints} footprints, {record.failures} failures,"
            f" edited={record.edited}, svg={record.svg_count}",
            flush=True,
        )
    print(f"Results: {args.output / 'results.json'}")


if __name__ == "__main__":
    main()
