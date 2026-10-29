# 项目 UML 工作区

主界面由目录、项目图文档和可收起会话组成。图不是会话的附件副本：同一规范化项目路径共享同一图集。每个版本记录类型、标题、用途、结构化元素、逐元素解释、来源会话、任务及源码快照。

## 交互

- 每个 Tab 显示图名和类型；用途位于标签栏下方的精简说明栏。长用途可悬停查看。关闭 Tab 不删除文档，图列表可重新打开；选中 Tab 后用左右方向键、Home、End 切换。
- 单击节点或关系打开底部检查窗，自动展开相关目录。当前依据文件高亮整行，其他关联文件显示标记；单击目录文件只打开快照源码，不切换到另一工作区。
- 检查窗把源码与 AI 解释并排显示。存在多个调用处、定义或关联文件时，通过位置标签切换；点击解释中的源码引用也能定位。源码每次读取不超过 300 行，支持前后分页。
- 检查窗上边界、目录右边界、会话左边界可拖动；聚焦分隔条后用方向键调整。Esc 关闭检查窗并恢复原焦点。窄窗口使用目录抽屉，源码和解释上下排列。
- 各图、各版本分别保存选择和视口；切换 Tab、版本、项目或关闭检查窗会废弃过期源码请求。浏览器偏好使用项目路径作为键，不随会话切换。
- 技术栈、规模及解析范围收在顶栏“项目概览”图标中。旧的代码地图／功能解读切换、常驻源码和调用层级不占主工作区。

## 图形与布局

使用现有 React Flow 和 ELK。活动图、状态图按层级向下布局，较长的无分支活动链折行显示并保留真实连接顺序；类型、组件、用例和部署结构采用层级与容器布局。时序图使用独立生命线，按唯一 `order` 排列消息，支持同步消息、异步、返回、创建、销毁及自身调用。继承／实现使用空心三角，组合／聚合使用菱形，依赖及返回使用虚线。

这是一套有明确类型及关系角色的源码阅读 UML 子集；不导入任意 PlantUML、Mermaid 或 HTML。不会把静态关系说成运行时调用栈、实际变量值或完整程序证明。长图初始缩放有可读性下限，可平移、缩放或点击适应全图。

## Agent 工具与证据

运行期新增 `list_diagrams`、`get_diagram`、`get_diagram_draft` 和 `save_diagrams`。已有 `search_code`、`query_code`、`read_source` 仍只访问本轮不可变快照；`query_code` 也支持 `hierarchy` 的直接调用关系分页。`save_view` 和旧读取工具继续兼容历史记录，不用于新增 UML。

`save_diagrams` 的输入示例：

```json
{
  "diagrams": [{
    "type": "activity",
    "title": "安全发布配置",
    "purpose": "说明先备份，再发布的源码顺序",
    "nodes": [
      {"id":"backup","label":"备份旧配置","role":"action","evidenceIds":["本轮 read_source 返回的 evidenceId"],"explanation":"先持久化备份。"},
      {"id":"check","label":"检查旧文件未变化","role":"action","evidenceIds":["检查处真实 evidenceId"],"explanation":"变化时抛出异常并停止。"},
      {"id":"publish","label":"发布新配置","role":"action","evidenceIds":["另一处真实 evidenceId"],"explanation":"原文件检查成功后才发布。"}
    ],
    "edges": [
      {"id":"checked","source":"backup","target":"check","role":"flow","evidenceIds":["相关真实 evidenceId"],"explanation":"备份完成后检查原文件。"},
      {"id":"publishNext","source":"check","target":"publish","role":"flow","evidenceIds":["相关真实 evidenceId"],"explanation":"检查通过后发布；检查失败抛出异常。"}
    ]
  }]
}
```

占位 evidenceId 不可实际提交。真实调用先读取源码或查询代码，后端只接受该任务收到的节点／关系 ID 或 `read_source` 返回的 `evidenceId`，并补齐快照、路径、行范围、内容哈希和依据类型。关系中的多个调用位置逐一保留；定义行号与调用行号分别展示。普通业务节点和关系必须有依据；起止、汇合等纯 UML 符号继承整图依据。

源码推导与分析器事实分开。只有图中两个端点分别引用分析器关系的原端点，才将该关系标为 `basis: analyzer`；其他关系为 `inferred`。候选及未解析状态不能由 Agent 改为确定。角色、模块和流程推导只是引用源码的解释，不表示分析器证明了该业务含义。

后端验证类型角色、端点、容器循环及容器类型、唯一时序顺序、依据来源、源码范围和数量预算。只读取捕获过的正文，不接受自由磁盘路径或活动内容。每图最多 100 个节点、300 条关系，每轮 1–12 张图；超过时需缩小范围。

## 共享、版本与发布

- 新文档不带 ID。明确更新时带文档 `id` 和 `expectedRevision`。消息包含当前图 ID 和预期版本，作为本轮上下文；普通追问无需保存图，另画新图不会强制覆盖当前图。
- `save_diagrams` 校验后写草稿，只有任务正常结束才在一个 SQLite 事务中发布整批文档。任务失败、取消或重启中断不发布。
- 事务先检查所有预期版本，再写任何文档。其他会话抢先更新时整批拒绝，保留草稿，重新读取并重新查询后恢复。图列表中的“未发布草稿”可查看原数据或准备恢复问题，发送后才调用 Agent。
- 历史阅读图按来源会话幂等导入；新的旧式阅读任务形成该旧文档的新版本，不会重启一次就复制一份。只有明确重新生成时才转换 UML。

## HTTP 接口

所有接口沿用本地应用令牌；图文档访问范围限定到当前项目。

| 方法与路径 | 输入／结果 |
| --- | --- |
| `GET /api/explore/diagrams?offset=0&limit=50` | 分页摘要、`nextOffset`；详细数据按需读取 |
| `GET /api/explore/diagrams/{id}?revision=1` | 指定版本；省略版本读取最新 |
| `GET /api/explore/diagrams/{id}/versions` | 不可变版本列表 |
| `POST /api/explore/diagrams/{id}/source` | `revision,path,startLine,endLine`；读取该图快照正文 |
| `POST /api/explore/diagrams/{id}/check` | 可选 `revision`；返回逐文件状态及分析器变化 |
| `POST /api/explore/diagrams/check` | `diagrams:[{id,revision}]`；最多 100 张，合并重复文件哈希读取 |
| `GET /api/explore/diagrams/drafts` | 本项目未发布任务草稿 |
| `POST /api/explore/conversations/{id}/messages` | 原问题参数加 `diagramId,expectedRevision`；`update:true` 显式捕获新快照并要求更新指定图 |

更新冲突返回 409；合约无效返回 422；文档不在当前项目或源码正文不存在返回 404。读取历史版本不会自动重定位到实时文件。

## 源码变化

打开项目、焦点恢复、手动扫描以及页面可见时每 30 秒，检查已打开图的依据文件。未变化、修改、删除、检查失败分别记录；其他文件变化不直接判定图过期。分析器变化另行提示，需显式重新分析。

版本始终打开其原快照。删除和移动之后，目录提供“历史快照文件”入口；没有猜测改名和自动行号迁移。点击“根据当前代码更新”才调用模型、重捕获和查询；成功增加版本，失败、取消或冲突保留现有版本。检查本身不调用模型。

## 七种类型的可复现样例

创建一个**尚不存在**的临时目录；脚本只写隔离示例，不调用模型，不执行目标项目代码：

```sh
python3 scripts/uml_demo.py /tmp/strata-uml-demo
python3 scripts/serve.py --project /tmp/strata-uml-demo/project --history-db /tmp/strata-uml-demo/history.sqlite3 --open
```

脚本通过与 Agent 相同的证据验证及原子存储建立七图；配置迁移使用真实源码的固定回归副本，其余使用显式的示例领域模型，不能解读为用户项目的生产架构。图列表打开各图；也可以在会话中发送下列问题，验证真实模型生成：

| 类型 | 生成问题与检查点 |
| --- | --- |
| 活动图 | “画 migration.py 加锁后的安全发布路径。”检查 L63–65 加锁后读取，L76 备份，L77 检查旧文件，L79 发布，L80 回读校验；异常不作为正常顺序。 |
| 时序图 | “画 domain.py 的 CLI 保存交互。”检查 CLI → ConfigService → Repository，返回虚线，自身状态赋值按消息顺序排列。 |
| 类图 | “画 domain.py 类型关系。”检查 MemoryRepository 继承 Repository、ConfigService 依赖 Repository 和 State，成员单独分隔。 |
| 组件图 | “按职责整理 CLI、服务与存储。”明确为源码推导，不说成三个部署进程。 |
| 状态图 | “画 State 在保存成功和失败时的变化。”检查 READY → SAVED／FAILED，无虚构的恢复边。 |
| 用例图 | “说明 CLI 操作者可以做什么。”检查角色、系统边界、保存配置用例；角色来自已读 CLI 语义。 |
| 部署图 | “根据 pyproject.toml 的示例拓扑画本地部署。”检查工作站包含 Python 进程及 domain.py，不能虚构远端服务。 |

验证源码漂移时，可在隔离项目中给 migration.py 前面插入注释、删除或移动文件，再手动扫描。旧图仍应打开旧 L76/L79/L80；更新后新版本依据应随新快照重新查询，旧版本不变。

## 回归

```sh
node --test assets/board-source/tests/*.test.mjs
python3 -m unittest discover -s tests -v
npm --prefix assets/board-source run build
```

`test_uml.py` 覆盖七类合约、共享／隔离、不可变版本、原子冲突、迁移、多调用处及修改／删除／移动。`test_uml_transport.py` 通过真实 MCP 桥和五种 CLI 适配器（无 LLM 的协议夹具）验证发布、显式更新、另建新图、失败和取消。浏览器验收见 [design-qa.md](../design-qa.md)。
