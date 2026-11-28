"""实验参数、效能和作答窗调度，以及随机计分的历史匹配。"""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
from itertools import accumulate

from .study2_schedule import (
    RANDOM_FIRST_BLOCKS,
    SCHEDULE_VERSION,
    SOURCE_COMMIT,
    WINDOW_BLOCK,
)


def rgb255(r, g, b, alpha=None):
    """按 0–255 的直觉填色，内部换算成 PsychoPy 的 rgb（-1…1）。"""

    def conv(v):
        return max(-1.0, min(1.0, v / 127.5 - 1.0))

    out = (conv(r), conv(g), conv(b))
    return out if alpha is None else out + (alpha,)


# ==============================================================================
#  一、参数区
# ==============================================================================
CFG = {
    # ---------- 屏幕与文字 ----------
    "FULLSCR": True,  # 正式实验全屏；调试可改 False
    "BG_COLOR": rgb255(0, 0, 0),  # 纯黑背景
    "FONT": "Microsoft YaHei",  # 中文必须用中文字体（macOS 改 'PingFang SC'）
    "DEBUG_FAST": False,  # True = 缩短时长/区段数，仅用于跑通流程
    "SKIP_PRACTICE": False,  # True = 跳过练习，仅供调试
    # ---------- 刺激材料与按键（沿用研究一的色词与映射）----------
    "KEYS": {"red": "d", "green": "f", "blue": "j", "yellow": "k"},
    "COLOR_RGB": {
        "red": (1.0, -1.0, -1.0),
        "green": (-1.0, 1.0, -1.0),
        "blue": (-1.0, -1.0, 1.0),
        "yellow": (1.0, 1.0, -1.0),
    },
    "WORD": {"red": "红", "green": "绿", "blue": "蓝", "yellow": "黄"},
    "WORD_HEIGHT": 0.11,
    "COND_RATIO": 0.50,  # 每题独立抽取一致或不一致
    # ---------- 时间参数（秒，2.2）----------
    "FIX_CHOICES": (1.0, 1.5, 2.0),  # 注视点随机 1000/1500/2000ms
    "WINDOW_CHOICES": (2.0, 3.0, 4.0),  # 正式顺序从 Study 2 日志重放
    "FB_DUR": 1.5,  # 区段反馈 1500ms
    "ISI_BETWEEN": 0.25,  # 题间空屏，以作者分析脚本的参数作开发基线
    "MIN_TRIAL_TIME": 0.35,  # 剩余可呈现时间不足时留空到截止
    # ---------- 区段构成（2.2）----------
    "N_INTERVALS": len(WINDOW_BLOCK) * len(RANDOM_FIRST_BLOCKS),
    "BREAK_EVERY": len(WINDOW_BLOCK),  # 本项目在观察到的组块边界休息；0=不休息
    # ---------- 连续计分与 yoking（2.2）----------
    "POINT_PER_CORRECT": 10,  # 每答对一次 +10 分
    "YOKE_WINDOW": 10,  # 存最近 10 个“看表现”区段的得分
    # 以公开日志随机先行组首段得分的十个分位点初始化（最旧在前，见 README）。
    "YOKE_INIT_SCORES": (20, 30, 10, 20, 30, 20, 30, 10, 20, 30),
    "SHOW_TOTAL_SCORE": True,  # 反馈里是否显示“累计 xxx 分”
    # ---------- 主观探针（2.2）----------
    "SHOW_VAS_NUMBER": False,  # 量表上是否显示 0–100 数字（原文不显示）
    # ---------- 练习（原文未细写，按实验1的结构压缩）----------
    "N_PRAC1": 8,  # 色块—按键映射
    "N_PRAC2": 12,  # 色词干扰
    "N_PRAC3": 4,  # 自由作答窗口（体验“窗口结束才结算”）
    "PRAC_TIMEOUT": 2.0,  # 练习单试次的作答上限
    "PRAC_WINDOW": 2.0,  # 练习区段的窗口长度
}

if CFG["DEBUG_FAST"]:  # 一键快跑，只为检查流程
    CFG.update(
        N_INTERVALS=12,
        FULLSCR=False,
        BREAK_EVERY=0,
        FIX_CHOICES=(0.3,),
        WINDOW_CHOICES=(1.0,),
        FB_DUR=0.5,
        PRAC_WINDOW=1.0,
        PRAC_TIMEOUT=1.2,
    )


# ==============================================================================
#  二、纯逻辑函数（与界面无关，方便校验）
# ==============================================================================
@dataclass(frozen=True)
class MainSchedule:
    version: str
    sequence: str
    windows: tuple[float, ...]
    sources: tuple[str, ...]
    probes: dict[int, str]
    block_ends: tuple[int, ...]

    def block_number(self, interval_index):
        """返回正式调度中从 1 起算的组块编号。"""
        if not 0 <= interval_index < len(self.windows):
            raise ValueError("区段下标超出正式调度。")
        return bisect_right(self.block_ends, interval_index) + 1

    def metadata(self):
        """保留开跑前的完整调度，区段位置以 1 为起点。"""
        return dict(
            版本=self.version,
            来源提交=SOURCE_COMMIT,
            来源序列=self.sequence,
            效能概率来源="未取得作者逐段概率",
            窗长s=self.windows,
            计分来源=self.sources,
            组块末段=self.block_ends,
            探测题=[dict(区段=i + 1, 类型=kind) for i, kind in self.probes.items()],
        )


def make_main_schedule(performance_first, probe_rng):
    """重放正式窗长和来源。探测题采用公开日志中的配额与交替规则。"""
    n = CFG["N_INTERVALS"]
    flags = "".join(RANDOM_FIRST_BLOCKS)
    windows = WINDOW_BLOCK * len(RANDOM_FIRST_BLOCKS)
    fast = CFG["DEBUG_FAST"]
    if n < 1 or n > len(flags) or (not fast and n != len(flags)):
        raise ValueError("正式调度须包含完整的 Study 2 区段，快跑可截短。")

    sequence = "B" if performance_first else "A"
    performance_flag = "0" if performance_first else "1"
    sources = tuple(
        "performance" if flag == performance_flag else "random" for flag in flags[:n]
    )
    kinds = (
        ("efficacy", "reward")
        if probe_rng.randrange(2) == 0
        else ("reward", "efficacy")
    )
    if fast:
        windows = (CFG["WINDOW_CHOICES"][0],) * n
        gaps = [probe_rng.randint(2, 3) for _ in range(n // 2)]
        block_ends = (n,)
    else:
        gaps = [3, 4, 5] * 24
        probe_rng.shuffle(gaps)
        block_ends = tuple(range(len(WINDOW_BLOCK), n + 1, len(WINDOW_BLOCK)))
    probes = {
        end - 1: kinds[i % 2] for i, end in enumerate(accumulate(gaps)) if end <= n
    }
    version = SCHEDULE_VERSION + "-fast" if fast else SCHEDULE_VERSION
    return MainSchedule(version, sequence, windows, sources, probes, block_ends)


class YokeWindow(object):
    """连续分数的 yoking 窗口（2.2）。

    窗口里存最近 10 个“看表现”区段的**得分**（不再是 0/1 的奖赏有无）。
    随机区段从这个窗口抽取分数，用于匹配两类区段的得分分布。
    每来一个“看表现”区段，它的得分入窗、最旧的一条出窗。
    """

    def __init__(self, n=None, init=None):
        n = CFG["YOKE_WINDOW"] if n is None else n
        init = CFG["YOKE_INIT_SCORES"] if init is None else init
        self.buf = deque([float(v) for v in init][-n:], maxlen=n)

    def sample(self, rng):
        return float(rng.choice(list(self.buf)))

    def add(self, score):
        self.buf.append(float(score))

    def mean(self):
        return sum(self.buf) / float(len(self.buf))
