# 维护与发布

在 Windows x64 上使用 CPython 3.13。默认构建不读取任何旧插件目录，资产按固定清单加入 EXE；每次使用新的暂存目录，现有记录和旧构建不会被清除。

1. 修改 VERSION 与应用版本，固定需要更新的依赖版本，执行 `Build.cmd`。
2. 执行 `.venv\Scripts\python.exe tools/run_tests.py`。测试只生成合成记录；每条测试独立进程，避免 Tk 对象在工作线程销毁。
3. 对解压后的新 ZIP 运行 `Check.cmd`、`Demo.cmd`，正常关闭后检查完整圈和离线报告。也可执行 `LMU-StintLab.exe --release-smoke`；43 秒后在私有 `data/release-smoke.json` 写入验证结果。
4. 使用明确文件清单暂存源码，然后执行 `.venv\Scripts\python.exe tools/audit_publication.py`。检查 `git diff --cached --stat`。不要暂存 dist 或任何个人记录。
5. 正常提交并推送；CI 运行测试、构建和便携包验证，上传 ZIP 与 SHA256 为 Actions 构建产物。
6. 推送与 VERSION 一致的 `v*` 标签，例如 `v0.1.0`。工作流生成草稿 Release，维护者下载、验证并点击发布后，其他用户就能从 Releases 下载。草稿不会自动公开。

ZIP 内包括独立解释器、Tk、DuckDB、离线模板、许可证及 build-manifest.json，不要求用户安装 RaceCom 或 Python。GitHub 的源码 Download ZIP 不包含二进制，但 Setup.cmd 可一次配置并启动。

源码与输出分离的改动限于路径、SDK / DuckDB 依赖及发行脚本；公开版无授权不明的预置底图库。车轮盘体为程序绘制的示意图。新增静态素材前必须确认可再分发许可。
