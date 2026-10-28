# CodeStrata

从源码生成可浏览、可追溯的项目地图。仓库根目录是一套完整的 AI Skill，调用名为 `$code-architecture`，入口见 [SKILL.md](SKILL.md)。

Joern 的双语言分析验证作为独立实验维护，准备、运行与数据口径见 [Joern 验证说明](references/joern-evaluation.md)；它不是正式扫描器或看板的必需依赖。

首轮实测结论为“适合作为可选增强”，具体能力、缺口、资源成本与证据索引见 [Joern 验证结果](references/joern-evaluation-results.md)。

看板联动展示架构图与真实代码树，支持技术栈依据、代码行构成、语言与目录排名、静态引用及解析范围。扫描只读取目标项目，不执行项目代码；图中连线表示静态引用，功能测试与运行时行为仍需单独验证。

看板现在支持 **文件依赖 → 函数关系 → 逻辑与变量**，JS/TS 与 Python 同步可用。函数图按调用方、当前函数、被调用方分栏；源码与代码树联动；代码结构位于左侧，可独立展开、收起并拖动调宽，收起后保留目录展开状态。使用与数据边界见 [三层浏览说明](references/code-browser.md)，实测见 [验证结果](references/code-browser-results.md)。

## 运行要求

- Python 3.10+。
- JS/TS 静态分析需要 Node.js 18+；可通过 `--node /absolute/path/to/node` 指定。
- 代码计数使用 scc。已附带 macOS arm64 的 scc 4.1.0；其他平台可使用 PATH 中的 scc，或通过 `--scc /absolute/path/to/scc` 指定。缺失时明确显示代码行数“未采集”。

看板和 JS/TS 解析器已打包，日常使用无需安装 npm 依赖，也不会自动联网下载工具或安装目标项目依赖。

## 使用

在本仓库根目录检查工具并打开目标项目：

```sh
python3 scripts/preflight.py
python3 scripts/serve.py --project /absolute/project/path --open
```

服务仅监听 `127.0.0.1`，默认固定使用 **http://127.0.0.1:8765**，并输出访问地址。可用 `--port 9000` 指定其他端口，或用 `--port 0` 自动选择空闲端口。固定端口被占用时会明确提示并退出，不会自动换地址。没有图形环境时省略 `--open`，手动打开输出的地址；结束后按 Ctrl+C 停止服务。不传 `--project` 时展示交互示例。

### 开发与热加载

修改看板时使用开发模式，前后端一起启动：

```sh
python3 scripts/serve.py --dev --project /absolute/project/path
```

前端依赖未安装时，先在 `assets/board-source` 执行 `npm ci`。也可在该目录执行 `npm run dev -- --project /absolute/project/path`。React/CSS 由 Vite 热更新，无需重新打包；`scripts/` 下的 Python 和分析器文件变动会自动重载后端，保留页面地址、当前项目及原历史库，页面不会因后端重载而刷新。新增、删除文件也会触发检查；Python 语法错误会打印到终端，并继续运行上一个版本。

已有 Agent 任务、连接测试和请求结束后才执行后端重载；等待期间可停止原任务，新任务会提示稍后重试。历史图和源码快照继续按原规则保存，应用代码热加载不会把旧快照替换成当前磁盘内容。`--port`、`--history-db` 等参数在重载后沿用；Ctrl+C 同时关闭前后端进程。普通启动仍直接使用打包产物，无需 npm 依赖。`npm run dev:frontend` 只启动独立的 Vite 前端。

在看板的“打开项目”弹窗点击“选择文件夹”，即可通过系统选择器填入目录，再点击“打开项目”扫描。也可直接粘贴绝对路径。选择器在运行服务的电脑上弹出：macOS 使用系统选择器，其他平台需要 Tkinter 和图形桌面；不可用时可继续手动输入。

可选的外置架构映射通过 `--mapping /absolute/map.json` 传入，格式见 [映射规范](references/mapping.md)。默认按目录分组，不代表已经确认的业务架构。

导出扫描 JSON：

```sh
python3 scripts/scan.py /absolute/project/path --output /absolute/output/architecture.json
```

扫描数据口径与覆盖限制见 [工程盘点契约](references/inventory.md)。目标项目限制临时文件位置时，使用 `--work-dir /absolute/allowed/path` 指定扫描工作目录。

将本仓库内容复制到 AI 工具的 Skill 目录时，使用 `code-architecture` 作为安装目录名，保留本仓库内的相对结构。例如 Codex 的个人安装目录可为 `~/.codex/skills/code-architecture/`；先检查已有版本，避免覆盖本地修改。

## 本地 Code Agent

右上角齿轮打开设置，支持 Codex、OpenCode、DeepSeek Harness（dsh）、Claude Code 和 Pi。首次打开检测本机 CLI，也可填写可执行文件绝对路径后重新检测。CLI 检测只查询版本，不调用模型、不安装软件；“已检测到”不代表已登录或模型连接有效。

选中 Agent 后自动读取其模型目录，支持搜索名称、ID 和提供商；选中模型可复制完整 ID，也可从列表底部切换为手动输入。已有但不在目录里的 ID 会保留，不自动替换成其他模型。未设置覆盖值时，直接显示 CLI 读出的具体模型与完整 ID，并标明本机配置来源。读取失败则明确提示，不使用目录第一项代替默认模型。选择默认 Agent 和模型后点击“保存设置”。路径留空使用自动检测；登录、密钥和服务地址继续由各 CLI 管理，网页不保存密钥。Node 启动的 CLI 可共用服务的 `--node` 参数指定可用解释器。

模型目录按 CLI 实际返回值展示，缓存五分钟，可点击刷新强制重取；它可能需要联网读取目录，但不发送生成请求，也不证明账号可调用所有条目。旧版本不支持查询、未登录或没有模型时，仍可手动输入 ID。DeepSeek Harness 使用原生 ACP profile 获取目录，创建无提示词会话后关闭，CLI 自身可能保留空会话记录；其模型 ID 可能是结构化字符串，选择或复制时原样保留，不改写成猜测的名称。

模型下方按实际能力显示额外参数，未设置覆盖值时显示本机实际配置及来源；只有 CLI 明确表示未配置时才使用其模型目录给出的默认值，未知值不会猜成 medium、标准或关闭：

| Agent | 额外配置与调用方式 |
| --- | --- |
| Codex | 模型目录提供的推理强度与速度档位，使用 `-c model_reasoning_effort=…`、`-c service_tier=…`；先选择具体模型。 |
| OpenCode | 当前模型元数据中的变体，原样传给 `--variant`，不猜测固定档位。 |
| DeepSeek Harness | ACP 当前模型的思考档位；切换模型后重新查询，通过 `session/set_config_option` 应用。 |
| Claude Code | 初始化元数据中当前模型支持的 effort 与快速模式，使用 `--effort` 和单次调用的 `--settings`，不改写 Claude 的设置文件。 |
| Pi | 本机 `--help` 声明的 `--thinking` 档位；CLI 会根据模型能力调整实际档位。 |

切换模型会清除旧模型的参数覆盖，重新读取对应模型的具体参数，并提示该变化；切换 Agent 会分别保留各自配置。刷新目录不修改已有参数或测试结果；当前模型不再支持已保存的档位时保留原值并提示，重新选择有效值后才能测试。测试前后端会再次校验参数，参数确实进入本次 CLI/ACP 调用。本机值通过 Codex `config/read`、Claude `get_settings` 的 `applied` 和初始化状态、DeepSeek Harness ACP `currentValue`、Pi RPC `get_state`、OpenCode `debug config` 读取；只返回模型和参数字段，不返回原始配置或凭据。已知用户配置文件变化会使缓存失效，刷新可强制重新读取。下拉列表中同一个实际值只显示一次，配置来源放在字段旁说明，不再拆成“本机”和“固定值”两个选项。Codex 可明确选择“标准”（`default`）或目录中支持的速度档位。Fast 档位可能增加费用或额度消耗，也可能受账户权限限制。行为参考 [OpenCode CLI](https://opencode.ai/docs/cli/)、[Claude effort](https://code.claude.com/docs/en/cli-reference)、[Claude 快速模式](https://code.claude.com/docs/en/fast-mode) 与 [Pi CLI](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli.md)，实际可选项以本机 CLI 返回为准。

“测试连接”使用当前表单配置，无需先保存。点击后才会发送一条实际模型请求，可能消耗 CLI 对应账号的额度；测试在临时空目录执行，不提供当前项目路径或源码。测试最多运行 90 秒，可手动取消，关闭设置也会取消。CLI 自身仍可能保存其运行记录或初始化原生 profile。结果详情仅在本次服务内保留，不写入设置文件。

设置对当前系统用户的所有项目生效，保存在 `$XDG_CONFIG_HOME/code-strata/settings.json`；未设置该变量时使用 `~/.config/code-strata/settings.json`。已有服务进程需重启才能加载新增接口。

## Agent 探索

打开本地项目后，切换到 **功能解读**，选择 Agent 并描述要理解的功能。左侧显示阅读图，右侧通高会话滑窗保存聊天与真实工具记录；点击节点或连线，在图区域的源码弹窗查看分析时的代码。每个会话固定一种 Agent，同时执行一个任务，维护一张当前图；后续轮次使用设置中该 Agent 的模型和参数。

会话滑窗从页面顶部延伸到底部，桌面默认约占三分之一，左侧代码图随宽度调整。拖动左边界调宽，方向键每次调整 24px（Shift 为 48px），双击恢复默认宽度，偏好在当前浏览器保存。点右上角收起，或按 Esc 关闭当前菜单/源码弹窗后收起会话；页面顶栏“会话”可在代码地图、文件浏览和功能解读中独立展开、收起，图右上角也可重新打开。收起不取消任务，也不清空草稿、历史或阅读图。窄屏使用覆盖式滑窗，手机尺寸占满视口；阅读历史、新主题、复制会话 ID 和输入框都位于滑窗内。

工具提供 Python/TS 静态关系和源码依据；Agent 负责范围、分组、阅读顺序和解释。调用边只能引用本轮查询返回的 ID，确定性保持原状；调用、导入和函数结构分别呈现。点击“发送”才调用模型并向其提供查询到的源码；不执行目标项目代码。CLI 登录、原生会话和联网由各 CLI 管理。Codex、OpenCode、Claude Code 使用单次 MCP 配置，dsh 通过 ACP 注入 MCP，Pi 使用工具扩展与 RPC。

会话、图和源码快照保存到 `$XDG_DATA_HOME/code-strata/exploration.sqlite3`，默认 `~/.local/share/code-strata/exploration.sqlite3`；可用 `serve.py --history-db /absolute/history.sqlite3` 指定位置。源码按内容去重，历史消息绑定各自的快照，重启后可恢复。打开会话、重新扫描时检查整个扫描范围的源码、配置和分析器变化，保守地标记“已过时”，覆盖新增调用方。点击“让 Agent 更新”才分析当前代码；正常完成并通过证据校验后替换图，失败或停止保留原图，历史源码仍可读。

### 外部 Agent 读取历史

`read_source` 和 `read_snapshot_source` 可以读取快照中已捕获的源码及配置正文，包括 `package.json`、HTML、CSS 和暂不支持语义解析的语言；调用关系分析仍按各语言解析器的实际能力提供。读取范围沿用扫描的排除规则和预算。旧快照已有的配置正文可直接读取；旧快照没有保存的其他正文，需要点击“让 Agent 更新”创建新快照，历史快照不会回填当前磁盘内容。

复制应用会话 ID，在外部 Agent 中配置本地 MCP stdio 服务（替换实际绝对路径）：

```json
{"mcpServers":{"code-strata-history":{"command":"python3","args":["/absolute/code-strata/scripts/exploration_mcp.py","--stdio"]}}}
```

服务直接以只读模式查询 SQLite，不依赖网页或 HTTP 服务存活。自定义数据库在 args 中追加 `--database /absolute/history.sqlite3`。提供 `get_conversation(id,cursor,limit)`、`get_view(id)`、`read_snapshot_source(id,snapshotId,path,startLine,endLine)`；不暴露生成图或修改会话的能力。聊天每页最多 100 条，源码每次最多 300 行，返回 `nextCursor`/`nextLine`；消息的 `snapshot_id` 指向其原始源码。ID 是记录定位符，访问权限来自本机数据文件权限，不是公开分享链接。

也可以直接查询：

```sh
python3 scripts/exploration_mcp.py --call get_conversation --arguments '{"id":"应用会话ID","limit":20}'
```

## 开发与验证

```sh
python3 -m unittest discover -s tests -v
```

测试可通过 `CODE_ARCHITECTURE_TEST_NODE` 指定 Node 路径，通过 `CODE_ARCHITECTURE_TEST_TMP` 指定临时目录。

前端源码位于 `assets/board-source/`，运行成品位于 `assets/board/`。修改前端后，在源码目录安装锁定依赖并重建；构建也会更新 `scripts/parse-js.cjs` 和 `scripts/analyze-code.cjs`：

```sh
cd assets/board-source
npm ci
npm run build
```

重建后运行测试，并检查架构图与代码树双向选择、源码定位和桌面布局。第三方许可保留在 `assets/third-party/`、`assets/tools/`、`scripts/_vendor/` 及相关 bundle 的许可文件中。
