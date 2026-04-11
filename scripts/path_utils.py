from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
SAMPLE_INPUT_DIR = DATA_DIR / "sample_input"


def repo_relative_path(path: str | Path) -> str:
    """Return a portable repo-relative path when the input is inside the repository."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        return candidate.as_posix()

    try:
        return candidate.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return candidate.as_posix()


def resolve_repo_path(path: str | Path) -> Path:
    """Resolve a stored mock-data path against the repository and data directories."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate

    candidates = [ROOT_DIR / candidate]
    if not candidate.parts or candidate.parts[0] != "data":
        candidates.append(DATA_DIR / candidate)
        candidates.append(SAMPLE_INPUT_DIR / candidate)

    for resolved_candidate in candidates:
        if resolved_candidate.exists():
            return resolved_candidate

    return candidates[0]
