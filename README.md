# 色词 Stroop 表现效能学习任务

本项目用研究一的四色 Stroop 刺激和按键映射，结合研究二的定长连续作答区段、区段积分与效能反馈。方法来源见 [Grahek 等（2023），Study 2 — Experimental design](https://doi.org/10.1093/cercor/bhac215)。

## 在 PsychoPy Studio 运行

在 PsychoPy Studio 打开 **Coder**，打开仓库根目录的 [stroop_efficacy_learning.py](stroop_efficacy_learning.py)，点击 **Run**。脚本使用 Studio 的 PsychoPy 环境。被试信息确认后按空格开始，任务中可按 Esc 退出并保存已有记录。

- **快跑**　将脚本顶部 `CFG` 中的 `DEBUG_FAST` 改为 `True`，以窗口模式运行 12 个区段，作答窗口缩短为 1 秒。适用于检查按键、反馈、探测与导出。
- **完整流程**　保持 `DEBUG_FAST=False` 和 `SKIP_PRACTICE=False`。以全屏运行三段练习和 288 个正式区段。当前合并版用于开发验证，采集版本将在[路线图](https://gitee.com/evclab/stroop-efficacy-learning/issues/IKY26F)中的验收完成后锁定。

## 作答流程

判断字色，忽略字义。红、绿、蓝、黄分别按 **D、F、J、K**。例如，用绿色写的“红”应按 F。

1. 先练颜色与按键，再练色词冲突，最后练在一个区段内连续作答。第三段练习交替体验按表现计分和随机计分。随机练习从先前表现练习的积分抽取，练习独立记录，正式任务从自身的初始积分池和零累计分开始。
2. 正式任务每段先呈现注视点，再提供 2、3 或 4 秒作答窗口。作答后可接着做下一题。正式试次包含一致与不一致两类。
3. 每段结束显示一次积分与来源。表现决定的区段每答对一题加 10 分，随机区段从最近十次表现区段积分的滚动窗口中抽取。每隔 2–4 个区段插入一个滑块问题，分别询问对效能或积分的当前估计。

## 与 Grahek 研究二的对照

- 本项目沿用论文的 288 个区段、2/3/4 秒作答窗、1/1.5/2 秒注视点、1.5 秒反馈、每次正确作答 10 分和最近 10 个表现区段的积分匹配。刺激采用研究一的四色色词，计分来源用文字呈现。研究二将积分与奖金挂钩，本项目的积分兑现规则在采集方案中确定。正文见 [Study 2 — Experimental design](https://doi.org/10.1093/cercor/bhac215)。
- 作者公开日志中，84 个可按原始区段编号重建的完整会话使用同一套窗长顺序，2、3、4 秒各 96 段。有图词记录的题目中，一致刺激约占 47%，被试间比例有波动。本项目从三种窗长各取 96 段后按被试打乱，正式色词按 0.5 概率独立抽取一致性，记录实际配比供核查。[作者公开日志](https://github.com/igrahek/LFXC_EEG_2022/tree/eaebcb7a348109f20606a87f2210d3bb59bc7bf7/Data/Experiment2)
- 正文写每隔 2–4 个区段探测一次。公开日志中每人记录 72 次有效探测，间隔为 3–5 个区段。当前按正文的 2–4 个区段运行，采集版需确定采用的规则。公开日志还显示两组在相同区段位置的计分来源逐段互补。采集版的效能序列在 [IKY25S](https://gitee.com/evclab/stroop-efficacy-learning/issues/IKY25S) 核对。
- 当前开发版以作者分析脚本的 250 ms 作为区段内题间空屏基线。剩余可呈现时间不足 350 ms 时停止出新题，已经显示的末题可以作答到区段截止。350 ms 是本项目的末题规则，采集版在预测试后锁定。[作者分析脚本](https://github.com/igrahek/LFXC_EEG_2022/blob/eaebcb7a348109f20606a87f2210d3bb59bc7bf7/Analyses/Experiment2/Stats/brms/Experiment2_brms_models.R#L37)

## 计时核对

区段从首个目标翻屏开始计时。按键有效时段从本题翻屏起，到固定区段截止时刻前。反应时由 PsychoPy Studio 的 Psychtoolbox 按键时间戳减去目标翻屏时间得到。反馈在截止后的首个可用刷新呈现，按反馈翻屏计时约 1.5 秒。

在 PsychoPy Studio 的 Python 环境下，从仓库根目录运行：

```powershell
python tests/check_timing.py --studio
```

脚本在 2、3、4 秒区段验证正常作答、截止前、截止时、截止后和未答。它开启真实窗口并使用模拟按键，以软件时间戳核对计时。也可用 `--isi 0.15` 对照旧版的题间空屏。

## 输出与版本

输出写到脚本旁的 `data/`，包括单题 `trials.csv`、区段 `intervals.csv`、探测 `probes.csv` 和会话信息 `meta.json`。单题表的 `词` 与 `墨色` 记录实际刺激，`反应时` 以秒为单位。区段表记录注视点、区段起止和反馈起止的翻屏时间或计划截止时间。它们同单题的目标与按键时间共用 PsychoPy 日志时钟。会话信息记录 Git 提交、脚本 SHA-256、运行参数和正式任务的字色 × 字义计数。分别统计已呈现和有按键的刺激。数据目录已被 Git 忽略。

迁入的研究一色词版本可从 [`v1.2`](https://gitee.com/evclab/stroop-efficacy-learning/tree/v1.2) 查阅。研究二水果版和原说明见 [`exp2-v1.0`](https://gitee.com/evclab/stroop-efficacy-learning/tree/exp2-v1.0)。
