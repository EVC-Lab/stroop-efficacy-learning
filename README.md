# 色词 Stroop 表现效能学习任务

本项目用研究一的四色 Stroop 刺激和按键映射，结合研究二的定长连续作答区段、区段积分与效能反馈。方法来源见 [Grahek 等（2023），Study 2 — Experimental design](https://doi.org/10.1093/cercor/bhac215)。

## 在 PsychoPy Studio 运行

在 PsychoPy Studio 打开 **Coder**，打开仓库根目录的 [stroop_efficacy_learning.py](stroop_efficacy_learning.py)，点击 **Run**。运行时将同目录的 `stroop_efficacy/` 与主脚本一起保留。启动时先检查 Studio 的 Psychtoolbox 键盘后端，然后进入被试登记。被试信息确认后按空格开始，任务中可按 Esc 退出并保存已有记录。

- **快跑**　将 `stroop_efficacy/design.py` 的 `CFG` 中 `DEBUG_FAST` 改为 `True`，以窗口模式运行 12 个区段，作答窗口缩短为 1 秒。适用于检查按键、反馈、探测与导出。
- **完整流程**　保持 `DEBUG_FAST=False` 和 `SKIP_PRACTICE=False`。以全屏运行三段练习和 288 个正式区段。当前合并版用于开发验证，采集版本将在[路线图](https://github.com/EVC-Lab/stroop-efficacy-learning/issues/8)中的验收完成后锁定。

## 程序结构

主脚本负责实验界面、作答与区段流程。[`design.py`](stroop_efficacy/design.py) 管理实验参数、窗长与效能调度和历史积分抽样。[`timing.py`](stroop_efficacy/timing.py) 管理 PTB 按键和截止判定。[`session_data.py`](stroop_efficacy/session_data.py) 负责保存会话文件和记录代码摘要。

## 作答流程

判断字色，忽略字义。红、绿、蓝、黄分别按 **D、F、J、K**。例如，用绿色写的“红”应按 F。

1. 先练颜色与按键，再练色词冲突，最后练在一个区段内连续作答。第三段练习交替体验按表现计分和随机计分。随机练习从先前表现练习的积分抽取，练习独立记录，正式任务从自身的初始积分池和零累计分开始。
2. 正式任务每段先呈现注视点，再提供 2、3 或 4 秒作答窗口。作答后可接着做下一题。正式试次包含一致与不一致两类。
3. 每段结束显示一次积分与来源。表现决定的区段每答对一题加 10 分，随机区段从最近十次表现区段积分的滚动窗口中抽取。相邻的滑块问题之间有 2–4 个不带探测题的区段，效能与积分问题交替出现。

## 与 Grahek 研究二的对照

- 本项目沿用论文的 288 个区段、2/3/4 秒作答窗、1/1.5/2 秒注视点、1.5 秒反馈、每次正确作答 10 分和最近 10 个表现区段的积分匹配。刺激采用研究一的四色色词，计分来源用文字呈现。研究二将积分与奖金挂钩，本项目的积分兑现规则在采集方案中确定。正文见 [Study 2 — Experimental design](https://doi.org/10.1093/cercor/bhac215)。
- 84 个完整会话的窗长顺序一致。正式流程按 `2、2、3、3、4、4` 秒循环，组成 8 个组块，每组 36 段。本项目在组块之间安排休息。正式色词仍按 0.5 概率独立抽取一致性，记录实际配比供核查。[作者公开日志](https://github.com/igrahek/LFXC_EEG_2022/tree/eaebcb7a348109f20606a87f2210d3bb59bc7bf7/Data/Experiment2)
- 正式任务重放日志中的两条逐段互补的计分来源序列。序列 A 首段为随机计分，288 段中有 141 个表现区段。序列 B 首段按表现计分，有 147 个表现区段。自动分配时，编号最后一个数字为奇数或没有数字用 A，偶数用 B。旧登记界面的「正向」「反向」分别对应 A 和 B。序列与答题速度、出题和积分抽样无关。作者逐段概率尚不可得，区段表的「效能概率」留空。[核对记录](https://github.com/EVC-Lab/stroop-efficacy-learning/issues/5)
- 正式任务开跑前打乱 3、4、5 段的探测间距，各 24 次。从区段 0 起算间距，最后一次探测在第 288 段。题型随机起始，随后交替，各 36 次。所用随机数流由编号和组别固定。这个生成规则重现公开日志的配额与间隔，具体位置由本程序生成。[作者公开日志](https://github.com/igrahek/LFXC_EEG_2022/tree/eaebcb7a348109f20606a87f2210d3bb59bc7bf7/Data/Experiment2)
- 正式积分池起始值按从旧到新排列为 `20, 30, 10, 20, 30, 20, 30, 10, 20, 30`。取公开日志中随机先行组 46 个完整会话的首段得分，以最近秩法取第 5、15、…、95 百分位并交错排列。均值为 22 分。这是本项目用于预测试的初始池。它会随表现区段结算逐步替换，满十次后只含该参与者最近十个表现区段的积分。随机区段用独立随机数流从池内抽取，整段作答完成后按反馈是否结算记录积分。分窗长的积分匹配留到色词版[预测试](https://github.com/EVC-Lab/stroop-efficacy-learning/issues/7)核对。
- 当前开发版以作者分析脚本的 250 ms 作为区段内题间空屏基线。剩余可呈现时间不足 350 ms 时停止出新题，已经显示的末题可以作答到区段截止。350 ms 是本项目的末题规则，采集版在预测试后锁定。[作者分析脚本](https://github.com/igrahek/LFXC_EEG_2022/blob/eaebcb7a348109f20606a87f2210d3bb59bc7bf7/Analyses/Experiment2/Stats/brms/Experiment2_brms_models.R#L37)

## 计时核对

区段从首个目标翻屏开始计时。按键有效时段从本题翻屏起，到固定区段截止时刻前。反应时由 PsychoPy Studio 的 Psychtoolbox 按键时间戳减去目标翻屏时间得到。反馈在截止后翻屏，以实际反馈翻屏为起点计时约 1.5 秒。键盘交互统一使用 PTB，在注视、作答、题间空屏、等待反馈或反馈显示时按 Esc，均会保存当前区段和中断时刻。中断时还未答完的题保留呈现时间并标为「试次中断」，正确字段留空。积分在反馈翻屏时结算。Esc 按下时刻早于反馈翻屏时，区段标为「反馈前」并留空得分，实际发生的翻屏与显示时长仍会记录。刷新率未测得或明显异常时，记录所采用的备用帧长，实测刷新率字段留空。

在 PsychoPy Studio 的 Python 环境下，从仓库根目录运行：

```powershell
python tests/check_timing.py --studio
```

脚本在 2、3、4 秒区段验证正常作答、截止前、截止时、截止后和未答。它还覆盖确认页、说明页、探测按键以及区段内五个阶段的中断保存、反馈翻屏边界和落盘失败后的文件保留。真实窗口测试使用模拟按键，以软件时间戳核对计时。可加 `--fullscreen` 复测正式全屏。可用 `--isi 0.15` 对照旧版的题间空屏。

去掉 `--studio` 可运行虚拟时钟检查。它也会以两种合成作答速度执行完整的 288 段流程，核对预定序列、探测题、历史积分抽样与累计分。

在采集设备上可运行以下命令，按屏幕提示各轻按一次 D 和 J，核对当前设备的原生 PTB 队列是否能收到首键和已松开的短按，并确认同一次按压只记一次。

```powershell
python tests/check_timing.py --ptb-keyboard --fullscreen
```

## 输出与版本

每次运行在脚本旁的 `data/` 写出 `trials.csv`、`intervals.csv`、`probes.csv` 和 `meta.json`。三个表用会话编号、阶段和区段号关联。同一被试重跑有新的会话编号。单题 RT 以秒保存，并区分有效作答、截止未答与中断。元数据记录正式调度、代码和参数版本、各表行数及 SHA-256，可校验同一次保存的文件。

[行为数据导出与分析说明](docs/behavior-analysis.md)包含字段、合表键、旧数据导入、反馈前模型预期和 DDM 筛选。真实被试数据保存在采集端。`data/` 已由 Git 忽略。

迁入的研究一色词版本可从 [`v1.2`](https://gitee.com/evclab/stroop-efficacy-learning/tree/v1.2) 查阅。研究二水果版和原说明见 [`exp2-v1.0`](https://gitee.com/evclab/stroop-efficacy-learning/tree/exp2-v1.0)。
