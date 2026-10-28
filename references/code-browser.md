# 三层代码浏览

系统架构是默认入口。选中模块或文件后点击“浏览文件”，依次查看文件引用、函数调用、函数内部结构与变量引用。日常运行不依赖 Joern 或 JDK。

## 阅读与交互

- 文件图：**引用方 → 当前文件 → 被引用方**。箭头仍是原扫描器解析的文件导入，不把函数调用汇总冒充文件导入。
- 函数图：**调用方 → 当前函数 → 被调用方**。从文件进入时，按顶层函数、名称与函数体范围选择默认浏览焦点；这不表示识别出了运行时入口。使用“选择当前函数”或左侧结构列表切换。
- 未解析调用先合并成可展开卡片。候选使用不同的虚线；递归和互相调用有明确标识。嵌套声明在结构列表中，不作为调用边。
- 逻辑图：标出函数体开始、语句、分支、返回或抛错位置；连线表示简化结构顺序和包含关系。异常、finally、异步和生成器保留源码结构，不声称完整恢复控制流或运行路径。
- 选中变量查看定义及符号引用。读取、赋值、读写、删除、类型引用、闭包捕获分别记录；多次赋值不建立未经验证的“赋值流向使用”关系。
- 单击选择，明确按钮或双击进入；面包屑返回。缩放不切换层级。返回时保留对象、视口、代码树展开状态和未解析调用展开状态。
- 系统架构也可以点击模块聚焦上下游，或返回全项目概览；概览按有向依赖分层，循环引用和无已解析关联的模块单独表达。
- 拖动两侧面板之间的分隔条调整宽度；方向键可微调，双击恢复默认。架构与代码视图分别保存宽度，保存在同一本地服务地址的浏览器存储中。

## 分析边界

JS/TS 使用固定的 TypeScript 5.9.3 Compiler API；Python 使用当前 Python 的 `ast` 和 `symtable`。解析器只读取同次扫描捕获的源码与配置，不调用目标项目代码、不安装目标依赖、不读取安装环境中的类型声明，也不展开跨语言调用。

源码预算沿用现有规则：最多 5000 个解析文件，单文件 512 KiB、合计 32 MiB。未解析或超限文件仍保留盘点、计数和原因。配置继承仅处理捕获范围内的 tsconfig；未捕获的继承配置会产生诊断。Python 支持相对导入及现有 src/backend 模块布局；依赖脚本启动目录或动态修改 sys.path 的导入可能保持未解析。

静态调用目标分为 `resolved`、`candidate`、`unresolved`。属性派发、装饰器、重赋值和未定位的构造实现保留不确定性。仅来自调用签名的声明也保持候选，不视为已确定的函数值；候选集合不保证完整。Python 的 from-import 产生独立局部绑定，未把导入值与原模块变量当成同一个可变变量。实例动态属性、框架注入、外部库以及回调参数经常无法定位到实现。

## 快照与查询接口

原 `scan.py` JSON 的 `version: 1`、文件导入、架构边和 API 保持原含义。配置保存在服务器私有快照中，不添加到原扫描响应。语义索引首次使用时在后台建立，在当前会话复用；逻辑结构按函数生成并缓存。

`POST /api/code/query` 沿用本地服务的来源检查和 `X-Architecture-Token`。请求最少包含：

```json
{"snapshotId":"当前快照 ID","view":"functions","focusId":"文件相对路径或对象 ID"}
```

- `view`：`files`、`functions`、`logic`、`references`、`symbols`、`search`。
- `groupId`：文件视图中的架构分组；`text`：搜索词。
- `hops`：1–5；`limit`：1–100；`offset`：节点窗口；`edgeOffset`：当前窗口内的关系分页。
- 返回 `version`、`snapshotId`、`status`、`focus`、`nodes`、`relations`、`symbols`、`variables`、`references`、诊断及剩余数量。`defaultFocus` 明确自动选取浏览焦点的依据。引擎元数据含编译器/解释器版本及适配器哈希；`ready` 表示索引流程完成，不表示全部调用均已解析。
- 首次索引返回 HTTP 202、`status: building` 和重试时间；完成为 `ready` 或 `partial`。分析器失败返回原因，并保留架构结果。快照过期或项目切换返回 HTTP 409。
- 一次画布最多 100 个代码对象和 300 条关系，额外 UI 标记独立生成；窗口切换保留可见焦点。详情另有 100 个变量、300 个引用的预算，超限明确标记，可进入变量引用视图继续分页。

所有源码范围统一为一基行号、零基 UTF-16 列、结束位置不包含。对象 ID 基于相对路径、对象类型及范围生成；不使用内部 AST/编译器编号。它们在相同输入下稳定，不保证编辑后仍标识同一语义对象。重扫后重新校验对象，失效时回到有效文件范围。

## 导出和复现

建议导出有界视图，避免把大型项目完整索引一次性放入 AI 上下文：

```sh
python3 scripts/analyze_code.py --project /absolute/project --view files --focus src/example.py --output /absolute/output/files.json
python3 scripts/analyze_code.py --project /absolute/project --view search --query download --output /absolute/output/symbols.json
```

使用查询返回的函数或变量 ID，继续导出 `functions`、`logic` 或 `references`。省略 `--view` 导出完整统一模型；大项目可能有数百 MiB。可显式指定 `--node`、`--scc`、`--mapping` 和 `--work-dir`。导出只分析捕获的输入，不修改目标项目。

复现实测与生成固定核对工作表：

```sh
python3 scripts/evaluate_code_browser.py --project /absolute/project --output /absolute/allowed/evaluation --node /absolute/node
```

输出完整模型、源码快照、资源与查询测量，以及每语言 20 个调用、10 个变量的核对工作表。新生成的工作表为 `pending`，不会自动声称已完成源码核对。测试与结果见 [三层浏览验证](code-browser-results.md)。
