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

页面和本地内容操作共用这一个服务，不需要再启动第二个端口。使用普通静态托管时，阅读、图谱和时间线仍然可用，但安全重命名会保持只读。

作为其他小说仓库的子模块使用时，可以通过 `STORY_TELLER_CONTENT_ROOT` 指定父仓库中的内容目录：

```sh
STORY_TELLER_CONTENT_ROOT=/path/to/novel/content \
STORY_TELLER_DEFAULT_PROJECT=my-novel \
./run.sh
```

设置 `STORY_TELLER_DEFAULT_PROJECT` 后，直接访问根地址即可打开该内容包，无需添加 `?project=`。

## 编辑数据

小说数据按内容包放在 `content/` 目录中。当前仓库只跟踪 `content/demo/` 作为开发样例，真实小说内容包可以放在 `content/你的项目名/`，默认不会被提交。

使用 `./run.sh` 启动 localhost 后，从网页完成剧情、人物、关系、设定、碎片、时间线、篇章和图谱布局的新增与修改。Markdown 是内部持久化格式，不需要通过文件编辑器维护。

扫描结果会同时写入当前内容包的 `content-index.json`。localhost 和静态部署读取同一份索引结构，不再维护两套文件清单；准备静态部署前，先在 localhost 刷新一次对应项目即可更新索引。

访问不同内容包：

```text
http://127.0.0.1:4180/index.html?project=demo
```

所有内容类型都支持网页写入；删除内容统一保留 7 天后才永久清理。`timeline.md`、`graph-layout.md`、`manifest.md` 和 `content-index.json` 都由对应页面或本地服务维护。具体操作说明见 `content/demo/README.md`。

## 安全重命名

打开“配置检查”，在“安全重命名”中选择人物或设定档案。工具会先列出所有受影响的 Markdown 文件和行，确认后才会写入，并支持撤销最近一次重命名。

重命名不会改变稳定 ID，但会同步正文引用以及人物、关系的可读文件名。
