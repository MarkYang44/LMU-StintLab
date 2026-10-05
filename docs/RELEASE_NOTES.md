# LMU StintLab v0.1.7 · 新桌面界面与赛车图标

下载 `LMU-StintLab-v0.1.7-windows-x64.zip`，完整解压后直接双击 **LMU-StintLab.exe**。无需安装 Python，也无需通过 CMD 启动。保留 EXE 旁的 `_internal` 文件夹；更新时保留自己的 `data/` 和 `local_settings.json`。

- 修复 StintLab 品牌文字在 Windows 缩放下被裁切：品牌按实际字体宽度布局，窗口尺寸和控件间距适配 DPI，宽屏设置卡片并排，窄屏自动纵向排列。
- 重新设计侧栏、玻璃卡片、图标、按钮与遥测开关。增加导航滑动、页面淡入位移、悬停与按压反馈、平滑滚动和开关动画；过渡结束后不继续调度动画帧。
- 修复页面过渡后的滚动原点，确保第一张卡片的顶部圆角和内容不会被裁切。
- 取消整窗透明，避免桌面文字透入干扰阅读；保留深蓝玻璃层次、柔和边缘高光与 Windows 圆角。
- 新图标以用户提供的 Endfield 工业倒三角为灵感，融入赛车走线与方格旗。EXE、任务栏、窗口和控制中心使用统一身份，并包含多分辨率图标与版本信息。
- 原版 RaceCom 报告、赛事复盘、完整圈 A/B、赛事包、HUD 与所有遥测功能保持兼容；仍仅自动记录 Qualify / Race。个人记录、设置与游戏文件不改动。

源代码中的 SVG 可编辑；PNG / ICO 在构建时由 Windows GDI+ 生成，不引入新的浏览器或图像运行库。公开包继续排除开发测试、个人数据、RaceCom 程序与车辆照片。

**English:** Launch LMU-StintLab.exe directly. This release adds a DPI-aware desktop layout, animated navigation and controls, readable glass-style surfaces, and a new racing-themed app icon. Existing telemetry, RaceCom reports and local records remain compatible.
