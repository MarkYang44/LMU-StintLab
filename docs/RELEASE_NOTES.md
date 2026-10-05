# LMU StintLab v0.1.10 · GTD 离线赛道指南与车型图鉴

完整解压 `LMU-StintLab-v0.1.10-windows-x64.zip`，双击 **LMU-StintLab.exe**，保留 `_internal`；更新时保留 `data/` 和 `local_settings.json`。

- 左侧新增赛道指南、车型图鉴；原生菜单提供搜索、车型组别筛选及练习摘要。
- 自带完整离线页面：18 条赛道、24 台车型、144 条推荐（含 Sleeper 之选）、42 张官方来源图片，保留 GTD 资料日期、来源和未验证标记。
- 深浅终末地工业主题，中文 / English、收藏、2–3 项并排对比、赛道和车型互相跳转；图片延迟加载，展开时才生成推荐详情。
- 指南按需加载，不启动 GTD / Flask 或常驻服务器；收藏保存在浏览器本地，个人赛事仍排除出发布。

**English:** Bundled offline GTD circuit guide and car catalog, integrated into the desktop navigation with StintLab's dark/light industrial themes.

## LMU StintLab v0.1.9 · 赛事批量导出

完整解压 `LMU-StintLab-v0.1.9-windows-x64.zip`，双击 **LMU-StintLab.exe**。保留 `_internal` 文件夹；更新时保留自己的 `data/` 和 `local_settings.json`。

- 图像与数据页增加赛事复选框、表头全选、全选当前搜索列表、清除选择与已选数量。
- 一次选择导出目录，后台逐场生成独立且完整校验的 ZIP；部分失败不影响其他赛事，重复点击不会启动第二批任务。
- GTD 六尺寸图标继续内嵌在 EXE 中，深浅主题和既有遥测功能保持兼容。
- 完整文件夹可迁移到其他位置；默认数据、RaceCom 生成器和资产使用项目内相对路径，个人记录仍排除出公开发布。

**English:** Checkbox-based bulk session exports. Select a destination once; each checked session becomes a separately verified ZIP, with partial failures reported independently.

## v0.1.8 · 双主题工业界面与平滑列表

完整解压 `LMU-StintLab-v0.1.8-windows-x64.zip`，双击 **LMU-StintLab.exe**。保留 `_internal` 文件夹；更新时保留自己的 `data/` 和 `local_settings.json`。

- 深色主题使用炭黑 + 黄绿，浅色使用暖灰白 + 石墨文字 + 黄绿；切角卡片、工业刻度、短位移与悬停反馈参考终末地风格。右上角即时切换，主题偏好只保存在本机。
- 主题切换保留页面、搜索、赛事选择和表单，正在运行的 HUD、采集线程与记录器继续工作。纯净 HUD 保持全黑，油门 / 刹车 / 转向仍用绿 / 红 / 蓝区分，浅色面板使用更深的色调。
- 赛事列表改为独立虚拟组件，按像素平滑滚动；连续滚轮输入累积，选中立即生效并带颜色过渡。保留 Ctrl / Shift 多选、双击或 Enter 复盘，新增方向键、Home / End / PageUp / PageDown 浏览。
- 只绘制可见记录行，文本缓存有界；停止交互后动画不继续运行。刷新或过滤保留真实赛事身份，滚动位置随内容边界安全收敛。
- EXE、任务栏、标题栏和侧栏改用项目所有者指定的 GTD 菜单角色图标，保留原始 ICO 的六个尺寸。构建与发布校验精确资产哈希。
- 新生成的 Review、圈速对比与地图 / 遥测图表支持深浅主题，HTML 仍可离线分享；旧 HTML 保留。RaceCom 原版两张图的版式保持不变。
- 个人圈速、车型照片、私有设置和 RaceCom 程序继续排除出公开仓库及便携包。仅 Qualify / Race 自动记录；无需改动游戏文件。

**English:** Two Endfield-inspired industrial themes, the requested GTD menu icon, virtualized pixel-smooth session scrolling and animated selection. Switch themes without restarting telemetry. Launch the EXE directly; existing private data and RaceCom rendering remain compatible.
