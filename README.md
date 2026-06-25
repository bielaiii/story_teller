# Story Teller

一个用于记录小说剧情、人物关系图谱、故事线时间线和人物详情的本地网页工具。

## 本地运行

当前项目是静态网页，可以直接用任意静态服务器打开：

```sh
python3 -m http.server 4180 --bind 127.0.0.1
```

然后访问：

```text
http://127.0.0.1:4180/index.html
```

## 编辑数据

小说数据放在 `data/` 目录中，人物、剧情、关系、时间线都使用 Markdown 文件配置。具体格式见 `data/README.md`。

