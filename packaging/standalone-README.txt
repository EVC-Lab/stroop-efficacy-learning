色词 Stroop 表现效能学习任务 · 独立版 {{VERSION}}
================================================

本程序包不需要另装 Python 或 PsychoPy Studio。请先从 Release 下载与操作系统和处理器架构相符的包，再完整解压；不要只运行压缩包内的程序。

启动
----
Windows：打开 StroopEfficacyLearning 文件夹，双击 StroopEfficacyLearning.exe。
macOS：双击 StroopEfficacyLearning.app。发布包目前未签名和公证；如系统阻止打开，请遵守本机构安全政策，在系统设置中核对后允许打开，不要关闭整体安全保护。
Linux：在 StroopEfficacyLearning 文件夹中运行 StroopEfficacyLearning。需要目标机具备正常的图形桌面、OpenGL 和 Psychtoolbox 可用的键盘环境。

数据保存
--------
程序文件与会话数据分开保存，重新解压或升级程序不会覆盖既有场次。登记页始终显示本次实际使用的保存位置。

Windows：%LOCALAPPDATA%\EVC-Lab\StroopEfficacyLearning\data
macOS：~/Library/Application Support/EVC-Lab/StroopEfficacyLearning/data
Linux：${XDG_DATA_HOME:-~/.local/share}/EVC-Lab/stroop-efficacy-learning/data

如需由实验员统一指定采集目录，可在启动前设置环境变量 STROOP_EFFICACY_DATA_DIR。该目录必须可写，并应按项目的数据管理要求备份和限制访问。

验收与版本
----------
每个发布包附带 build-info.json、smoke-test.json 和 SHA-256 校验文件。启动自检只验证程序资源、版本记录和数据目录可写；它不替代真实显示器、实体 PTB 键盘、中文输入法、完整任务流程及正式导出验收。

正式发布前，请用同一提交核对 Studio 版与独立版的三种模式、A/B 分配、练习、288 段调度、积分与来源反馈、两类探测、Esc 中断和导出。预测试锁定协议参数后，再创建对应版本的采集包。
