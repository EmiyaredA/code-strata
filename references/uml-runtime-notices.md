# 标准 UML 私有运行时

- PlantUML **MIT source distribution** 1.2026.9，由官方 GitHub Releases 获取 MIT 发行 JAR；发行与许可入口：https://plantuml.com/download ，对应源码发行包位于 https://github.com/plantuml/plantuml/releases/tag/v1.2026.9 。本应用通过独立 Java 子进程调用，不改写发行包。
- Eclipse Temurin JRE 21.0.13+9，由 Adoptium 官方发行归档获取；上游：https://github.com/adoptium/temurin21-binaries 。归档内的 LICENSE、NOTICE 和 legal 文件随私有运行时完整保留。OpenJDK 使用 GPLv2 with Classpath Exception；具体依赖通知见归档 legal 目录。
- 发布 URL、版本、平台、校验值均固定在依赖锁定清单。首次安装下载二进制依赖，后续 UML 数据及源码仅在本机处理。
- 应用私有目录中的 `runtime.json` 保存所用清单，便于离线复核。清单变更产生新的安装目录；失败安装不覆盖既有目录。
