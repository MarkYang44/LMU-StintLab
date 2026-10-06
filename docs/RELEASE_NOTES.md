## 0.2.2

- 菜单标识采用真正透明背景，分别提供深色白字 / 黄绿和浅色炭黑 / 橄榄黄绿两版，与侧栏背景融合。
- 赛道、车型、车型推荐及资料对比卡片的来源链接默认折叠，点击展开；保留复制功能，切换主题与语言时保留已展开状态。
- EXE 的黑底白字 STX + STINTRIX 图标保持原样。

## 0.2.1

- 菜单采用彩色黑底 STX / STINTRIX 标识；EXE、任务栏与开始菜单统一为黑底白色 STX + STINTRIX 完整图标。
- Windows 图标提供 16 / 32 / 48 / 64 / 128 / 256 像素，移除旧 GTD 角色图标。
- 保留 0.2.0 的 LMU-Stintrix 更名、中文 / English 开关和旧赛事包兼容。

## 0.2.0

- 项目统一更名为 LMU-Stintrix：控制中心、HUD、Windows 应用入口、EXE、报告页面、源码文档与便携包均使用新名称。
- 控制中心提供中文 / English 开关；页面、按钮、选项、设置和状态消息可切换，语言偏好仅保存在本机。
- 赛道指南与车型图鉴同步菜单语言；切换保留页面、筛选、多选和运行中的 HUD。
- 新导出的赛事包使用 `.stintrix.zip`，旧格式赛事包与原有记录仍可读取，不修改采样数据。

## 0.1.14

- 修复打开下拉选项后框外鼠标失效的问题；点击导航或按钮会在同一次点击中关闭菜单并执行操作。
- 下拉菜单不再抢占鼠标，保留键盘、滚动和动画；切页、调整窗口大小和失焦时清理弹出层。
- 开始菜单入口增加文件刷新通知与 Windows 应用目录核验；已启用入口由实际运行程序的用户在后台检查并修复。
- 入口识别状态仅保存在本机，不打包或上传个人赛事记录。

## 0.1.13

- 提供当前用户的 Windows 开始菜单 / 搜索入口，菜单内一键创建、修复或移除；移动便携目录后可更新路径。
- 统一菜单、车型设置与圈选择的原生下拉面板，加入短展开动画、平滑选项高亮和键盘操作。
- 统一主要设置与搜索输入框的切角表面、焦点反馈，兼容深浅主题；无新增运行依赖，动画结束后无帧循环。

# LMU Stintrix v0.1.12 · 完整原生图文指南

完整解压 `LMU-Stintrix-v0.1.12-windows-x64.zip`，双击 **LMU-Stintrix.exe**。保留 `_internal`；更新时保留 `data/` 与 `local_settings.json`。

- 赛道指南、车型图鉴的完整图片、描述、练习建议与原始来源全部在程序菜单中呈现，移除浏览器跳转入口。
- 单列完整卡片，每页 3 条；原生搜索、组别 / 车型 / 收藏筛选、中英切换、收藏、推荐展开和 A / B / C 对比；对比同样采用单列，避免信息过密。
- 深浅终末地主题统一；收藏与语言保存到本机私有配置，排除出赛事包和发布。
- 图片随可视区域按需解码，离开视野、翻页与关闭后释放；无需浏览器内核、GTD 后端或常驻服务器。

- 页面关闭时显式清理搜索变量回调，避免反复切换页面后滞留。

**English:** Complete native circuit guide and car catalog with spacious single-column cards, in-menu pictures, descriptions, favorites and comparisons. No browser navigation.

## LMU Stintrix v0.1.10 · GTD 离线赛道指南与车型图鉴

完整解压 `LMU-Stintrix-v0.1.10-windows-x64.zip`，双击 **LMU-Stintrix.exe**，保留 `_internal`；更新时保留 `data/` 和 `local_settings.json`。

- 左侧新增赛道指南、车型图鉴；原生菜单提供搜索、车型组别筛选及练习摘要。
- 自带完整离线页面：18 条赛道、24 台车型、144 条推荐（含 Sleeper 之选）、42 张官方来源图片，保留 GTD 资料日期、来源和未验证标记。
- 深浅终末地工业主题，中文 / English、收藏、2–3 项并排对比、赛道和车型互相跳转；图片延迟加载，展开时才生成推荐详情。
- 指南按需加载，不启动 GTD / Flask 或常驻服务器；收藏保存在浏览器本地，个人赛事仍排除出发布。

**English:** Bundled offline GTD circuit guide and car catalog, integrated into the desktop navigation with Stintrix's dark/light industrial themes.

## LMU Stintrix v0.1.9 · 赛事批量导出

完整解压 `LMU-Stintrix-v0.1.9-windows-x64.zip`，双击 **LMU-Stintrix.exe**。保留 `_internal` 文件夹；更新时保留自己的 `data/` 和 `local_settings.json`。

- 图像与数据页增加赛事复选框、表头全选、全选当前搜索列表、清除选择与已选数量。
- 一次选择导出目录，后台逐场生成独立且完整校验的 ZIP；部分失败不影响其他赛事，重复点击不会启动第二批任务。
- GTD 六尺寸图标继续内嵌在 EXE 中，深浅主题和既有遥测功能保持兼容。
- 完整文件夹可迁移到其他位置；默认数据、RaceCom 生成器和资产使用项目内相对路径，个人记录仍排除出公开发布。

**English:** Checkbox-based bulk session exports. Select a destination once; each checked session becomes a separately verified ZIP, with partial failures reported independently.

## v0.1.8 · 双主题工业界面与平滑列表

完整解压 `LMU-Stintrix-v0.1.8-windows-x64.zip`，双击 **LMU-Stintrix.exe**。保留 `_internal` 文件夹；更新时保留自己的 `data/` 和 `local_settings.json`。

- 深色主题使用炭黑 + 黄绿，浅色使用暖灰白 + 石墨文字 + 黄绿；切角卡片、工业刻度、短位移与悬停反馈参考终末地风格。右上角即时切换，主题偏好只保存在本机。
- 主题切换保留页面、搜索、赛事选择和表单，正在运行的 HUD、采集线程与记录器继续工作。纯净 HUD 保持全黑，油门 / 刹车 / 转向仍用绿 / 红 / 蓝区分，浅色面板使用更深的色调。
- 赛事列表改为独立虚拟组件，按像素平滑滚动；连续滚轮输入累积，选中立即生效并带颜色过渡。保留 Ctrl / Shift 多选、双击或 Enter 复盘，新增方向键、Home / End / PageUp / PageDown 浏览。
- 只绘制可见记录行，文本缓存有界；停止交互后动画不继续运行。刷新或过滤保留真实赛事身份，滚动位置随内容边界安全收敛。
- EXE、任务栏、标题栏和侧栏改用项目所有者指定的 GTD 菜单角色图标，保留原始 ICO 的六个尺寸。构建与发布校验精确资产哈希。
- 新生成的 Review、圈速对比与地图 / 遥测图表支持深浅主题，HTML 仍可离线分享；旧 HTML 保留。RaceCom 原版两张图的版式保持不变。
- 个人圈速、车型照片、私有设置和 RaceCom 程序继续排除出公开仓库及便携包。仅 Qualify / Race 自动记录；无需改动游戏文件。

**English:** Two Endfield-inspired industrial themes, the requested GTD menu icon, virtualized pixel-smooth session scrolling and animated selection. Switch themes without restarting telemetry. Launch the EXE directly; existing private data and RaceCom rendering remain compatible.
