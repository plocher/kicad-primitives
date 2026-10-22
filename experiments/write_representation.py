"""THROWAWAY #4 proof, not a public interface or a parser selection.

Run (downloads pinned sources and donor tests into a fresh scratch directory):
    uv run --no-project --python 3.11 --with pytest==8.4.2 \
        python experiments/write_representation.py --workdir /tmp/NEW-proof \
        --kicad /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli

No original designs are written. Results and copied designs stay in workdir.
Candidate failures are observations, not failures of the measurement runner.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Any, Callable, Iterator
from urllib.request import urlopen
from uuid import NAMESPACE_URL, UUID, uuid5


ROOT = Path(__file__).resolve().parents[1]
RAILROAD = Path.home() / "Dropbox/KiCad/Railroad"
SPECS = (
    (
        "circuitdk",
        "td2sk/circuitdk",
        "aca240a0404f6bb2162bb60257f7b1f0c756db06",
        "packages/lossless-sexpr/",
        (
            "LICENSE",
            "pyproject.toml",
            "tests/test_parser.py",
            *(
                f"src/lossless_sexpr/{name}.py"
                for name in (
                    "__init__",
                    "diagnostics",
                    "edits",
                    "nodes",
                    "parser",
                    "strings",
                    "tokens",
                )
            ),
        ),
    ),
    (
        "parts2kicad",
        "julianschick/parts2kicad",
        "7b00d7ce223379f03183cf40482667e608258dd1",
        "",
        ("LICENSE", "pyproject.toml", "src/parts2kicad/sexp.py", "tests/test_sexp.py"),
    ),
    (
        "sexpdata",
        "jd-boyd/sexpdata",
        "29170a5daed7c07a8d035856356416141210d963",
        "",
        ("LICENSE", "sexpdata.py", "test_sexpdata.py"),
    ),
)
DESCRIPTION = re.compile(r'\(property\s+"Description"\s+("(?:\\.|[^"\\])*")')


@dataclass
class Observation:
    """One measurement; None means the operation was not exercised."""

    candidate: str
    case: str
    passed: bool | None
    detail: str = ""


@dataclass
class Candidate:
    """Experimental access to each native representation, not a migration shim."""

    name: str
    module: ModuleType

    def parse(self, source: str) -> Any:
        """Parse with this candidate alone."""
        if self.name == "circuitdk":
            return self.module.parse(source)
        if self.name == "parts2kicad":
            return self.module.read_from_string(source)
        return self.module.loads(source)

    def emit(self, document: Any) -> str:
        """Use the candidate's own no-change output path."""
        if self.name == "circuitdk":
            return document.render()
        if self.name == "parts2kicad":
            return document.write_string()
        return self.module.dumps(document)

    def children(self, node: Any) -> list[Any]:
        """Read children without using another candidate's parser."""
        if self.name == "circuitdk":
            if isinstance(node, self.module.Document):
                return list(node.roots())
            return (
                list(node.children()) if isinstance(node, self.module.ListNode) else []
            )
        if self.name == "parts2kicad":
            return (
                node.subnodes_without_whitespace
                if isinstance(node, self.module.List)
                else []
            )
        return node if isinstance(node, list) else []

    def is_list(self, node: Any) -> bool:
        """Identify structural nodes."""
        if self.name == "circuitdk":
            return isinstance(node, self.module.ListNode)
        if self.name == "parts2kicad":
            return isinstance(node, self.module.List)
        return isinstance(node, list)

    def atom(self, node: Any) -> str:
        """Read an atom; raw-content differences remain visible in observations."""
        if self.name == "circuitdk":
            return node.value
        if self.name == "parts2kicad":
            return node.content
        return str(node)

    def walk(self, node: Any) -> Iterator[Any]:
        """Walk the native representation in source order."""
        children = self.children(node)
        if self.is_list(node) and children and not self.is_list(children[0]):
            yield node
        for child in children:
            if self.is_list(child):
                yield from self.walk(child)

    def head(self, node: Any) -> str:
        """Return the structural head."""
        return self.atom(self.children(node)[0])

    def set_description(self, source: str, value: str) -> str:
        """Measure one targeted edit through the candidate representation."""
        document = self.parse(source)
        for node in self.walk(document):
            children = self.children(node)
            if (
                self.head(node) == "property"
                and self.atom(children[1]) == "Description"
            ):
                if self.name == "circuitdk":
                    return self.module.apply_edits(
                        source, [self.module.TextEdit(children[2].span, quote(value))]
                    )
                if self.name == "parts2kicad":
                    children[2].content = quote(value)[1:-1]
                else:
                    children[2] = value
                return self.emit(document)
        raise ValueError("no Description property")


def digest(data: bytes) -> str:
    """Hash exact bytes for the experiment's provenance records."""
    return hashlib.sha256(data).hexdigest()


def quote(value: str) -> str:
    """Quote the limited string values used by these measurement cases."""
    return json.dumps(value, ensure_ascii=False)


def prepare(work: Path) -> None:
    """Fetch pinned source and tests, retaining upstream licenses, and snapshot designs."""
    if work.is_relative_to(ROOT) or work.is_relative_to(RAILROAD):
        raise ValueError(
            "workdir must not be the repository or a donor design directory"
        )
    work.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, repo, ref, base, paths in SPECS:
        for rel in paths:
            path = work / "candidates" / name / rel
            if not path.exists():
                url = f"https://raw.githubusercontent.com/{repo}/{ref}/{base}{rel}"
                with urlopen(url, timeout=30) as response:
                    data = response.read()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            manifest.append(
                {
                    "candidate": name,
                    "repo": repo,
                    "revision": ref,
                    "path": base + rel,
                    "sha256": digest(path.read_bytes()),
                }
            )
    (work / "candidate-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if not (work / "sources.json").exists():
        sources = []
        paths = list((RAILROAD / "SPCoast").glob("*.kicad_sch"))
        paths += list((RAILROAD / "SPCoast").glob("*.kicad_pro"))
        paths += list((RAILROAD / "symbols").glob("*.kicad_sym"))
        paths += [
            path
            for name in ("sym-lib-table", "fp-lib-table")
            if (path := RAILROAD / "SPCoast" / name).exists()
        ]
        for source in sorted(paths):
            data = source.read_bytes()
            rel = source.relative_to(RAILROAD)
            target = work / "snapshot" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            sources.append(
                {
                    "source": str(source),
                    "snapshot": str(rel),
                    "sha256": digest(data),
                    "bytes": len(data),
                }
            )
        (work / "sources.json").write_text(json.dumps(sources, indent=2) + "\n")


def load_candidates(work: Path) -> list[Candidate]:
    """Import only the pinned source modules, not candidate packaging hooks."""
    paths = [
        work / "candidates/circuitdk/src",
        work / "candidates/parts2kicad/src",
        work / "candidates/sexpdata",
    ]
    sys.path[:0] = [str(path) for path in paths]
    return [
        Candidate(name, importlib.import_module(module))
        for name, module in (
            ("circuitdk", "lossless_sexpr"),
            ("parts2kicad", "parts2kicad.sexp"),
            ("sexpdata", "sexpdata"),
        )
    ]


def measure(
    observations: list[Observation],
    candidate: str,
    case: str,
    check: Callable[[], tuple[bool, str]],
) -> None:
    """Record failures without hiding which candidate operation failed."""
    try:
        passed, detail = check()
        observations.append(Observation(candidate, case, passed, detail))
    except Exception as exc:
        observations.append(
            Observation(candidate, case, False, f"{type(exc).__name__}: {exc}")
        )


def no_change(candidate: Candidate, data: bytes) -> tuple[bool, str]:
    """Check byte equality and actual structural interpretation."""
    source = data.decode("utf-8")
    document = candidate.parse(source)
    heads = [candidate.head(node) for node in candidate.walk(document)]
    output = candidate.emit(document).encode("utf-8")
    count = len(heads)
    return output == data and count > 0, (
        f"{count} lists; {len(data)} -> {len(output)} bytes; "
        f"sha256_equal={digest(data) == digest(output)}"
    )


def targeted(candidate: Candidate, data: bytes) -> tuple[bool, str]:
    """Compare two successive edits against a textual test oracle, not a second parser."""
    source = data.decode("utf-8")
    for value in ("representation proof first", "representation proof second"):
        match = DESCRIPTION.search(source)
        if match is None:
            raise ValueError("test article has no Description")
        expected = source[: match.start(1)] + quote(value) + source[match.end(1) :]
        actual = candidate.set_description(source, value)
        document = candidate.parse(actual)
        properties = [
            candidate.children(node)
            for node in candidate.walk(document)
            if candidate.head(node) == "property"
        ]
        found = next(
            candidate.atom(children[2])
            for children in properties
            if candidate.atom(children[1]) == "Description"
        )
        if actual.encode("utf-8") != expected.encode("utf-8") or found != value:
            return (
                False,
                "changed bytes outside selected value, or wrong interpreted value",
            )
        source = actual
    return True, "two reparsed edits; only selected value changed"


def rejected(candidate: Candidate, source: str) -> tuple[bool, str]:
    """Require malformed input to fail, distinguishing incidental from deliberate errors."""
    try:
        candidate.parse(source)
    except Exception as exc:
        return True, type(exc).__name__ + ": " + str(exc)
    return False, "accepted malformed input"


def run_measurements(
    work: Path,
    candidates: list[Candidate],
    observations: list[Observation],
) -> None:
    """Measure real files and small adversarial lexical cases."""
    selected = sorted((work / "snapshot/symbols").glob("*.kicad_sym"))
    selected += [
        work / "snapshot/SPCoast/SPCoast.kicad_sch",
        work / "snapshot/SPCoast/GilroyCalTrain.kicad_sch",
    ]
    edge_cases = {
        "escaped_quote": '(root (property "Description" "a\\"b"))\n',
        "backslashes": '(root (property "Description" "C:\\\\tmp\\\\part"))\n',
        "unicode": '(root (property "Description" "µ Ω 電車"))\n',
        "crlf": '(root\r\n\t(property "Description" "value")\r\n)\r\n',
        "numbers": '(root (property "Description" "value") (n +001.00 -0.000 1e-03))\n',
        "opaque": '(root (property "Description" "value") (future_node (nested "x(y)" 00.10)))\n',
        "escaped_neighbor": '(root (property "Description" "value") (opaque "a\\"b"))\n',
    }
    for candidate in candidates:
        for path in selected:
            label = str(path.relative_to(work / "snapshot"))
            data = path.read_bytes()
            measure(
                observations,
                candidate.name,
                f"real.noop:{label}",
                lambda c=candidate, d=data: no_change(c, d),
            )
            if DESCRIPTION.search(data.decode("utf-8")):
                measure(
                    observations,
                    candidate.name,
                    f"real.edit:{label}",
                    lambda c=candidate, d=data: targeted(c, d),
                )
            else:
                observations.append(
                    Observation(
                        candidate.name,
                        f"real.edit:{label}",
                        None,
                        "test article has no Description property",
                    )
                )
        for label, source in edge_cases.items():
            measure(
                observations,
                candidate.name,
                f"edge.noop:{label}",
                lambda c=candidate, s=source: no_change(c, s.encode("utf-8")),
            )
            measure(
                observations,
                candidate.name,
                f"edge.edit:{label}",
                lambda c=candidate, s=source: targeted(c, s.encode("utf-8")),
            )
        for label, source in {
            "unclosed_list": "(root",
            "extra_close": "(root))",
            "bare_close": ")",
            "unclosed_string": '(root "unterminated)',
        }.items():
            measure(
                observations,
                candidate.name,
                f"malformed:{label}",
                lambda c=candidate, s=source: rejected(c, s),
            )
        if candidate.name == "circuitdk":

            def overlap(c: Candidate = candidate) -> tuple[bool, str]:
                try:
                    c.module.apply_edits(
                        "abcdef",
                        [
                            c.module.TextEdit.replace(1, 4, "x"),
                            c.module.TextEdit.replace(3, 5, "y"),
                        ],
                    )
                except c.module.EditConflictError:
                    return True, "overlap rejected"
                return False, "overlap accepted"

            measure(observations, candidate.name, "overlapping_edits", overlap)
        else:
            observations.append(
                Observation(
                    candidate.name, "overlapping_edits", None, "no span-edit API"
                )
            )


def ordered_insertion(
    candidate: Candidate, source: str, position: str
) -> tuple[str, str]:
    """Clone a real single-unit Bumper at a fixed UUID, with new instance/pin identities."""
    module = candidate.module
    root = candidate.parse(source).roots()[0]
    symbols = list(root.child_lists("symbol"))
    keys = [UUID(node.first_list("uuid").atom(1).value).int for node in symbols]
    assert keys == sorted(keys), "insertion test requires a KiCad-ordered baseline"
    template = next(
        node
        for node in symbols
        if node.first_list("lib_id").atom(1).value == "Railroad-Trackplan:Bumper"
    )
    selected = {
        "beginning": 1,
        "middle": (keys[len(keys) // 2 - 1] + keys[len(keys) // 2]) // 2,
        "end": (1 << 128) - 1,
    }[position]
    assert selected not in keys
    new_uuid = str(UUID(int=selected))
    # Reverse reference order relative to UUID order, to catch the wrong sorting key.
    new_ref = {"beginning": "B999003", "middle": "B999002", "end": "B999001"}[position]
    assert quote(new_ref) not in source
    block = source[template.span.start : template.span.end]
    cloned = module.parse(block)
    edits = []
    for index, node in enumerate(cloned.lists("uuid")):
        value = (
            new_uuid
            if index == 0
            else str(uuid5(NAMESPACE_URL, f"proof:{position}:{index}"))
        )
        edits.append(module.TextEdit(node.atom(1).span, quote(value)))
    for node in cloned.lists("property"):
        if node.atom(1).value == "Reference":
            edits.append(module.TextEdit(node.atom(2).span, quote(new_ref)))
    for node in cloned.lists("reference"):
        edits.append(module.TextEdit(node.atom(1).span, quote(new_ref)))
    block = module.apply_edits(block, edits)
    successor = next((node for node, key in zip(symbols, keys) if key > selected), None)
    if successor:
        offset, addition = successor.span.start, block + "\n\t"
    else:
        offset, addition = symbols[-1].span.end, "\n\t" + block
    output = module.apply_edits(
        source, [module.TextEdit.replace(offset, offset, addition)]
    )
    assert output[:offset] + output[offset + len(addition) :] == source
    after = module.parse(output).roots()[0].child_lists("symbol")
    after_keys = [UUID(node.first_list("uuid").atom(1).value).int for node in after]
    assert after_keys == sorted(keys + [selected])
    before_blocks = {
        node.first_list("uuid").atom(1).value: source[node.span.start : node.span.end]
        for node in symbols
    }
    after_blocks = {
        node.first_list("uuid").atom(1).value: output[node.span.start : node.span.end]
        for node in after
    }
    assert all(after_blocks[key] == value for key, value in before_blocks.items())
    # Negative control: append the same middle-UUID block at the end.
    wrong = module.apply_edits(
        source,
        [
            module.TextEdit.replace(
                symbols[-1].span.end, symbols[-1].span.end, "\n\t" + block
            )
        ],
    )
    return output, wrong


def run_kicad(
    work: Path,
    cli: Path,
    candidate: Candidate,
    observations: list[Observation],
) -> list[dict[str, Any]]:
    """Separate byte preservation, CLI acceptance, normalization, and fixed-point results."""
    if candidate.name != "circuitdk":
        raise ValueError("this prototype's insertion path uses CircuitDK source spans")
    run = Path(tempfile.mkdtemp(prefix="kicad-", dir=work))
    logs: list[dict[str, Any]] = []

    def resave(path: Path) -> bool:
        kind = "sym" if path.suffix == ".kicad_sym" else "sch"
        command = [str(cli), kind, "upgrade", "--force", str(path)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        logs.append(
            {
                "command": command,
                "exit": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        return result.returncode == 0

    def case(
        label: str,
        relative: Path,
        content: bytes,
        expect_reorder: bool = False,
    ) -> tuple[bytes, bool]:
        directory = run / label
        shutil.copytree(work / "snapshot", directory)
        path = directory / relative
        path.write_bytes(content)
        print("KiCad:", label, flush=True)
        accepted = resave(path)
        first = path.read_bytes()
        observations.append(Observation(candidate.name, f"ki.accept:{label}", accepted))
        observations.append(
            Observation(
                candidate.name,
                f"ki.normalized:{label}",
                first != content if expect_reorder else first == content,
                f"{len(content)} -> {len(first)} bytes; sha256_equal={first == content}; "
                f"expected_reorder={expect_reorder}",
            )
        )
        stable = resave(path) and path.read_bytes() == first if accepted else False
        observations.append(
            Observation(candidate.name, f"ki.fixed_point:{label}", stable)
        )
        return first, accepted

    selected = sorted((work / "snapshot/symbols").glob("*.kicad_sym"))
    selected += [
        work / "snapshot/SPCoast/SPCoast.kicad_sch",
        work / "snapshot/SPCoast/GilroyCalTrain.kicad_sch",
    ]
    for path in selected:
        relative = path.relative_to(work / "snapshot")
        data = path.read_bytes()
        baseline, accepted = case(f"baseline-{path.stem}", relative, data)
        if accepted and DESCRIPTION.search(data.decode("utf-8")):
            edited = candidate.set_description(
                data.decode("utf-8"), "representation proof"
            )
            case(f"edit-{path.stem}", relative, edited.encode("utf-8"))
        if baseline != data:
            observations.append(
                Observation(
                    candidate.name,
                    f"ki.baseline_caveat:{path.name}",
                    None,
                    "donor is not byte-stable under this KiCad resave; do not blame candidate",
                )
            )
    relative = Path("SPCoast/GilroyCalTrain.kicad_sch")
    source = (work / "snapshot" / relative).read_bytes().decode("utf-8")
    for position in ("beginning", "middle", "end"):
        ordered, wrong = ordered_insertion(candidate, source, position)
        observations.append(
            Observation(
                candidate.name,
                f"insert.preservation:{position}",
                True,
                "fixed UUID; original blocks byte-identical; old relative order unchanged",
            )
        )
        normalized, accepted = case(
            f"insert-{position}", relative, ordered.encode("utf-8")
        )
        if position == "middle":
            wrong_normalized, wrong_accepted = case(
                "negative-append-middle-uuid",
                relative,
                wrong.encode("utf-8"),
                expect_reorder=True,
            )
            observations.append(
                Observation(
                    candidate.name,
                    "insert.negative_control",
                    accepted
                    and wrong_accepted
                    and wrong != ordered
                    and wrong_normalized == normalized,
                    "incorrect append normalizes to the same output as ordered insertion",
                )
            )
    (work / "kicad-log.json").write_text(json.dumps(logs, indent=2) + "\n")
    return logs


def run_donor_tests(work: Path) -> subprocess.CompletedProcess[str]:
    """Run unchanged upstream tests with no cache files or candidate installation."""
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    environment["PYTHONPATH"] = os.pathsep.join(sys.path[:3])
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            str(work / "candidates/circuitdk/tests"),
            str(work / "candidates/parts2kicad/tests"),
            str(work / "candidates/sexpdata/test_sexpdata.py"),
        ],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
    )
    (work / "donor-tests.txt").write_text(result.stdout + result.stderr)
    return result


def verify_sources(work: Path) -> bool:
    """Check both source originals and their frozen snapshots for changes."""
    for record in json.loads((work / "sources.json").read_text()):
        for path in (Path(record["source"]), work / "snapshot" / record["snapshot"]):
            if digest(path.read_bytes()) != record["sha256"]:
                return False
    return True


def main() -> int:
    """Run the bounded measurement and write machine-readable scratch evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--kicad", type=Path)
    args = parser.parse_args()
    work = args.workdir.resolve()
    prepare(work)
    candidates = load_candidates(work)
    donor = run_donor_tests(work)
    print("Donor tests:", donor.stdout.strip())
    observations: list[Observation] = []
    run_measurements(work, candidates, observations)
    cli_version = None
    if args.kicad:
        cli_version = subprocess.run(
            [str(args.kicad), "version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        run_kicad(work, args.kicad, candidates[0], observations)
        for candidate in candidates[1:]:
            observations.append(
                Observation(
                    candidate.name,
                    "insert.ki_comparison",
                    None,
                    "not pursued: native no-op already violates real-file preservation",
                )
            )
    intact = verify_sources(work)
    report = {
        "python": sys.version,
        "harness_sha256": digest(Path(__file__).read_bytes()),
        "source_manifest": "sources.json",
        "candidate_manifest": "candidate-manifest.json",
        "donor_tests_exit": donor.returncode,
        "sources_unchanged": intact,
        "kicad_version": cli_version,
        "observations": [asdict(item) for item in observations],
    }
    suffix = "-kicad" if args.kicad else ""
    output = (
        work
        / f"results-python{sys.version_info.major}{sys.version_info.minor}{suffix}.json"
    )
    output.write_text(json.dumps(report, indent=2) + "\n")
    for candidate in candidates:
        items = [item for item in observations if item.candidate == candidate.name]
        print(
            candidate.name,
            dict(
                Counter(
                    "pass"
                    if item.passed
                    else "unsupported"
                    if item.passed is None
                    else "fail"
                    for item in items
                )
            ),
        )
        for item in items:
            if item.passed is False:
                print(" ", item.case, item.detail)
    print("Originals and snapshots unchanged:", intact)
    print("Evidence:", output)
    return 0 if intact and donor.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
