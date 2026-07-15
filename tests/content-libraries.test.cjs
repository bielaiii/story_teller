const test = require("node:test");
const assert = require("node:assert/strict");

const markdownit = require("../vendor/markdown-it/markdown-it.min.js");
const yaml = require("../vendor/js-yaml/js-yaml.min.js");
const pinyinPro = require("../vendor/pinyin-pro/pinyin-pro.min.js");

test("YAML frontmatter supports structured values", () => {
  const result = yaml.load(`
id: 12
name: 沈知微
aliases:
  - 知微
  - 阿微
markers: [女主, 主角团]
facts:
  关系: 沈清妙的儿子
`);

  assert.deepEqual(result.aliases, ["知微", "阿微"]);
  assert.deepEqual(result.markers, ["女主", "主角团"]);
  assert.deepEqual(result.facts, { 关系: "沈清妙的儿子" });
});

test("Markdown supports rich structure without executing raw HTML", () => {
  const renderer = markdownit({ html: false, breaks: true, linkify: true });
  const html = renderer.render(`
# 标题

- 第一层
  - 第二层

[链接](https://example.com)

<script>alert("unsafe")</script>
`);

  assert.match(html, /<h1>标题<\/h1>/);
  assert.match(html, /<ul>/);
  assert.match(html, /href="https:\/\/example.com"/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("Relationship endpoints keep a role for each person", () => {
  const result = yaml.load(`
people:
  - id: 9
    role: 母亲
  - id: 3
    role: 儿子
label: 母子
`);

  assert.deepEqual(result.people, [
    { id: 9, role: "母亲" },
    { id: 3, role: "儿子" },
  ]);
});

test("Pinyin matching supports full spelling and initials offline", () => {
  assert.deepEqual(pinyinPro.match("沈清妙", "shen"), [0]);
  assert.deepEqual(pinyinPro.match("沈清妙", "sqm"), [0, 1, 2]);
  assert.deepEqual(pinyinPro.match("东港", "dong"), [0]);
  assert.deepEqual(pinyinPro.match("东港", "dg"), [0, 1]);
});
