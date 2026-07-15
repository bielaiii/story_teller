# Story Teller

一个用于记录小说剧情、人物关系图谱、故事线时间线和人物详情的本地网页工具。

## 本地运行

使用项目自带的本地服务启动：

```sh
./run.sh
```

然后访问：

```text
http://127.0.0.1:4180/
```

页面和本地内容操作共用这一个服务，不需要再启动第二个端口。localhost 直接从 SQLite 读取；使用普通静态托管时，阅读、图谱和时间线改读生成的 Markdown/JSON 导出，并保持只读。

作为其他小说仓库的子模块使用时，可以通过 `STORY_TELLER_CONTENT_ROOT` 指定父仓库中的内容目录：

```sh
STORY_TELLER_CONTENT_ROOT=/path/to/novel/content \
STORY_TELLER_DEFAULT_PROJECT=my-novel \
./run.sh
```

设置 `STORY_TELLER_DEFAULT_PROJECT` 后，直接访问根地址即可打开该内容包，无需添加 `?project=`。

## 数据与编辑

小说数据按内容包放在 `content/` 目录中。当前仓库只跟踪 `content/demo/` 作为开发样例，真实小说内容包可以放在 `content/你的项目名/`，默认不会被提交。

使用 `./run.sh` 启动 localhost 后，从网页完成剧情、人物、关系、设定、碎片、时间线、篇章和图谱布局的新增与修改。每个内容包的 `story.db` 是唯一数据源；文章正文仍以 Markdown 文本保存在数据库中，因此保留原有写作能力，但不再依赖文件编辑器。

服务会在数据库事务成功后自动生成 Markdown、JSON 和附件导出。它们方便 Git 查看文本差异和静态部署，但手工修改导出文件不会改变数据库，下一次启动或写入时会被数据库内容恢复。

首次启动旧内容包时，如果还没有数据库，服务会自动导入现有文件并创建 `story.db`；数据库一旦存在，普通启动绝不会再次从导出文件覆盖它。`story.db` 应随内容仓库提交到 GitHub，SQLite 的 `-journal`、`-wal`、`-shm` 临时文件不应提交。

数据库状态可用只读命令检查：

```sh
python3 storage_cli.py content/demo status
```

只有在数据库丢失或确认需要灾难恢复时，才显式执行 `import-exports`。已有数据库必须添加 `--force`，工具会先在内容包的上一级目录保存备份；普通启动不会执行这项操作。

访问不同内容包：

```text
http://127.0.0.1:4180/index.html?project=demo
```

所有内容类型都支持网页写入；删除内容统一在数据库回收站保留 7 天后才永久清理。`timeline.md`、`graph-layout.md`、`manifest.md` 和 `content-index.json` 都是应用维护的导出文件。具体操作说明见 `content/demo/README.md`。

## 安全重命名

打开“配置检查”，在“安全重命名”中选择人物或设定档案。工具会先列出所有受影响的内容和引用，确认后才会在同一数据库事务中写入，并支持撤销最近一次重命名。

重命名不会改变稳定 ID，但会同步正文引用以及人物、关系的可读文件名。
