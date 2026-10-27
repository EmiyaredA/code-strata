# CodeStrata

从源码生成可浏览、可追溯的项目地图。仓库根目录是一套完整的 AI Skill，调用名为 `$code-architecture`，入口见 [SKILL.md](SKILL.md)。

Joern 的双语言分析验证作为独立实验维护，准备、运行与数据口径见 [Joern 验证说明](references/joern-evaluation.md)；它不是正式扫描器或看板的必需依赖。

首轮实测结论为“适合作为可选增强”，具体能力、缺口、资源成本与证据索引见 [Joern 验证结果](references/joern-evaluation-results.md)。

看板联动展示架构图与真实代码树，支持技术栈依据、代码行构成、语言与目录排名、静态引用及解析范围。扫描只读取目标项目，不执行项目代码；图中连线表示静态引用，功能测试与运行时行为仍需单独验证。

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

服务仅监听 `127.0.0.1`，自动选择端口并输出访问地址。没有图形环境时省略 `--open`，手动打开输出的地址；结束后按 Ctrl+C 停止服务。不传 `--project` 时展示交互示例。

在看板的“打开项目”弹窗点击“选择文件夹”，即可通过系统选择器填入目录，再点击“打开项目”扫描。也可直接粘贴绝对路径。选择器在运行服务的电脑上弹出：macOS 使用系统选择器，其他平台需要 Tkinter 和图形桌面；不可用时可继续手动输入。

可选的外置架构映射通过 `--mapping /absolute/map.json` 传入，格式见 [映射规范](references/mapping.md)。默认按目录分组，不代表已经确认的业务架构。

导出扫描 JSON：

```sh
python3 scripts/scan.py /absolute/project/path --output /absolute/output/architecture.json
```

扫描数据口径与覆盖限制见 [工程盘点契约](references/inventory.md)。目标项目限制临时文件位置时，使用 `--work-dir /absolute/allowed/path` 指定扫描工作目录。

将本仓库内容复制到 AI 工具的 Skill 目录时，使用 `code-architecture` 作为安装目录名，保留本仓库内的相对结构。例如 Codex 的个人安装目录可为 `~/.codex/skills/code-architecture/`；先检查已有版本，避免覆盖本地修改。

## 开发与验证

```sh
python3 -m unittest discover -s tests -v
```

测试可通过 `CODE_ARCHITECTURE_TEST_NODE` 指定 Node 路径，通过 `CODE_ARCHITECTURE_TEST_TMP` 指定临时目录。

前端源码位于 `assets/board-source/`，运行成品位于 `assets/board/`。修改前端后，在源码目录安装锁定依赖并重建；构建也会更新 `scripts/parse-js.cjs`：

```sh
cd assets/board-source
npm ci
npm run build
```

重建后运行测试，并检查架构图与代码树双向选择、源码定位和桌面布局。第三方许可保留在 `assets/third-party/`、`assets/tools/`、`scripts/_vendor/` 及相关 bundle 的许可文件中。
