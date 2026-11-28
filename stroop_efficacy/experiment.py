"""色词 Stroop 的被试界面、作答、计分和区段流程。"""

import random
import statistics
from contextlib import ExitStack
from datetime import datetime
from math import isfinite
from pathlib import Path
from uuid import uuid4

from psychopy import visual, core, event
from psychopy import logging as psylog

from .archive import MODES, participant_code, performance_first
from .design import CFG, YokeWindow, make_main_schedule, run_settings
from .session_data import (
    EXPORT_VERSION,
    code_version,
    parameter_hash,
    stimulus_counts,
    trial_response_fields,
    write_snapshot,
)
from .timing import TimedInput, open_timed_keyboard, resolve_frame_timing

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


class StroopEfficacyExp:
    def __init__(
        self, info, keyboard=None, *, entrypoint, mode=None, archive_root=None
    ):
        self.outdir = None
        self.session_id = uuid4().hex
        self.mode = (
            mode if mode is not None else ("quick" if CFG["DEBUG_FAST"] else "pilot")
        )
        if self.mode not in MODES:
            raise ValueError("无法识别运行模式。")
        self.settings = (
            CFG if mode is None and self.mode == "pilot" else run_settings(self.mode)
        )
        entrypoint = Path(entrypoint).resolve()
        self.archive_root = (
            Path(archive_root)
            if archive_root is not None
            else entrypoint.parent / "data"
        )
        self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.finished_at = ""
        self.session_status = "running"
        self.update_info(info)
        self.code_commit, self.script_hash, self.module_hashes = code_version(
            entrypoint
        )

        # 初始化失败时，关闭已接管的资源。成功后由场次启动方正常收尾。
        with ExitStack() as cleanup:
            if keyboard is None:
                keyboard = open_timed_keyboard()
                cleanup.callback(keyboard.stop)
            self.timed_input = TimedInput(keyboard)
            self.win = visual.Window(
                size=(1280, 800),
                fullscr=self.settings["FULLSCR"],
                color=self.settings["BG_COLOR"],
                units="height",
                allowGUI=False,
                checkTiming=False,
                waitBlanking=True,
            )
            cleanup.callback(self.win.close)
            self._initialize_window()

            self.response_keys = [*self.settings["KEYS"].values(), "escape"]
            self.yoke = YokeWindow(
                self.settings["YOKE_WINDOW"], self.settings["YOKE_INIT_SCORES"]
            )
            self.total_score = 0.0
            self.rows_trials = []
            self.rows_intervals = []
            self.rows_probes = []
            cleanup.pop_all()

    def _initialize_window(self):
        self.win.setMouseVisible(False)
        f = self.settings["FONT"]
        # PsychoPy 的内置测量提示使用默认字体，这里用任务字体绘制中文提示。
        splash = visual.TextStim(
            self.win,
            "正在测量显示器刷新率，请稍候",
            font=f,
            color=(1, 1, 1),
            height=0.04,
            autoDraw=True,
            autoLog=False,
        )
        try:
            measured_hz = self.win.getActualFrameRate(infoMsg="")
        finally:
            splash.autoDraw = False
        self.refresh_hz, self.frame_period = resolve_frame_timing(
            measured_hz, self.win.monitorFramePeriod
        )
        self.timed_input.keyboard.start()

        self.fix = visual.TextStim(self.win, "+", font=f, color=(1, 1, 1), height=0.09)
        self.word = visual.TextStim(
            self.win,
            "",
            font=f,
            color=(1, 1, 1),
            height=self.settings["WORD_HEIGHT"],
            bold=True,
        )
        self.square = visual.Rect(self.win, width=0.16, height=0.16, lineColor=None)

        # ---- 区段反馈 ----
        self.fb_score = visual.TextStim(
            self.win, "", font=f, color=(1, 1, 1), height=0.095, pos=(0, 0.115)
        )
        self.fb_total = visual.TextStim(
            self.win, "", font=f, color=(0.75, 0.75, 0.75), height=0.034, pos=(0, 0.275)
        )
        self.fb_source = visual.TextStim(
            self.win,
            "",
            font=f,
            color=(0.85, 0.85, 0.85),
            height=0.040,
            pos=(0, -0.075),
        )

        # ---- 练习用的正误反馈 ----
        self.fb_acc = visual.TextStim(
            self.win, "", font=f, color=(1, 1, 1), height=0.075
        )

        # ---- 主观探针（0–100 VAS）----
        self.probe_q = visual.TextStim(
            self.win,
            "",
            font=f,
            color=(1, 1, 1),
            height=0.048,
            wrapWidth=0.95,
            pos=(0, 0.26),
        )
        self.probe_line = visual.Line(
            self.win,
            start=(-0.32, -0.04),
            end=(0.32, -0.04),
            lineColor=(1, 1, 1),
            lineWidth=4,
        )
        self.probe_lab_l = visual.TextStim(
            self.win,
            "",
            font=f,
            color=(0.85, 0.85, 0.85),
            height=0.034,
            pos=(-0.32, -0.14),
        )
        self.probe_lab_r = visual.TextStim(
            self.win,
            "",
            font=f,
            color=(0.85, 0.85, 0.85),
            height=0.034,
            pos=(0.32, -0.14),
        )
        self.probe_mark = visual.Circle(
            self.win, radius=0.016, fillColor=(1, 1, 1), lineColor=None, pos=(0, -0.04)
        )
        self.probe_hint = visual.TextStim(
            self.win,
            "拖动滑块（或按 ← → 键）到你的答案位置，然后按 空格 确认",
            font=f,
            color=(0.8, 0.8, 0.8),
            height=0.032,
            pos=(0, -0.30),
        )
        self.probe_num = visual.TextStim(
            self.win, "", font=f, color=(1, 1, 1), height=0.04, pos=(0, 0.10)
        )

    # -------------------------------------------------------------- 被试信息
    def update_info(self, info):
        """更新登记信息和依参与者编号固定的随机数流。"""
        self.subj = participant_code(info.get("被试编号", ""))
        direction = str(info.get("漂移方向", "自动")).strip()
        self.assignment = "auto" if direction.startswith("自动") else "manual"
        first = performance_first(self.subj, direction)
        self.group = "反向" if first else "正向"
        seed = f"{self.subj}-{self.group}"
        self.rng = random.Random(seed)
        self.score_rng = random.Random(f"{seed}:score")
        self.main_schedule = make_main_schedule(
            first, random.Random(f"{seed}:probes"), self.settings
        )

    # ------------------------------------------------------------------ 输出
    def _make_outdir(self):
        directory = self.archive_root / self.mode / self.subj / self.session_id
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def save(self, verbose=False):
        if self.outdir is None:
            self.outdir = self._make_outdir()
        trials = self.rows_trials
        orphan_trials = []
        if self.session_status == "error":
            saved_intervals = {
                (row["阶段"], row["区段"]) for row in self.rows_intervals
            }
            trials = []
            for row in self.rows_trials:
                key = row["阶段"], row["区段"]
                if row["阶段"] in {"main", "prac3"} and key not in saved_intervals:
                    orphan_trials.append(row)
                else:
                    trials.append(row)
        main_rows = [r for r in self.rows_intervals if r["阶段"] == "main"]
        scored_rows = [r for r in main_rows if r["区段得分"] != ""]
        scores = [r["区段得分"] for r in scored_rows]
        main_trials = [r for r in self.rows_trials if r["阶段"] == "main"]
        inks = tuple(self.settings["KEYS"])
        words = tuple(self.settings["WORD"].values())
        meta = dict(
            会话编号=self.session_id,
            导出版本=EXPORT_VERSION,
            RT单位="s",
            参数SHA256=parameter_hash(self.settings),
            被试编号=self.subj,
            运行模式=self.mode,
            会话状态=self.session_status,
            会话开始时间=self.started_at,
            会话结束时间=self.finished_at,
            序列分配方式=self.assignment,
            漂移方向=self.group,
            区段数=len(scored_rows),
            中断区段数=sum(bool(r["中断阶段"]) for r in main_rows),
            完整区段数=sum(r["区段状态"] == "completed" for r in main_rows),
            总分=round(
                sum(scores) if self.session_status == "error" else self.total_score, 1
            ),
            平均每区段得分=(round(statistics.mean(scores), 2) if scores else ""),
            平均每区段试次数=(
                round(statistics.mean([r["试次数"] for r in scored_rows]), 2)
                if scored_rows
                else ""
            ),
            yoking窗口均值=round(self.yoke.mean(), 2),
            正式调度=self.main_schedule.metadata(),
            每对一次得分=self.settings["POINT_PER_CORRECT"],
            窗口长度选项=list(self.settings["WINDOW_CHOICES"]),
            正式刺激呈现计数=stimulus_counts(main_trials, inks, words),
            正式刺激作答计数=stimulus_counts(
                (r for r in main_trials if r["反应键"]), inks, words
            ),
            版本="stroop-efficacy-dev",
            代码版本=self.code_commit,
            脚本SHA256=self.script_hash,
            模块SHA256=self.module_hashes,
            运行参数=self.settings,
            定时键盘后端=self.timed_input.keyboard.getBackend(),
            实测刷新率Hz=self.refresh_hz,
            出题估计帧长s=self.frame_period,
        )
        if orphan_trials:
            meta["异常未关联试次"] = orphan_trials
        tables = (
            ("intervals.csv", self.rows_intervals),
            ("trials.csv", trials),
            ("probes.csv", self.rows_probes),
        )
        write_snapshot(self.outdir, tables, meta)
        if verbose:
            print("\n数据已保存到：", self.outdir)

    # ------------------------------------------------------------------ 通用界面
    def wait_space(self, text, height=0.042, color=(1, 1, 1)):
        stim = visual.TextStim(
            self.win,
            text,
            font=self.settings["FONT"],
            color=color,
            height=height,
            wrapWidth=1.1,
            alignText="center",
        )
        self._clear_response_buffer()
        stim.draw()
        onset = float(self.win.flip())
        if self.timed_input.wait_for_ui_key(onset, ["space"]) == "escape":
            self.abort()

    def abort(self):
        if self.session_status == "running":
            self.finish("interrupted")
        core.quit()

    def finish(self, status):
        previous = self.session_status, self.finished_at
        self.session_status = status
        self.finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            self.save(verbose=True)
        except (Exception, KeyboardInterrupt):
            self.session_status, self.finished_at = previous
            raise

    def check_escape(self):
        if self.timed_input.poll_keys(["escape"]):
            self.abort()

    def _clear_response_buffer(self):
        self.check_escape()
        self.timed_input.keyboard.clearEvents()

    # ------------------------------------------------------------------ 区段反馈
    def _fb_interval(self, score, eff_type, deadline, practice=False):
        """区段反馈（2.2）：本次得多少分 + 分数是否取决于表现，共 1500ms。"""
        if deadline is None or not isfinite(deadline):
            raise ValueError("区段反馈需要有限的作答截止时刻。")
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

        if self.settings["SHOW_TOTAL_SCORE"] and not practice:
            self.fb_total.text = "累计 %d 分" % int(round(self.total_score + score))
            self.fb_total.draw()

        escape_at = self.timed_input.wait_until_or_escape(deadline)
        if escape_at is not None:
            return None, None, escape_at
        onset = float(self.win.flip())
        escape_at = self.timed_input.wait_until_or_escape(
            onset + self.settings["FB_DUR"]
        )
        offset = float(self.win.flip())
        return onset, offset, escape_at

    # ------------------------------------------------------------------ 单试次
    def make_trial_content(self):
        """抽取字色、色词和一致性条件。"""
        ink = self.rng.choice(list(self.settings["KEYS"]))
        if self.rng.random() < self.settings["COND_RATIO"]:
            return ink, self.settings["WORD"][ink], "congruent"
        other_colors = [color for color in self.settings["KEYS"] if color != ink]
        word_color = self.rng.choice(other_colors)
        return ink, self.settings["WORD"][word_color], "incongruent"

    def _present_target(self, ink, word):
        """呈现色块或色词。按键保留在队列中，由实际翻屏时间筛选。"""
        if word:
            self.word.text = word
            self.word.color = self.settings["COLOR_RGB"][ink]
            self.word.draw()
        else:
            self.square.fillColor = self.settings["COLOR_RGB"][ink]
            self.square.draw()
        return float(self.win.flip())

    # ------------------------------------------------------------------ 区段
    def run_interval(self, idx, window, eff_type, phase="main", practice_yoke=None):
        """跑一个区段：注视点 → 自由作答窗口 → 反馈（2.2）。"""
        interval_number = "" if idx is None else idx + 1
        block = (
            self.main_schedule.block_number(idx)
            if phase == "main" and idx is not None
            else ""
        )
        self.fix.draw()
        fixation_on = float(self.win.flip())
        escape_at = self.timed_input.wait_until_or_escape(
            fixation_on + self.rng.choice(self.settings["FIX_CHOICES"])
        )
        interrupt_stage = "注视中" if escape_at is not None else ""

        interval_start = deadline = None
        n_done = 0
        n_answered = 0
        n_correct = 0
        n_congruent = 0
        interrupted_trial = False
        frame_period = self.frame_period
        while escape_at is None:
            ink, word, condition = self.make_trial_content()
            onset = self._present_target(ink, word)
            if interval_start is None:
                interval_start = onset
                deadline = interval_start + window
            response, pressed_at, escape_at = self.timed_input.wait_for_response(
                self.response_keys, onset, deadline
            )
            interrupted_trial = (
                escape_at is not None and not response and escape_at < deadline
            )

            correct_key = self.settings["KEYS"][ink]
            correct = int(response == correct_key)
            n_done += 1
            n_answered += int(bool(response))
            n_correct += correct
            n_congruent += int(condition == "congruent")
            self.rows_trials.append(
                dict(
                    被试=self.subj,
                    组别=self.group,
                    阶段=phase,
                    会话编号=self.session_id,
                    组块=block,
                    试次编号=len(self.rows_trials) + 1,
                    区段=interval_number,
                    区段内序号=n_done,
                    窗口s=window,
                    区段内开始时刻s=round(onset - interval_start, 4),
                    目标翻屏时刻s=onset,
                    作答截止时刻s=deadline,
                    条件=condition,
                    词=word,
                    墨色=ink,
                    正确键=correct_key,
                    正确=("" if interrupted_trial else correct),
                    试次中断=int(interrupted_trial),
                    **trial_response_fields(
                        response, pressed_at, onset, deadline, interrupted_trial
                    ),
                )
            )
            if escape_at is not None:
                interrupt_stage = "作答中"
                break
            if not response:
                break
            # 离截止不足一次刷新时，由反馈直接替换当前刺激。
            if psylog.defaultClock.getTime() + frame_period >= deadline:
                break
            blank_on = float(self.win.flip())
            next_on = blank_on + self.settings["ISI_BETWEEN"]
            # 为下一次刷新预留一帧。尾部留空仍使用同一个区段截止时刻。
            if next_on + frame_period + self.settings["MIN_TRIAL_TIME"] >= deadline:
                break
            escape_at = self.timed_input.wait_until_or_escape(next_on)
            if escape_at is not None:
                interrupt_stage = "题间空屏"
                break
            if (
                psylog.defaultClock.getTime()
                + frame_period
                + self.settings["MIN_TRIAL_TIME"]
                >= deadline
            ):
                break

        # 3) 计分（2.2）：表现区段 = 真实得分；随机区段 = 从 yoking 窗口抽
        practice = practice_yoke is not None
        history = practice_yoke if practice else self.yoke
        feedback_on = feedback_off = None
        score, source = None, ""
        if escape_at is None:
            if eff_type == "performance":
                score = float(n_correct * self.settings["POINT_PER_CORRECT"])
                source = "表现"
            else:
                score = history.sample(self.rng if practice else self.score_rng)
                source = "抽取"
            feedback_on, feedback_off, escape_at = self._fb_interval(
                score, eff_type, deadline, practice=practice
            )
            if escape_at is not None:
                if feedback_on is None or escape_at < feedback_on:
                    interrupt_stage = "反馈前"
                else:
                    interrupt_stage = "反馈中"

        feedback_shown = feedback_on is not None
        # 保留已经发生的反馈翻屏记录，按 Esc 的实际时刻决定积分是否结算。
        score_awarded = feedback_shown and interrupt_stage != "反馈前"
        if score_awarded:
            if eff_type == "performance":
                history.add(score)
            if not practice:
                self.total_score += score

        elapsed = ""
        if interval_start is not None:
            window_end = deadline if escape_at is None else min(deadline, escape_at)
            elapsed = round(max(0.0, window_end - interval_start), 6)
        # 正确率排除中断试次。一致比例按所有已呈现试次统计。
        n_evaluable = n_done - int(interrupted_trial)
        row = dict(
            被试=self.subj,
            组别=self.group,
            阶段=phase,
            会话编号=self.session_id,
            组块=block,
            区段=interval_number,
            窗口s=window,
            作答窗用时s=elapsed,
            注视翻屏时刻s=fixation_on,
            区段开始时刻s=interval_start,
            区段截止时刻s=deadline,
            反馈翻屏时刻s=feedback_on,
            反馈结束时刻s=feedback_off,
            反馈延迟s=(round(feedback_on - deadline, 6) if feedback_shown else ""),
            反馈时长s=(round(feedback_off - feedback_on, 6) if feedback_shown else ""),
            中断阶段=interrupt_stage,
            中断时刻s=escape_at,
            区段状态=("interrupted" if interrupt_stage else "completed"),
            反馈中断=int(interrupt_stage == "反馈中"),
            试次数=n_done,
            作答数=n_answered,
            正确数=n_correct,
            截止未答数=n_evaluable - n_answered,
            正确率=(round(n_correct / float(n_evaluable), 3) if n_evaluable else ""),
            一致比例=(round(n_congruent / float(n_done), 3) if n_done else ""),
            效能概率="",
            效能类型=eff_type,
            得分来源=(source if score_awarded else ""),
            区段得分=(round(score, 2) if score_awarded else ""),
            累计得分=round(self.total_score, 2),
        )
        self.rows_intervals.append(row)
        if escape_at is not None:
            self.abort()
        self.check_escape()
        return row

    # ------------------------------------------------------------------ 主观探针
    def run_probe(self, kind, after_interval):
        interval_number = "" if after_interval is None else after_interval + 1
        block = (
            self.main_schedule.block_number(after_interval)
            if after_interval is not None
            else ""
        )
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
        self._clear_response_buffer()
        t0 = core.getTime()

        while True:
            if mouse_left_pressed(mouse):
                mx, my = mouse.getPos()
                if abs(my - (-0.04)) < 0.14:  # 只在量表条附近才算有效拖动
                    nx = min(max(mx, x_lo), x_hi)
                    if abs(nx - x) > 1e-4:
                        moved = True
                    x = nx
            keys = {
                key.name
                for key in self.timed_input.poll_keys(
                    ["space", "escape", "left", "right"]
                )
            }
            if "left" in keys:  # 键盘兜底：鼠标失灵也能作答
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
            if self.settings["SHOW_VAS_NUMBER"]:
                self.probe_num.text = "%d" % round((x - x_lo) / (x_hi - x_lo) * 100)
                self.probe_num.draw()
            self.win.flip()

        value = (x - x_lo) / (x_hi - x_lo) * 100.0
        self.win.setMouseVisible(False)
        core.wait(0.2)
        self.rows_probes.append(
            dict(
                被试=self.subj,
                组别=self.group,
                探针类型=kind,
                会话编号=self.session_id,
                阶段="main",
                组块=block,
                区段=interval_number,
                探测编号=len(self.rows_probes) + 1,
                插入位置=interval_number,
                评价值=round(value, 2),
                用时s=round(core.getTime() - t0, 3),
                累计得分=round(self.total_score, 2),
            )
        )

    # ------------------------------------------------------------------ 练习
    def _practice_trial(self, ink, word, timeout=None, with_fb=True, phase="prac"):
        """练习用的单试次：注视点 → 色块或色词 → 正误反馈。"""
        timeout = self.settings["PRAC_TIMEOUT"] if timeout is None else timeout
        self.fix.draw()
        self.win.flip()
        core.wait(self.rng.uniform(0.4, 0.7))

        onset = self._present_target(ink, word)
        deadline = onset + timeout
        resp_key, pressed_at, escape_at = self.timed_input.wait_for_response(
            self.response_keys, onset, deadline
        )
        ok = int(resp_key == self.settings["KEYS"][ink])
        interrupted = escape_at is not None and not resp_key and escape_at < deadline

        self.rows_trials.append(
            dict(
                被试=self.subj,
                组别=self.group,
                阶段=phase,
                会话编号=self.session_id,
                组块="",
                试次编号=len(self.rows_trials) + 1,
                区段="",
                区段内序号="",
                窗口s=timeout,
                区段内开始时刻s="",
                目标翻屏时刻s=onset,
                作答截止时刻s=deadline,
                条件=(
                    "mapping"
                    if not word
                    else (
                        "congruent"
                        if word == self.settings["WORD"][ink]
                        else "incongruent"
                    )
                ),
                词=word or "色块",
                墨色=ink,
                正确键=self.settings["KEYS"][ink],
                正确=("" if interrupted else ok),
                试次中断=int(interrupted),
                **trial_response_fields(
                    resp_key, pressed_at, onset, deadline, interrupted
                ),
            )
        )
        if escape_at is not None:
            self.abort()

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

        return ok

    def practice_mapping(self):
        self.wait_space(
            "练习 1 / 3：颜色与按键\n\n"
            "屏幕中央会出现一个色块，请判断它的颜色并按下对应按键。\n\n"
            "红色 → D    绿色 → F    蓝色 → J    黄色 → K\n\n"
            "按空格开始。",
            height=0.038,
        )
        seq = []
        while len(seq) < self.settings["N_PRAC1"]:
            seq += list(self.settings["KEYS"])
        seq = seq[: self.settings["N_PRAC1"]]
        self.rng.shuffle(seq)
        for ink in seq:
            self._practice_trial(ink, "", phase="prac1")

    def practice_color_word(self):
        self.wait_space(
            "练习 2 / 3：判断字色\n\n"
            "屏幕中央会出现一个表示颜色的字。请按字的颜色选键，忽略字义。\n\n"
            "例如，用绿色写的“红”应该按 F。\n\n"
            "按空格开始。",
            height=0.038,
        )
        for _ in range(self.settings["N_PRAC2"]):
            ink, word, _ = self.make_trial_content()
            self._practice_trial(ink, word, phase="prac2")

    def practice_free_window(self):
        self.wait_space(
            "练习 3 / 3：在一个区段内连续作答\n\n"
            "每段给你一段固定的作答时间。每答完一题，就可以继续做下一题。\n"
            "时间结束后会显示得分和来源。按表现计分时，每答对一题得 %d 分；"
            "随机计分时，这一段答对多少题不会改变它的得分。\n\n"
            "按空格开始。" % self.settings["POINT_PER_CORRECT"],
            height=0.036,
        )
        history = YokeWindow(self.settings["YOKE_WINDOW"], init=[])
        for i in range(self.settings["N_PRAC3"]):
            eff_type = "performance" if i % 2 == 0 else "random"
            self.run_interval(
                i,
                self.settings["PRAC_WINDOW"],
                eff_type,
                phase="prac3",
                practice_yoke=history,
            )

    # ------------------------------------------------------------------ 休息
    def show_break(self, done, total):
        self.wait_space(
            "休息一下\n\n已完成 %d / %d 个区段\n累计得分：%d 分\n\n"
            "准备好后按 空格 继续。" % (done, total, int(round(self.total_score))),
            height=0.042,
        )

    # ------------------------------------------------------------------ 正式任务
    def run_main(self):
        schedule = self.main_schedule
        n = len(schedule.windows)
        self.wait_space(
            "正式任务开始\n\n"
            "请按字的颜色选键，忽略字义。红 → D，绿 → F，蓝 → J，黄 → K。\n"
            "请在每段给定的时间内连续作答，区段结束时会显示得分和来源。\n\n"
            "有的区段按表现计分，每答对一题得 %d 分；有的区段由系统随机给分。\n"
            "作答时请兼顾速度和准确性。任务中会偶尔出现滑块问题，请按当下的判断作答。\n\n"
            "共 %d 个区段。按空格开始。" % (self.settings["POINT_PER_CORRECT"], n),
            height=0.036,
        )

        for i, window in enumerate(schedule.windows):
            if (
                self.settings["BREAK_EVERY"]
                and i > 0
                and i % self.settings["BREAK_EVERY"] == 0
            ):
                self.show_break(i, n)
            self.run_interval(i, window, eff_type=schedule.sources[i])
            if i in schedule.probes:
                self.run_probe(schedule.probes[i], after_interval=i)
            if i % 10 == 0:  # 每 10 区段落盘一次，防崩溃丢数据
                self.save()

    # ------------------------------------------------------------------ 主流程
    def run(self):
        self.save()
        if not self.settings.get("SKIP_PRACTICE", False):
            self.practice_mapping()
            self.practice_color_word()
            self.practice_free_window()
        self.run_main()
        self.finish("completed")
        self.wait_space(
            "实验结束，谢谢参与！\n\n总得分：%d 分\n\n按 空格 退出。"
            % int(round(self.total_score)),
            height=0.045,
        )
