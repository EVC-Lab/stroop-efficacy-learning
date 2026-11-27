"""会话文件的写入、刺激计数和代码版本记录。"""

import csv
import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory


def code_version(entrypoint):
    """记录入口及模块的摘要，离开 Git 仓库也可核对运行版本。"""
    path = Path(entrypoint).resolve()
    modules = sorted(Path(__file__).resolve().parent.glob("*.py"))
    source_paths = [path, *modules]
    hashes = {p.relative_to(path.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in source_paths}
    source_hash = hashes.pop(path.name)
    relative_paths = [p.relative_to(path.parent).as_posix() for p in source_paths]

    def git(*args):
        return subprocess.check_output(
            ["git", *args], cwd=path.parent, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", timeout=2,
            env={**os.environ, "GIT_CONFIG_COUNT": "0"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()

    try:
        git("ls-files", "--error-unmatch", "--", *relative_paths)
        commit = git("rev-parse", "HEAD")
        if git("status", "--porcelain", "--", *relative_paths):
            commit += "-dirty"
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    return commit, source_hash, hashes


def stimulus_counts(rows, inks, words):
    """按字色和字义统计 16 种正式刺激，保留未出现组合的零计数。"""
    counts = Counter((r["墨色"], r["词"]) for r in rows)
    return {
        ink: {word: counts[ink, word] for word in words}
        for ink in inks
    }


def write_snapshot(outdir, tables, meta):
    # 所有文件写完后才发布。区段先于试次替换，单个文件不会被截断。
    with TemporaryDirectory(prefix=".save-", dir=outdir) as staging:
        staged_files = []
        for fname, rows in tables:
            if not rows:
                continue
            staged = Path(staging) / fname
            with staged.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(
                    {field: f"{value:.6f}" if field.endswith("时刻s") and isinstance(value, float) else value
                     for field, value in row.items()}
                    for row in rows
                )
                fh.flush()
                os.fsync(fh.fileno())
            staged_files.append(staged)

        staged_meta = Path(staging) / "meta.json"
        with staged_meta.open("w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        for staged in (*staged_files, staged_meta):
            os.replace(staged, Path(outdir) / staged.name)
