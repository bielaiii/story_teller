# 本地 RAG 与 AI 接入

## 数据职责

- `story.db` 仍是唯一事实来源。
- `rag.db` 是派生检索缓存，保存 AI 可检索的文档块、全文索引、关联边和 embedding。它可以随时删除，不应提交 Git。
- `rag.config.json` 只保存 embedding provider、模型名、维度和服务地址，不保存 API key。

RAG 不挂在写作网页的 4187 端口。每个 Content 根目录由一个无端口 stdio worker 读取其多个 Project 的 `story.db`；唯一的 Story World Hub 监听 4188，对外提供统一 MCP。网页写入提交后会将目标 revision 放入后台同步队列，连续保存会在短暂防抖窗口内合并，只替换受影响文档和关联边。网页服务与 MCP worker 使用跨进程项目锁，避免同时更新同一个 `rag.db`。数据库损坏、Schema/模型变化、revision 回退或历史缺口时自动原子完整重建。

同步由保存事件触发，不依赖后台轮询，也不需要重启 Hub。MCP 在每次检索、取上下文和读取 RAG 实体前仍比较 `story.db` revision：正常情况下索引已由后台更新，可直接查询；若外部工具直接修改 SQLite、后台同步尚未完成或曾临时失败，请求会兜底完成同步后再返回，因此不会静默读取旧内容。若运行期间直接删除 `rag.db`，后台任务或下一次检索会自动重新生成。

碎片是“已确定会进入故事、但尚未正式编入时间线”的一等内容，普通检索和上下文构建默认包含。`includeFragments` / `include_fragments` 保留为兼容参数，未来若增加“暂定素材”，显式开启才会额外包含这类非确定内容。

精确事实（例如组织归属、双向人物印象、剧情出场）直接读取最新 `story.db`，无需等待 embedding；自然语言探索使用全文索引和 embedding。`build_world_context` 会先放入直接读取的结构化事实，再补充 RAG 文档。

## 启动与端口复用

正常运行小说网页即可：

```sh
./run.sh
```

部署脚本在数据库迁移后自动执行以下流程：

1. 若 4188 空闲，后台启动 Story World Hub；
2. 若 4188 已经是协议兼容的 Story World Hub，直接复用；
3. 若 4188 是其他服务或不兼容版本，报错退出，不会终止占用者；
4. 使用 Git 仓库名作为对外工作区短名称，并按 Content 根目录真实路径生成内部稳定 `workspaceId`；
5. `run.sh` 在线时创建临时租约；管理页也可以创建持久的 Hub 托管状态来启动 Web。Web 正常退出、被管理页停止、崩溃或心跳超时后，跟随模式的 stdio worker 自动释放；
6. 只有明确执行 `run-rag.sh` 开启独立模式时，Web 关闭后该 MCP worker 才继续运行。

只启动/检查 Hub 并注册当前仓库时，可运行：

```sh
./run-rag.sh
```

这个命令完成独立 MCP 注册后退出，不会再启动第二个前台 RAG 服务。使用 `run-rag.sh stop` 关闭独立模式；若 Web 仍在线，MCP 会无缝回到跟随状态。Hub 状态保存在 `~/.story-teller/hub/`：

- `registry.json`：已注册 Content、Hub 托管 Web、独立 MCP 模式和停用的 Project；
- `token`：仅本机部署脚本使用的注册凭据，权限为 0600；
- `hub.pid`、`hub.log`：运行诊断信息。

Hub 启动时会清理数据库、仓库或框架已不存在的注册记录。终端 Web 租约只存在于内存，Hub 重启不会把已经失联的终端误判为在线；在管理页明确启动的 Hub 托管 Web 会随 Hub 恢复。每个 Project 独立检查，失败项会保留错误和日志但不会阻止健康项。Web Worker 持有 Content 路径所有权锁并监控 Hub 父进程，避免重复部署和异常退出后的孤儿写进程。Hub 只接受 loopback 地址，管理接口需要本机 token。健康检查和已注册工作区可分别读取：

- `GET http://127.0.0.1:4188/api/v1/hub/health`
- `GET http://127.0.0.1:4188/api/v1/hub/workspaces`

## MCP

### 本地 stdio（推荐）

本地 AI 不需要固定端口。安装一次全局启动器：

```sh
./scripts/install-story-world-mcp.sh
opencode mcp add story-world -- story-world-mcp
```

OpenCode 全局配置：

```json
{
  "mcp": {
    "story-world": {
      "type": "local",
      "command": ["story-world-mcp"],
      "enabled": true,
      "timeout": 10000
    }
  }
}
```

`story-world-mcp` 从 AI 客户端的当前目录向上发现最近的 `content/<project>/story.db`。单项目自动选中；同一工作区包含多个项目时，AI 先调用 `list_world_projects`，再给其他工具传入 `project`。每个项目维护自己的 `rag.db`，进程间不共享端口。使用 stdio 时不必启动 `run-rag.sh`。

### 统一 Streamable HTTP Hub

Streamable HTTP MCP 地址：

```text
http://127.0.0.1:4188/mcp/
```

提供以下只读工具：

- `list_world_workspaces`：列出已部署的 Git 小说仓库、工作区短名称 `displayName` 与内部稳定 `workspaceId`；
- `list_world_projects`：列出所选仓库 `content/` 下当前可用的项目与默认选择；
- `describe_world`：读取实体类型、字段语义与碎片策略；
- `world_catalog`
- `resolve_world_entity`：将姓名、别名或稳定 ID 解析为实体；
- `query_world`：按类型和字段查询最新 SQLite；
- `search_world`
- `get_world_entity`
- `get_related_world`
- `build_world_context`
- `rag_status`

每个 Hub 工具都会在参数 JSON Schema 中动态列出当前可用 `workspace` 和 `project`。`workspace` 选择 Git 仓库，`project` 选择该仓库的 `content/<project>`；新建含 `story.db` 的项目后，下一次读取工具定义即可看到新选项。`project` 默认可省略：优先选择与 workspace 同名的项目，否则单项目自动选中；多项目且无同名项时才要求明确选择。客户端无法判断时应调用 `list_world_workspaces`、`list_world_projects` 或询问用户。Hub 不使用“最近部署项目”之类的全局当前值，避免 AI 静默读错小说。

推荐调用顺序：先用 `list_world_workspaces` 选择仓库，再用 `describe_world` 和 `world_catalog` 发现数据；精确问题使用 `resolve_world_entity`、`query_world`、`get_world_entity`、`get_related_world`；只有模糊探索和创作联想才使用 `search_world` 或 `build_world_context`。

OpenCode 1.x 可这样添加：

```sh
opencode mcp add story-world-hub --url http://127.0.0.1:4188/mcp/
opencode mcp list
```

对能从仓库目录启动命令的 OpenCode，前面的 stdio 方式更直接；对不能动态设置命令工作目录、但能连接 HTTP MCP 的客户端，Hub 方式只需配置一次固定地址。

## 切换 embedding

默认 `builtin / hash-char-2-3-v1 / 384` 完全离线，不需要下载模型。可切换到：

- `builtin`：`hash-char-2-3-v1` 或 `hash-char-3-v1`；
- `openai-compatible`：Ollama、LM Studio、vLLM 或其他兼容 `/v1/embeddings` 的服务，可填写任意模型名；
- `sentence-transformers`：任意本地或 Hugging Face 模型名，需要额外安装 `sentence-transformers`；
- `disabled`：只使用结构化信息和全文检索。

示例：切到本地 OpenAI 兼容服务：

```json
{
  "provider": "openai-compatible",
  "model": "bge-m3",
  "dimensions": 1024,
  "baseUrl": "http://127.0.0.1:11434/v1",
  "apiKeyEnv": "OPENAI_API_KEY",
  "batchSize": 32
}
```

模型配置保存后会立即重建。远程 embedding 暂时不可用时，文本和结构化索引仍可正常使用，`rag/status` 会显示 `embeddingStatus: failed` 和原因。
