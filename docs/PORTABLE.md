# LMU Stintrix · Windows x64 便携版

完整解压到可写文件夹，双击 **LMU-Stintrix.exe** 打开控制中心，再点击 **启动 HUD**。无需安装 Python，无需往游戏目录复制文件。请保留 EXE 旁的 **_internal** 文件夹。

右上角可切换深色 / 浅色工业风主题；选择只保存在本机。赛事列表支持平滑滚动、Ctrl / Shift 多选和键盘浏览，切换主题不中断正在运行的 HUD。

- 不开游戏时，在控制中心点击 **演示模式**；`Demo.cmd` 保留为快捷入口。
- 在控制中心的 **显示模式** 选择纯曲线；`Start Clean.cmd` 保留为快捷入口。
- 另一种纯净模式同时显示曲线、油刹柱形图和方向盘；启动脚本继续兼容。
- 控制中心按功能分类；**赛事复盘** 直接打开圈速单、比赛日志和 Review，**曲线对比** 选择同场 A / B 或跨场最快圈。
- HUD 标题栏菜单按钮打开控制中心；右键快捷菜单继续保留。`LMU-Stintrix.exe --hud` 可直接进入旧 HUD。

仅 Qualify / Race 自动记录；Practice / Warmup 仅实时显示，旧记录保留。正常退出 HUD 会等待写入与报告完成；停止 HUD 后控制中心仍可用。记录保存在 `data/`。

要使用 RaceCom 原版圈速单和比赛日志，在 **图像与数据** 中选择自己 RaceCom 安装目录里的 **Image Generate.exe**，保留该目录下的 `Source` 文件夹。生成器不会随本软件分发；未配置时记录仍保存，可配置后补图。可明确选择 `native` 兼容版式；演示模式使用兼容版式。

完整操作见 [使用说明](docs/USAGE.md)，本机记录与设置保护见 [数据与隐私](docs/PRIVACY.md)。便携包只包含运行文件、启动入口、使用文档和必要许可证；开发测试、构建发布脚本和自检程序留在源码仓库。

更新时保留自己的 `data/` 和 `local_settings.json`。演示记录也仅保存在本机；软件不会自动上传任何遥测数据。打不开程序时查看 `data/startup_error.log`。

源码、更新与问题反馈：[MarkYang44/LMU-Stintrix](https://github.com/MarkYang44/LMU-Stintrix)。公开版不附带授权不明的赛道底图，仍可根据记录中的世界坐标 / GPS 展示实测轨迹。

**English:** Fully extract, then run **LMU-Stintrix.exe**. Keep **_internal** next to the executable. Python is bundled. No game files are modified; all telemetry and settings stay local. Developer tests and standalone environment-check tools are excluded from this portable package.

## Windows 快捷启动与表单操作

控制中心 **运行与 HUD → Windows 快捷启动 → 添加 / 更新开始菜单** 会创建当前用户的 `LMU Stintrix` 快捷方式。程序会核验 Windows 应用目录，确认识别后可在 Windows 搜索中输入 `Stintrix` 或 `LMU`，也可从开始菜单的所有应用启动；无需管理员权限。可右键搜索结果固定到开始菜单或任务栏。移动便携文件夹后，重新打开 EXE 点击更新入口即可；移除入口不会删除程序或个人数据。首次解压仍需保留完整 `_internal` 文件夹。

表单使用统一的切角输入框与下拉面板：黄绿焦点描边、短展开过渡、平滑选项高亮，兼容深浅主题。下拉框支持方向键、Home / End、输入前缀跳转、Enter 确认、Escape 取消和 Tab 切换；长列表可滚动。动画仅在交互时运行，离开页面会清理弹层与回调。

已启用的入口在新版启动时会按当前登录用户检查并修复；检查在后台进行。若显示“Windows 尚未列出应用”，可稍后再次点击更新。入口识别状态保存在本机 `data/desktop_registration.json`，不参与发布。

控制中心顶部 **EN / 中文** 可切换整个菜单语言，重启后保留；主题和语言分别保存到本机 `data/interface_settings.json`。赛道指南与车型图鉴随菜单语言切换，赛事记录、配置值和文件名不因语言切换而改变。
