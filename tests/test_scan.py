from pathlib import Path

from tokensaver.pricing import load_prices
from tokensaver.scan import find_prompt_files, scan

PRETTY = '{\n    "name": "string",\n    "tags": [\n        "a",\n        "b"\n    ]\n}\n'
FILLER = "I would like you to please summarize the text.\n"


def _write(path: Path, text: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def test_finds_prompt_files_in_subfolders(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "x")
    _write(tmp_path / "sub" / "b.md", "x")
    _write(tmp_path / "sub" / "deeper" / "c.PROMPT", "x")
    _write(tmp_path / "sub" / "d.j2", "x")
    _write(tmp_path / "code.py", "x")
    found = [p.relative_to(tmp_path).as_posix() for p in find_prompt_files(tmp_path)]
    assert found == ["a.txt", "sub/b.md", "sub/d.j2", "sub/deeper/c.PROMPT"]


def test_skips_hidden_dependency_and_virtualenv_folders(tmp_path: Path) -> None:
    _write(tmp_path / "keep.txt", "x")
    _write(tmp_path / ".git" / "notes.txt", "x")
    _write(tmp_path / "node_modules" / "pkg" / "README.md", "x")
    _write(tmp_path / "__pycache__" / "x.txt", "x")
    _write(tmp_path / "myenv" / "pyvenv.cfg", "home = /usr")
    _write(tmp_path / "myenv" / "lib" / "LICENSE.txt", "x")
    found = [p.name for p in find_prompt_files(tmp_path)]
    assert found == ["keep.txt"]


def test_custom_patterns(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "x")
    _write(tmp_path / "b.yaml", "x")
    assert [p.name for p in find_prompt_files(tmp_path, ("*.yaml",))] == ["b.yaml"]


def test_scan_measures_safe_and_all_savings(tmp_path: Path) -> None:
    _write(tmp_path / "json.txt", PRETTY)  # safe fix only
    _write(tmp_path / "filler.txt", FILLER)  # review fix only
    _write(tmp_path / "lean.txt", "Summarize the text in three bullet points.")
    result = scan(tmp_path, load_prices().get("gpt-4o"))

    by_name = {f.path: f for f in result.files}
    assert by_name["json.txt"].safe_saved > 0
    assert by_name["json.txt"].all_saved == by_name["json.txt"].safe_saved
    assert by_name["filler.txt"].safe_saved == 0
    assert by_name["filler.txt"].all_saved > 0
    assert by_name["lean.txt"].all_saved == 0

    savings = [f.all_saved for f in result.files]
    assert savings == sorted(savings, reverse=True)
    assert result.files[-1].path == "lean.txt"
    assert result.all_saved == sum(savings)
    assert result.tokens == sum(f.tokens for f in result.files)


def test_scan_skips_files_that_are_not_utf8(tmp_path: Path) -> None:
    _write(tmp_path / "ok.txt", "Hello")
    _write(tmp_path / "binary.txt", b"\xff\xfe\x00\x81")
    result = scan(tmp_path, load_prices().get("gpt-4o"))
    assert [f.path for f in result.files] == ["ok.txt"]
    assert result.skipped == ["binary.txt"]
