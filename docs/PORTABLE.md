# LMU StintLab · Windows x64 便携版

完整解压到可写文件夹，双击 **Start.cmd**。无需安装 Python，无需往游戏目录复制文件。请保留 EXE 旁的 **_internal** 文件夹。

- **Demo.cmd / Start Demo.cmd**：不开游戏时演示合成曲线。
- **Start Clean.cmd**：只显示曲线。
- **Start Clean Controls.cmd**：显示曲线、油刹柱形图和方向盘。
- 右键 HUD 打开设置、比赛记录管理、圈速对比和退出菜单。

进入 LMU 驾驶会话后自动记录；正常退出 HUD 会等待写入与报告完成。记录保存在 `data/`，新文件夹与导出比赛包带 `Practice / Qualify / Race` 阶段标签。

完整操作见 [使用说明](docs/USAGE.md)，本机记录与设置保护见 [数据与隐私](docs/PRIVACY.md)。便携包只包含运行文件、启动入口、使用文档和必要许可证；开发测试、构建发布脚本和自检程序留在源码仓库。

更新时保留自己的 `data/` 和 `local_settings.json`。演示记录也仅保存在本机；软件不会自动上传任何遥测数据。打不开程序时查看 `data/startup_error.log`。

源码、更新与问题反馈：[MarkYang44/LMU-StintLab](https://github.com/MarkYang44/LMU-StintLab)。公开版不附带授权不明的赛道底图，仍可根据记录中的世界坐标 / GPS 展示实测轨迹。

**English:** Fully extract, then run **Start.cmd**. Keep **_internal** next to the executable. Python is bundled. No game files are modified; all telemetry and settings stay local. Developer tests and standalone environment-check tools are excluded from this portable package.
