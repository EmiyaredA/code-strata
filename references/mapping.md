# 架构映射与扫描数据

映射是版本化 JSON。它只维护架构、来源和文件成员；依赖关系由真实 import 记录投影。源码相对路径使用 `/`，精确匹配，不支持通配符。未知成员在诊断中保留，不参与连线。

```json
{
  "version": 1,
  "groups": [
    {
      "id": "content.save",
      "title": "内容保存",
      "description": "编辑入口和保存处理。",
      "files": ["apps/editor/src/SavePanel.tsx", "packages/content/src/save.ts"],
      "origin": "inferred",
      "source": "docs/architecture.md 的内容编辑章节；相关源码"
    }
  ]
}
```

- `id` 在同一项目中唯一；架构改名时保持 ID。`title` 必填。
- `files` 可跨目录，也允许一份源码被多个架构引用。没有对应模块的文件仍在代码树和搜索中可见。
- `origin`：`confirmed` 人工确认、`inferred` 推断待确认、`directory` 机械目录分组。省略时默认 `inferred`。
- `source` 引用现有文档或判断依据，不复制一套架构正文。

扫描输出 `version: 1`：

- `project`：名称、显式打开的根目录、是否示例。
- `snapshot`：源码内容指纹（包括解析配置）、独立的映射指纹、可用的 Git commit 与扫描时间。内容指纹是实际输入身份，commit 不能代替未提交源码的状态。
- `files`：相对路径 ID、语言、内容 hash、源码、顶层符号及行号。
- `imports`：`from`、`to` 文件 ID，`line`、`text`、`specifier` 和静态引用种类。
- `groups`：校验后的架构成员。
- `edges`：架构间投影连线，每条带原始 `evidence` 引用记录。不生成无源码依据的人工依赖。
- 新增工程盘点字段见 [工程盘点契约](inventory.md)。
- `diagnostics` / `limitations`：未解析导入、语法错误、失效映射、预算截断和能力边界。

这些数据仅在本地读取和浏览。JSON 导出包含源代码；只保存到明确允许的位置，不自动上传或发布。
