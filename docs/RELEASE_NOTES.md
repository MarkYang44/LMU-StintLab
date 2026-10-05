# LMU StintLab v0.1.8 · 双主题工业界面与平滑列表

完整解压 `LMU-StintLab-v0.1.8-windows-x64.zip`，双击 **LMU-StintLab.exe**。保留 `_internal` 文件夹；更新时保留自己的 `data/` 和 `local_settings.json`。

- 深色主题使用炭黑 + 黄绿，浅色使用暖灰白 + 石墨文字 + 黄绿；切角卡片、工业刻度、短位移与悬停反馈参考终末地风格。右上角即时切换，主题偏好只保存在本机。
- 主题切换保留页面、搜索、赛事选择和表单，正在运行的 HUD、采集线程与记录器继续工作。纯净 HUD 保持全黑，油门 / 刹车 / 转向仍用绿 / 红 / 蓝区分，浅色面板使用更深的色调。
- 赛事列表改为独立虚拟组件，按像素平滑滚动；连续滚轮输入累积，选中立即生效并带颜色过渡。保留 Ctrl / Shift 多选、双击或 Enter 复盘，新增方向键、Home / End / PageUp / PageDown 浏览。
- 只绘制可见记录行，文本缓存有界；停止交互后动画不继续运行。刷新或过滤保留真实赛事身份，滚动位置随内容边界安全收敛。
- EXE、任务栏、标题栏和侧栏改用项目所有者指定的 GTD 菜单角色图标，保留原始 ICO 的六个尺寸。构建与发布校验精确资产哈希。
- 新生成的 Review、圈速对比与地图 / 遥测图表支持深浅主题，HTML 仍可离线分享；旧 HTML 保留。RaceCom 原版两张图的版式保持不变。
- 个人圈速、车型照片、私有设置和 RaceCom 程序继续排除出公开仓库及便携包。仅 Qualify / Race 自动记录；无需改动游戏文件。

**English:** Two Endfield-inspired industrial themes, the requested GTD menu icon, virtualized pixel-smooth session scrolling and animated selection. Switch themes without restarting telemetry. Launch the EXE directly; existing private data and RaceCom rendering remain compatible.
