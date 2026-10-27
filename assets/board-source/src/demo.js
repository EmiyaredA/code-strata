const code = {
  "apps/editor/src/SavePanel.tsx":
    'import { saveDocument } from "../../../packages/content/src/save";\nexport function SavePanel() {\n  return <button onClick={() => saveDocument("demo", "内容")}>保存</button>;\n}\n',
  "apps/editor/src/LoadPanel.tsx":
    'import { loadDocument } from "../../../packages/content/src/load";\nexport function LoadPanel() { return <article>{loadDocument("demo")}</article>; }\n',
  "packages/content/src/save.ts":
    'import { canEdit } from "../../access/src/canEdit";\nimport type { Document } from "../../shared/src/documentTypes";\nexport function saveDocument(id: string, text: string): Document {\n  if (!canEdit(id)) throw new Error("没有编辑权限");\n  return { id, text };\n}\n',
  "packages/content/src/load.ts":
    'import type { Document } from "../../shared/src/documentTypes";\nexport function loadDocument(id: string): Document { return { id, text: "示例" }; }\n',
  "packages/access/src/canEdit.ts":
    "export function canEdit(documentId: string) {\n  return documentId.length > 0;\n}\n",
  "packages/shared/src/documentTypes.ts":
    "export interface Document {\n  id: string;\n  text: string;\n}\n",
  "packages/assets/src/upload.ts":
    'import { canEdit } from "../../access/src/canEdit";\nexport function upload(id: string, file: File) {\n  if (!canEdit(id)) throw new Error("没有上传权限");\n  return file.name;\n}\n',
  "scripts/tools/diagnostics/inspect-very-long-source-filename-for-document-integrity.ts":
    "export function inspectDocumentIntegrity() {\n  return { valid: true };\n}\n",
  ...Object.fromEntries(
    Array.from({ length: 22 }, (_, i) => [
      `scripts/maintenance/task-${String(i + 1).padStart(2, "0")}.ts`,
      `export const task${i + 1} = "maintenance";\n`,
    ]),
  ),
};
const files = Object.entries(code).map(([id, content]) => ({
  id,
  path: id,
  content,
  language: id.endsWith("tsx") ? "typescript" : "typescript",
  symbols: [],
}));
const groups = [
  {
    id: "save",
    title: "内容保存",
    files: [
      "apps/editor/src/SavePanel.tsx",
      "packages/content/src/save.ts",
      "packages/shared/src/documentTypes.ts",
    ],
    origin: "confirmed",
    description: "编辑入口与内容保存，包含跨目录的界面和核心实现。",
    source: "示例架构映射",
  },
  {
    id: "read",
    title: "内容读取",
    files: [
      "apps/editor/src/LoadPanel.tsx",
      "packages/content/src/load.ts",
      "packages/shared/src/documentTypes.ts",
    ],
    origin: "confirmed",
    description: "读取文档并在编辑器中展示。",
    source: "示例架构映射",
  },
  {
    id: "access",
    title: "访问校验",
    files: ["packages/access/src/canEdit.ts"],
    origin: "confirmed",
    description: "供内容和文件操作共用的权限检查。",
    source: "示例架构映射",
  },
  {
    id: "assets",
    title: "文件处理",
    files: ["packages/assets/src/upload.ts"],
    origin: "confirmed",
    description: "编辑器文件上传与访问检查。",
    source: "示例架构映射",
  },
];
const imports = [
  {
    from: files[0].id,
    to: files[2].id,
    line: 1,
    text: code[files[0].id].split("\n")[0],
  },
  {
    from: files[1].id,
    to: files[3].id,
    line: 1,
    text: code[files[1].id].split("\n")[0],
  },
  {
    from: files[2].id,
    to: files[4].id,
    line: 1,
    text: code[files[2].id].split("\n")[0],
  },
  {
    from: files[6].id,
    to: files[4].id,
    line: 1,
    text: code[files[6].id].split("\n")[0],
  },
];
const edges = [
  {
    id: "save-access",
    source: "save",
    target: "access",
    evidence: [imports[2]],
  },
  {
    id: "assets-access",
    source: "assets",
    target: "access",
    evidence: [imports[3]],
  },
];
export const demo = {
  version: 1,
  project: { name: "示例工程", sample: true, root: "" },
  snapshot: { id: "S-017", scannedAt: "2026-10-27T00:00:00Z" },
  files,
  groups,
  imports,
  edges,
  diagnostics: [],
  mappingPath: null,
  limitations: ["示例用于展示联动；打开项目后将使用实际扫描结果。"],
};
