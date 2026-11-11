# Lyradon
一个未完成的聊天机器人

面向 Windows 与 OneBot v11 的 Python 机器人功能集合：雷达图、观星天气评分、定时消息、关键词回复，以及可选的 LangBot 辅助工具。

本仓库提供已脱敏的独立功能模块。不包含原机器人的人格插件、人格文本、记忆关系系统、聊天数据、登录信息或历史配置。项目代码与文档沿用本仓库的 MIT 许可证；`langbot/patch_split_send.py` 含 LangBot 适配片段，按 Apache-2.0 提供，许可文本见 `LICENSES/Apache-2.0.txt`。外部服务与依赖来源见 `NOTICE`。

## 文件入口

| 目录 | 用途 |
|---|---|
| radar | 从公开气象页面取得雷达图 |
| stargaze | 基于天气数据和近似月相计算观星参考分数 |
| scheduler | 按时间计划发送文本 |
| wordlib | 按关键词选择回复 |
| personasync | 可选的本地文本同步工具，默认禁用；不附任何人格内容 |
| langbot | 可选的 LangBot 安装、启动和分段发送工具 |
| tools/diagnostics | 可选的 OneBot 状态观察器和模拟测试 |
| tools | 发布目录检查工具 |

## 四个独立模块的使用

1. 安装 Python 3.11 或更高版本及你自行配置的 OneBot v11 服务。QQ 协议客户端须另行安装，本目录没有打包客户端。
2. 进入需要使用的模块，运行其 `setup_*.bat`：创建本模块虚拟环境、安装依赖，且只在本地配置不存在时从 `*.example.json` 复制配置。
3. 编辑生成的本地 JSON 配置，填入自己的群号与连接地址。示例群列表为空、定时任务关闭，必须主动配置才会向群发送。
4. 运行本模块启动脚本，或在项目根运行 `启动机器人.bat` 启动已配置的四个模块。
5. 根目录 `停止机器人.bat` 只停止根管理器记录且路径验证通过的进程。直接用模块脚本启动的前台服务请用 Ctrl+C 停止。LangBot 需使用其独立停止脚本。

模块行为和依赖见各目录 README。示例中的“小Q”和 `123456789` 是占位内容，全部回复与定时文案均为通用示例。真实配置、日志、数据库和本地运行记录被 `.gitignore` 排除；忽略规则不等于自动清除已加入版本库的文件。

默认 OneBot 地址仅指本机回环接口。`radar`、`stargaze`、`wordlib` 保留源版连接能力，使用带鉴权的接口前须按模块说明配置或适配，不能将不支持的 token 参数当作已生效。不要为适配示例而将服务暴露到公网。

## 可选工具

- 根启动器默认不启动 LangBot 和人格同步。需要文本同步时先按 `personasync/README.md` 配置，再显式使用管理器的 `-IncludePersonaSync`。
- `autostart_bot.ps1` 只是可选启动入口，不会替用户注册计划任务。
- `langbot/patch_split_send.py` 仅在显式传入目标及 `--apply` 时修改目标安装；根启动器不自动调用它。
- 诊断工具不包含任何实际采集结果；使用方式见其 README。

## 发布前核验

在项目根运行 `python tools/verify_release.py`。工具检查文件清单及指纹、配置占位值和常见敏感模式，不读取项目之外的个人数据，不连接机器人。

## 离线功能测试

使用独立测试环境，避免在实际服务进程内运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tests/requirements.txt
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

测试使用临时副本及模拟消息，不访问真实 OneBot 服务。可选诊断工具的纯内存和模拟服务测试见其 README。运行测试或安装后产生的本地文件不属于发布清单；`verify_release.py` 用于核验清单对应的干净源码；只忽略根目录 Git 元数据。

## 其他一些需要注意的情况说明

此bot最开始是在napcat底座部署，后迁移至snowluma底座。
就目前部署环境而言，平均每两小时登录凭据失效一次。
目前已知存在记忆错乱问题。此前bot曾发生一次人格漂移，现已将人格模块单独重置并添加新机制及新限制。
人格模块暂不考虑开放，但其功能稍后会另行上传文档进行概述。
