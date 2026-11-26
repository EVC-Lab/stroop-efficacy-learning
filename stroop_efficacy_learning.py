# -*- coding: utf-8 -*-
"""色词 Stroop 行为任务，结合研究一的刺激与研究二的区段流程。

用 PsychoPy Studio 的 Coder 运行本文件。流程及快跑设置见 README。
"""

import csv
import hashlib
import json
import math
import os
import random
import re
import statistics
import subprocess
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

from psychopy import visual, core, event, gui, logging
from psychopy.hardware.keyboard import Keyboard

try:  # 老接口优先：event.Mouse 方法齐全（getPressed / getPos），新版 PsychoPy 仍提供
    MouseClass = event.Mouse
except AttributeError:  # 极新版本若移除，再退回 hardware.mouse
    from psychopy.hardware import mouse as mouse_mod
    MouseClass = mouse_mod.Mouse



def mouse_left_pressed(mouse):
    """跨版本判断鼠标左键是否按下。

    PsychoPy 2024.x 的 psychopy.hardware.mouse.Mouse 已经删掉了 getPressed()，
    只剩 getLeftButtonPressed()；老版本则只有 getPressed()。直接写 getPressed()
    会在新版本上抛 AttributeError，把整个实验打断。
    """
    if hasattr(mouse, "getPressed"):
        try:
            return bool(mouse.getPressed()[0])
        except Exception:
            pass
    if hasattr(mouse, "getLeftButtonPressed"):
        return bool(mouse.getLeftButtonPressed())
    return False


def code_version():
    """记录启动时的 Git 版本和脚本摘要，离开仓库运行时仍可核对脚本。"""
    path = Path(__file__).resolve()
    try:
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unknown", ""

    def git(*args):
        return subprocess.check_output(
            ["git", *args], cwd=path.parent, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", timeout=2,
            env={**os.environ, "GIT_CONFIG_COUNT": "0"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()

    try:
        git("ls-files", "--error-unmatch", "--", path.name)
        commit = git("rev-parse", "HEAD")
        if git("status", "--porcelain", "--", path.name):
            commit += "-dirty"
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    return commit, source_hash


def stimulus_counts(rows):
    """按字色和字义统计 16 种正式刺激，保留未出现组合的零计数。"""
    counts = Counter((r["墨色"], r["词"]) for r in rows)
    return {
        ink: {word: counts[ink, word] for word in CFG["WORD"].values()}
        for ink in CFG["KEYS"]
    }


# ==============================================================================
#  颜色小工具
#  PsychoPy 默认色彩空间是 rgb，范围 -1…1，不是 0…255！
#  (0,0,0)→(-1,-1,-1) 纯黑    (128,128,128)→(0,0,0) 中灰    (255,255,255)→(1,1,1) 纯白
#  直接把 128 之类 0–255 的值填进去会被截断成 1.0，画出来是“纯白”。
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


# ==============================================================================
#  三、实验主流程
# ==============================================================================
class StroopEfficacyExp:
    def __init__(self, info):
        self.outdir = None
        self.update_info(info)
        self.code_commit, self.script_hash = code_version()

        self.rng = random.Random()
        self.traj_seed = CFG["TRAJ_SEED"]
        self.rng.seed("%s-%s" % (self.subj, self.group))   # 每个被试可复现

        self.keyboard = Keyboard(backend="ptb")
        if self.keyboard.getBackend() != "ptb":
            raise RuntimeError("需要 PsychoPy Studio 的 Psychtoolbox 键盘后端来记录按键时间。")

        core.checkPygletDuringWait = False
        self.win = visual.Window(
            size=(1280, 800), fullscr=CFG["FULLSCR"], color=CFG["BG_COLOR"],
            units="height", allowGUI=False, checkTiming=False, waitBlanking=True,
        )
        self.win.setMouseVisible(False)

        f = CFG["FONT"]
        self.fix = visual.TextStim(self.win, "+", font=f, color=(1, 1, 1), height=0.09)
        self.word = visual.TextStim(self.win, "", font=f, color=(1, 1, 1),
                                    height=CFG["WORD_HEIGHT"], bold=True)
        self.square = visual.Rect(self.win, width=0.16, height=0.16, lineColor=None)

        # ---- 区段反馈 ----
        self.fb_score = visual.TextStim(self.win, "", font=f, color=(1, 1, 1),
                                        height=0.095, pos=(0, 0.115))
        self.fb_total = visual.TextStim(self.win, "", font=f, color=(0.75, 0.75, 0.75),
                                        height=0.034, pos=(0, 0.275))
        self.fb_source = visual.TextStim(self.win, "", font=f, color=(0.85, 0.85, 0.85),
                                         height=0.040, pos=(0, -0.075))

        # ---- 练习用的正误反馈 ----
        self.fb_acc = visual.TextStim(self.win, "", font=f, color=(1, 1, 1), height=0.075)

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
        self.response_keys = [*CFG["KEYS"].values(), "escape"]
        self.yoke = YokeWindow()
        self.total_score = 0.0
        self.rows_trials = []
        self.rows_intervals = []
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

    def save(self, verbose=False):
        if self.outdir is None:
            self.outdir = self._make_outdir()
        for fname, rows in (("trials.csv", self.rows_trials),
                            ("intervals.csv", self.rows_intervals),
                            ("probes.csv", self.rows_probes)):
            if not rows:
                continue
            path = os.path.join(self.outdir, fname)
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)

        main_rows = [r for r in self.rows_intervals if r["阶段"] == "main"]
        scores = [float(r["区段得分"]) for r in main_rows]
        main_trials = [r for r in self.rows_trials if r["阶段"] == "main"]
        meta = dict(
            姓名=self.name, 被试编号=self.subj, 年龄=self.info.get("年龄", ""),
            性别=self.info.get("性别", ""), 漂移方向=self.group,
            区段数=len(main_rows), 总分=round(self.total_score, 1),
            平均每区段得分=(round(statistics.mean(scores), 2) if scores else ""),
            平均每区段试次数=(round(statistics.mean([int(r["试次数"]) for r in main_rows]), 2)
                              if main_rows else ""),
            yoking窗口均值=round(self.yoke.mean(), 2),
            轨迹种子=self.traj_seed, 效能下限=CFG["P_MIN"], 效能上限=CFG["P_MAX"],
            每对一次得分=CFG["POINT_PER_CORRECT"], 窗口长度选项=list(CFG["WINDOW_CHOICES"]),
            正式刺激呈现计数=stimulus_counts(main_trials),
            正式刺激作答计数=stimulus_counts(r for r in main_trials if r["反应键"]),
            版本="stroop-efficacy-dev", 代码版本=self.code_commit,
            脚本SHA256=self.script_hash, 运行参数=CFG,
            定时键盘后端=self.keyboard.getBackend(),
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

    @staticmethod
    def _wait_until(timestamp):
        core.wait(max(0.0, timestamp - logging.defaultClock.getTime()))

    def _clear_response_buffer(self):
        if self.keyboard.getKeys(keyList=["escape"], waitRelease=False):
            self.abort()
        self.keyboard.clearEvents()

    def _wait_for_response(self, onset, deadline):
        """翻屏和 PTB 按下时刻共用 PsychoPy 的日志时钟。"""
        while True:
            poll_time = logging.defaultClock.getTime()
            keys = self.keyboard.getKeys(keyList=self.response_keys, waitRelease=False)
            if any(press.name == "escape" for press in keys):
                self.abort()
            for press in sorted(keys, key=lambda key: key.tDown):
                if onset <= press.tDown < deadline:
                    return press.name, press.tDown
            if poll_time >= deadline:
                return "", None
            # 在截止后还会检查一次队列，按键的实际时刻决定是否有效。
            self._wait_until(min(poll_time + 0.001, deadline))

    # ------------------------------------------------------------------ 区段反馈
    def _fb_interval(self, score, eff_type, deadline, practice=False):
        """区段反馈（2.2）：本次得多少分 + 分数是否取决于表现，共 1500ms。"""
        if score > 0:
            self.fb_score.text = "+%d 分" % int(round(score))
            self.fb_score.setColor((0.5, 1.0, 0.5))
        else:
            self.fb_score.text = "+0 分"
            self.fb_score.setColor((0.8, 0.8, 0.8))
        self.fb_score.draw()

        if eff_type == "performance":
            self.fb_source.text = "本段得分取决于你的表现"
        else:
            self.fb_source.text = "本段得分由随机抽取得到"
        self.fb_source.draw()

        if CFG["SHOW_TOTAL_SCORE"] and not practice:
            self.fb_total.text = "累计 %d 分" % int(round(self.total_score))
            self.fb_total.draw()

        self._wait_until(deadline)
        onset = float(self.win.flip())
        self._wait_until(onset + CFG["FB_DUR"])
        offset = float(self.win.flip())
        return onset, offset

    # ------------------------------------------------------------------ 单试次
    def make_trial_content(self):
        """抽取字色、色词和一致性条件。"""
        ink = self.rng.choice(list(CFG["KEYS"]))
        if self.rng.random() < CFG["COND_RATIO"]:
            return ink, CFG["WORD"][ink], "congruent"
        other_colors = [color for color in CFG["KEYS"] if color != ink]
        word_color = self.rng.choice(other_colors)
        return ink, CFG["WORD"][word_color], "incongruent"

    def run_free_trial(self, sub_idx, interval_start, phase, interval_idx, window):
        """呈现一道色词题，接受作答直到区段结束。"""
        ink, word, cond = self.make_trial_content()
        self.word.text = word
        self.word.color = CFG["COLOR_RGB"][ink]

        self._clear_response_buffer()
        self.word.draw()
        onset = float(self.win.flip())
        start = onset if interval_start is None else interval_start
        deadline = start + window
        resp_key, pressed_at = self._wait_for_response(onset, deadline)
        rt = None if pressed_at is None else pressed_at - onset

        correct_key = CFG["KEYS"][ink]
        row = dict(
            被试=self.subj, 组别=self.group, 阶段=phase,
            区段=("" if interval_idx is None else interval_idx + 1),
            区段内序号=sub_idx, 窗口s=window,
            区段内开始时刻s=round(onset - start, 4),
            目标翻屏时刻s=onset, 作答截止时刻s=deadline,
            按键时刻s=("" if pressed_at is None else pressed_at),
            条件=cond, 词=word, 墨色=ink,
            正确键=correct_key, 反应键=resp_key, 正确=int(resp_key == correct_key),
            反应时=("" if rt is None else round(rt, 4)),
            过快=int(rt is not None and rt < 0.25),   # DDM 分析按原文剔除 RT<250ms
        )
        self.rows_trials.append(row)
        return row

    # ------------------------------------------------------------------ 区段
    def run_interval(self, idx, window, eff_type, p_eff=None, phase="main", practice_yoke=None):
        """跑一个区段：注视点 → 自由作答窗口 → 反馈（2.2）。"""
        self.fix.draw()
        fixation_on = float(self.win.flip())
        self._wait_until(fixation_on + self.rng.choice(CFG["FIX_CHOICES"]))

        interval_start = None
        n_done = 0
        n_correct = 0
        conds = []
        frame_period = self.win.monitorFramePeriod
        while True:
            row = self.run_free_trial(n_done + 1, interval_start, phase, idx, window)
            if interval_start is None:
                interval_start = row["目标翻屏时刻s"]
            deadline = row["作答截止时刻s"]
            n_done += 1
            n_correct += int(row["正确"])
            conds.append(row["条件"])
            if not row["反应键"]:
                break
            # 离截止不足一次刷新时，由反馈直接替换当前刺激。
            if logging.defaultClock.getTime() + frame_period >= deadline:
                break
            blank_on = float(self.win.flip())
            next_on = blank_on + CFG["ISI_BETWEEN"]
            # 为下一次刷新预留一帧。尾部留空仍使用同一个区段截止时刻。
            if next_on + frame_period + CFG["MIN_TRIAL_TIME"] >= deadline:
                break
            self._wait_until(next_on)
            if logging.defaultClock.getTime() + frame_period + CFG["MIN_TRIAL_TIME"] >= deadline:
                break

        # 3) 计分（2.2）：表现区段 = 真实得分；随机区段 = 从 yoking 窗口抽
        practice = practice_yoke is not None
        history = practice_yoke if practice else self.yoke
        if eff_type == "performance":
            score = float(n_correct * CFG["POINT_PER_CORRECT"])
            history.add(score)
            source = "表现"
        else:
            score = history.sample(self.rng)
            source = "抽取"
        if not practice:
            self.total_score += score
        feedback_on, feedback_off = self._fb_interval(score, eff_type, deadline, practice=practice)

        n_cong = sum(1 for c in conds if c == "congruent")
        row = dict(
            被试=self.subj, 组别=self.group, 阶段=phase,
            区段=("" if idx is None else idx + 1),
            窗口s=window, 实际用时s=round(feedback_on - interval_start, 4),
            注视翻屏时刻s=fixation_on, 区段开始时刻s=interval_start, 区段截止时刻s=deadline,
            反馈翻屏时刻s=feedback_on, 反馈结束时刻s=feedback_off,
            试次数=n_done, 正确数=n_correct,
            正确率=(round(n_correct / float(n_done), 3) if n_done else ""),
            一致比例=(round(n_cong / float(n_done), 3) if n_done else ""),
            效能概率=("" if p_eff is None else round(float(p_eff), 4)),
            效能类型=eff_type,
            得分来源=source, 区段得分=round(score, 2),
            累计得分=round(self.total_score, 2),
        )
        self.rows_intervals.append(row)
        self.check_escape()
        return row

    # ------------------------------------------------------------------ 主观探针
    def run_probe(self, kind, after_interval):
        if kind == "efficacy":
            q = "你认为你当前的得分在多大程度上取决于你的表现？"
            lab_l, lab_r = "完全不由表现决定", "完全由表现决定"
        else:
            q = "你认为你当前获得的分数有多高？"
            lab_l, lab_r = "很低", "很高"

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
            if "left" in keys:                    # 键盘兜底：鼠标失灵也能作答
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
        self.rows_probes.append(dict(
            被试=self.subj, 组别=self.group, 探针类型=kind,
            插入位置=("" if after_interval is None else after_interval + 1),
            评价值=round(value, 2), 用时s=round(core.getTime() - t0, 3),
            累计得分=round(self.total_score, 2),
        ))

    # ------------------------------------------------------------------ 练习
    def _practice_trial(self, ink, word, timeout=None, with_fb=True, phase="prac"):
        """练习用的单试次：注视点 → 色块或色词 → 正误反馈。"""
        timeout = CFG["PRAC_TIMEOUT"] if timeout is None else timeout
        self.fix.draw()
        self.win.flip()
        core.wait(self.rng.uniform(0.4, 0.7))

        self._clear_response_buffer()
        if word:
            self.word.text = word
            self.word.color = CFG["COLOR_RGB"][ink]
            self.word.draw()
        else:
            self.square.fillColor = CFG["COLOR_RGB"][ink]
            self.square.draw()
        onset = float(self.win.flip())
        deadline = onset + timeout
        resp_key, pressed_at = self._wait_for_response(onset, deadline)
        rt = None if pressed_at is None else pressed_at - onset
        ok = int(resp_key == CFG["KEYS"][ink])

        if with_fb:
            if not resp_key:
                self.fb_acc.text = "太慢"
                self.fb_acc.setColor((0.9, 0.9, 0.9))
            elif ok:
                self.fb_acc.text = "正确"
                self.fb_acc.setColor((0.5, 1.0, 0.5))
            else:
                self.fb_acc.text = "错误"
                self.fb_acc.setColor((1.0, 0.5, 0.5))
            self.fb_acc.draw()
            self.win.flip()
            core.wait(0.6)
            self.check_escape()

        self.rows_trials.append(dict(
            被试=self.subj, 组别=self.group, 阶段=phase,
            区段="", 区段内序号="", 窗口s=timeout, 区段内开始时刻s="",
            目标翻屏时刻s=onset, 作答截止时刻s=deadline,
            按键时刻s=("" if pressed_at is None else pressed_at),
            条件=("mapping" if not word else ("congruent" if word == CFG["WORD"][ink]
                                             else "incongruent")),
            词=word or "色块", 墨色=ink,
            正确键=CFG["KEYS"][ink], 反应键=resp_key, 正确=ok,
            反应时=("" if rt is None else round(rt, 4)),
            过快=int(rt is not None and rt < 0.25),
        ))
        return ok

    def practice_mapping(self):
        self.wait_space(
            "练习 1 / 3：颜色与按键\n\n"
            "屏幕中央会出现一个色块，请判断它的颜色并按下对应按键。\n\n"
            "红色 → D    绿色 → F    蓝色 → J    黄色 → K\n\n"
            "按空格开始。", height=0.038)
        seq = []
        while len(seq) < CFG["N_PRAC1"]:
            seq += list(CFG["KEYS"])
        seq = seq[:CFG["N_PRAC1"]]
        self.rng.shuffle(seq)
        for ink in seq:
            self._practice_trial(ink, "", phase="prac1")

    def practice_color_word(self):
        self.wait_space(
            "练习 2 / 3：判断字色\n\n"
            "屏幕中央会出现一个表示颜色的字。请按字的颜色选键，忽略字义。\n\n"
            "例如，用绿色写的“红”应该按 F。\n\n"
            "按空格开始。", height=0.038)
        for _ in range(CFG["N_PRAC2"]):
            ink, word, _ = self.make_trial_content()
            self._practice_trial(ink, word, phase="prac2")

    def practice_free_window(self):
        self.wait_space(
            "练习 3 / 3：在一个区段内连续作答\n\n"
            "每段给你一段固定的作答时间。每答完一题，就可以继续做下一题。\n"
            "时间结束后会显示得分和来源。按表现计分时，每答对一题得 %d 分；"
            "随机计分时，这一段答对多少题不会改变它的得分。\n\n"
            "按空格开始。" % CFG["POINT_PER_CORRECT"], height=0.036)
        history = YokeWindow(init=[])
        for i in range(CFG["N_PRAC3"]):
            eff_type = "performance" if i % 2 == 0 else "random"
            self.run_interval(None, CFG["PRAC_WINDOW"], eff_type, phase="prac3",
                              practice_yoke=history)

    # ------------------------------------------------------------------ 休息
    def show_break(self, done, total):
        self.wait_space(
            "休息一下\n\n已完成 %d / %d 个区段\n累计得分：%d 分\n\n"
            "准备好后按 空格 继续。" % (done, total, int(round(self.total_score))),
            height=0.042)

    # ------------------------------------------------------------------ 正式任务
    def run_main(self):
        self.wait_space(
            "正式任务开始\n\n"
            "请按字的颜色选键，忽略字义。红 → D，绿 → F，蓝 → J，黄 → K。\n"
            "请在每段给定的时间内连续作答，区段结束时会显示得分和来源。\n\n"
            "有的区段按表现计分，每答对一题得 %d 分；有的区段由系统随机给分。\n"
            "作答时请兼顾速度和准确性。任务中会偶尔出现滑块问题，请按当下的判断作答。\n\n"
            "共 %d 个区段。按空格开始。"
            % (CFG["POINT_PER_CORRECT"], CFG["N_INTERVALS"]), height=0.036)

        n = CFG["N_INTERVALS"]
        p_traj = make_trajectory(n, CFG["P_MIN"], CFG["P_MAX"], self.traj_seed,
                                 reverse=self.reverse, smooth_frac=CFG["TRAJ_SMOOTH"])
        windows = make_score_schedule(n, self.rng)
        probes = make_probe_schedule(n, CFG["PROBE_EVERY"], self.rng)

        for i in range(n):
            if CFG["BREAK_EVERY"] and i > 0 and i % CFG["BREAK_EVERY"] == 0:
                self.show_break(i, n)
            p = float(p_traj[i])
            eff_type = "performance" if self.rng.random() < p else "random"
            self.run_interval(i, windows[i], eff_type=eff_type, p_eff=p, phase="main")
            if i in probes:
                self.run_probe(probes[i], after_interval=i)
            if i % 10 == 0:                    # 每 10 区段落盘一次，防崩溃丢数据
                self.save()

        self.wait_space(
            "实验结束，谢谢参与！\n\n总得分：%d 分\n\n按 空格 退出。"
            % int(round(self.total_score)), height=0.045)

    # ------------------------------------------------------------------ 主流程
    def run(self):
        while not self.confirm_info():
            self.update_info(ask_info(prev=self.info))
        if not CFG.get("SKIP_PRACTICE", False):
            self.practice_mapping()
            self.practice_color_word()
            self.practice_free_window()
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

    “漂移方向”选“自动”时按编号末位奇偶分配（奇数→正向，偶数→反向），
    这样单双号被试自然对半，不用手工平衡。
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
        title="色词 Stroop 行为任务 · 被试信息",
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
        # 中途崩了也别丢数据：落盘 + 把 traceback 写进 error.log
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
