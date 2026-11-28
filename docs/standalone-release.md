# 独立版发布机制

本仓库的源码具备 PyInstaller 独立运行适配，但**普通提交、PR 和常规 CI 不生成程序包**。只有发布一个标签符合 `standalone-vX.Y.Z` 的 GitHub Release，才启动跨平台构建。预发布可使用 `standalone-vX.Y.Z-rc.1` 这类标签。

## 发布步骤

1. 在 `main` 合并已通过常规测试的代码，并完成该版本要求的预测试和设备验收。独立版不替代 Issue #7 的协议锁定。
2. 确定版本号后，以目标提交创建并发布 GitHub Release，标签使用 `standalone-v1.0.0` 这样的格式。不要复用或移动已经发布的标签。
3. `Standalone release` 工作流从该标签检出同一提交，安装 `packaging/requirements-standalone.txt` 中锁定的依赖，分别构建并运行启动自检。
4. 四个平台任务全部成功后，工作流把压缩包和对应 SHA-256 文件上传到原 Release。任一平台失败时，发布附件步骤不会执行；可在修复后重新运行失败任务，或按项目决策发布新版本。
5. 下载目标平台包，核对 SHA-256，并在实际采集设备完成下述人工验收后才投入使用。

自动生成的目标为：

| Runner | 包内目标 | 文件名中的平台标识 |
| --- | --- | --- |
| `windows-2025` | Windows x64 | `windows-x64` |
| `ubuntu-24.04` | Linux x64 | `linux-x64` |
| `macos-15` | macOS Apple Silicon | `macos-arm64` |
| `macos-15-intel` | macOS Intel | `macos-x64` |

这些不是通用二进制。其他操作系统或处理器架构需要在对应 runner 上单独构建和验证。

## 源码适配

- `stroop_efficacy/runtime.py` 区分源码／Studio 与 PyInstaller 运行，读取包内 `build-info.json`，并解析持久数据目录。
- `run.py --standalone-smoke-test` 在不打开实验窗口的情况下检查构建信息、代码摘要和数据目录可写状态。构建脚本自动执行此检查。
- `packaging/build_standalone.py` 强制要求 `--tag` 或 `--version`，拒绝生成无版本包；同时要求源码来自干净、可识别的 Git 提交。
- 构建记录包含发布版本、源码提交、入口与模块 SHA-256、Python／PsychoPy／PyInstaller 版本、目标平台和构建时间。包外也附一份供核对。
- `packaging/standalone-README.txt` 是包内的 `START-HERE.txt`，说明启动、数据位置和验收限制。

## 数据位置与升级

独立版不把会话写入程序目录。默认位置为：

- Windows：`%LOCALAPPDATA%\EVC-Lab\StroopEfficacyLearning\data`
- macOS：`~/Library/Application Support/EVC-Lab/StroopEfficacyLearning/data`
- Linux：`${XDG_DATA_HOME:-~/.local/share}/EVC-Lab/stroop-efficacy-learning/data`

因此重新解压或升级程序不会覆盖已有场次。登记页显示实际路径。需要统一采集目录时，可在启动前设置 `STROOP_EFFICACY_DATA_DIR`；该位置必须可写，并按项目要求控制访问和备份。源码／Studio 模式仍使用仓库的 `data/`。

## 发布验收边界

启动自检不打开窗口，也不测量显示延迟或实体键盘时间戳。每个目标采集平台仍需：

1. 在未预装 Python／PsychoPy Studio 的环境验证启动、中文界面、全屏、字体、PTB 键盘和中文输入法。
2. 从同一提交分别运行 Studio 与独立版，核对三种模式、A/B 分配、288 段调度、积分与来源反馈、两类探测、Esc 中断和导出。
3. 核对常驻登记、失败重试、场次保存状态、筛选和关闭；确认升级后仍能按编码找到旧场次。
4. 完成 Issue #7 的完整预测试，并记录采集版锁定的提交、协议参数、设备与预处理口径。

macOS 包目前未签名和公证；Linux 包依赖目标机的图形桌面、OpenGL、音频及 Psychtoolbox 运行环境。若项目需要签名、公证、安装器或更多架构，应另行验收后再加入发布矩阵。
