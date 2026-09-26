# PermitMCP

[English](README.md) | [中文](README_CN.md)

**阻止 AI Agent 在未经控制的情况下直接执行工具。**

一个面向 MCP Agent 的轻量级执行控制层，通过确定性策略、JEV 决策、人工审批和一次性 Execution Permit 控制真实工具执行。

**版本状态：** v0.4.0 包含可复用的 `ControlChain`，以及对仓库内固定 `read_sample` 工具的一次 Permit 控制的上游 MCP 调用。当前不支持通用 MCP Proxy、任意第三方 MCP 服务或操作系统级沙箱。本次发布未重新验证真实 JEV API。

### Controlled Agent Showcase

<!-- 视觉占位：可靠录制 GIF 后可替换这段真实终端输出。 -->
```text
SAFE ACTION        ALLOW  → 签发 Permit → 执行
SENSITIVE ACTION  REVIEW → 等待人工批准 → 执行
FORBIDDEN ACTION  DENY   → 无 Permit → 不调用 Executor
```

[查看真实终端输出](docs/assets/showcase/controlled-agent-showcase.txt)，或直接运行：

```bash
python -m examples.showcase
```

Showcase 使用控制场景专用的离线决策 mock，针对临时沙箱内的真实文件运行。覆盖已有文件时，在调用方明确批准前保持原样；`../secret.txt` 不会进入决策提供者或 Executor。无需 API key。

### 执行路径

`Agent proposal → ControlChain（确定性策略 → 可选决策提供者 → ExecutionPermit → Executor）→ Observation`

策略 `DENY` 在 JEV 前阻止操作；策略 `REVIEW` 等待调用方批准；`ALLOW` 获取一次性 Permit。三种结果是本项目对 TypeSafe Choice 的应用层解释，并非 TypeSafe 独立的 Gate primitive。沙箱限制和机器可读 Trace 见[受控 Agent 说明](docs/controlled-agent.md)。

JEV 是可选决策组件，不执行工具，也不能覆盖确定性 Policy。调用外部决策组件前，Policy 或 Controller 必须显式提供安全参数投影；缺少投影时执行链会安全失败。Permit 绑定完整 proposal 的摘要，默认一分钟过期，在 Executor 边界只能消费一次。

v0.4.0 上游验证会启动仓库内独立的 stdio MCP 进程，并通过真实 `tools/call` 调用固定的 `read_sample` 工具。离线运行：`python -m examples.upstream_mcp_demo`。范围、故障处理与限制见[上游 MCP 验证说明](docs/upstream-mcp.md)。

## Quick Start

需要 Python 3.11 或更新版本。克隆 [PermitMCP](https://github.com/qinpei-dev/permit-mcp) 后，在仓库根目录运行：

```bash
git clone https://github.com/qinpei-dev/permit-mcp.git
cd permit-mcp
pip install -r requirements.txt
python -m examples.showcase
python -m examples.upstream_mcp_demo
python -m pytest -q
```

MCP 配置与可选的真实 JEV API 见下方 [MCP](#mcp)；旧版 `agent_run` 技能流程继续保留。

## Features

- 通过 MCP 工具提供 JEV 决策、技能执行和技能发现。
- 提供带 Permit 的受控 Agent loop、本地沙箱文件工具、显式审批和可程序化 Trace。
- 配置 `JEV_API_KEY` 后调用 TypeSafe JEV API，并校验返回的选项是否在调用方允许的范围内。
- 未配置 key 时使用确定性的本地 mock，方便在没有外部凭据的情况下体验项目。
- 除 MCP Server 外，还提供 FastAPI 服务、Docker 打包配置和演示脚本。
- 提供可扩展的技能注册表和 Skill Executor。

## Why Decision Layer?

现代 AI Agents 常让 LLM 同时负责内容生成和决策。本项目把结构化决策与可预测的路由交给独立、轻量的 Decision Layer。

没有 Decision Layer 时：

```text
任务
  ↓
LLM 决策
  ↓
执行
```

使用 JEV 时：

```text
任务
  ↓
JEV Decision Layer
  ↓
技能路由
  ↓
执行
```

MCP 客户端提供任务和允许的选项。JEV 返回选择，系统在路由前检查该选择是否属于允许范围。LLM 仍可生成内容并管理完整的 Agent 工作流。具体示例和限制见[决策路由用例](docs/use-cases.md)。

## 架构

下图展示早期决策路由路径；Permit 控制的执行路径见上文和[受控 Agent 说明](docs/controlled-agent.md)。

![PermitMCP 决策路由图](docs/images/architecture.png)

MCP 负责通信；JEV 根据客户端允许的选项作出结构化决策；Skill Router 找到已注册的技能；Skill Executor 运行相应的本地工作流。

## MCP

MCP（Model Context Protocol）为 AI 客户端连接外部工具与服务提供标准方式。本 MCP Server 暴露 `jev_decide`、`agent_run`、`list_skills`、`controlled_agent_run` 和 `approve_action`。

安装依赖后，将以下配置加入 MCP host。启动 host 时，以仓库根目录为工作目录，使 Python 能导入 `src`。

```json
{
  "mcpServers": {
    "permit-mcp": {
      "command": "python",
      "args": ["-m", "src.mcp.server"],
      "env": {}
    }
  }
}
```

也可以从 [`mcp.json.example`](mcp.json.example) 开始配置。桌面端安装步骤见[豆包 MCP 配置](docs/doubao-mcp.md)。MCP Server 使用 stdio 传输，提供以下工具：

| 工具 | 用途 |
| --- | --- |
| `jev_decide` | 使用 JEV 从调用方给定的选项中作出选择。 |
| `agent_run` | 选择并执行已注册的技能，返回决策和执行结果。 |
| `list_skills` | 列出此服务器已注册的技能。 |
| `controlled_agent_run` | 通过确定性策略、JEV Choice、Permit 和沙箱执行器运行本地文件操作。 |
| `approve_action` | 批准并继续执行 `approval_required` 返回的单个 Action。 |

### MCP Client Compatibility

v0.2.1 的 MCP 连接已在 Doubao Desktop 和 Antigravity 上测试。新增的受控工具目前有 FastMCP 自动化测试，但尚未在这两个客户端中手动验证。详情见 [MCP 客户端兼容性说明](docs/mcp-clients.md)。每位用户都需要运行自己的本地 MCP Server；本项目不提供共享的远程 MCP 服务或 JEV 额度。

### 使用真实 JEV API

通过 [TypeSafe](https://typesafe.ai/) 申请自己的 JEV API key。将其设为服务器进程的环境变量，或写入仓库根目录中私有且不受版本控制的 `.env` 文件：

```dotenv
JEV_API_KEY=your_own_key
```

之后运行 `python -m src.mcp.server` 启动 MCP Server，或运行真实 API 演示：

```bash
python -m examples.real_jev_demo
```

未配置 key 时，两者都使用本地 mock。配置 key 后，请求会从你的设备通过 HTTPS 直接发送至 TypeSafe，并使用你自己的账号和额度。不要提交 `.env` 文件，也不要在共享的 MCP 配置中放入 key。

## Legacy / Earlier examples（早期示例）

内置的职业、论文、编程、研究和写作技能均为模拟工作流，用于展示路由与执行流程；它们不会调用外部服务，也不会真正完成所描述的任务。豆包适配器定义的是扩展接口，并非可用的豆包 API 集成。

![豆包 MCP 演示：调用 jev_decide 并返回决策结果](docs/images/doubao-mcp-demo.png)

已测试的 MCP 客户端：

- Doubao Desktop MCP Connector
- Antigravity MCP Client

真实 MCP 调用 → 真实 TypeSafe JEV API → 决策结果。

在仓库根目录运行决策与本地技能执行演示：

```bash
python -m examples.agent_run_demo
```

在 mock 模式下，示例会选择 `career_skill`，并显示执行结果：

```text
JEV: career_skill (91.00%)
Executor: career_skill.execute()
结果: Career analysis workflow executed
```

运行此演示无需 API key。设置 `JEV_API_KEY` 后，演示会调用真实的 TypeSafe JEV API，决策结果可能不同。

在仓库根目录运行新的文件执行循环：

```bash
python -m examples.controlled_agent_demo
```

确定性演示会读取真实的 `README.md`，在配置的 sandbox 内创建 `output/summary.md`，并打印结构化 Trace。生成的 `output/` 目录由 Git 忽略。默认不配置控制决策提供者，且不访问网络；添加 `--real-jev` 才会使用已配置的 `JEV_API_KEY`。再次运行且输出文件已存在时，Action 会等待审批；只有明确同意覆盖时才添加 `--approve-existing`。文件工具仍会真实执行。

## 示例

在仓库根目录运行以下命令：

```bash
python -m examples.skill_router_demo
python -m examples.doubao_demo
python -m examples.agent_router_demo
python -m examples.agent_run_demo
python -m examples.real_jev_demo
```

演示默认使用本地 mock。设置 `JEV_API_KEY` 后，`agent_run_demo` 和 `real_jev_demo` 会使用 TypeSafe JEV。演示不附带 API key，也不提供项目共享额度。

## 决策路由示例

路由流程为 **任务 → JEV 决策 → 选中技能 → 执行路径**。以下示例通过当前环境选定的 JEV 客户端展示决策环节，只返回选择，不执行技能。未配置 `JEV_API_KEY` 时，本地 mock 给出确定性的演示结果；配置 key 后，选择来自真实的 TypeSafe JEV API，结果可能不同。请在仓库根目录运行：

### Use Cases

- [Agent Routing](examples/use_cases/career_decision.py)：`python -m examples.use_cases.career_decision`
- [Coding Decision](examples/use_cases/coding_decision.py)：`python -m examples.use_cases.coding_decision`
- [Research Decision](examples/use_cases/tool_selection.py)：`python -m examples.use_cases.tool_selection`

各用例的设计思路见[决策路由用例](docs/use-cases.md)。

### HTTP API 示例

本地 API 启动后，可以发送任务：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/agent/run \
  -H 'Content-Type: application/json' \
  -d '{"task":"帮我分析这个招聘岗位"}'
```

在 mock 模式下，响应包含选中的技能和执行结果。服务还提供：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 检查服务健康状态。 |
| `POST` | `/decide` | 从调用方提供的选项中选择。 |
| `POST` | `/route/skill` | 将任务路由至内置技能。 |
| `POST` | `/route/agent` | 将任务路由至 Agent。 |
| `POST` | `/api/v1/agent/run` | 决定使用哪项技能，并执行其工作流。 |
| `POST` | `/api/v1/controlled-agent/run` | 通过受控执行循环运行 Action，并返回 Trace。 |
| `POST` | `/api/v1/controlled-agent/{run_id}/approve` | 批准等待审核的对应 Action。 |

## Decision Routing Evaluation

评估结果见 [Decision Routing Evaluation](benchmark/results.md)。运行 `python benchmark/run_benchmark.py` 可在本地重新生成。10 个示例任务覆盖职业、编程、研究和写作技能的决策路由流程、示例任务匹配、置信度及本地演示执行。决策后端是确定性的本地 mock；其延迟不能代表真实 API 的延迟或 LLM 生成速度。这项评估不对性能或成本作出结论，也不会调用付费模型或外部研究服务。

## 路线图

最新已发布版本为 [v0.3.0](https://github.com/qinpei-dev/permit-mcp/releases/tag/v0.3.0)。尚未发布的 v0.4 源码增加可复用执行控制链，并验证一次固定的上游 stdio MCP 调用。未来可能增加更多 MCP host 配置示例，但尚未承诺交付日期。

## Docker

```bash
docker compose up --build
```

API 位于 `http://localhost:8000`。Docker Compose 将主机端口绑定到 `127.0.0.1`，默认使用 mock 模式。

## 安全与部署

- 使用你自己的 JEV API key；项目没有共享凭据或额度。
- 对 `.env` 及含有 key 的 MCP host 配置保密。
- HTTP API 没有身份验证。使用真实 key 时，应将其限制在可信的本地接口；项目自带的 Compose 配置将其绑定到 localhost。
- 真实 JEV 请求会从你的服务器通过 HTTPS 直接发送至 `https://api.typesafe.ai/v1/systemone`。

## Contributing

提交更改前运行 `python -m pytest`。技能扩展步骤和贡献建议见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 扩展技能

开发者可以添加 `BaseSkill` 子类来扩展本地技能注册表。子类需提供 `name`、`description` 和 `execute(input)`，并将实例注册到 `SkillRegistry`。可运行的示例见[自定义技能示例](examples/custom_skill.py)。若要让默认 MCP Server 提供新技能，还需按 [CONTRIBUTING.md](CONTRIBUTING.md) 的说明将其加入 `create_default_registry()`。

漏洞报告和凭据使用建议见[安全政策](SECURITY.md)。

## 许可证

本项目采用 [MIT License](LICENSE)。
