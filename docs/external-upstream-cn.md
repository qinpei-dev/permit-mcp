# 配置第三方 stdio MCP 服务（v0.5.0）

PermitMCP 通过本机所有者选定的一个 stdio 服务连接外部工具。安装命令：

```bash
python -m pip install permit-mcp==0.5.0
python -m pip install mcp-server-time==2026.8.18
```

复制 `examples/time-server.json.example` 到私有位置，把 `command` 换成安装了该第三方包的 Python 绝对路径。`args` 固定为 `-m mcp_server_time`。`tools` 把已发现的 `get_current_time` 设为 `allow`，`convert_time` 设为 `review`；也可设为 `deny`。客户端不能设置进程命令或增加未发现的工具。`env` 只填写目标变量名到本机已有环境变量名的映射，不能填密钥值；缺失时启动失败。本例无需凭据。

设置 `PERMITMCP_UPSTREAM_CONFIG` 为上述 JSON 文件绝对路径、`PERMITMCP_UPSTREAM_APPROVAL_TOKEN` 为仅供审批者使用的独立私密值，运行 `permit-mcp`。在 MCP 客户端中配置 `permit-mcp` 命令与这两个本机环境变量；完整 JSON 见[英文指南](external-upstream.md)。不可信 Agent 只能获得 `upstream_tools` 与 `upstream_call`，不能获得 `upstream_approve` 或审批密钥。stdio 主机仍需可信，审批密钥也不能证明真人审核。

先调用 `upstream_tools`，再通过 `upstream_call` 调用 `get_current_time`，参数为 `{"timezone":"UTC"}`。`convert_time` 参数为 `{"source_timezone":"UTC","time":"12:00","target_timezone":"Asia/Shanghai"}`，初次调用返回 `review` 和 `action_id`；审批者用此 ID 与独立密钥调用 `upstream_approve`，才会执行。未知工具、无效参数与 `deny` 规则都不会转发到上游。上游报错会得到通用控制错误，不返回 stderr。

本机也可运行 `permit-mcp-upstream --config PRIVATE_CONFIG_PATH --tool get_current_time --arguments '{"timezone":"UTC"}'`。测试命令是 `python -m pytest -q tests/test_configured_upstream.py`，需事先安装指定版本的独立服务。缺少该依赖时相关测试跳过，不能视为第三方集成验证。

该路径采用确定性策略，默认不调用 JEV；原有决策工具仍可用自备 `JEV_API_KEY` 访问 TypeSafe，不配置则用本地 mock。PermitMCP 不提供共享密钥或额度。完整提案摘要绑定 Permit，默认一分钟过期、仅可消费一次。上游工具使用运行用户的系统权限，PermitMCP 不提供操作系统沙箱；JSON Schema 只检查参数形状，不能证明操作安全。审批与 Permit 状态保存在进程内存中，重启后丢失；不支持多用户共享部署、远程 HTTP 上游或自动配置任意服务。
