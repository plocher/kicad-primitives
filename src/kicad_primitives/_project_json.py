"""Localized known JSON member edits; values and boundaries use stdlib decoding."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .projects import InvalidProjectError

_DECODER = json.JSONDecoder()


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    value: object


@dataclass(frozen=True)
class _Member:
    name: str
    key_start: int
    value: _Span


def _white(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _decode(text: str, index: int) -> _Span:
    start = _white(text, index)
    try:
        value, end = _DECODER.raw_decode(text, start)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise InvalidProjectError("Invalid JSON metadata structure") from exc
    return _Span(start, end, value)


def _members(text: str, node: _Span) -> tuple[_Member, ...]:
    if not isinstance(node.value, dict) or text[node.start] != "{":
        raise InvalidProjectError("Known metadata parent must be a JSON object")
    result: list[_Member] = []
    cursor = _white(text, node.start + 1)
    while cursor < node.end and text[cursor] != "}":
        key = _decode(text, cursor)
        if not isinstance(key.value, str):
            raise InvalidProjectError("Expected a JSON member name")
        cursor = _white(text, key.end)
        if text[cursor] != ":":
            raise InvalidProjectError("Expected a JSON member separator")
        value = _decode(text, cursor + 1)
        result.append(_Member(key.value, key.start, value))
        cursor = _white(text, value.end)
        if text[cursor] == "}":
            break
        if text[cursor] != ",":
            raise InvalidProjectError("Expected a JSON member delimiter")
        cursor = _white(text, cursor + 1)
    return tuple(result)


def _element(text: str, node: _Span, index: int) -> _Span:
    if not isinstance(node.value, list) or index < 0:
        raise InvalidProjectError("Known metadata parent must be a JSON array")
    cursor = _white(text, node.start + 1)
    for position in range(len(node.value)):
        child = _decode(text, cursor)
        if position == index:
            return child
        cursor = _white(text, child.end)
        if text[cursor] == ",":
            cursor = _white(text, cursor + 1)
    raise InvalidProjectError("Known JSON metadata array index is missing")


def _child(text: str, node: _Span, component: str | int) -> _Span | None:
    if isinstance(component, int):
        return _element(text, node, component)
    matches = tuple(
        member for member in _members(text, node) if member.name == component
    )
    if len(matches) > 1:
        raise InvalidProjectError(f"Ambiguous known JSON metadata member: {component}")
    return matches[0].value if matches else None


def get(raw: bytes, path: tuple[str | int, ...], *, default: object = None) -> object:
    """Read a relevant path while rejecting ambiguous members instead of choosing one."""
    text = raw.decode("utf-8")
    node = _decode(text, 1 if text.startswith("\ufeff") else 0)
    for component in path:
        child = _child(text, node, component)
        if child is None:
            return default
        node = child
    return node.value


def _insert(text: str, parent: _Span, name: str, value: object) -> str:
    members = _members(text, parent)
    anchor = members[-1].value.end if members else parent.start + 1
    multiline = "\n" in text[parent.start : parent.end]
    separator = "," if members else ""
    if multiline:
        sample = members[0].key_start if members else parent.start
        line = text.rfind("\n", 0, sample) + 1
        indent = text[line:sample]
        if indent.strip() or not members:
            base = text[text.rfind("\n", 0, parent.start) + 1 : parent.start]
            indent = (base if not base.strip() else "") + (
                "\t" if "\t" in text else "  "
            )
        separator += ("\r\n" if "\r\n" in text else "\n") + indent
    elif members:
        separator += " "
    fragment = (
        separator
        + json.dumps(name, ensure_ascii=False)
        + ": "
        + json.dumps(value, ensure_ascii=False)
    )
    return text[:anchor] + fragment + text[anchor:]


def set_string(
    raw: bytes, path: tuple[str | int, ...], value: str, *, create: bool = False
) -> bytes:
    """Set one known string token, or insert only missing known object members."""
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise InvalidProjectError("Project metadata must be UTF-8") from exc
    node = _decode(text, 1 if text.startswith("\ufeff") else 0)
    if (
        _white(text, node.end) != len(text)
        or not isinstance(node.value, dict)
        or not path
    ):
        raise InvalidProjectError("Expected one Project JSON object and metadata path")
    for offset, component in enumerate(path):
        child = _child(text, node, component)
        if child is None:
            if not create or any(not isinstance(part, str) for part in path[offset:]):
                raise InvalidProjectError(
                    f"Missing known JSON metadata member: {component}"
                )
            assert isinstance(component, str)
            nested: object = value
            for part in reversed(path[offset + 1 :]):
                assert isinstance(part, str)
                nested = {part: nested}
            edited = _insert(text, node, component, nested)
            json.loads(edited.encode("utf-8"))
            return edited.encode("utf-8")
        node = child
    if not isinstance(node.value, str):
        raise InvalidProjectError("Known JSON filename/path metadata must be a string")
    if node.value == value:
        return raw
    edited = (
        text[: node.start] + json.dumps(value, ensure_ascii=False) + text[node.end :]
    )
    json.loads(edited.encode("utf-8"))
    return edited.encode("utf-8")
