"""Opt-in public-service gates on explicit libraries; originals are never written.

Run with --help. Normal unittest discovery does not depend on local installations.
The output directory must not exist; all KiCad resaves use copies beneath it.
"""

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path

from kicad_primitives.symbols import SymbolLibrary


@dataclass(frozen=True)
class CaseResult:
    """Measured source-preservation and normalization facts for one edit."""

    symbol: str
    property_name: str
    exact_delta: bool
    first_save_unchanged: bool | None
    second_save_stable: bool | None
    normalized_delta_only: bool | None


@dataclass(frozen=True)
class LibraryResult:
    """Measured facts and input identity, not a general compatibility claim."""

    input_path: str
    sha256: str
    version: int
    symbols: int
    resolved: int
    no_op_bytes: bool
    baseline_first_save_unchanged: bool | None
    baseline_second_save_stable: bool | None
    cases: tuple[CaseResult, ...]


def _quote(value: str) -> bytes:
    # Independent oracle for the exercised ordinary KiCad/JSON shared escapes.
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _only_delta(before: bytes, after: bytes, old: str, new: str) -> bool:
    old_token, new_token = _quote(old), _quote(new)
    start = before.find(old_token)
    while start != -1:
        end = start + len(old_token)
        if after == before[:start] + new_token + before[end:]:
            return True
        start = before.find(old_token, start + 1)
    return False


def _upgrade(cli: Path, path: Path) -> tuple[bool, bool]:
    original = path.read_bytes()
    subprocess.run(
        [str(cli), "sym", "upgrade", "--force", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    first = path.read_bytes()
    subprocess.run(
        [str(cli), "sym", "upgrade", "--force", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return first == original, path.read_bytes() == first


def _verify(path: Path, output: Path, cli: Path | None) -> LibraryResult:
    original = path.read_bytes()
    digest = sha256(original).hexdigest()
    output.mkdir()
    baseline = output / path.name
    baseline.write_bytes(original)
    library = SymbolLibrary.open(baseline)
    assert library.to_bytes() == original, "No-op byte mismatch"
    library.save()
    for symbol in library.symbols:
        library.resolve(symbol.name)
    targets = [
        (s.name, p.name)
        for s in library.symbols
        for p in s.properties
        if p.name == "Description"
    ][:1]
    # Exercise the real modifier grammar in addition to an ordinary property.
    private_target = next(
        (
            (s.name, p.name)
            for s in library.symbols
            for p in s.properties
            if p.is_private
        ),
        None,
    )
    if private_target is not None:
        targets.append(private_target)
    assert targets, f"No existing property target in {path}"
    baseline_first: bool | None = None
    baseline_stable: bool | None = None
    if cli is not None:
        baseline_first, baseline_stable = _upgrade(cli, baseline)
        assert baseline_stable, "Baseline second resave is unstable"
    cases: list[CaseResult] = []
    for i, (name, key) in enumerate(targets):
        edited_path = output / f"edit-{i}.kicad_sym"
        edited_path.write_bytes(original)
        edited = SymbolLibrary.open(edited_path)
        old = edited.symbol(name).property(key).value
        edited.set_property(name, key, old + " [first edit]")
        value = (old + " " if old else "") + '[slice proof: "quoted" café \\ path]'
        edited.set_property(name, key, value)
        changed = edited.to_bytes()
        assert _only_delta(original, changed, old, value), "Unexpected source delta"
        expected_symbols = tuple(
            replace(
                s,
                properties=tuple(
                    replace(p, value=value) if s.name == name and p.name == key else p
                    for p in s.properties
                ),
            )
            for s in library.symbols
        )
        assert edited.symbols == expected_symbols, "Unexpected declared semantic delta"
        assert edited_path.read_bytes() == original, "Editing implicitly wrote to disk"
        edited.save()
        assert edited_path.read_bytes() == changed, "Save changed preview bytes"
        first: bool | None = None
        stable: bool | None = None
        delta_only: bool | None = None
        if cli is not None:
            first, stable = _upgrade(cli, edited_path)
            assert stable, "Edited second resave is unstable"
            normalized_original = SymbolLibrary.open(baseline)
            normalized_edit = SymbolLibrary.open(edited_path)
            assert normalized_edit.symbol(name).property(key).value == value
            normalized_old = normalized_original.symbol(name).property(key).value
            delta_only = _only_delta(
                baseline.read_bytes(), edited_path.read_bytes(), normalized_old, value
            )
            assert delta_only, (
                "Normalization introduced changes beyond the required edit"
            )
        cases.append(CaseResult(name, key, True, first, stable, delta_only))
    assert sha256(path.read_bytes()).hexdigest() == digest, (
        "Original changed during verification"
    )
    return LibraryResult(
        str(path),
        digest,
        library.version,
        len(library.symbols),
        len(library.symbols),
        True,
        baseline_first,
        baseline_stable,
        tuple(cases),
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
            f"{path.name}: {record.symbols} symbols, {len(record.cases)} edits passed",
            flush=True,
        )
    print(f"Results: {args.output / 'results.json'}")


if __name__ == "__main__":
    main()
