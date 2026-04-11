from __future__ import annotations

from collections.abc import Callable, Iterable
import shutil
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ORIGINAL_SUFFIX = "_original.json"


def _copy_runtime_data(
    *,
    source_paths: Iterable[Path],
    target_path_for: Callable[[Path], Path],
) -> tuple[Path, ...]:
    copied_paths: list[Path] = []

    for source_path in sorted(source_paths):
        if not source_path.is_file():
            continue

        target_path = target_path_for(source_path)
        shutil.copy2(source_path, target_path)
        copied_paths.append(target_path)

    return tuple(copied_paths)


def restore_runtime_data() -> tuple[Path, ...]:
    """Restore runtime JSON data files from their preserved originals."""

    return _copy_runtime_data(
        source_paths=DATA_DIR.glob(f"*{ORIGINAL_SUFFIX}"),
        target_path_for=lambda source_path: source_path.with_name(
            source_path.name.removesuffix(ORIGINAL_SUFFIX) + ".json"
        ),
    )


def save_runtime_data() -> tuple[Path, ...]:
    """Save the current runtime JSON data files as preserved originals."""

    return _copy_runtime_data(
        source_paths=(
            source_path
            for source_path in DATA_DIR.glob("*.json")
            if not source_path.name.endswith(ORIGINAL_SUFFIX)
        ),
        target_path_for=lambda source_path: source_path.with_name(
            f"{source_path.stem}_original.json"
        ),
    )


def main() -> None:
    restored_paths = restore_runtime_data()

    if not restored_paths:
        print(f"No top-level {ORIGINAL_SUFFIX} files found in {DATA_DIR}")
        return

    print(f"Restored {len(restored_paths)} runtime JSON file(s):")
    for restored_path in restored_paths:
        print(f"- {restored_path}")


if __name__ == "__main__":
    main()
