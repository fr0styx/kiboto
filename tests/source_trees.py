"""One read and one parse of each source file per test worker, shared by the tests that scan the
code (the ratchets). CI runs them on one worker (xdist_group "source_scan", --dist loadgroup), so
the backend is parsed once instead of once per test. The trees are shared: never change them."""

import ast
import functools
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


@functools.cache
def text(path: pathlib.Path) -> str:
    return pathlib.Path(path).read_text(encoding="utf-8")


@functools.cache
def tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(text(path))


@functools.cache
def files(folder: str = "backend") -> tuple[pathlib.Path, ...]:
    """The .py files under ROOT/folder, sorted."""
    return tuple(sorted((ROOT / folder).rglob("*.py")))
