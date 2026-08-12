# 世界领域注册表

## 目的

SQLite 负责可靠存储，但表名和列名本身不能完整表达业务语义。领域注册表为 AI 和导出层补上这一层契约：每种实体是什么、字段叫什么、来自哪个表、是否允许 AI 读取、是否参与搜索、是否导出，以及碎片、关系方向等跨表规则。

注册表分为两份：

- `storyteller/domain/world_schema.yaml`：人工维护的业务语义，是 AI 可见契约；
- `storyteller/domain/world_schema.storage.yaml`：根据当前 SQLite Schema 自动生成的物理结构清单，记录每个字段已经映射为 `domain`、明确属于 `internal`，还是尚待处理的 `TODO`。

导出的 `content/<project>/world-schema.json` 是公开契约，不包含物理表名和内部控制字段；`ai-manifest.json` 和 `AI_CONTEXT.md` 告诉外部 AI 从哪里开始读取。

## 修改 SQLite 结构

新增或修改表、列以后运行：

```sh
npm run schema:sync
```

新业务字段应先在 `world_schema.yaml` 对应实体中声明：

```yaml
secrecyLevel:
  label: 秘密程度
  type: integer
  source: characters.secrecy_level
  aiVisible: true
  searchable: true
  exportable: true
```

字段必须明确三个边界：

- `aiVisible`：结构化查询和 MCP 是否可返回；
- `searchable`：是否写入 RAG 文档；
- `exportable`：是否写入 Markdown 元数据。

如果是纯数据库实现细节，将生成文件中的 `review: TODO` 改成 `review: internal`。不要把业务字段伪装成 internal；否则 AI 无法理解或检索它。

完成后执行：

```sh
npm run schema:check
npm run test:unit
```

CI 会运行 `schema:check`。只要物理 Schema 与登记清单不一致、出现 `TODO`，或领域字段缺少必要语义，检查就会失败。`--bootstrap` 只允许在注册表尚不存在时建立首次基线，不能用来绕过后续审核。

## 自动传播范围

普通实体主表字段只要声明了 `source`，便会自动进入结构化读取、MCP/HTTP 返回、RAG 文档和 Markdown 导出，无需在 repository、MCP 和 exporter 各写一遍映射。跨表集合、方向性关系和计算字段仍需在领域读取器中实现明确聚合规则，因为它们不是单列可以自描述的结构。

当前明确的复杂语义包括：

- `fragment`：确定会进入故事但尚未编入时间线，默认参与检索；
- `relationship`：关系名称可以共用，但双方角色和双方印象分别有方向；
- 组织：人物可属于多个组织，角色名称属于“人物—组织”成员关系；
- 出场：人物与剧情、碎片之间是结构化引用，不靠向量相似度猜测。
