"""实验参数、效能和作答窗调度，以及随机计分的历史匹配。"""

import math
import random
from collections import deque

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
    "FULLSCR": True,                 # 正式实验全屏；调试可改 False
    "BG_COLOR": rgb255(0, 0, 0),     # 纯黑背景
    "FONT": "Microsoft YaHei",       # 中文必须用中文字体（macOS 改 'PingFang SC'）
    "DEBUG_FAST": False,             # True = 缩短时长/区段数，仅用于跑通流程
    "SKIP_PRACTICE": False,          # True = 跳过练习，仅供调试

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
    "COND_RATIO": 0.50,          # 每题独立抽取一致或不一致

    # ---------- 时间参数（秒，2.2）----------
    "FIX_CHOICES": (1.0, 1.5, 2.0),        # 注视点随机 1000/1500/2000ms
    "WINDOW_CHOICES": (2.0, 3.0, 4.0),     # 作答窗口随机 2000/3000/4000ms
    "FB_DUR": 1.5,                         # 区段反馈 1500ms
    "ISI_BETWEEN": 0.25,                   # 题间空屏，以作者分析脚本的参数作开发基线
    "MIN_TRIAL_TIME": 0.35,                # 剩余可呈现时间不足时留空到截止

    # ---------- 区段构成（2.2）----------
    "N_INTERVALS": 288,
    "BREAK_EVERY": 48,           # 每 48 区段休息一次（原文未写，可改；0=不休息）

    # ---------- 效能漂移（2.2）----------
    "P_MIN": 0.10,
    "P_MAX": 0.90,
    "TRAJ_SEED": 20260202,       # 按 288 区段重新生成，与实验1不同但可比
    "TRAJ_SMOOTH": 0.05,

    # ---------- 连续计分与 yoking（2.2）----------
    "POINT_PER_CORRECT": 10,     # 每答对一次 +10 分
    "YOKE_WINDOW": 10,           # 存最近 10 个“看表现”区段的得分
    # 初始窗口：8 个常规分 + 2 个低分，均值与预试的典型区段得分接近
    "YOKE_INIT_SCORES": [30.0] * 8 + [10.0] * 2,
    "SHOW_TOTAL_SCORE": True,    # 反馈里是否显示“累计 xxx 分”

    # ---------- 主观探针（2.2）----------
    "PROBE_EVERY": (2, 4),       # 每 2–4 个区段插一次
    "SHOW_VAS_NUMBER": False,    # 量表上是否显示 0–100 数字（原文不显示）

    # ---------- 练习（原文未细写，按实验1的结构压缩）----------
    "N_PRAC1": 8,                # 色块—按键映射
    "N_PRAC2": 12,               # 色词干扰
    "N_PRAC3": 4,                # 自由作答窗口（体验“窗口结束才结算”）
    "PRAC_TIMEOUT": 2.0,         # 练习单试次的作答上限
    "PRAC_WINDOW": 2.0,          # 练习区段的窗口长度
}

if CFG["DEBUG_FAST"]:  # 一键快跑，只为检查流程
    CFG.update(
        N_INTERVALS=12, FULLSCR=False, BREAK_EVERY=0,
        FIX_CHOICES=(0.3,), WINDOW_CHOICES=(1.0,), FB_DUR=0.5,
        PRAC_WINDOW=1.0, PRAC_TIMEOUT=1.2, PROBE_EVERY=(2, 3),
    )


# ==============================================================================
#  二、纯逻辑函数（与界面无关，方便校验）
# ==============================================================================
def make_trajectory(n, p_min, p_max, seed, reverse=False, smooth_frac=0.05):
    """生成一条事先固定的效能漂移轨迹（2.2）。

    高斯白噪声 → 环形高斯核平滑（缓慢漂移）→ 线性映射到 [p_min, p_max]。
    reverse=True 输出镜像序列，用于“一半被试正向、一半反向”平衡时间顺序效应。
    """
    rng = random.Random(seed)
    noise = [rng.gauss(0.0, 1.0) for _ in range(n)]

    sigma = max(1.0, n * smooth_frac)
    half = int(3 * sigma)
    kernel = [math.exp(-0.5 * ((i / sigma) ** 2)) for i in range(-half, half + 1)]
    ksum = sum(kernel)
    kernel = [k / ksum for k in kernel]

    padded = noise[-half:] + noise + noise[:half]
    smooth = []
    for i in range(half, half + n):
        acc = 0.0
        for j, k in enumerate(kernel):
            acc += padded[i - half + j] * k
        smooth.append(acc)

    lo, hi = min(smooth), max(smooth)
    unit = [(v - lo) / (hi - lo + 1e-12) for v in smooth]
    p = [p_min + u * (p_max - p_min) for u in unit]
    if reverse:
        p = p[::-1]
    return p


def make_probe_schedule(n_intervals, every, rng):
    """安排主观探针位置（2.2）：每 2–4 个区段插一次，两类探针交替。

    返回 {区段下标: 'efficacy' / 'reward'}，表示“在第 i 个区段之后插入”。
    """
    sched = {}
    i = -1
    kind = "efficacy" if rng.random() < 0.5 else "reward"
    while True:
        i += rng.randint(*every)
        if i > n_intervals - 1:
            break
        sched[i] = kind
        kind = "reward" if kind == "efficacy" else "efficacy"
    return sched


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


def make_score_schedule(n_intervals, rng):
    """预先平衡区段窗口长度：三个长度各占 1/3，再整体打乱。

    原文只说“随机取 2000/3000/4000ms”。纯随机会出现某长度偏多（尤其样本小时），
    进而让“区段平均试次数”抖动；这里改成等量分配 + 打乱，统计上更干净，
    分析时仍把区段长度作为协变量（2.3）。
    """
    lens = list(CFG["WINDOW_CHOICES"])
    n_each = n_intervals // len(lens)
    seq = []
    for L in lens:
        seq += [L] * n_each
    while len(seq) < n_intervals:
        seq.append(rng.choice(lens))
    rng.shuffle(seq)
    return seq
