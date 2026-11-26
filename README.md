# 色词 Stroop 表现效能学习任务

本项目用研究一的四色 Stroop 刺激和按键映射，结合研究二的定长连续作答区段、区段积分与效能反馈。方法来源见 [Grahek 等（2023），Study 2 — Experimental design](https://doi.org/10.1093/cercor/bhac215)。

## 在 PsychoPy Studio 运行

在 PsychoPy Studio 打开 **Coder**，打开仓库根目录的 [stroop_efficacy_learning.py](stroop_efficacy_learning.py)，点击 **Run**。脚本使用 Studio 的 PsychoPy 环境。被试信息确认后按空格开始，任务中可按 Esc 退出并保存已有记录。

- **快跑**　将脚本顶部 `CFG` 中的 `DEBUG_FAST` 改为 `True`，以窗口模式运行 12 个区段，作答窗口缩短为 1 秒。适用于检查按键、反馈、探测与导出。
- **完整流程**　保持 `DEBUG_FAST=False` 和 `SKIP_PRACTICE=False`。以全屏运行三段练习和 288 个正式区段。当前合并版用于开发验证，采集版本将在[路线图](https://gitee.com/evclab/stroop-efficacy-learning/issues/IKY26F)中的验收完成后锁定。

## 作答流程

判断字色，忽略字义。红、绿、蓝、黄分别按 **D、F、J、K**。例如，用绿色写的“红”应按 F。

1. 先练颜色与按键，再练色词冲突，最后练在一个区段内连续作答。第三段练习按正确数计分，用于熟悉区段结算。
2. 正式任务每段先呈现注视点，再提供 2、3 或 4 秒作答窗口。作答后可接着做下一题。正式试次包含一致与不一致两类。
3. 每段结束显示一次积分与来源。表现决定的区段每答对一题加 10 分，随机区段从最近十次表现区段积分的滚动窗口中抽取。每隔 2–4 个区段插入一个滑块问题，分别询问对效能或积分的当前估计。

## 输出与版本

输出写到脚本旁的 `data/`，包括单题 `trials.csv`、区段 `intervals.csv`、探测 `probes.csv` 和会话信息 `meta.json`。单题表的 `词` 与 `墨色` 记录实际刺激，`反应时` 以秒为单位。数据目录已被 Git 忽略。

迁入的研究一色词版本可从 [`v1.2`](https://gitee.com/evclab/stroop-efficacy-learning/tree/v1.2) 查阅。研究二水果版和原说明见 [`exp2-v1.0`](https://gitee.com/evclab/stroop-efficacy-learning/tree/exp2-v1.0)。
