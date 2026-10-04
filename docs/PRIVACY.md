# 本地数据与迁移

以下内容属于本机私有数据，不进入 Git 或发布 ZIP：

- `data/` 内的 Logs、DemoLogs、ImportedLogs、RecoveredLogs、圈文件、CSV、数据库、HTML / SVG 报告、诊断和用户设置。
- 根目录 `local_settings.json` 中的机器路径。
- `.venv/`、`_local/`、dist、构建缓存、备份和验证目录。

`.gitignore` 使用根目录白名单，额外排除嵌套日志和常见遥测文件；`tools/audit_publication.py` 审计 Git 实际暂存的文本文件并拒绝不在白名单的文件、凭证和个人机器路径。CI 在构建前重复检查。公开源码不会自动同步 `data/`。

最快圈与 HTML 报告包含个人姓名、圈速、日期和原生记录信息，分享前应自行脱敏。不要把这些文件改名成源文件，也不要用 `git add -f` 绕过排除规则。脚本只能检测常见敏感项，手动分享前仍需检查。

迁移旧版 InputScope：关闭两个版本后，把原版 Logs、ImportedLogs、RecoveredLogs 和需要的设置复制到新版 `data/` 的同名位置。DemoLogs 可选。不要复制原 EXE、runtime、vendor、src 或旧 `_verification`。原记录格式与 InputScope 标识保留以维持兼容；原数据不需要改写。重新打开报告会在自己的私有数据目录生成新版 HTML。

运行时不上传记录或调用外部 AI。联网仅发生在首次源码安装 / 构建依赖下载、你主动打开外部链接，以及 GitHub 的发布流程。环境检查可能显示数据目录；请勿将未脱敏检查输出作为公开 issue 附件。
