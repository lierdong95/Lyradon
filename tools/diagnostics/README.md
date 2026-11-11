# 可选 OneBot 状态观察器

仅供操作者主动启用。默认 `enabled: false`，不自动访问正在运行的机器人。只读取当前目录的 `observer.json`，不会读取电脑上的 NapCat 或其他软件配置。

## 安装与启用

需要 Python 3.11+。运行 `setup_diagnostics.bat` 建立独立环境，安装 `websockets==17.1`，并仅在不存在时复制示例为本地配置。编辑 `observer.json` 中两个回环地址和自己的令牌，再设 `enabled: true`。

使用 `.venv\Scripts\python.exe observe_status.py --once` 只读取一次状态；省略 `--once` 时观察默认六小时，可用 `--minutes 10` 缩短。HTTP 只调用 `get_status`；WebSocket 不主动发送应用消息。只接受 `127.0.0.1`、`localhost` 或 `::1`，拒绝重定向、URL 内凭据、查询参数和远程代理。

输出 `status_*.jsonl` 包含状态、群/私聊消息计数、时间与固定格式的离线原因代码；不保存消息正文、成员信息或离线事件的自由文本。错误只记录异常类型。运行结果也属于本地数据，不应提交。

## 无真实机器人验证

- `.venv\Scripts\python.exe observe_status.py --self-test`：纯内存过滤检查，无网络。
- `.venv\Scripts\python.exe verify_observer.py`：自行启动随机端口的本地模拟 HTTP/WebSocket 服务，验证认证头、状态采集、隐私字段丢弃，以及观察器没有发送应用消息。使用系统临时目录并自动清理，不连接真实机器人。
