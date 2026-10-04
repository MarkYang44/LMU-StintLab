## LMU StintLab v0.1.3 · 运行优化与模块拆分

下载下方 `LMU-StintLab-v0.1.3-windows-x64.zip`，完整解压到可写目录，双击 **Start.cmd** 即可启动。无需安装 Python，无需改动 LMU 游戏文件；保留 EXE 旁的 `_internal` 文件夹。**Demo.cmd** 可在不开游戏时演示。

- HUD 波形按时间索引提取可见窗口，避免扫描整段历史；实际频率统计避免构建临时时间列表。保留完整 20 秒双通道历史、尖峰与采样设置。
- 官方日志圈条件使用二分查询，减少重复临时分配；高频实时分析复用一次样本转换，共享内存车辆查找避免先构建整张车辆列表。
- 采集、录制、报告、HUD、几何与配置拆成独立模块，核心和命令行分析按需加载界面库。
- 文件导入、指定圈提取、比赛包传输、库扫描和参考圈加载统一到两条后台任务线程。界面回调在主线程运行，正常退出等待已提交的任务完成。
- 修复场次切换时 elapsed time 与上一场相同导致首帧未记录的问题。

保留现有油刹 / 转向 HUD、过滤后输入切换、纯净模式、自动记录、完整圈比较、赛道轨迹回放和轮胎 / 燃油 / 耐力赛分析。比赛包仍保留完整遥测、离线报告、圈文件和备注。

更新时保留自己的 `data/` 和 `local_settings.json`；发布包不包含个人记录、设置或授权不明的预置底图。ZIP 旁的 `.zip.sha256` 用于校验下载完整性。

精简便携包继续排除开发测试、自检入口、构建脚本和开发文档。更多维护说明和有条件的性能测量见源码中的 `docs/ARCHITECTURE.md` 与 `docs/PERFORMANCE.md`。

**English:** Fully extract the Windows x64 portable ZIP and run **Start.cmd**. This release separates telemetry, recording, reports and the HUD; indexes visible waveform windows and native lap-condition lookups; and uses two background workers with main-thread callbacks and safe shutdown. All telemetry features, data formats and launch modes remain compatible. Private data stays local, and developer tests/tools stay out of the portable bundle.
