# 仓库代码审查指引

## Code Review Rules

审查实验行为时，先核对 Grahek 等（2023）Study 2 的 **Experimental design**、相关分析方法和补充图 **S2A**。正文未给出实现细节时，用作者的公开日志或分析脚本核查，并注明观察到的结果及尚待确认的细节。Issue 用于追溯本项目的适配决策和待验收事项。报告方法偏差时，请注明所依据的论文章节、图、日志字段、脚本行号或已确认的项目决策。[论文与补充材料](https://doi.org/10.1093/cercor/bhac215) · [作者公开日志](https://github.com/igrahek/LFXC_EEG_2022/tree/eaebcb7a348109f20606a87f2210d3bb59bc7bf7/Data/Experiment2)

- **实验协议与积分。** 按 Study 2 正文核对 288 个连续作答区段、区段末的积分及来源反馈、效能与积分两类主观探测。表现区段每答对一题得 10 分，随机区段从最近 10 个表现区段的积分中抽样。用公开日志复核逐段窗长、两条互补的实际来源序列和探测位置。日志中相邻带探测区段的编号差为 3–5，中间夹着 2–4 个无探测区段。项目重放两条来源序列，出题、作答速度和积分抽样均不得改动它们。补充图 S2A 展示效能概率的变化，逐段概率有可追溯的数值来源才填。初始积分池、练习独立计分和色词刺激属于本项目适配。[作者公开日志](https://github.com/igrahek/LFXC_EEG_2022/tree/eaebcb7a348109f20606a87f2210d3bb59bc7bf7/Data/Experiment2) · [项目调度与积分适配](https://github.com/EVC-Lab/stroop-efficacy-learning/issues/5)
- **计时与退出。** 正文规定 1、1.5 或 2 秒注视，2、3 或 4 秒定长作答窗，随后约 1.5 秒反馈。PsychoPy 版从首题实际翻屏起计作答窗，用实际目标翻屏与 PTB 按下时刻计算单题 RT，只接受本题翻屏起至区段截止前的按键。剩余时间不足以呈现新题时，已呈现的题仍可作答到区段截止。反馈显示时长从实际反馈翻屏起算。Esc 在反馈翻屏前按下时，保留已呈现试次和实际时间戳，区段得分留空。[论文 Study 2](https://doi.org/10.1093/cercor/bhac215) · [项目计时与退出规则](https://github.com/EVC-Lab/stroop-efficacy-learning/issues/4)
- **导出与数据含义。** 按作者分析所用数据核对区段、试次与探测题可关联，分别保存实际计分来源、积分和主观评定。涉及学习模型时，核对反馈前的效能和积分预期用于解释当段表现。本项目保留有效按键、截止未答和中断的标记。区段正确率计入普通超时未答，排除因退出被截断的试次。一致比例按实际呈现的全部刺激计算。仓库、PR 和 CI 使用合成样例或脱敏汇总，真实被试数据留在采集端。[作者区段汇总](https://github.com/igrahek/LFXC_EEG_2022/blob/eaebcb7a348109f20606a87f2210d3bb59bc7bf7/Analyses/Experiment2/Stats/brms/Experiment2_brms_models.R#L133-L150) · [反馈前模型预期](https://github.com/igrahek/LFXC_EEG_2022/blob/eaebcb7a348109f20606a87f2210d3bb59bc7bf7/Analyses/Experiment2/Stats/brms/Experiment2_brms_models.R#L581-L586) · [项目导出规则](https://github.com/EVC-Lab/stroop-efficacy-learning/issues/6)
- **评审证据。** 引用 PR 最新提交中的路径和行号。对会改变实验操纵、计分或数据含义的问题，给出从正常运行入口可触发的输入或事件顺序。旧意见若仍成立，说明当前代码怎样触发。核对正式调度测试与快跑设置的隔离，注明计时结论的依据是虚拟时钟、Studio 全屏软件时间戳，还是采集设备实测。
