"""Filesystem tools with a root-jail.

All paths are resolved relative to a fixed workspace root. Any resolved
path that escapes the root (via '..', an absolute path, or a symlink
target outside the root) is refused and returned to the model as an
error string, so the model can try a different path instead of the
loop dying.

The three actions are intentionally split into three atomic tools
(fs_read, fs_write, fs_list) so each shows up as its own Langfuse span
and gets a narrow JSON schema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from buildagent.domain import Tool

MAX_BYTES = 100_000


def build_filesystem_tools(root: str | Path) -> list[Tool]:
    root_path = Path(root).expanduser().resolve()
    root_path.mkdir(parents=True, exist_ok=True)

    async def read_handler(arguments: dict[str, Any]) -> str:
        target, err = _resolve(root_path, arguments["path"])
        if err is not None:
            return err
        if not target.is_file():
            return f"error: not a file: {arguments['path']}"
        data = target.read_bytes()
        if len(data) > MAX_BYTES:
            return f"error: file exceeds {MAX_BYTES}-byte read cap ({len(data)} bytes)"
        return data.decode("utf-8", errors="replace")

    async def write_handler(arguments: dict[str, Any]) -> str:
        content: str = arguments["content"]
        raw = content.encode("utf-8")
        if len(raw) > MAX_BYTES:
            return f"error: content exceeds {MAX_BYTES}-byte write cap ({len(raw)} bytes)"
        target, err = _resolve(root_path, arguments["path"])
        if err is not None:
            return err
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return f"wrote {len(raw)} bytes to {arguments['path']}"

    async def list_handler(arguments: dict[str, Any]) -> str:
        rel = arguments.get("path", ".")
        target, err = _resolve(root_path, rel)
        if err is not None:
            return err
        if not target.is_dir():
            return f"error: not a directory: {rel}"
        entries = sorted(target.iterdir(), key=lambda p: p.name)
        if not entries:
            return "(empty)"
        return "\n".join(f"{'d' if p.is_dir() else 'f'} {p.name}" for p in entries)

    return [
        Tool(
            name="fs_read",
            description=(
                "Read a UTF-8 text file from the agent workspace. The path is "
                f"resolved relative to the workspace root. Rejects files larger "
                f"than {MAX_BYTES} bytes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path to the file.",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=read_handler,
        ),
        Tool(
            name="fs_write",
            description=(
                "Write UTF-8 text to a file inside the agent workspace, "
                "creating parent directories as needed. Overwrites existing "
                f"files. Rejects content larger than {MAX_BYTES} bytes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative path to the file.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full text to write (overwrites existing content).",
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            handler=write_handler,
        ),
        Tool(
            name="fs_list",
            description=(
                "List entries in a workspace directory. Each line is prefixed "
                "with 'd' for a directory or 'f' for a file. Path defaults to "
                "the workspace root."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative directory path.",
                    },
                },
                "additionalProperties": False,
            },
            handler=list_handler,
        ),
    ]


def _resolve(root: Path, rel: str) -> tuple[Path, str | None]:
    """Resolve `rel` under `root`, refusing any escape.

    Returns (path, None) on success and (root, error_string) on refusal
    so callers can propagate the error to the model as a normal tool
    result instead of crashing the loop.

    ponytail: resolves symlinks via Path.resolve() then verifies
    containment. Replace with a chroot or explicit symlink policy if we
    ever expose a workspace with untrusted symlinks.
    """

    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root):
        return root, f"error: path escapes workspace root: {rel}"
    return candidate, None
