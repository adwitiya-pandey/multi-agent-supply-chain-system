"""Test ensuring all paths listed in README.md Repository Tree exist on disk."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def parse_readme_tree(readme_content: str) -> list[str]:
    """Parse relative file and directory paths from README.md Repository Tree."""
    match = re.search(r"## Repository Tree\s+```(?:text)?\n(.*?)\n```", readme_content, re.DOTALL)
    if not match:
        raise ValueError("Could not find ## Repository Tree block in README.md")

    tree_text = match.group(1)
    stack: list[tuple[str, int]] = [("", -1)]  # (parent_path, depth)
    paths: list[str] = []

    for raw_line in tree_text.splitlines():
        line = raw_line.split("#")[0].rstrip()
        if not line or line.strip() == ".":
            continue
        line_match = re.match(r"^([ │\t]*)[├└]──\s*(.+)$", line)
        if not line_match:
            continue
        prefix, item = line_match.groups()
        depth = len(prefix) // 4
        item = item.strip()

        while stack and stack[-1][1] >= depth:
            stack.pop()

        parent = stack[-1][0]
        curr_path = f"{parent}/{item}" if parent else item
        curr_path = curr_path.rstrip("/")
        paths.append(curr_path)

        if item.endswith("/"):
            stack.append((curr_path, depth))

    return paths


def test_readme_tree_paths_exist():
    """Every path mentioned in the README.md Repository Tree must exist on disk."""
    readme_path = REPO_ROOT / "README.md"
    assert readme_path.exists(), "README.md does not exist"

    paths = parse_readme_tree(readme_path.read_text(encoding="utf-8"))
    assert paths, "README.md Repository Tree is empty or failed to parse"

    missing = [p for p in paths if not (REPO_ROOT / p).exists()]
    assert not missing, f"README.md Repository Tree references non-existent path(s): {missing}"


def test_readme_tree_parser_detects_missing_paths():
    """Parser must detect and fail on non-existent paths."""
    sample_tree = (
        "## Repository Tree\n```\n.\n├── pyproject.toml\n└── non_existent_dummy_file.xyz\n```\n"
    )
    paths = parse_readme_tree(sample_tree)
    missing = [p for p in paths if not (REPO_ROOT / p).exists()]
    assert "non_existent_dummy_file.xyz" in missing
