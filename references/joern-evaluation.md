# Joern 独立验证

这是一个显式运行的实验，不属于正式扫描或看板的运行依赖。固定 Joern **4.0.666**，不执行被分析项目，不安装其依赖，不修改系统 Java、Shell 配置或个人 Skill。

## 准备工具

在仓库根目录执行：

```sh
python3 scripts/experiments/setup_joern.py --output .local/joern-evaluation/tools
```

准备命令仅支持 macOS arm64，下载固定 Joern 发行包与 Temurin JDK 21.0.13+9，验证固定 SHA-256 后解压。下载需要网络；命令不会执行远程安装脚本。工具路径与来源摘要保存在 `tools.json`。其他平台可自行准备同版 Joern，并向验证命令传入可执行文件路径。

Joern 压缩包约 1.76 GB，JDK 包约 200 MB；解压后体积另外记录。已有正确摘要的包和完整下载分段可以复用。

macOS 启动脚本（包括内部 frontend 启动器）使用 `greadlink -f`。本机没有 coreutils 时，先验证系统 `/usr/bin/readlink -f` 的路径规范化行为，再在每次运行的工作目录创建仅供该进程使用的兼容链接；不改发行包或安装全局命令。不支持该行为的旧系统会显式失败。

## 执行验证

```sh
python3 scripts/experiments/joern_probe.py \
  --project /absolute/project \
  --joern /absolute/joern-cli/joern \
  --java /absolute/jdk/Contents/Home/bin/java \
  --output /absolute/allowed/new-run-directory \
  --dataflow
```

`--output` 必须是新目录；不覆盖历史证据。在被分析项目内输出时只允许 `.local/` 下的位置。每种语言默认进行两次独立索引，单阶段最多 600 秒、每个 JVM 堆上限 4 GiB；`--repeats 1` 可用于冒烟检查，`--timeout` 只能收紧超时。所有阶段保留原始输出及进程状态。

退出码 0 表示采集完成，不表示语义质量全部通过；工具失败或超时为 1，原始输入在扫描期间变化为 2。语法与覆盖诊断保存在结果中，不以工具退出成功掩盖。

三个验收输入分别为 `tests/fixtures/joern/`、CodeStrata 根目录，以及显式指定的 Future Props Lab 源码目录。真实项目路径不写入默认值。输入通过现有 inventory 捕获，沿用 Git 排除、符号链接处理、5,000 文件/单文件 512 KiB/总计 32 MiB 的引用解析预算。超限源码仍出现在盘点清单，但不喂给 Joern。

JS/TS 与 Python 使用不同输入目录与 CPG，不产生跨语言调用。分析读取捕获的源码，不导入 Python 模块，不执行 npm、项目脚本或构建；安装后的实验分析不需要联网。

macOS 上每个分析命令额外通过 `sandbox-exec` 禁止网络，并在指标中记录该隔离方式。其他平台的显式工具模式会记录网络隔离未由 runner 强制，不能据此宣称已验证离线运行。

## 结果与口径

- `snapshot.json`：捕获范围、逐文件 hash、跳过状态和源码身份。
- `results.json`：工具版本、实验文件摘要、阶段耗时、资源用量、产物体积、扫描期间输入变化与每语言状态；`experiment-source/` 保留运行时实验脚本副本。
- 每语言目录：捕获输入、两次索引、查询与导出日志、原始按需导出 JSONL、`model.json`、`joern-queries.json`、`consumer-queries.json` 和 `source-review.json`。
- 夹具另外输出 `fixture-checks.json`，与源码维护的 `expected.json` 核对，不从分析器输出生成预期。

对象 ID 来自快照、语言、源码位置、语法身份和内容，不将 Joern 数字 ID 暴露为产品身份。关系区分包含、调用候选、符号引用、控制流和数据依赖。运算符调用保留为语句，不当作业务函数。无法定位内部实现的调用保留原因；存在静态候选不等于运行时实际调用。

完整官方 GraphSON 导出在真实项目中超过 12 GB，因此正式实验命令改用有界导出：保留全局声明索引，较小项目展开全部方法，大项目按源码顺序展开 40 个非合成方法和每方法最多 100 个入向调用点，语句详细节点总预算 50,000。导出元数据记录详细范围与截断，不把全局声明覆盖误报为全图语义覆盖。JS 的 `<operator>.new` 单独保留为构造调用点，其余算术/访问运算符不作为业务函数。

核心关系最多 200,000 条、数据依赖最多 50,000 条，分别记录截断；没有详细展开的函数查询返回 `detailStatus: not-exported`，不能把空关系解释为“没有调用”。`model.json` 是离线验证产物，正式界面仍应通过焦点查询返回更小的子图。

位置中的行号先验证是否落在源码范围内，列号保留原值并标记未验证；必须通过 Unicode/多行夹具和源代码抽查后才可宣称位置精确。未提供的类型与位置不猜测。

`joern-queries.json` 测量同一个 Joern 会话内的查询；`consumer-queries.json` 测量标准化 JSON 在内存中的消费。这两组耗时不能互相替代。macOS 系统 time 提供进程峰值 RSS，另外抽样进程树 RSS；共享页可能重复计数，两者均不等于 JVM 堆使用量。

固定版本的 `joern-parse` 默认分析层已经包含数据流处理，`joern-export` 也会补充缺失的数据流层。因此索引耗时包含默认增强；`--dataflow` 请求显式核对/补充该层，不表示未传参数就没有数据流。查询结果记录实际存在的层。

源码抽查按固定文件/行顺序，选取每语言最多 10 处有内部目标、10 处未解析调用，以及 10 个有原文赋值依据的变量绑定，排除合成对象、夹具与 vendored 代码。`pending-source-review` 必须由核对源码后的记录替换，不可将自动选样描述成人工验收完成；样本也不是随机准确性调查。

机器可读汇总使用 `summarize_joern.py --run /absolute/run --run /absolute/another-run --recommendation optional-enhancement --output /absolute/new-summary.json`。接入建议必须显式指定，脚本不会从“进程成功”推导“语义正确”。

## 判定

报告分别列出两种语言的实测能力、漏报/误报、未支持语义和索引成本。最终建议仅从以下三种中选择：适合作为核心引擎、适合作为可选增强、暂不接入。不能因成功生成 CPG 或节点数量较多就判定可用；异常、finally、异步等语义未核实前不宣称完整控制流。

实验代码与正式 `scan.py`、扫描 JSON、HTTP API、看板解耦。实验失败不改变当前项目数据。原始证据留在 `.local/joern-evaluation/`，可复现说明与测试随仓库维护。
