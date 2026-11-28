"""会话文件的写入、刺激计数和代码版本记录。"""

import csv
import hashlib
import json
import os
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory


EXPORT_VERSION = 1

TABLE_FIELDS = {
    "trials.csv": (
        "被试",
        "组别",
        "阶段",
        "区段",
        "区段内序号",
        "窗口s",
        "区段内开始时刻s",
        "目标翻屏时刻s",
        "作答截止时刻s",
        "按键时刻s",
        "条件",
        "词",
        "墨色",
        "正确键",
        "反应键",
        "正确",
        "试次中断",
        "反应时",
        "过快",
        "会话编号",
        "组块",
        "试次编号",
        "作答状态",
        "可作答时长s",
    ),
    "intervals.csv": (
        "被试",
        "组别",
        "阶段",
        "区段",
        "窗口s",
        "作答窗用时s",
        "注视翻屏时刻s",
        "区段开始时刻s",
        "区段截止时刻s",
        "反馈翻屏时刻s",
        "反馈结束时刻s",
        "反馈延迟s",
        "反馈时长s",
        "中断阶段",
        "中断时刻s",
        "反馈中断",
        "试次数",
        "正确数",
        "正确率",
        "一致比例",
        "效能概率",
        "效能类型",
        "得分来源",
        "区段得分",
        "累计得分",
        "会话编号",
        "组块",
        "区段状态",
        "作答数",
        "截止未答数",
    ),
    "probes.csv": (
        "被试",
        "组别",
        "探针类型",
        "插入位置",
        "评价值",
        "用时s",
        "累计得分",
        "会话编号",
        "阶段",
        "组块",
        "区段",
        "探测编号",
    ),
}


def trial_response_fields(response, pressed_at, onset, deadline, interrupted):
    """保留按键时间差的秒制精度，并标记缺失的原因。"""
    rt = None if pressed_at is None else pressed_at - onset
    status = "responded" if response else ("interrupted" if interrupted else "timeout")
    return dict(
        按键时刻s=("" if pressed_at is None else pressed_at),
        反应键=response,
        反应时=("" if rt is None else rt),
        过快=("" if rt is None else int(rt < 0.25)),
        作答状态=status,
        可作答时长s=max(0.0, deadline - onset),
    )


def parameter_hash(settings):
    """对完整运行参数的规范 JSON 生成可复核摘要。"""
    encoded = json.dumps(
        settings, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def code_version(entrypoint):
    """记录入口及模块的摘要，离开 Git 仓库也可核对运行版本。"""
    path = Path(entrypoint).resolve()
    modules = sorted(Path(__file__).resolve().parent.glob("*.py"))
    source_paths = [path, *modules]
    hashes = {
        p.relative_to(path.parent).as_posix(): hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        for p in source_paths
    }
    source_hash = hashes.pop(path.name)
    relative_paths = [p.relative_to(path.parent).as_posix() for p in source_paths]

    def git(*args):
        return subprocess.check_output(
            ["git", *args],
            cwd=path.parent,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
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
    return {ink: {word: counts[ink, word] for word in words} for ink in inks}


def write_snapshot(outdir, tables, meta):
    # 各文件写完整后逐个替换，最后发布元数据供读者校验同一快照。
    with TemporaryDirectory(prefix=".save-", dir=outdir) as staging:
        staged_files = []
        summaries = {}
        for fname, rows in tables:
            staged = Path(staging) / fname
            with staged.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=TABLE_FIELDS[fname])
                writer.writeheader()
                writer.writerows(
                    {
                        field: f"{value:.6f}"
                        if field.endswith("时刻s") and isinstance(value, float)
                        else value
                        for field, value in row.items()
                    }
                    for row in rows
                )
                fh.flush()
                os.fsync(fh.fileno())
            staged_files.append(staged)
            summaries[fname] = {
                "行数": len(rows),
                "SHA256": hashlib.sha256(staged.read_bytes()).hexdigest(),
            }

        staged_meta = Path(staging) / "meta.json"
        with staged_meta.open("w", encoding="utf-8") as fh:
            json.dump({**meta, "数据表": summaries}, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        for staged in (*staged_files, staged_meta):
            os.replace(staged, Path(outdir) / staged.name)
