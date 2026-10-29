"""Artifact-owned editable symbol nouns over private immutable projections."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from . import _symbol_parse
from ._symbol_types import (
    BodyDefinition as _BodyData,
)
from ._symbol_types import (
    PinDefinition as _PinData,
)
from ._symbol_types import (
    RectangleDefinition,
    SymbolAttribute,
    SymbolLibraryError,
    TextDefinition,
)
from ._symbol_types import (
    SymbolDefinition as _SymbolData,
)

if TYPE_CHECKING:
    from .symbols import SymbolLibrary


class StaleSymbolError(SymbolLibraryError, RuntimeError):
    """An owned editable object was deleted or its library was closed."""


class Symbol:
    """One live declared definition owned by its source library."""

    def __init__(self, library: SymbolLibrary, data: _SymbolData) -> None:
        self._library = library
        self._data = data
        self._alive = True
        self._bodies: tuple[SymbolBody, ...] = ()
        self._refresh(data)

    def _check(self) -> None:
        if not self._alive:
            raise StaleSymbolError("Symbol is deleted or its library is closed")

    def _refresh(self, data: _SymbolData) -> None:
        self._data = data
        old = {(b._data.unit, b._data.body_style): b for b in self._bodies}
        bodies: list[SymbolBody] = []
        for view in data.bodies:
            body = old.pop((view.unit, view.body_style), None)
            if body is None:
                body = SymbolBody(self, view)
            else:
                body._refresh(view)
            bodies.append(body)
        for body in old.values():
            body._alive = False
        self._bodies = tuple(bodies)

    @property
    def name(self) -> str:
        """Current declared name, including a successful rename."""
        self._check()
        return self._data.name

    @property
    def extends(self) -> str | None:
        """Declared parent name, never an implicit editing target."""
        self._check()
        return self._data.extends

    @property
    def attributes(self) -> tuple[SymbolAttribute, ...]:
        """Current immutable declared occurrences, including repeats."""
        self._check()
        return self._data.attributes

    @property
    def bodies(self) -> tuple[SymbolBody, ...]:
        """Live declared bodies in source order."""
        self._check()
        return self._bodies

    @property
    def units_locked(self) -> bool:
        """Whether this declaration locks its units."""
        self._check()
        return self._data.units_locked

    @property
    def resolved(self) -> bool:
        """False: this editable object always targets its own declaration."""
        self._check()
        return False

    def attribute(self, name: str) -> SymbolAttribute:
        """Inspect one declared attribute, rejecting ambiguous identity."""
        self._check()
        return self._data.attribute(name)

    def set_attribute(self, name: str, value: str) -> None:
        """Create, update, or exactly preserve one declared attribute in memory."""
        self._check()
        name = _symbol_parse._require_attribute_name(name)
        try:
            self.attribute(name)
        except KeyError:
            updated = _symbol_parse.insert_attribute(
                self._library._source, self.name, name, value
            )
        else:
            updated = _symbol_parse.replace_attribute(
                self._library._source, self.name, name, value
            )
        self._library._accept_source(updated)

    def add_attribute(self, name: str, value: str, *, private: bool = False) -> None:
        """Create one new declared occurrence, optionally private; reject duplicates."""
        self._check()
        self._library._accept_source(
            _symbol_parse.insert_attribute(
                self._library._source, self.name, name, value, private=private
            )
        )

    def delete_attribute(self, name: str) -> None:
        """Delete one declared attribute without changing an inherited parent."""
        self._check()
        self._library._accept_source(
            _symbol_parse.delete_attribute(self._library._source, self.name, name)
        )

    def body(self, unit: int, body_style: int) -> SymbolBody:
        """Select a declared body by unit and style; never select a parent body."""
        self._check()
        _symbol_parse._require_unit_style(unit, body_style)
        self._data.body(unit, body_style)
        return next(
            b for b in self._bodies if b.unit == unit and b.body_style == body_style
        )

    def ensure_body(self, unit: int, body_style: int) -> SymbolBody:
        """Create a missing declared body, or return the existing live body."""
        self._check()
        self._library._accept_source(
            _symbol_parse.ensure_body(
                self._library._source, self.name, unit, body_style
            )
        )
        return self.body(unit, body_style)


class SymbolBody:
    """One live declared unit/body-style body owned by a Symbol."""

    def __init__(self, symbol: Symbol, data: _BodyData) -> None:
        self._symbol = symbol
        self._data = data
        self._alive = True
        self._pins: tuple[SymbolPin, ...] = ()
        self._rectangles: tuple[SymbolRectangle, ...] = ()
        self._texts: tuple[SymbolText, ...] = ()
        self._refresh(data)

    def _check(self) -> None:
        self._symbol._check()
        if not self._alive:
            raise StaleSymbolError("Body has been deleted")

    def _refresh(self, data: _BodyData) -> None:
        self._data = data
        old = list(self._pins)
        pins: list[SymbolPin] = []
        for view in data.pins:
            pin = next((p for p in old if p._data.number == view.number), None)
            if pin is None:
                pin = SymbolPin(self, view)
            else:
                old.remove(pin)
                pin._data = view
            pins.append(pin)
        for pin in old:
            pin._alive = False
        self._pins = tuple(pins)
        self._rectangles = _refresh_graphics(
            self._rectangles, data.rectangles, lambda v: SymbolRectangle(self, v)
        )
        self._texts = _refresh_graphics(
            self._texts, data.texts, lambda v: SymbolText(self, v)
        )

    @property
    def name(self) -> str:
        """Current declared body name."""
        self._check()
        return self._data.name

    @property
    def unit(self) -> int:
        """Unit identity; zero denotes shared content."""
        self._check()
        return self._data.unit

    @property
    def body_style(self) -> int:
        """Body-style identity, distinct from unit identity."""
        self._check()
        return self._data.body_style

    @property
    def origin_symbol(self) -> str:
        """Current name of the declaring symbol."""
        self._check()
        return self._data.origin_symbol

    @property
    def pins(self) -> tuple[SymbolPin, ...]:
        """Live declared pin occurrences in source order."""
        self._check()
        return self._pins

    @property
    def rectangles(self) -> tuple[SymbolRectangle, ...]:
        """Live rectangle handles in source order."""
        self._check()
        return self._rectangles

    @property
    def texts(self) -> tuple[SymbolText, ...]:
        """Live body text handles in source order."""
        self._check()
        return self._texts

    def pin(self, number: str) -> SymbolPin:
        """Select one live pin, rejecting missing or repeated numbers."""
        self._check()
        self._data.pin(number)
        return next(p for p in self._pins if p.number == number)

    def add_pin(
        self,
        number: str,
        name: str,
        electrical_type: str,
        *,
        x: float,
        y: float,
        rotation: float = 0.0,
        length: float = 2.54,
        shape: str = "line",
        hidden: bool = False,
    ) -> SymbolPin:
        """Create one pin on this declared body without changing other styles."""
        self._check()
        library = self._symbol._library
        library._accept_source(
            _symbol_parse.insert_pin(
                library._source,
                self._symbol.name,
                self.unit,
                self.body_style,
                number,
                name,
                electrical_type,
                x=x,
                y=y,
                rotation=rotation,
                length=length,
                shape=shape,
                hidden=hidden,
            )
        )
        return self.pin(number)

    def add_rectangle(
        self, *, start: tuple[float, float], end: tuple[float, float]
    ) -> SymbolRectangle:
        """Insert a rectangle on this body and return its live handle."""
        self._check()
        library = self._symbol._library
        library._accept_source(
            _symbol_parse.insert_rectangle(
                library._source,
                self._symbol.name,
                self.unit,
                self.body_style,
                start_x=start[0],
                start_y=start[1],
                end_x=end[0],
                end_y=end[1],
            )
        )
        return self._rectangles[-1]

    def add_text(
        self, text: str, *, x: float, y: float, rotation: float = 0.0
    ) -> SymbolText:
        """Insert text on this declared body and return its live handle."""
        self._check()
        library = self._symbol._library
        library._accept_source(
            _symbol_parse.insert_body_text(
                library._source,
                self._symbol.name,
                self.unit,
                self.body_style,
                text,
                x=x,
                y=y,
                rotation=rotation,
            )
        )
        return self._texts[-1]


_Handle = TypeVar("_Handle", "SymbolRectangle", "SymbolText")
_View = TypeVar("_View", RectangleDefinition, TextDefinition)


def _refresh_graphics(
    old: tuple[_Handle, ...],
    views: tuple[_View, ...],
    factory: Callable[[_View], _Handle],
) -> tuple[_Handle, ...]:
    """Map handles by ordinal within one body.

    Package edits keep ordinals stable: inserts append and handle deletes remove
    their handle first. A count drop without that cannot be mapped safely, so all
    old handles become stale instead of guessing.
    """
    if len(views) < len(old):
        for handle in old:
            handle._alive = False
        old = ()
    for handle, view in zip(old, views, strict=False):
        handle._data = view  # type: ignore[assignment]
    return old + tuple(factory(view) for view in views[len(old) :])


class _BodyGraphic:
    """Shared lifecycle for ordinal graphic handles owned by a body."""

    _kind = ""

    def __init__(self, body: SymbolBody) -> None:
        self._body = body
        self._alive = True

    def _check(self) -> None:
        self._body._check()
        if not self._alive:
            raise StaleSymbolError(f"Body {self._kind} has been deleted")

    def _siblings(self) -> tuple[_BodyGraphic, ...]:
        raise NotImplementedError

    def _set_siblings(self, handles: tuple[_BodyGraphic, ...]) -> None:
        raise NotImplementedError

    def delete(self) -> None:
        """Remove this graphic and invalidate its handle, without writing."""
        self._check()
        body = self._body
        library = body._symbol._library
        updated = _symbol_parse.delete_graphic(
            library._source,
            body._symbol.name,
            body.unit,
            body.body_style,
            self._kind,
            self._siblings().index(self),
        )
        self._alive = False
        self._set_siblings(tuple(h for h in self._siblings() if h is not self))
        library._accept_source(updated)


class SymbolRectangle(_BodyGraphic):
    """One live rectangle on a declared body, identified by its ordinal there."""

    _kind = "rectangle"

    def __init__(self, body: SymbolBody, data: RectangleDefinition) -> None:
        super().__init__(body)
        self._data = data

    def _siblings(self) -> tuple[_BodyGraphic, ...]:
        return self._body._rectangles

    def _set_siblings(self, handles: tuple[_BodyGraphic, ...]) -> None:
        self._body._rectangles = tuple(
            h for h in handles if isinstance(h, SymbolRectangle)
        )

    def set(
        self,
        *,
        start: tuple[float, float] | None = None,
        end: tuple[float, float] | None = None,
    ) -> None:
        """Set start and/or end in memory; equal values preserve exact bytes.

        Only the changed coordinate atoms are replaced. Stroke, fill, and other
        source remain unchanged. At least one argument is required.
        """
        self._check()
        body = self._body
        library = body._symbol._library
        library._accept_source(
            _symbol_parse.replace_rectangle(
                library._source,
                body._symbol.name,
                body.unit,
                body.body_style,
                body._rectangles.index(self),
                start=start,
                end=end,
            )
        )

    @property
    def start_x(self) -> float:
        """Current start x."""
        self._check()
        return self._data.start_x

    @property
    def start_y(self) -> float:
        """Current start y."""
        self._check()
        return self._data.start_y

    @property
    def end_x(self) -> float:
        """Current end x."""
        self._check()
        return self._data.end_x

    @property
    def end_y(self) -> float:
        """Current end y."""
        self._check()
        return self._data.end_y


class SymbolText(_BodyGraphic):
    """One live body text on a declared body, identified by its ordinal there."""

    _kind = "text"

    def __init__(self, body: SymbolBody, data: TextDefinition) -> None:
        super().__init__(body)
        self._data = data

    def _siblings(self) -> tuple[_BodyGraphic, ...]:
        return self._body._texts

    def _set_siblings(self, handles: tuple[_BodyGraphic, ...]) -> None:
        self._body._texts = tuple(h for h in handles if isinstance(h, SymbolText))

    def set(
        self,
        *,
        text: str | None = None,
        x: float | None = None,
        y: float | None = None,
        rotation: float | None = None,
    ) -> None:
        """Set text value, position, and/or rotation in memory.

        Equal values preserve exact bytes. Only changed atoms are replaced;
        effects and other source remain unchanged. At least one argument is
        required.
        """
        self._check()
        body = self._body
        library = body._symbol._library
        library._accept_source(
            _symbol_parse.replace_body_text(
                library._source,
                body._symbol.name,
                body.unit,
                body.body_style,
                body._texts.index(self),
                text=text,
                x=x,
                y=y,
                rotation=rotation,
            )
        )

    @property
    def text(self) -> str:
        """Current text value."""
        self._check()
        return self._data.text

    @property
    def x(self) -> float:
        """Current x."""
        self._check()
        return self._data.x

    @property
    def y(self) -> float:
        """Current y."""
        self._check()
        return self._data.y

    @property
    def rotation(self) -> float:
        """Current rotation, as the raw number in the file's ``at`` node.

        The package does not convert units. KiCad symbol files can store body
        text angles in tenths of a degree (for example ``900`` for 90 degrees).
        ``set(rotation=...)`` writes the given number unchanged.
        """
        self._check()
        return self._data.rotation


class SymbolPin:
    """One live pin occurrence owned by its declared body."""

    def __init__(self, body: SymbolBody, data: _PinData) -> None:
        self._body = body
        self._data = data
        self._alive = True

    def _check(self) -> None:
        self._body._check()
        if not self._alive:
            raise StaleSymbolError("Pin has been deleted")

    def set(
        self,
        *,
        name: str | None = None,
        electrical_type: str | None = None,
        x: float | None = None,
        y: float | None = None,
        rotation: float | None = None,
        length: float | None = None,
        shape: str | None = None,
        hidden: bool | None = None,
    ) -> None:
        """Set selected pin fields in memory; equal values preserve exact bytes."""
        self._check()
        symbol = self._body._symbol
        library = symbol._library
        library._accept_source(
            _symbol_parse.replace_pin(
                library._source,
                symbol.name,
                self._body.unit,
                self._body.body_style,
                self.number,
                name=name,
                electrical_type=electrical_type,
                x=x,
                y=y,
                rotation=rotation,
                length=length,
                shape=shape,
                hidden=hidden,
            )
        )

    def delete(self) -> None:
        """Remove this pin and invalidate its handle, without writing the library."""
        self._check()
        symbol = self._body._symbol
        library = symbol._library
        updated = _symbol_parse.delete_pin(
            library._source,
            symbol.name,
            self._body.unit,
            self._body.body_style,
            self.number,
        )
        self._alive = False
        self._body._pins = tuple(p for p in self._body._pins if p is not self)
        library._accept_source(updated)

    @property
    def number(self) -> str:
        """Current declared pin number."""
        self._check()
        return self._data.number

    @property
    def name(self) -> str:
        """Current declared pin name."""
        self._check()
        return self._data.name

    @property
    def electrical_type(self) -> str:
        """Current declared pin electrical type."""
        self._check()
        return self._data.electrical_type

    @property
    def x(self) -> float:
        """Current declared pin x."""
        self._check()
        return self._data.x

    @property
    def y(self) -> float:
        """Current declared pin y."""
        self._check()
        return self._data.y

    @property
    def rotation(self) -> float:
        """Current declared pin rotation."""
        self._check()
        return self._data.rotation

    @property
    def length(self) -> float:
        """Current declared pin length."""
        self._check()
        return self._data.length

    @property
    def shape(self) -> str:
        """Current declared pin shape."""
        self._check()
        return self._data.shape

    @property
    def hidden(self) -> bool:
        """Current declared pin hidden."""
        self._check()
        return self._data.hidden
