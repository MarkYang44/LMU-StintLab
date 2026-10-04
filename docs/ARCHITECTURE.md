# 模块与维护边界

入口 `src/inputscope.py` 保留命令行和原有类 / 函数导出。`App` 及 Tk 对象按需加载；导入采集核心或运行 `--version` / `--import-duckdb` 无需加载 Tk。启动脚本、快捷键、HUD 模式和数据路径保持兼容。

| 模块 | 职责 |
| --- | --- |
| app_config.py / paths.py | 公共 CSV 列定义、界面常量、便携资源与本机私有路径 |
| telemetry.py | 验证共享内存快照、提取遥测；只读打开已有 LMU_Data |
| engine.py / sampling.py | 采样策略、时间调度、实时分析与双通道历史 |
| recorder.py / storage.py | 原样精度的 CSV、检查点、写盘故障与恢复 |
| session_reports.py / reporting.py | 结束后的分析调度、流式离线 HTML |
| race_journal.py | 官方计时与赛事事件；只对状态变化写入独立有界队列，不扩充高频输入行 |
| race_model.py / race_report.py | 流式圈摘要、官方圈号对齐、完整事件日志与带校验的生成缓存 |
| race_images.py / windows_png.py / race_art.py | 逐页高清 PNG、Windows 原生 GDI+ 与可选私有车辆照片 |
| hud.py / hud_geometry.py | Windows Tk 窗口、交互与绘制、几何和方向盘 |
| background.py | 至多两条后台任务线程；结果回到 GUI 主线程 |
| laps.py / sessionlab.py / reference.py | 完整圈、选定圈与参考圈分析 |
| vehiclelab.py / endurance.py | 轮胎、燃油、能量、进站、stint 和天气 |
| management.py / session_archive.py | 比赛库、备注和比赛包导入导出 |
| *view.js / laplab.js / dataview.js | 独立网页的图表、地图、分析和压缩数据读取 |

核心模块不导入 HUD 或 Tk，也不依赖入口模块，因此可独立测试或用于无界面的采集 / 分析工具。界面读取 Engine 的快照和有界缓存，不负责共享内存读取或比赛格式写入。

## 时间索引

NumericRing 保留 float64 数据和逻辑顺序。`lower_bound` 在首列时间戳上二分，支持环形回绕与相等时间；`iter_since` 只构建窗口内行，`rate_since` 直接计算首尾跨度。使用时间索引的调用者必须追加非递减时间戳，并在场次重置时清空。Engine 的共享缓存仍受原有锁保护；GUI 的绘制计数缓存仅由 GUI 线程访问。

完整 20 秒双通道历史、极值桶、单帧尖峰和完整赛事 CSV 都保留。性能收益来自跳过不可见行与避免临时时间列表，不依赖降低采样频率。

## 后台任务与退出

App 在主线程提交任务，并定时从完成队列取结果。后台任务禁止调用 Tk，包括 `root.after`。日志导入、完整圈提取、比赛包传输、库扫描和参考圈加载共享两线程执行器。关闭窗口时禁止新任务，完成已提交的工作，再释放界面；完成结果在关闭期间不再触发 UI 操作。

Recorder 的写盘及结束报告保留各自生命周期，App 继续等待 CSV 写完和报告完成。结束报告保持串行处理，避免多个大赛事同时生成网页的内存峰值。

赛后图片复用同一后台生命周期，在事件队列排空后生成。官方 `mLastSector2` 是 S1+S2，必须相减得到 S2；官方已完成圈数与可能从 0 开始的遥测圈号通过圈起点对齐。缓存 scoring 的车辆扫描，但同一时间戳下的终场名次 / 圈数变化仍采集；不把当前圈的计圈标志误用作上一圈有效性。事件记录与高频输入独立，有界队列溢出或写盘失败会显式报错。

图片生成使用系统 GDI+，无需第三方绘图运行包。每次仅持有一页光栅；CSV 摘要不持有整场样本，内存随圈数 / 事件数增长。PNG 保存到临时文件后替换，所有页完成后写入带源文件 / 输出 SHA256 的生成回执。旧记录的未知字段不回填估算分段。全局私有图片库不进入发布 ZIP，比赛包保留已生成的图片。

## 兼容与验证

CSV 字段、JSON 格式标记、原始 / 过滤后输入、采样设置和旧记录路径保持一致。入口继续导出 Engine、Recorder、SharedReader、App 及既有辅助函数；测试替换全局依赖时应 patch 实际所属模块，例如 `recorder.make_report` 或 `hud.ROOT`。

开发测试只放在 tests/，开发工具只放在 tools/；便携包和编译 EXE 继续排除这些模块。发布白名单与个人数据哈希校验分别验证分享内容和本机数据保护。
