## LMU StintLab v0.1.4 · 赛后圈速单与比赛日志

下载下方 `LMU-StintLab-v0.1.4-windows-x64.zip`，完整解压到可写目录，双击 **Start.cmd**。无需安装 Python，保留 EXE 旁的 `_internal` 文件夹。更新时保留自己的 `data/` 和 `local_settings.json`。

- 比赛结束后自动生成 1800 像素宽的圈速单与比赛日志 PNG，和完整 JSON / TXT 一起保存在同场赛事目录，无需运行 RaceCom 或 Image Generate.exe。
- 新记录增加独立赛事事件流：官方圈号与圈速、三个分段、观测名次、进站、处罚数量变化、无效圈、碰撞与赛事阶段。连续碰撞合并；出界仅为边界估算，不是官方警告。
- 长赛事自动分页，完整日志不截断；比赛包自动包含图片与事件文件。恢复中断记录时一并恢复已提交事件。
- 记录管理页新增 **圈速单 / 比赛日志**，可为旧记录补图；旧记录未采集的名次 / 分段 / 碰撞显示未知，不改写原始遥测。
- 可选私有车型照片按校准范围留边、保持比例放置，未知车型显示文字。公开源码与便携包不含 RaceCom 程序或第三方车辆照片。

图片使用 Windows 原生绘制，逐页生成；赛事事件只在变化时写入，不扩充高频输入行。原有 HUD、完整圈对比、赛道回放和轮胎 / 燃油 / 耐力赛分析保持兼容。个人记录、设置、车型照片留在本机。

更新时保留自己的 `data/` 和 `local_settings.json`；发布包不包含个人记录、设置或授权不明的预置底图。ZIP 旁的 `.zip.sha256` 用于校验下载完整性。

精简便携包继续排除开发测试、自检入口、构建脚本和开发文档。更多维护说明和有条件的性能测量见源码中的 `docs/ARCHITECTURE.md` 与 `docs/PERFORMANCE.md`。

**English:** Automatically creates high-resolution lap sheets and race-log PNGs alongside each completed session. Official lap timing, sectors and compact race events are recorded separately from high-rate inputs. Long sessions are paginated without truncating the full JSON/text log, and session ZIPs include the generated reports. Legacy sessions can generate reports from the library, with missing scoring fields marked unknown. Optional calibrated car artwork stays private and is not distributed. No RaceCom executable, extra graphics package, or game-file changes are required.
