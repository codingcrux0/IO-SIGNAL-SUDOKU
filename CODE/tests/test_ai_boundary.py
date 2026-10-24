"""Proof that no AI code is in the allocation path (CLAUDE_RULES: deterministic solver)."""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "io_sudoku"
FORBIDDEN = ("anthropic", "io_sudoku.core.advisor")


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def test_only_advisor_and_ui_may_touch_ai():
    offenders = []
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        if rel == "core/advisor.py" or rel.startswith("ui/"):
            continue
        for name in _imports(path):
            if name == "anthropic" or name.startswith("anthropic.") or name in FORBIDDEN or name.endswith(".advisor"):
                offenders.append((rel, name))
    assert not offenders, offenders


def test_advisor_imports_the_sdk_lazily_only():
    tree = ast.parse((PKG / "core/advisor.py").read_text(encoding="utf-8"))
    top_level = {n.names[0].name for n in tree.body if isinstance(n, ast.Import)}
    assert "anthropic" not in top_level


def test_fresh_solve_never_loads_ai_modules():
    code = ("import sys; from io_sudoku.core import pipeline, revision, rulepack, rulechange; "
            "bad=[m for m in sys.modules if m=='anthropic' or m=='io_sudoku.core.advisor']; "
            "print(bad); sys.exit(1 if bad else 0)")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
