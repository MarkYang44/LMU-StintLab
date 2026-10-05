# LMU StintLab · Windows x64 便携版

完整解压到可写文件夹，双击 **LMU-StintLab.exe** 打开控制中心，再点击 **启动 HUD**。无需安装 Python，无需往游戏目录复制文件。请保留 EXE 旁的 **_internal** 文件夹。

- 不开游戏时，在控制中心点击 **演示模式**；`Demo.cmd` 保留为快捷入口。
- 在控制中心的 **显示模式** 选择纯曲线；`Start Clean.cmd` 保留为快捷入口。
- 另一种纯净模式同时显示曲线、油刹柱形图和方向盘；启动脚本继续兼容。
- 控制中心按功能分类；**赛事复盘** 直接打开圈速单、比赛日志和 Review，**曲线对比** 选择同场 A / B 或跨场最快圈。
- HUD 标题栏菜单按钮打开控制中心；右键快捷菜单继续保留。`LMU-StintLab.exe --hud` 可直接进入旧 HUD。

仅 Qualify / Race 自动记录；Practice / Warmup 仅实时显示，旧记录保留。正常退出 HUD 会等待写入与报告完成；停止 HUD 后控制中心仍可用。记录保存在 `data/`。

要使用 RaceCom 原版圈速单和比赛日志，在 **图像与数据** 中选择自己 RaceCom 安装目录里的 **Image Generate.exe**，保留该目录下的 `Source` 文件夹。生成器不会随本软件分发；未配置时记录仍保存，可配置后补图。可明确选择 `native` 兼容版式；演示模式使用兼容版式。

完整操作见 [使用说明](docs/USAGE.md)，本机记录与设置保护见 [数据与隐私](docs/PRIVACY.md)。便携包只包含运行文件、启动入口、使用文档和必要许可证；开发测试、构建发布脚本和自检程序留在源码仓库。

更新时保留自己的 `data/` 和 `local_settings.json`。演示记录也仅保存在本机；软件不会自动上传任何遥测数据。打不开程序时查看 `data/startup_error.log`。

源码、更新与问题反馈：[MarkYang44/LMU-StintLab](https://github.com/MarkYang44/LMU-StintLab)。公开版不附带授权不明的赛道底图，仍可根据记录中的世界坐标 / GPS 展示实测轨迹。

**English:** Fully extract, then run **LMU-StintLab.exe**. Keep **_internal** next to the executable. Python is bundled. No game files are modified; all telemetry and settings stay local. Developer tests and standalone environment-check tools are excluded from this portable package.
