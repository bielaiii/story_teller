# 本地 RAG 与 AI 接入

## 数据职责

- `story.db` 仍是唯一事实来源。
- `rag.db` 是派生检索缓存，保存 AI 可检索的文档块、全文索引、关联边和 embedding。它可以随时删除，不应提交 Git。
- `rag.config.json` 只保存 embedding provider、模型名、维度和服务地址，不保存 API key。

RAG 是独立服务，不再挂在写作网页的 4180 端口。每次启动 RAG 服务时，它会读取一次 `story.db`：找不到 `rag.db`、数据库损坏、项目 revision 改变、`story.db` 文件变化或 embedding 配置变化时，会原子重建索引。

服务运行期间不会后台轮询 SQLite。写作内容变化后，重启 `./run-rag.sh` 即可同步；也可以调用手动重建接口。若运行期间直接删除 `rag.db`，下一次检索会自动重新生成。

碎片会进入索引，但默认标为非正史；普通检索不会返回碎片，只有显式传入 `includeFragments=true`（MCP 参数为 `include_fragments`）才会加入。

## HTTP

独立 RAG 服务默认监听 `127.0.0.1:4181`。在小说仓库另开一个终端启动：

```sh
./run-rag.sh
```

普通 JSON API：

- `GET /api/v1/projects/{project}/rag/status`
- `GET /api/v1/projects/{project}/rag/catalog`
- `GET /api/v1/projects/{project}/rag/search?q=...`
- `POST /api/v1/projects/{project}/rag/search`
- `POST /api/v1/projects/{project}/rag/context`
- `GET /api/v1/projects/{project}/rag/entities/{entityId}`
- `GET|PUT /api/v1/projects/{project}/rag/config`
- `POST /api/v1/projects/{project}/rag/rebuild`

完整地址以 `http://127.0.0.1:4181` 开头。修改配置和手动重建需要 RAG 服务 `/api/v1/meta` 返回的 `X-Story-Teller-Token`，其他接口只读。

## MCP

Streamable HTTP MCP 地址：

```text
http://127.0.0.1:4181/mcp
```

提供以下只读工具：

- `world_catalog`
- `search_world`
- `get_world_entity`
- `get_related_world`
- `build_world_context`
- `rag_status`

也提供 `story://{project}/catalog` 和 `story://{project}/entity/{entityId}` 资源。

OpenCode 1.x 可这样添加：

```sh
opencode mcp add story-world --url http://127.0.0.1:4181/mcp
opencode mcp list
```

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
