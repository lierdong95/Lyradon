# 可选的人格文本同步工具

这是通用的本地文本同步程序，不包含人格插件、人格文本、角色数据库或任何真实流水线标识。四个功能模块无需它即可运行。

仅适配 LangBot 4.11.4 的 `legacy_pipelines` 表及 `ai/local-agent/prompt` 配置结构；其他版本先核对数据库结构。启用后会把你提供的本地文本写入指定流水线提示词，应先自行备份数据库。

## 使用

1. 安装 Python 3.10+，运行 `setup_personasync.bat`；只使用标准库。
2. 在项目根自行创建 `persona.txt`（不应提交），在 LangBot 中创建流水线并取得自己的 UUID。
3. 编辑生成的 `persona-sync.json`：填入自己的 `pipeline_uuid`，确认文件和数据库路径，再把 `enabled` 改为 `true`。所有相对路径以公开项目根目录为基准。
4. 运行 `persona-sync.bat`；未配置或默认禁用时，程序不访问数据库、不启动或停止服务。

`restart_langbot` 默认 `false`，同步后按需要手动重启。若主动开启自动重启，工具只读取指定 PID 文件，核实该进程的可执行文件正是配置的 `langbot_executable` 后才结束其进程树并调用 `langbot/start_langbot.ps1`。无法核实、PID 文件缺失、非 Windows 系统时跳过重启；不会按端口或进程名称查杀服务。根启动脚本写入的 PID 文件是 `langbot/langbot.pid`。

运行时的 `persona-sync.json`、日志、人格文本和数据库均为本地私有文件。公开发布前只保留 `.example.json` 模板。
