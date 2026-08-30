"""Filesystem tool root-jail and roundtrip checks.

Root-jail is a security path, so the escape cases carry the weight of
these tests; the read/write/list happy paths are here mostly to guard
against a regression where a handler stops returning a string or the
tool factory forgets to register one of the three actions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from buildagent.domain import Tool
from buildagent.tools.filesystem import MAX_BYTES, build_filesystem_tools


@pytest.fixture
def tools(tmp_path: Path) -> dict[str, Tool]:
    return {t.name: t for t in build_filesystem_tools(tmp_path)}


@pytest.mark.asyncio
async def test_registers_three_atomic_tools(tools: dict[str, Tool]) -> None:
    assert set(tools.keys()) == {"fs_read", "fs_write", "fs_list"}


@pytest.mark.asyncio
async def test_write_then_read_roundtrip(tools: dict[str, Tool]) -> None:
    write_result = await tools["fs_write"].handler(
        {"path": "notes/todo.md", "content": "buy milk\n"}
    )
    assert "wrote" in write_result

    read_result = await tools["fs_read"].handler({"path": "notes/todo.md"})
    assert read_result == "buy milk\n"


@pytest.mark.asyncio
async def test_list_shows_files_and_dirs(
    tools: dict[str, Tool], tmp_path: Path
) -> None:
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()

    listing = await tools["fs_list"].handler({"path": "."})
    assert "f a.txt" in listing
    assert "d sub" in listing


@pytest.mark.asyncio
async def test_read_rejects_parent_escape(tools: dict[str, Tool]) -> None:
    result = await tools["fs_read"].handler({"path": "../etc/passwd"})
    assert result.startswith("error: path escapes workspace root")


@pytest.mark.asyncio
async def test_write_rejects_absolute_path(tools: dict[str, Tool]) -> None:
    result = await tools["fs_write"].handler(
        {"path": "/tmp/pwned", "content": "x"}
    )
    assert result.startswith("error: path escapes workspace root")


@pytest.mark.asyncio
async def test_write_rejects_symlink_escape(
    tools: dict[str, Tool], tmp_path: Path
) -> None:
    outside = tmp_path.parent / "outside_dir"
    outside.mkdir(exist_ok=True)
    (tmp_path / "escape").symlink_to(outside)

    result = await tools["fs_write"].handler(
        {"path": "escape/pwned", "content": "x"}
    )
    assert result.startswith("error: path escapes workspace root")
    assert not (outside / "pwned").exists()


@pytest.mark.asyncio
async def test_write_rejects_oversize(tools: dict[str, Tool]) -> None:
    huge = "a" * (MAX_BYTES + 1)
    result = await tools["fs_write"].handler({"path": "big.txt", "content": huge})
    assert "exceeds" in result


@pytest.mark.asyncio
async def test_read_of_missing_file_returns_error(tools: dict[str, Tool]) -> None:
    result = await tools["fs_read"].handler({"path": "nope.txt"})
    assert result.startswith("error: not a file")
