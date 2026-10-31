"""One private seam that stages project hierarchy content for KiCad backends.

Save verification, ``Project.erc``, and project report/export operations all
stage the captured ``.kicad_pro`` bytes and the strict internal schematic
hierarchy at their project-relative paths in a temporary directory. No source
is saved, no pending state is reset, and no write guard is required.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from ._schematic_persist import _hierarchy
from ._snapshot_types import ProjectSnapshot, SnapshotDocument
from .schematics import SheetFile, UnsupportedSchematicOperationError

if TYPE_CHECKING:
    from .projects import Project


@dataclass(frozen=True)
class PendingHierarchy:
    """Captured pending hierarchy content and its provenance."""

    root: Path
    documents: tuple[SheetFile, ...]
    content: Mapping[Path, bytes]
    snapshot: ProjectSnapshot


def capture_pending(project: Project, *, operation: str) -> PendingHierarchy:
    """Capture every hierarchy document's pending ``to_bytes()`` content.

    The root schematic and project must share a basename, as KiCad resolves the
    staged ``.kicad_pro`` by that name.
    """
    root = project.schematic_file
    if root is None or root.stem != project.project_file.stem:
        raise UnsupportedSchematicOperationError(
            f"{operation} requires matching project and root schematic basenames"
        )
    documents = _hierarchy(project)  # strict source paths; no save preflight
    content = {document.path: document.to_bytes() for document in documents}
    snapshot = ProjectSnapshot(
        project.project_file,
        hashlib.sha256(project._project_baseline).hexdigest(),
        tuple(
            SnapshotDocument(
                document.path,
                hashlib.sha256(content[document.path]).hexdigest(),
                document.is_modified,
            )
            for document in documents
        ),
    )
    return PendingHierarchy(root, documents, content, snapshot)


@contextmanager
def staged_hierarchy(
    project: Project,
    content: Mapping[Path, bytes],
    *,
    prefix: str,
    extra: Mapping[str, bytes] | None = None,
) -> Iterator[Path]:
    """Yield a temporary stage holding project JSON, *extra* files, and *content*.

    *content* maps original document paths to the bytes to stage at the same
    project-relative path. The stage is removed on exit.
    """
    with TemporaryDirectory(prefix=prefix) as temporary:
        stage = Path(temporary)
        (stage / project.project_file.name).write_bytes(project._project_baseline)
        for name, raw in (extra or {}).items():
            (stage / name).write_bytes(raw)
        for path, raw in content.items():
            target = stage / path.relative_to(project.directory)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        yield stage
