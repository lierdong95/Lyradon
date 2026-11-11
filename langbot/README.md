# 可选 LangBot 集成

四个独立功能模块不需要安装 LangBot。本目录仅提供通用启动辅助和可选分段发送工具，不含任何人格插件、人格文本或运行数据。

1. Windows 下准备 Python 3.11 或更高版本，运行 `setup_langbot.bat`。
2. 运行 `run-langbot.bat`，在本机管理界面自行配置机器人与模型连接。
3. 停止本目录启动的实例：`powershell -File .\langbot\stop_langbot.ps1`（从项目根执行）。

安装入口固定 LangBot 4.11.4。`requirements-lock.txt` 是源项目的依赖版本参考，仅包含包名和版本；默认安装只使用 `requirements.txt`，本次未重新安装验证整套锁定依赖。

启动器使用项目根的 `langbot-venv`，工作目录是本目录，PID 保存在 `langbot.pid`；不会自动注册开机启动，也不会自动打补丁。端口 5300 被占用时拒绝启动，不结束占用进程。

## 可选分段发送

`patch_split_send.py` 保留原分段算法。公开版移除了自动搜索其他安装位置的逻辑，必须明确指定 `respback.py`，默认只检查。停用目标 LangBot 后先备份，再自行执行：

```powershell
python .\langbot\patch_split_send.py --target .\langbot-venv\Lib\site-packages\langbot\pkg\pipeline\respback\respback.py
# 确认目标和备份后，添加 --apply 才会写入。
```

工具首次应用时在目标旁保存 `.before-public-split.bak`，不随本项目公开。仅适配所标注的 LangBot 版本；其他版本必须重新核对代码结构。
