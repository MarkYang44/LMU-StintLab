## LMU StintLab v0.1.2 · Windows x64 精简便携版

下载下方 `LMU-StintLab-v0.1.2-windows-x64.zip`，完整解压到可写目录，双击 **Start.cmd** 即可启动。无需安装 Python，无需改动 LMU 游戏文件；保留 EXE 旁的 `_internal` 文件夹。**Demo.cmd** 可在不开游戏时演示。

- 精简便携包：移除自检入口、测试代码、构建发布脚本与开发文档，只保留运行文件、原有启动方式、使用说明和必要许可证。
- 整理源码仓库：回归测试集中在 `tests/`，维护工具集中在 `tools/`。GitHub Actions 继续验证，但测试程序不再打进发布 EXE。
- 新记录文件夹和导出比赛包自动包含 `Practice / Qualify / Race` 标签，比赛记录管理新增阶段列，可按标签搜索。旧文件夹保留原名，已有阶段信息直接显示。

保留现有油刹 / 转向 HUD、过滤后输入切换、纯净模式、自动记录、完整圈比较、赛道轨迹回放和轮胎 / 燃油 / 耐力赛分析。比赛包仍保留完整遥测、离线报告、圈文件和备注。

更新时保留自己的 `data/` 和 `local_settings.json`；发布包不包含个人记录、设置或授权不明的预置底图。ZIP 旁的 `.zip.sha256` 用于校验下载完整性。

**English:** Fully extract the Windows x64 portable ZIP and run **Start.cmd**. The lean package excludes developer tests, standalone environment-check tools and build tools while keeping all telemetry features and launch modes. Recordings and session archives now carry Practice / Qualify / Race labels. Existing private data stays local.
