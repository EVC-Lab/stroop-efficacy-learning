# -*- coding: utf-8 -*-
"""
实验1复现：Stroop 任务 + 随时间漂移的“效能”反馈（含奖赏 yoking 与主观探针）
================================================================================
对应《实验内容》1.1–1.5 全部流程：
    练习1  颜色—按键映射        80 试次      （1.5-1）
    练习2  Stroop + 正误反馈    30 试次      （1.5-2）
    校准   反应时限自适应      100 试次      （1.5-3，目标 ~80% “又对又快”）
    练习4  两类反馈形式介绍     30 试次      （1.5-4）
    正式   288 试次 + 主观探针  约 40 分钟   （1.1–1.4）

运行方式（重要）：
    不要用系统自带的 python 运行；必须用 **PsychoPy 自带的 Python**。
    方式A：打开 PsychoPy → Coder 视图 → File/Open 本文件 → 点绿色 Run 三角。
    方式B：命令行调用 PsychoPy 的 python.exe，例如 Windows:
        "C:\\Program Files\\PsychoPy\\python.exe" exp1_stroop_efficacy.py

    PsychoPy 版本：2023.2.x LTS 或 2024.x 均可（代码只用了最稳定的 API）。
    想快速试跑看流程是否正常：把下面 DEBUG_FAST 改成 True。

数据输出：
    ./data/<被试号>_<时间>/trials.csv     每个试次一行（正式任务+各练习阶段）
    ./data/<被试号>_<时间>/probes.csv     每次主观探针一行
    ./data/<被试号>_<时间>/meta.json      组别、最终反应时限、随机种子等
================================================================================
"""

import os
import csv
import json
import math
import random
import re
import statistics
from collections import deque
from datetime import datetime

from psychopy import visual, core, event, gui

try:  # 老接口优先：event.Mouse 方法齐全（getPressed / getPos），新版 PsychoPy 仍提供
    MouseClass = event.Mouse
except AttributeError:  # 极新版本若移除，再退回 hardware.mouse
    from psychopy.hardware import mouse as mouse_mod
    MouseClass = mouse_mod.Mouse


def mouse_left_pressed(mouse):
    """跨版本判断鼠标左键是否按下。

    PsychoPy 2024.x 的 psychopy.hardware.mouse.Mouse 已经**删掉了 getPressed()**，
    只剩 getLeftButtonPressed()/getPressedTimes() 等；老版本则只有 getPressed()。
    直接写 mouse.getPressed() 会在新版本上抛 AttributeError，把整个实验打断。
    """
    if hasattr(mouse, "getPressed"):
        try:
            return bool(mouse.getPressed()[0])
        except Exception:
            pass
    if hasattr(mouse, "getLeftButtonPressed"):
        return bool(mouse.getLeftButtonPressed())
    return False


# ==============================================================================
#  代码版本标记：把 git 提交号写进 meta.json
#  每份被试数据都能追溯到“由哪一版代码跑出来”，改过参数却忘了记的坑可以避免。
#  不在 git 仓库里 / 没装 git 时返回 "unknown"，不影响实验运行。
# ==============================================================================
_CODE_VERSION = None


def code_version():
    """返回形如 'v1.2+3a7f1c9' 的版本标记；工作区有未提交改动时追加 '-dirty'。"""
    global _CODE_VERSION
    if _CODE_VERSION is not None:
        return _CODE_VERSION
    base = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    try:
        import subprocess

        def run(*args):
            p = subprocess.run(["git"] + list(args), cwd=base,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
            return p.stdout.decode("utf-8", "replace").strip()

        sha = run("rev-parse", "--short", "HEAD")
        if not sha:
            _CODE_VERSION = "unknown"
            return _CODE_VERSION
        tag = run("describe", "--tags", "--abbrev=0")
        dirt = run("status", "--porcelain")
        out = ("%s+%s" % (tag, sha)) if tag else sha
        _CODE_VERSION = out + ("-dirty" if dirt else "")
    except Exception:
        _CODE_VERSION = "unknown"
    return _CODE_VERSION


# ==============================================================================
#  颜色小工具
#  PsychoPy 默认色彩空间是 rgb，范围 -1…1，不是 0…255！
#  (0,0,0)→(-1,-1,-1) 纯黑    (128,128,128)→(0,0,0) 中灰    (255,255,255)→(1,1,1) 纯白
#  直接把 128 之类 0–255 的值填进去，会被截断到 1.0 —— 画出来是“纯白”，这就是白圈来源。
# ==============================================================================
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
    "FULLSCR": True,                 # 正式实验用全屏；调试可改 False
    "BG_COLOR": rgb255(0, 0, 0),     # 纯黑 = (-1,-1,-1)；别写 (0,0,0)，那是中灰
    "FONT": "Microsoft YaHei",       # 中文必须用中文字体（macOS 可改 'PingFang SC'）
    "DEBUG_FAST": False,             # True = 缩短时长/试次数，仅用于跑通流程
    # True = 只跑正式任务：跳过练习1/2/4 与时限校准（调试、演示、补数据时用）
    # 正式采集被试数据必须改回 False，否则没有练习、时限也不是个体化的
    "SKIP_PRACTICE": False,          # 改成 True = 只跑正式任务，跳过练习1/2/4 与时限校准
    "DEADLINE_WHEN_SKIPPED": 0.800,  # 跳过校准时套用的固定反应时限（秒）

    # ---------- 刺激材料与按键（1.1）----------
    # 键位：D F J K 从左到右对应 红 绿 蓝 黄
    "KEYS": {"red": "d", "green": "f", "blue": "j", "yellow": "k"},
    "COLOR_RGB": {
        "red": (1.0, -1.0, -1.0),
        "green": (-1.0, 1.0, -1.0),
        "blue": (-1.0, -1.0, 1.0),
        "yellow": (1.0, 1.0, -1.0),
    },
    "WORD": {"red": "红", "green": "绿", "blue": "蓝", "yellow": "黄"},
    "NEUTRAL_WORDS": ["桌", "窗", "门", "书", "椅", "灯"],  # 中性词（非颜色词）

    # ---------- 时间参数（秒，1.1）----------
    "FIX_JITTER": (1.0, 1.5),   # 注视点抖动 1000–1500ms
    "FIX_ON_BLACK": True,       # True = 先单独呈现“只有十字的黑屏”jitter，再出圆盘（Fig.1 顺序）
    "CUE_DUR": 1.5,             # Cue 阶段：圆盘 + 中央十字共 1500ms，不携带效能信息
    "FIX_ON_CUE": True,         # Cue 阶段圆环中央是否保留注视点十字（Fig.1 为保留）
    "ISI_DUR": 1.0,             # ISI：目标消失后、反馈前的空屏 1000ms（圆环仍保留）
    # 圆环描边：想要“白色一圈”就填 rgb255(255,255,255)，要中灰填 rgb255(128,128,128)
    "CUE_COLOR": rgb255(128, 128, 128),   # 中灰 = (0,0,0)，黑底上清楚但不刺眼
    # 圆环内部填充：None = 空心（透出背景）；填颜色就是实心圆盘。
    # 现在填成与 CUE_COLOR 相同的 128 灰 → 圆环变成一整块实心灰圆盘（描边与填充同色，看不出边线）。
    # 想恢复“空心细圈”就把这里改回 None。
    "CUE_FILL_COLOR": rgb255(128, 128, 128),  # 与 CUE_COLOR 同色：中灰实心圆盘
    "CUE_RADIUS": 0.20,         # 单位 = 窗口高度的比例，直径占屏高 40%
    "CUE_LINE_WIDTH": 6,
    "TARGET_MAX": 1.0,          # 目标刺激最长呈现 1000ms（按键即消失）
    "FB_DUR": 1.0,              # 每种反馈 1000ms
    "SHOW_TOTAL_REWARD": True,     # 是否显示“累计 $x.xx”（原文未明确，可按需关闭）
    # 效能反馈里的“按钮图标”：留空用矢量键帽；填 PNG 路径（透明底）则直接显示图片
    "BTN_ICON_IMG": "",
    "BTN_LABEL": "按 键",       # 键帽上的字，改成 "" 就是一块空白键帽

    # ---------- 正式任务试次构成（1.1）----------
    "N_CONGRUENT": 108,      # 一致
    "N_INCONGRUENT": 108,    # 不一致
    "N_NEUTRAL": 72,         # 中性
    "BREAK_EVERY": 48,       # 每 48 试次休息一次（原文未写，可按需改；0=不休息）

    # ---------- 效能漂移（1.2）----------
    "P_MIN": 0.10,           # “看表现”概率的下限
    "P_MAX": 0.90,           # 上限
    "TRAJ_SEED": 20260101,   # 漂移轨迹的固定种子（轨迹事先固定，可复现）
    "TRAJ_SMOOTH": 0.05,     # 平滑程度：占试次总数的比例，越大漂移越慢、时段越长

    # ---------- 奖赏率匹配 yoking（1.3）----------
    "REWARD_WINDOW": 10,     # 滑动窗口长度 = 前 10 个“看表现”试次
    "REWARD_INIT": (8, 2),   # 初始窗口 8 奖 2 无奖
    "REWARD_AMOUNT": 0.50,   # 每次 $0.50

    # ---------- 主观探针（1.4）----------
    "PROBE_EVERY": (2, 4),   # 每 2–4 个试次插入一次
    "SHOW_VAS_NUMBER": False,  # 是否在量表上显示 0–100 数字（原文不显示）

    # ---------- 练习与校准（1.5）----------
    "N_PRAC1": 80,           # 颜色—按键映射
    "N_PRAC2": 30,           # Stroop
    "N_PRAC4": 30,           # 两类反馈形式
    "CAL_TRIALS": 100,       # 校准试次
    "CAL_START": 0.750,      # 起始时限 750ms
    "CAL_BLOCK": 8,          # 每 8 试次调一次
    "CAL_TARGET": 0.80,      # 目标“又对又快”比例 80%
    "CAL_STEP": 0.030,       # 调整步长 30ms
    "CAL_BOUNDS": (0.35, 1.20),
    "CAL_FINAL_LAST": 20,    # 用最后 20 个试次的时限取中位数作为最终时限
}

if CFG["DEBUG_FAST"]:  # 一键快跑，只为检查流程
    CFG.update(
        N_CONGRUENT=9, N_INCONGRUENT=9, N_NEUTRAL=6,
        N_PRAC1=8, N_PRAC2=6, N_PRAC4=6, FULLSCR=False,
        CAL_TRIALS=12, CAL_BLOCK=4,
        FIX_JITTER=(0.3, 0.4), CUE_DUR=0.4, ISI_DUR=0.3, TARGET_MAX=1.0, FB_DUR=0.5,
        BREAK_EVERY=0, PROBE_EVERY=(2, 3),
    )


# ==============================================================================
#  二、纯逻辑函数（与界面无关，方便校验/单独测试）
# ==============================================================================
def make_trajectory(n, p_min, p_max, seed, reverse=False, smooth_frac=0.05):
    """生成一条事先固定的效能漂移轨迹（1.2）。

    做法：高斯白噪声 → 环形高斯核平滑（得到缓慢漂移的曲线）→ 线性映射到
    [p_min, p_max]。reverse=True 输出镜像序列，用于“一半被试正向、一半反向”
    来平衡时间顺序效应。同一个 seed 得到同一条轨迹，可复现。
    """
    rng = random.Random(seed)
    noise = [rng.gauss(0.0, 1.0) for _ in range(n)]

    # 环形高斯核
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


def fix_runs(seq, max_run=3):
    """打散序列中超过 max_run 的连续相同取值（用于平衡反馈呈现顺序）。"""
    seq = list(seq)
    for i in range(2, len(seq)):
        if seq[i] == seq[i - 1] == seq[i - 2]:
            for j in range(i + 1, len(seq)):
                if seq[j] != seq[i]:
                    seq[i], seq[j] = seq[j], seq[i]
                    break
    return seq


def make_main_trial_list(rng=None):
    """构造正式任务的 288 个试次（1.1）：一致 108 / 不一致 108 / 中性 72。

    平衡要求：每种墨色在各条件下出现次数相等；不一致条件下每个“词≠墨色”的
    组合出现次数相等；反馈呈现顺序（先奖赏/先效能）各半且不连续超过 3 次。
    """
    rng = rng or random.Random()
    colors = list(CFG["KEYS"].keys())
    trials = []

    # 一致：词 = 墨色，每种颜色 27 次
    for c in colors:
        for _ in range(CFG["N_CONGRUENT"] // len(colors)):
            trials.append(dict(condition="congruent", word=CFG["WORD"][c], ink=c))

    # 不一致：词 ≠ 墨色，每个（词, 墨色）组合 9 次 → 每种墨色 27 次
    for ink in colors:
        others = [w for w in colors if w != ink]
        per = CFG["N_INCONGRUENT"] // (len(colors) * (len(colors) - 1))
        for w in others:
            for _ in range(per):
                trials.append(dict(condition="incongruent", word=CFG["WORD"][w], ink=ink))

    # 中性：非颜色词，每种墨色 18 次
    for ink in colors:
        for i in range(CFG["N_NEUTRAL"] // len(colors)):
            w = CFG["NEUTRAL_WORDS"][i % len(CFG["NEUTRAL_WORDS"])]
            trials.append(dict(condition="neutral", word=w, ink=ink))

    rng.shuffle(trials)

    # 反馈顺序：一半先奖赏、一半先效能
    n = len(trials)
    orders = ["reward_first"] * (n // 2) + ["efficacy_first"] * (n - n // 2)
    rng.shuffle(orders)
    orders = fix_runs(orders, 3)
    for t, o in zip(trials, orders):
        t["feedback_order"] = o
    return trials


def make_probe_schedule(n_trials, every, rng):
    """安排主观探针位置（1.4）：每 2–4 个试次插一次，两类探针交替（数量近似相等）。

    返回 {试次下标: 'efficacy' / 'reward'}，表示“在第 i 个试次之后插入”。
    """
    sched = {}
    i = -1
    kind = "efficacy" if rng.random() < 0.5 else "reward"
    while True:
        i += rng.randint(*every)
        if i > n_trials - 1:
            break
        sched[i] = kind
        kind = "reward" if kind == "efficacy" else "efficacy"
    return sched


def next_deadline(p_fast, deadline, target=None, step=None, bounds=None):
    """校准阶梯（1.5-3）：又对又快比例高于 80% → 收紧时限，低于 → 放宽。"""
    target = CFG["CAL_TARGET"] if target is None else target
    step = CFG["CAL_STEP"] if step is None else step
    lo, hi = CFG["CAL_BOUNDS"] if bounds is None else bounds
    deadline = deadline - step if p_fast > target else deadline + step
    return float(min(max(deadline, lo), hi))


class RewardWindow(object):
    """奖赏率匹配的滑动窗口（1.3）。

    初始窗口 = 8 奖 + 2 无奖（对应预校准奖赏率）。此后每个“看表现”试次的结果
    入窗、最旧的一条出窗（窗口长度固定 10）。随机试次的奖赏直接从这个窗口里
    抽一条，于是两类试次的奖赏率被强制匹配。
    """

    def __init__(self, n=None, init=None):
        n = CFG["REWARD_WINDOW"] if n is None else n
        init = CFG["REWARD_INIT"] if init is None else init
        self.buf = deque([1] * init[0] + [0] * init[1], maxlen=n)

    def sample(self, rng):
        return int(rng.choice(list(self.buf)))

    def add(self, outcome):
        self.buf.append(int(outcome))


# ==============================================================================
#  三、实验主类
# ==============================================================================
class StroopEfficacyExp(object):
    def __init__(self, info):
        self.outdir = None
        self.update_info(info)

        self.rng = random.Random()
        self.traj_seed = CFG["TRAJ_SEED"]
        self.rng.seed("%s-%s" % (self.subj, self.group))  # 每个被试可复现

        core.checkPygletDuringWait = False
        self.win = visual.Window(
            size=(1280, 800), fullscr=CFG["FULLSCR"], color=CFG["BG_COLOR"],
            units="height", allowGUI=False, checkTiming=False,
        )
        self.win.setMouseVisible(False)

        f = CFG["FONT"]
        # ---- 基础刺激 ----
        self.fix = visual.TextStim(self.win, "+", font=f, color=(1, 1, 1), height=0.09)
        self.cue = visual.Circle(self.win, radius=CFG["CUE_RADIUS"], edges=96,
                                 lineColor=CFG["CUE_COLOR"],
                                 lineWidth=CFG["CUE_LINE_WIDTH"],
                                 fillColor=CFG.get("CUE_FILL_COLOR"))
        self.word = visual.TextStim(self.win, "", font=f, color=(1, 1, 1), height=0.11, bold=True)
        self.square = visual.Rect(self.win, width=0.16, height=0.16, fillColor=None)

        # ---- 反馈刺激 ----
        self.fb_main = visual.TextStim(self.win, "", font=f, color=(1, 1, 1), height=0.075)
        self.fb_sub = visual.TextStim(self.win, "", font=f, color=(0.85, 0.85, 0.85),
                                      height=0.038, pos=(0, -0.13))
        self.fb_top = visual.TextStim(self.win, "", font=f, color=(0.8, 0.8, 0.8),
                                      height=0.035, pos=(0, 0.14))
        # 效能反馈的两个图标（本次看表现 = 键帽 / 本次随机 = 骰子）
        self._build_efficacy_icons()

        # ---- 主观探针（0–100 VAS）----
        self.probe_q = visual.TextStim(self.win, "", font=f, color=(1, 1, 1),
                                       height=0.048, wrapWidth=0.95, pos=(0, 0.26))
        self.probe_line = visual.Line(self.win, start=(-0.32, -0.04), end=(0.32, -0.04),
                                      lineColor=(1, 1, 1), lineWidth=4)
        self.probe_lab_l = visual.TextStim(self.win, "", font=f, color=(0.85, 0.85, 0.85),
                                           height=0.034, pos=(-0.32, -0.14))
        self.probe_lab_r = visual.TextStim(self.win, "", font=f, color=(0.85, 0.85, 0.85),
                                           height=0.034, pos=(0.32, -0.14))
        self.probe_mark = visual.Circle(self.win, radius=0.016, fillColor=(1, 1, 1),
                                        lineColor=None, pos=(0, -0.04))
        self.probe_hint = visual.TextStim(self.win, "拖动滑块（或按 ← → 键）到你的答案位置，然后按 空格 确认",
                                          font=f, color=(0.8, 0.8, 0.8), height=0.032, pos=(0, -0.30))
        self.probe_num = visual.TextStim(self.win, "", font=f, color=(1, 1, 1), height=0.04,
                                         pos=(0, 0.10))

        # ---- 运行时状态 ----
        self.kb_clock = core.Clock()
        self.keys = list(CFG["KEYS"].values())
        self.reward_win = RewardWindow()
        self.total_reward = 0.0
        self.deadline = CFG["CAL_START"]
        self.rows_trials = []
        self.rows_probes = []

    # -------------------------------------------------------------- 被试信息
    def update_info(self, info):
        """登记/更新被试信息（姓名、编号、漂移方向）。"""
        self.info = info
        self.name = str(info.get("姓名", "")).strip() or "匿名"
        self.subj = str(info.get("被试编号", "")).strip() or auto_subject_id()
        direction = str(info.get("漂移方向", "正向")).strip()

        if direction.startswith("自动"):
            digits = re.findall(r"\d", self.subj)
            self.reverse = (int(digits[-1]) % 2 == 0) if digits else False
        else:
            self.reverse = (direction == "反向")
        self.group = "反向" if self.reverse else "正向"

    def info_text(self):
        return ("姓名：%s\n编号：%s\n年龄：%s    性别：%s\n漂移方向：%s"
                % (self.name, self.subj, self.info.get("年龄", ""),
                   self.info.get("性别", ""), self.group))

    def confirm_info(self):
        """开跑前的信息确认屏：按 R 可重新填写，按空格确认。"""
        stim = visual.TextStim(
            self.win,
            "请核对被试信息\n\n" + self.info_text() +
            "\n\n信息有误：按 R 重新填写        确认无误：按 空格 开始",
            font=CFG["FONT"], color=(1, 1, 1), height=0.045, wrapWidth=1.15,
            alignText="center")
        stim.draw()
        self.win.flip()
        event.clearEvents()
        while True:
            keys = event.waitKeys(keyList=["space", "r", "escape"])
            if keys and keys[0] == "escape":
                self.win.close()
                core.quit()
            if keys and keys[0] == "r":
                return False
            if keys and keys[0] == "space":
                return True

    # ------------------------------------------------------------------ 输出
    def _make_outdir(self):
        base = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r'[\\/:*?"<>|\s]+', "", "%s_%s" % (self.subj, self.name))
        d = os.path.join(base, "data", "%s_%s" % (safe, stamp))
        os.makedirs(d, exist_ok=True)
        return d

    def log_trial(self, row):
        self.rows_trials.append(row)

    def log_probe(self, row):
        self.rows_probes.append(row)

    def save(self, verbose=False):
        if self.outdir is None:
            self.outdir = self._make_outdir()
        if self.rows_trials:
            path = os.path.join(self.outdir, "trials.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=list(self.rows_trials[0].keys()))
                w.writeheader()
                w.writerows(self.rows_trials)
        if self.rows_probes:
            path = os.path.join(self.outdir, "probes.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=list(self.rows_probes[0].keys()))
                w.writeheader()
                w.writerows(self.rows_probes)
        meta = dict(
            姓名=self.name, 被试编号=self.subj, 年龄=self.info.get("年龄", ""),
            性别=self.info.get("性别", ""), 漂移方向=self.group,
            最终反应时限s=round(self.deadline, 4),
            校准=("跳过（固定 %.3f s）" % self.deadline if CFG.get("SKIP_PRACTICE") else "完成"),
            累计奖赏=round(self.total_reward, 2), 轨迹种子=self.traj_seed,
            效能下限=CFG["P_MIN"], 效能上限=CFG["P_MAX"], 版本="exp1_v1.2",
            代码版本=code_version(),
        )
        with open(os.path.join(self.outdir, "meta.json"), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        if verbose:
            print("\n数据已保存到：", self.outdir)

    # ------------------------------------------------------------------ 通用界面
    def wait_space(self, text, height=0.042, color=(1, 1, 1)):
        stim = visual.TextStim(self.win, text, font=CFG["FONT"], color=color,
                               height=height, wrapWidth=1.1, alignText="center")
        stim.draw()
        self.win.flip()
        event.clearEvents()
        while True:
            k = event.waitKeys(keyList=["space", "escape"])
            if k and k[0] == "escape":
                self.abort()
            if k and k[0] == "space":
                return

    def abort(self):
        self.save(verbose=True)
        self.win.close()
        core.quit()

    def check_escape(self):
        if "escape" in event.getKeys(keyList=["escape"]):
            self.abort()

    # ------------------------------------------------------------------ 单试次
    def run_trial(self, trial, phase, deadline=None, eff_type=None, p_eff=None, idx=None):
        """一个完整试次（对齐 Fig.1）：

        注视点 1000–1500ms → Cue 圆环 1500ms → 目标（至时限）
        一个试次内：圆盘+十字（jitter+Cue）→ 目标（至时限）→ ISI 1000ms
        → 反馈1 1000ms → 反馈2 1000ms

        圆盘从试次一开始就出现，一直保留到两条反馈结束，中途不消失、不重画新对象
        （同一个 Circle 反复 draw，避免闪一下）。
        """
        # 1) 试次开头：圆盘 + 注视点十字
        jitter = self.rng.uniform(*CFG["FIX_JITTER"])
        if CFG.get("FIX_ON_BLACK", False):
            # 保留 Fig.1 的独立注视点黑屏，随后单独呈现圆盘
            self.fix.draw()
            self.win.flip()
            core.wait(jitter)
            self.cue.draw()
            if CFG.get("FIX_ON_CUE", True):
                self.fix.draw()
            self.win.flip()
            core.wait(CFG["CUE_DUR"])
        else:
            # 不要独立黑屏：圆盘从试次一开始就在，十字叠在圆盘中央
            self.cue.draw()
            self.fix.draw()
            self.win.flip()
            core.wait(jitter + CFG["CUE_DUR"])

        # 3) 目标刺激（Stroop 词覆盖在圆环上），按键或超时消失
        self.word.text = trial["word"]
        self.word.setColor(CFG["COLOR_RGB"][trial["ink"]])
        max_wait = CFG["TARGET_MAX"]
        if deadline is not None:
            max_wait = max(max_wait, deadline)
        self.kb_clock.reset()
        event.clearEvents()
        self.cue.draw()
        self.word.draw()
        self.win.flip()
        resp_keys = event.waitKeys(maxWait=max_wait, keyList=self.keys + ["escape"],
                                   timeStamped=self.kb_clock)
        if resp_keys and resp_keys[0][0] == "escape":
            self.abort()
        if resp_keys:
            resp_key, rt = resp_keys[0][0], float(resp_keys[0][1])
        else:
            resp_key, rt = "", None

        correct_key = CFG["KEYS"][trial["ink"]]
        is_correct = int(resp_key == correct_key)
        in_time = int(rt is not None and deadline is not None and rt <= deadline)
        fast = int(is_correct and in_time)   # “又对又快”：正确且在个体化时限内
        got_reward = None

        # 3b) ISI：目标消失后的空屏，圆环仍在，屏上无字、无十字（Fig.1 的 ISI 面板）
        if CFG["ISI_DUR"] > 0:
            self.cue.draw()
            self.win.flip()
            core.wait(CFG["ISI_DUR"])

        # 4/5) 反馈
        if phase in ("prac1", "prac2", "calib"):
            self._fb_accuracy(phase, is_correct, fast, resp_key)
        else:  # prac4 / main：奖赏反馈 + 效能反馈，顺序伪随机
            # —— 判定本次是否“看表现”（1.2）——
            if phase == "prac4":
                eff_type = eff_type or self.rng.choice(["performance", "random"])
            # —— 计算奖赏（1.1 奖赏制 + 1.3 yoking）——
            if eff_type == "performance":
                got_reward = int(fast)
                self.reward_win.add(got_reward)
            else:
                got_reward = self.reward_win.sample(self.rng)
            if got_reward:
                self.total_reward += CFG["REWARD_AMOUNT"]

            if trial["feedback_order"] == "reward_first":
                self._fb_reward(got_reward)
                self._fb_efficacy(eff_type)
            else:
                self._fb_efficacy(eff_type)
                self._fb_reward(got_reward)

        # 记录
        row = dict(
            被试=self.subj, 组别=self.group, 阶段=phase, 试次=("" if idx is None else idx + 1),
            条件=trial["condition"], 词=trial["word"], 墨色=trial["ink"],
            正确键=correct_key, 反应键=resp_key, 正确=is_correct,
            反应时=("" if rt is None else round(rt, 4)),
            时限=("" if deadline is None else round(deadline, 4)),
            时限内=in_time,
            又对又快=fast,
            效能概率=("" if p_eff is None else round(float(p_eff), 4)),
            效能类型=("" if eff_type is None else eff_type),
            奖赏=("" if got_reward is None else got_reward),
            累计奖赏=round(self.total_reward, 2),
            反馈顺序=trial["feedback_order"],
        )
        self.log_trial(row)
        return row

    # ---- 反馈画面 ----
    def _fb_accuracy(self, phase, is_correct, fast, resp_key):
        if not resp_key:
            self.fb_main.text = "太慢"
            self.fb_main.setColor((0.9, 0.9, 0.9))
        elif is_correct:
            self.fb_main.text = "正确" + ("，太慢" if (phase == "calib" and not fast) else "")
            self.fb_main.setColor((0.5, 1.0, 0.5))
        else:
            self.fb_main.text = "错误"
            self.fb_main.setColor((1.0, 0.5, 0.5))
        self._draw_ring()
        self.fb_main.draw()
        self.win.flip()
        core.wait(CFG["FB_DUR"] if phase != "prac1" else 0.5)
        self.check_escape()

    def _build_efficacy_icons(self):
        """构建效能反馈的两个图标。

        按键图标做成“实体键帽”：深色侧壁 + 浅色顶面 + 标签，靠两层矩形叠出厚度，
        比单块浅灰方块更像一个可以按下去的键。想换成自己的图，把 CFG["BTN_ICON_IMG"]
        指向一张透明底 PNG 即可（建议 512×512 以上，主体居中）。
        """
        f = CFG["FONT"]
        # ---- 键帽（看表现）----
        img = CFG.get("BTN_ICON_IMG", "")
        self.btn_img = None
        if img and os.path.isfile(img):
            self.btn_img = visual.ImageStim(self.win, image=img, size=(0.14, 0.14), pos=(0, 0.01))
        else:
            self.btn_base = visual.Rect(self.win, width=0.170, height=0.064,
                                        fillColor=(0.30, 0.30, 0.30), lineColor=None,
                                        pos=(0, 0.000))
            self.btn_face = visual.Rect(self.win, width=0.164, height=0.048,
                                        fillColor=(0.90, 0.90, 0.90),
                                        lineColor=(0.62, 0.62, 0.62), lineWidth=1,
                                        pos=(0, 0.013))
            self.btn_txt = visual.TextStim(self.win, CFG.get("BTN_LABEL", ""), font=f,
                                           color=(-0.85, -0.85, -0.85), bold=True,
                                           height=0.026, pos=(0, 0.011))
        # ---- 骰子（随机）----
        self.dice_rect = visual.Rect(self.win, width=0.105, height=0.105,
                                     fillColor=(0.92, 0.92, 0.92), lineColor=(-1, -1, -1),
                                     lineWidth=2, pos=(0, 0.01))
        self.dice_dots = [
            visual.Circle(self.win, radius=0.0095, fillColor=(-1, -1, -1), lineColor=None,
                          pos=(0 + dx, 0.01 + dy))
            for dx, dy in ((-0.025, 0.025), (0.0, 0.0), (0.025, -0.025))
        ]

    def _draw_button_icon(self):
        if self.btn_img is not None:
            self.btn_img.draw()
            return
        self.btn_base.draw()   # 侧壁：向下偏移一点点，制造厚度
        self.btn_face.draw()   # 顶面
        if CFG.get("BTN_LABEL", ""):
            self.btn_txt.draw()

    def _draw_ring(self):
        """反馈阶段的底图：圆环必须一直在，所以这里无条件画。"""
        self.cue.draw()

    def _fb_reward(self, got_reward):
        if got_reward:
            self.fb_main.text = "+ $%.2f" % CFG["REWARD_AMOUNT"]
            self.fb_main.setColor((0.5, 1.0, 0.5))
        else:
            self.fb_main.text = "$ 0.00"
            self.fb_main.setColor((0.8, 0.8, 0.8))
        self._draw_ring()
        self.fb_main.draw()
        if CFG["SHOW_TOTAL_REWARD"]:
            self.fb_sub.text = "累计 $%.2f" % self.total_reward
            self.fb_sub.draw()
        self.win.flip()
        core.wait(CFG["FB_DUR"])
        self.check_escape()

    def _fb_efficacy(self, eff_type):
        self._draw_ring()
        if eff_type == "performance":
            self._draw_button_icon()
        else:
            self.dice_rect.draw()
            for d in self.dice_dots:
                d.draw()
        self.win.flip()
        core.wait(CFG["FB_DUR"])
        self.check_escape()

    # ------------------------------------------------------------------ 主观探针
    def run_probe(self, kind, after_trial):
        if kind == "efficacy":
            q = "你认为你当前的奖赏在多大程度上取决于你的表现？"
            lab_l, lab_r = "完全不由表现决定", "完全由表现决定"
        else:
            q = "你认为你当前获得奖赏的频率有多高？"
            lab_l, lab_r = "从不", "总是"

        self.probe_q.text = q
        self.probe_lab_l.text = lab_l
        self.probe_lab_r.text = lab_r
        self.win.setMouseVisible(True)
        mouse = MouseClass(win=self.win)
        x_lo, x_hi = -0.30, 0.30
        x = 0.0
        moved = False
        t0 = core.getTime()

        while True:
            self.check_escape()
            if mouse_left_pressed(mouse):
                mx, my = mouse.getPos()
                if abs(my - (-0.04)) < 0.14:      # 只在量表条附近才算有效拖动
                    nx = min(max(mx, x_lo), x_hi)
                    if abs(nx - x) > 1e-4:
                        moved = True
                    x = nx
            keys = event.getKeys(keyList=["space", "escape", "left", "right"])
            if "left" in keys:                 # 键盘兜底：鼠标失灵也能作答
                x = max(x_lo, x - 0.02)
                moved = True
            if "right" in keys:
                x = min(x_hi, x + 0.02)
                moved = True
            if "escape" in keys:
                self.abort()
            if "space" in keys and moved:
                break

            self.probe_q.draw()
            self.probe_line.draw()
            self.probe_lab_l.draw()
            self.probe_lab_r.draw()
            self.probe_hint.draw()
            self.probe_mark.pos = (x, -0.04)
            self.probe_mark.draw()
            if CFG["SHOW_VAS_NUMBER"]:
                self.probe_num.text = "%d" % round((x - x_lo) / (x_hi - x_lo) * 100)
                self.probe_num.draw()
            self.win.flip()

        value = (x - x_lo) / (x_hi - x_lo) * 100.0
        self.win.setMouseVisible(False)
        core.wait(0.2)
        self.log_probe(dict(
            被试=self.subj, 组别=self.group, 探针类型=kind,
            插入位置=("" if after_trial is None else after_trial + 1),
            评价值=round(value, 2), 用时s=round(core.getTime() - t0, 3),
            累计奖赏=round(self.total_reward, 2),
        ))

    # ------------------------------------------------------------------ 练习1
    def practice_mapping(self):
        self.wait_space(
            "练习 1 / 4：颜色—按键\n\n"
            "屏幕中央会出现一个色块，请判断它的颜色，并按下对应按键：\n\n"
            "        红色 → D      绿色 → F      蓝色 → J      黄色 → K\n\n"
            "（左手食指/中指按 D/F，右手食指/中指按 J/K）\n\n"
            "又快又准地反应。按 空格 开始。", height=0.038)
        colors = list(CFG["KEYS"].keys())
        for i in range(CFG["N_PRAC1"]):
            ink = self.rng.choice(colors)
            jitter = self.rng.uniform(0.4, 0.7)
            if CFG.get("FIX_ON_BLACK", False):
                self.fix.draw()
                self.win.flip()
                core.wait(jitter)
                self.cue.draw()
                if CFG.get("FIX_ON_CUE", True):
                    self.fix.draw()
                self.win.flip()
                core.wait(CFG["CUE_DUR"])
            else:
                self.cue.draw()
                self.fix.draw()
                self.win.flip()
                core.wait(jitter + CFG["CUE_DUR"])
            self.square.setLineColor(CFG["COLOR_RGB"][ink])
            self.square.setFillColor(CFG["COLOR_RGB"][ink])
            self.square.setLineWidth(1)
            self.kb_clock.reset()
            event.clearEvents()
            self.cue.draw()
            self.square.draw()
            self.win.flip()
            k = event.waitKeys(maxWait=2.0, keyList=self.keys + ["escape"],
                               timeStamped=self.kb_clock)
            if k and k[0][0] == "escape":
                self.abort()
            resp_key = k[0][0] if k else ""
            rt = float(k[0][1]) if k else None
            ok = int(resp_key == CFG["KEYS"][ink])
            if CFG["ISI_DUR"] > 0:
                self.cue.draw()
                self.win.flip()
                core.wait(CFG["ISI_DUR"])
            self.fb_main.text = "正确" if ok else ("太慢" if not resp_key else "错误")
            self.fb_main.setColor((0.5, 1.0, 0.5) if ok else (1.0, 0.5, 0.5))
            self.cue.draw()
            self.fb_main.draw()
            self.win.flip()
            core.wait(0.5)
            self.log_trial(dict(
                被试=self.subj, 组别=self.group, 阶段="prac1", 试次=i + 1,
                条件="mapping", 词="色块", 墨色=ink, 正确键=CFG["KEYS"][ink],
                反应键=resp_key, 正确=ok, 反应时=("" if rt is None else round(rt, 4)),
                时限="", 时限内="", 又对又快="", 效能概率="", 效能类型="", 奖赏="",
                累计奖赏=round(self.total_reward, 2), 反馈顺序="",
            ))
            self.check_escape()

    # ------------------------------------------------------------------ 练习2
    def practice_stroop(self):
        self.wait_space(
            "练习 2 / 4：判断字的“墨水颜色”\n\n"
            "接下来屏幕中央会出现一个颜色词（如“红”）。\n"
            "注意：请判断这个字是用什么颜色的墨水写的，而不是字本身的意思。\n\n"
            "例如：用绿色写的“红” → 按 F（绿）\n\n"
            "按 空格 开始。", height=0.038)
        colors = list(CFG["KEYS"].keys())
        for i in range(CFG["N_PRAC2"]):
            cond = self.rng.choice(["congruent", "incongruent", "neutral"])
            ink = self.rng.choice(colors)
            if cond == "congruent":
                w = CFG["WORD"][ink]
            elif cond == "incongruent":
                w = CFG["WORD"][self.rng.choice([c for c in colors if c != ink])]
            else:
                w = self.rng.choice(CFG["NEUTRAL_WORDS"])
            trial = dict(condition=cond, word=w, ink=ink, feedback_order="")
            self.run_trial(trial, phase="prac2", idx=i)

    # ------------------------------------------------------------------ 校准
    def calibrate(self):
        self.wait_space(
            "练习 3 / 4：反应速度校准\n\n"
            "这一阶段会调整你的“反应时限”。\n"
            "只有**又快又准**（在时限内按对）才能拿到奖赏，所以请尽量快、同时保持准确。\n\n"
            "试次较多，请保持专注。按 空格 开始。", height=0.038)
        colors = list(CFG["KEYS"].keys())
        deadline = CFG["CAL_START"]
        block = []
        applied = []
        for i in range(CFG["CAL_TRIALS"]):
            cond = self.rng.choice(["congruent", "incongruent", "neutral"])
            ink = self.rng.choice(colors)
            if cond == "congruent":
                w = CFG["WORD"][ink]
            elif cond == "incongruent":
                w = CFG["WORD"][self.rng.choice([c for c in colors if c != ink])]
            else:
                w = self.rng.choice(CFG["NEUTRAL_WORDS"])
            trial = dict(condition=cond, word=w, ink=ink, feedback_order="")
            applied.append(deadline)
            row = self.run_trial(trial, phase="calib", deadline=deadline, idx=i)
            block.append(int(row["又对又快"] or 0))
            if len(block) >= CFG["CAL_BLOCK"]:
                p_fast = sum(block) / float(len(block))
                deadline = next_deadline(p_fast, deadline)
                block = []
        tail = applied[-CFG["CAL_FINAL_LAST"]:]
        self.deadline = float(statistics.median(tail))
        self.wait_space(
            "校准完成。\n\n在接下来的正式任务中，反应时限固定为 %.0f 毫秒，不再改变。\n"
            "按 空格 继续。" % (self.deadline * 1000), height=0.042)

    # ------------------------------------------------------------------ 练习4
    def practice_feedback(self):
        self.wait_space(
            "练习 4 / 4：认识两种反馈\n\n"
            "正式任务中，每个试次结束后会依次出现两条反馈，顺序随机：\n\n"
            "① 奖赏反馈：显示你这一次得到多少美元（$0.50 或 $0.00）。\n\n"
            "② 结果来源反馈：\n"
            "   · 出现【按键】图标 → 这一次的结果取决于你的表现（又快又准才拿钱）；\n"
            "   · 出现【骰子】图标 → 这一次的结果是随机决定的，与你的表现无关。\n\n"
            "两种图标出现的比例会随时间变化，请注意观察并记住你的感受。\n\n"
            "按 空格 开始练习。", height=0.036)
        for i in range(CFG["N_PRAC4"]):
            cond = self.rng.choice(["congruent", "incongruent", "neutral"])
            ink = self.rng.choice(list(CFG["KEYS"].keys()))
            if cond == "congruent":
                w = CFG["WORD"][ink]
            elif cond == "incongruent":
                w = CFG["WORD"][self.rng.choice([c for c in CFG["KEYS"] if c != ink])]
            else:
                w = self.rng.choice(CFG["NEUTRAL_WORDS"])
            trial = dict(condition=cond, word=w, ink=ink,
                         feedback_order=self.rng.choice(["reward_first", "efficacy_first"]))
            self.run_trial(trial, phase="prac4", deadline=self.deadline, idx=i)

    # ------------------------------------------------------------------ 休息
    def show_break(self, done, total):
        self.wait_space(
            "休息一下\n\n已完成 %d / %d 个试次\n累计奖赏：$%.2f\n\n"
            "准备好后按 空格 继续。" % (done, total, self.total_reward), height=0.042)

    # ------------------------------------------------------------------ 正式任务
    def run_main(self):
        if CFG.get("SKIP_PRACTICE", False):
            rules = ("任务内容：屏幕中央会出现一个词，请判断**字的墨水颜色**（不是字义），按 D F J K。\n"
                     "        红色 → D    绿色 → F    蓝色 → J    黄色 → K\n\n")
        else:
            rules = "规则与刚才相同：判断字的墨水颜色，按 D F J K。\n"
        self.wait_space(
            "正式任务开始\n\n" + rules +
            "又快又准才能获得奖赏。\n\n"
            "任务中会不时弹出滑块问题，请根据你**当下**的感受作答。\n\n"
            "共 %d 个试次，约 40 分钟，中途可以休息。\n按 空格 开始。"
            % (CFG["N_CONGRUENT"] + CFG["N_INCONGRUENT"] + CFG["N_NEUTRAL"]),
            height=0.038)

        trials = make_main_trial_list(self.rng)
        n = len(trials)
        p_traj = make_trajectory(n, CFG["P_MIN"], CFG["P_MAX"], self.traj_seed,
                                 reverse=self.reverse, smooth_frac=CFG["TRAJ_SMOOTH"])
        probes = make_probe_schedule(n, CFG["PROBE_EVERY"], self.rng)

        for i, t in enumerate(trials):
            if CFG["BREAK_EVERY"] and i > 0 and i % CFG["BREAK_EVERY"] == 0:
                self.show_break(i, n)
            p = float(p_traj[i])
            eff_type = "performance" if self.rng.random() < p else "random"
            self.run_trial(t, phase="main", deadline=self.deadline, eff_type=eff_type,
                           p_eff=p, idx=i)
            if i in probes:
                self.run_probe(probes[i], after_trial=i)
            if i % 10 == 0:                      # 每 10 试次落盘一次，防中途崩溃丢数据
                self.save()

        self.wait_space(
            "实验结束，谢谢参与！\n\n总奖赏：$%.2f\n\n按 空格 退出。" % self.total_reward,
            height=0.045)

    # ------------------------------------------------------------------ 主流程
    def run(self):
        # 开跑前：确认被试信息，按 R 可回到对话框重填
        while not self.confirm_info():
            self.update_info(ask_info(prev=self.info))
        if CFG.get("SKIP_PRACTICE", False):
            # 跳过练习与校准：直接套用固定时限，只跑 288 个正式试次
            self.deadline = float(CFG["DEADLINE_WHEN_SKIPPED"])
        else:
            self.practice_mapping()
            self.practice_stroop()
            self.calibrate()
            self.practice_feedback()
        self.run_main()
        self.save(verbose=True)
        self.win.close()
        core.quit()


# ==============================================================================
#  四、入口
# ==============================================================================
def auto_subject_id():
    """编号留空时自动生成，例如 S11211930。"""
    return "S" + datetime.now().strftime("%m%d%H%M")


def ask_info(prev=None):
    """实验前的被试信息登记表（Qt 对话框，支持中文输入法直接打姓名）。

    返回 dict：姓名、被试编号、年龄、性别、漂移方向。
    编号留空会自动生成；“漂移方向”选“自动”时按编号末位奇偶分配
    （奇数→正向，偶数→反向），这样单双号被试自然对半，不用手工平衡。
    """
    prev = prev or {}
    dlg = gui.DlgFromDict(
        dictionary={
            "姓名": prev.get("姓名", ""),
            "被试编号": prev.get("被试编号", ""),
            "年龄": prev.get("年龄", ""),
            "性别": prev.get("性别", "女"),
            "漂移方向": ["自动（按编号奇偶）", "正向", "反向"],
        },
        title="实验1：Stroop + 漂移效能 —— 请填写被试信息",
        order=["姓名", "被试编号", "年龄", "性别", "漂移方向"],
    )
    if not dlg.OK:
        core.quit()
    info = dict(dlg.data)
    info["姓名"] = str(info.get("姓名", "")).strip() or "匿名"
    info["被试编号"] = str(info.get("被试编号", "")).strip() or auto_subject_id()
    info["年龄"] = str(info.get("年龄", "")).strip()
    return info


if __name__ == "__main__":
    info = ask_info()
    exp = StroopEfficacyExp(info)
    try:
        exp.run()
    except SystemExit:
        pass
    except BaseException:
        # 中途崩了也别丢数据：落盘 + 把 traceback 写进 error.log，方便事后定位
        import traceback
        tb = traceback.format_exc()
        print(tb)
        try:
            exp.save(verbose=True)
        except Exception:
            pass
        for folder in (getattr(exp, "outdir", None),
                       os.path.dirname(os.path.abspath(__file__))):
            if not folder:
                continue
            try:
                path = os.path.join(folder, "error.log")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(tb)
                print("错误已写入：", path)
                break
            except Exception:
                continue
        raise
