# Claude Subagent for Codex

让 Codex 调用官方 Claude Code CLI，完成实现、调查和独立审查。
Codex 负责交代任务、等待结果、检查改动；Claude 是受控的顺序 worker。

本插件包含 7 个 Skill 和一个 Python 运行器。使用已有的 Claude CLI 登录，
不需要额外 API key、代理服务或常驻进程。这是社区项目，与 OpenAI、Anthropic
没有隶属关系。代码使用 [MIT License](LICENSE)。

## 能做什么

| Skill | 职责 |
| --- | --- |
| `rescue` | 委派实现、调查、调试、重构；续接已有任务 |
| `review` | 在新会话里只读审查代码改动 |
| `adversarial-review` | 检查设计假设、回滚方案和隐藏失败情形 |
| `status` | 查看任务进度、官方额度和本地 App Code 会话 |
| `result` | 读取结果、定位原生会话、在 Claude Desktop 查看历史 |
| `cancel` | 通过所属运行器停止明确选中的任务 |
| `setup` | 检查安装、登录、配置和执行边界 |

默认使用 headless 模式并等待完成，续聊复用同一 Claude 原生 session。
默认模型为 `sonnet`；Codex 按任务选择 `--effort`，用户指定时优先遵循。
默认总并发为 4，独立 checkout 可同时写入，同一 checkout 或重叠目录的
托管 writer 互斥，同一原生 session 也不能被两个托管任务同时使用。

## 环境要求

- macOS，Python 3.10+；运行器仅依赖 Python 标准库。
- 支持插件的 Codex CLI / App。
- 已安装并登录的官方 Claude Code CLI：headless 要求 `2.1.203+`；
  可选 Remote Control 路径要求 `2.1.283+`。
- 可用的 Claude 官方账号和模型访问权限。写任务要求 Claude 原生 sandbox
  可用，默认使用 `auto` 权限模式和已验证的 Sonnet 模型系列。

当前验证平台是 macOS。运行器使用 `fcntl`、PTY 和 POSIX 进程信号，
不支持原生 Windows；Linux 尚未完成验收。Claude Desktop 的会话索引功能
使用 macOS 路径。最低版本检查通过不等于模型、额度或远程连接已经可用。

## 安装

```sh
codex plugin marketplace add Liii8888/codex-claude-subagent
codex plugin add claude-subagent@local-claude-subagent
```

`local-claude-subagent` 是保留的 marketplace 标识，同样用于 GitHub 安装。
添加来源的命令见 [Codex 官方插件文档](https://developers.openai.com/plugins/build/plugins#add-a-marketplace-from-the-cli)。
安装完成后，新建一个 Codex 对话，再调用 `$claude-subagent:setup`。

若 CLI 尚未登录，在自己的终端完成：

```sh
claude auth login --claudeai
```

### 首次配置工作区

运行器默认允许 `~/Agent` 下的项目。已有项目在该目录内时，可直接使用；
其他布局需先运行 setup，再编辑其报告的 runtime 下的 `config.json`，
把 `allowed_workspace_roots` 改成实际项目目录。例如：

```json
{
  "allowed_workspace_roots": ["~/Projects"],
  "max_concurrency": 4,
  "retention_days": 30
}
```

这是配置字段示例；修改已有文件时保留其他设置。目录必须实际存在。
setup 会检查配置，任务启动时会再次拒绝允许目录之外的路径。

默认 runtime 为 `~/Agent/Workspace-System/Claude-Subagent/runtime`。
可以通过 `CLAUDE_SUBAGENT_RUNTIME_ROOT` 指向另一个专用目录；同一安装的
所有调用应使用同一个值，确保并发调度和任务记录共享。路径不能是 `/` 或
整个 home。插件升级不需要移动已有 runtime。

安装后的脚本位于插件目录的 `scripts/claude_subagent.py`。本文后续以
`<plugin-root>` 表示该目录，Skill 会从自身位置解析，无需硬编码缓存版本。

```sh
"<plugin-root>/scripts/claude_subagent.py" setup --json
"<plugin-root>/scripts/claude_subagent.py" configure --max-concurrency 4
```

改变并发上限只影响后续预约，不取消现有任务。运行器需要访问官方登录和
共享 runtime；Codex 沙箱要求审批时，仅授权这个已安装脚本的精确路径。

## 使用

在 Codex 中直接说明任务：

```text
用 $claude-subagent:rescue 调查这个错误并修复，完成后运行相关测试。
用 $claude-subagent:review 审查当前 diff，重点看回归和数据丢失。
用 $claude-subagent:status 查看当前任务。
用 $claude-subagent:result 读取刚才任务的结果。
```

Claude 不继承整个 Codex 对话。委派 brief 需要写清目标、授权范围、关键决定
和验收条件。运行器自动收集允许工作区边界内适用的 `AGENTS.md`，以及最近的
`CONTEXT.md`；后者包含 `## 项目概况` 时只读取该段，并要求以
`<!-- /project-context -->` 结束。没有这些文件也可以运行。

已有 `~/Agent/Workspace-System/tools/agent-context-sync/registry.json` 时，
运行器支持按其中的 `projects` 映射解析概况和 worktree；普通安装不需要该登记表。
每次续聊重新读取上下文，并在该 job 的 `context.json` 保存来源和哈希。
上下文越界、读取失败或超过大小上限时停止，不扫描兄弟项目。

CLI 手动调用示例（先把任务正文保存到仅当前用户可读的文件）：

```sh
"<plugin-root>/scripts/claude_subagent.py" run \
  --kind task --mode read --cwd "$HOME/Projects/example" \
  --effort low --title "Example · Investigate" \
  --prompt-file /path/to/task.txt --receipt-only
"<plugin-root>/scripts/claude_subagent.py" result <job-id>
```

## 执行边界

- 只调用官方 `claude` CLI；拒绝 API key、自定义端点和第三方 provider 环境覆盖。
- 禁用嵌套 Agent、后台委派、Web、MCP、Hooks 和动态 workflow。
- 只读审查使用 `dontAsk`，仅开放限定工作区的 Read/Glob/Grep/Skill；
  没有 shell 或写工具。需要的 Git diff 由 Codex 先收集。
- 写任务使用 Claude `auto` 和原生 sandbox，禁止 unsandboxed fallback。
  `--unsafe-bypass` 只接受用户逐任务明确指定。
- 并发约束只管理本插件启动的任务；用户、Codex 和其他程序仍需协调写入。
  Codex 必须检查真实 diff 和相关验证，不能仅凭 worker 的总结验收。

job 包含 prompt、事件、结果和原生 session 信息。目录权限 `0700`，文件
`0600`，默认保留 30 天；setup / prune 清理过期终态 job，不删除 Claude
自身的原生历史。请勿把 runtime、账号配置或真实会话作为 issue 附件公开。

## Desktop 与 Remote Control

默认 headless 只写本地原生记录。模型推理仍使用 Claude 官方联网服务，
“本地”指执行和会话记录路径，不代表离线模型。

空闲的 headless 会话可经官方链接导入 Desktop。CLI 2.1.283 / App 2.9939.2
的已记录测试中，本地续聊保存正常，但已导入页面没有自动显示第二轮；
重新打开或 Reload 也不保证刷新。见 [本地显示边界](plugins/claude-subagent/references/local-session-sync.md)。

用户明确选择 Remote Control / 云端同步时，才传 `--live`；它经 Anthropic
服务器同步到官方 App。要求“在 App 看”或遇到陈旧页面不自动启用它。
连接完成前不提交任务；续接必须保持同一远程 session。正常完成后 CLI 退出，
`Remote Control disconnected` 不代表历史丢失。

可选实时路径使用 CLI 的实现相关控制协议，不能保证未来版本兼容。
保留历史、原生 session 连续性、App 正文显示与侧栏分组分别验证，详见
[会话保留与连接契约](plugins/claude-subagent/references/remote-session-retention.md)。
正常等待模式直接调用运行器并保持 Codex 当前轮次；后台自动回报存在单独的
[调度限制](plugins/claude-subagent/references/program-dispatch.md)。

## 开发与验证

```sh
python3 -B -m unittest discover -s tests -v
```

测试使用临时目录和假 Claude CLI，覆盖执行边界、并发、续聊、上下文、取消
及实时协议故障，不调用真实模型。发布前还需用 Codex 自带 `skill-creator`
的 `quick_validate.py` 检查全部 7 个 Skill，并用 `plugin-creator` 的
`validate_plugin.py` 检查插件。

公开包包含源码、测试、Skill 和通用参考资料；本机项目概况、runtime 和私人
开发历史不属于公开发行内容。

职责拆分参考了 [Sendbird cc-plugin-codex](https://github.com/sendbird/cc-plugin-codex)。
