# LMU StintLab

Local telemetry HUD, recorder and lap analysis for **Le Mans Ultimate** on Windows x64.

实时油门 / 刹车 / 转向 HUD、比赛记录、完整圈对比与耐力赛遥测分析。界面以中文为主，所有记录默认保存在本机。

实时缓存与离线复盘采用紧凑数值存储和流式压缩；保留完整采样、原始 CSV 与现有操作。实测结果、模块职责和旧网页升级方式见 [内存与赛事文件](docs/PERFORMANCE.md)。

## 下载与一键启动

**便携版（推荐）**：从 [Releases](https://github.com/MarkYang44/LMU-StintLab/releases) 下载 `LMU-StintLab-v*-windows-x64.zip`，完整解压到可写目录，双击 `Start.cmd`。不需要安装 Python；`Demo.cmd` 可在不开游戏时演示。不要只移动 EXE，保留 `_internal` 文件夹。

**源码版**：点击 GitHub **Code → Download ZIP**，完整解压，双击 `Setup.cmd`，完成后双击 `Start.cmd`。首次配置需要联网：脚本查找 64 位 Python 3.13；没有时使用 winget 为当前用户安装官方 Python，然后创建独立 `.venv`、校验固定版本依赖并安装。没有 winget 时，请手动安装带 Tcl/Tk 的 [Python 3.13](https://www.python.org/downloads/windows/)，然后重试。

运行游戏后，HUD 会等待 LMU 的 `LMU_Data` 共享内存并自动记录。**无需向游戏复制 DLL，也不修改游戏文件或现有 ApexLink / RaceCom 配置。** LMU StintLab 独立运行；不是 RaceCom 本体、ApexLink 或官方插件。

## 功能

- 三色输入波形：油门绿、刹车红、转向蓝；原始输入 / 游戏过滤后输入自由切换。
- 紧凑置顶 HUD、纯曲线和纯曲线 + 柱形图 / 540° 示意方向盘模式；缩放与磨砂风格显示。
- 1–4000 Hz 目标轮询频率、动态采样、同步绘制及实际速率诊断。游戏新数据频率、CPU、Tk 和屏幕刷新率决定实际效果；高轮询不会制造新的游戏遥测。
- 结束后自动保存 CSV、离线 HTML 回放、最快圈文件及油刹曲线图；最快圈带圈号、车辆、赛道和会话信息。
- 同车同赛道跨比赛参考圈、完整圈 A / 圈 B 选择与提取、距离对齐、差距分析和规则生成的驾驶建议。
- 赛道轨迹播放、位置对比、缩放和拖拽；胎温 / 胎压 / 磨损、燃油 / 能量及耐力赛相关面板与日志分析。部分通道需要导入原生遥测文件。
- 只读导入 LMU `.duckdb` 记录、会话库、恢复与压缩。不会上传遥测，也不会连接外部 AI 服务。
- 会话库支持多选导出 / 导入比赛包：每场一个校验 ZIP，保留完整遥测、离线复盘、圈文件和备注，可手动上传网盘。

游戏 HUD 建议使用窗口 / 无边框窗口模式。它是 Windows 置顶窗口；独占全屏可能不显示。右键打开菜单，拖动移动；快捷键与工作流见 [使用说明](docs/USAGE.md)。

## 数据与隐私

默认输出在 `data/`；机器配置在 `local_settings.json`。比赛记录包含驾驶员姓名、日期、车辆、圈速等个人信息，报告也会嵌入这些内容。默认配置仅存在本机，不会提交到 Git。详见 [隐私与迁移](docs/PRIVACY.md)。

公开版的预置底图库为空：此前本地参考图没有足够明确的再分发授权，因此未随项目发布。**有世界坐标或 GPS 的记录直接绘制实测赛道轨迹，位置回放、对比和缩放仍可使用。** 缺少坐标的旧记录会提示不可用，不会猜测车辆位置。

已有 InputScope 用户可以用 `tools/migrate_inputscope.py` 迁移记录、使用偏好和私有底图库；原文件保留，数据不会加入 Git 或发布包。具体见 [隐私与迁移](docs/PRIVACY.md)。`Start Clean.cmd`、`Start Clean Controls.cmd`、`Start Demo.cmd` 继续提供旧版相同的启动方式。

## 开发与发布

双击 `Build.cmd` 安装固定构建依赖并生成 `dist/LMU-StintLab-v0.1.1-windows-x64.zip` 和 SHA256 文件。源码无需商业运行包，SDK 的 MIT 源码已包含。Python 3.13 x64 是当前验证的构建环境。

```powershell
.venv\Scripts\python.exe tools/run_tests.py
.venv\Scripts\python.exe tools/audit_publication.py
```

Windows CI 检查公开文件、运行隔离测试并构建便携 ZIP；推送与 VERSION 一致的 `v*` 标签，在全部验证通过后自动发布带 ZIP 和 SHA256 附件的 **公开 Release**。发布步骤见 [维护说明](docs/RELEASE.md)。

## English quick start

Download and extract the portable Windows x64 release, then double-click **Start.cmd**. For source ZIPs, run **Setup.cmd** first; it provisions Python 3.13 and verified dependencies. **Demo.cmd** uses synthetic telemetry only. No files are installed in the game directory. All racing data stays in `data/` locally. The UI is primarily Chinese. Read-only LMU shared memory is supplied by the bundled MIT-licensed SDK.

This is an independent community project, not affiliated with Studio 397, Motorsport Games, Fanatec or BMW. The schematic steering wheel uses original drawing code; no commercial artwork is included. Project source: MIT; upstream notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
