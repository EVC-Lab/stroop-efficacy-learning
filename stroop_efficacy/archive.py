"""实验员登记和采集端场次查询所用的归档规则。"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .session_data import read_session_snapshot

MODES = {"formal": "正式采集", "pilot": "预测试", "quick": "快跑"}
STATUS = {
    "running": "未完成",
    "completed": "已完成",
    "interrupted": "已中断",
    "error": "异常结束",
    "recovery": "当前文件待恢复",
    "unverified": "未完成，需核对文件",
    "legacy": "旧版，状态未记录",
}
RESERVED_CODES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
}


def participant_code(value):
    code = str(value).strip()
    if (
        not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}", code)
        or code.upper() in RESERVED_CODES
    ):
        raise ValueError(
            "编码须以字母或数字开头，使用 1–32 位字母、数字、连字符或下划线。"
        )
    return code.upper()


def performance_first(code, direction="自动"):
    if direction.startswith("自动"):
        digits = re.findall(r"\d", code)
        return bool(digits) and int(digits[-1]) % 2 == 0
    return direction == "反向"


@dataclass(frozen=True)
class ArchiveEntry:
    code: str
    mode: str
    session_id: str
    status: str
    completed: int | str
    started_at: str
    finished_at: str
    path: Path


def describe_session(directory, code, mode):
    meta, recovered = read_session_snapshot(directory)
    meta = meta or {}
    if (
        meta.get("会话编号") != directory.name
        or meta.get("被试编号") != code
        or meta.get("运行模式") != mode
    ):
        meta, recovered = {}, False
    if recovered:
        status = "recovery"
    else:
        status = meta.get("会话状态", "unverified")
    return ArchiveEntry(
        code,
        mode,
        directory.name,
        status,
        meta.get("完整区段数", "—"),
        meta.get("会话开始时间", ""),
        meta.get("会话结束时间", "") if not recovered else "",
        directory,
    )


def list_sessions(root, code=""):
    """按参与者目录缩小范围，旧目录通过旧版元数据识别。"""
    root = Path(root)
    if not root.is_dir():
        return []
    entries = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        mode = directory.name
        if mode in MODES:
            for subject in directory.iterdir():
                if subject.is_dir() and (
                    not code or subject.name.casefold() == code.casefold()
                ):
                    entries.extend(
                        describe_session(path, subject.name, mode)
                        for path in subject.iterdir()
                        if path.is_dir()
                    )
        else:
            try:
                meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            prior_code = str(meta.get("被试编号", ""))
            if prior_code and (not code or prior_code.casefold() == code.casefold()):
                entries.append(
                    ArchiveEntry(
                        prior_code,
                        "legacy",
                        str(meta.get("会话编号", "—")),
                        "legacy",
                        meta.get("完整区段数", "—"),
                        "",
                        "",
                        directory,
                    )
                )
    return sorted(
        entries, key=lambda entry: (entry.started_at, entry.session_id), reverse=True
    )
