## LMU StintLab v0.1.5 · 控制中心与 RaceCom 原版报告

下载下方 `LMU-StintLab-v0.1.5-windows-x64.zip`，完整解压到可写目录，双击 **Start.cmd** 打开控制中心，再点击 **启动 HUD**。无需安装 Python，保留 `_internal` 文件夹。更新时保留自己的 `data/` 和 `local_settings.json`。

- 新增磨砂玻璃风格控制中心，按启动与 HUD、赛事复盘、曲线对比、采样与遥测、图像与数据分组。直接查看圈速单、比赛日志、Review、同场 A / B 与跨场最快圈。
- 在图像与数据中选择用户自有 RaceCom **Image Generate.exe** 后，赛后静默调用原版生成器，保留其浅色布局、字体、颜色与已有车辆校准。结果仍在同场赛事目录；没有完成圈时只生成比赛日志。第三方程序与照片不随本软件分发。
- 自动录制仅保留 Qualify / Race；Practice / Warmup 保持实时 HUD，不写赛事文件。旧记录保留，手动导入不受限制。停止 HUD 后控制中心继续可用。
- 新记录增加独立赛事事件流：官方圈号与圈速、三个分段、观测名次、进站、处罚数量变化、无效圈、碰撞与赛事阶段。连续碰撞合并；出界仅为边界估算，不是官方警告。
- 完整日志保留；比赛包包含原版图片与适配文件。未配置原版时保存数据并提示配置；只有明确选择 native 才使用兼容版式（长比赛分页），演示默认使用兼容版式。
- 记录管理页新增 **圈速单 / 比赛日志**，可为旧记录补图；旧记录未采集的名次 / 分段 / 碰撞显示未知，不改写原始遥测。
- 可选私有车型照片按校准范围留边、保持比例放置，未知车型显示文字。公开源码与便携包不含 RaceCom 程序或第三方车辆照片。

图像生成有超时和子进程清理，两个图片成功后才提交；更换版式保留旧报告备份。PIT / 部分记录 / 未验证圈取消最快圈统计，原始有效标志保留，不表示游戏处罚。赛事事件只在变化时写入，原有高频输入、参考圈、赛道回放和耐力赛分析保持兼容。

更新时保留自己的 `data/` 和 `local_settings.json`；发布包不包含个人记录、设置或授权不明的预置底图。ZIP 旁的 `.zip.sha256` 用于校验下载完整性。

精简便携包继续排除开发测试、自检入口、构建脚本和开发文档。更多维护说明和有条件的性能测量见源码中的 `docs/ARCHITECTURE.md` 与 `docs/PERFORMANCE.md`。

**English:** Adds a categorized frosted-glass control center for HUD startup, settings, session reviews and direct report access. Configure your own RaceCom Image Generate.exe to generate reports using its original light layout and artwork calibration. Third-party software and images are not distributed. Automatic recording is limited to qualifying and race sessions; practice and warmup remain live-only. Existing records, preferences and game files are preserved. Explicit native compatibility mode and self-contained synthetic demos remain available.
