import hljs from "highlight.js/lib/common";

const aliases = { jsx: "javascript", tsx: "typescript", ts: "typescript", js: "javascript", py: "python", html: "xml", htm: "xml", svg: "xml", yml: "yaml", sh: "bash", shell: "bash", toml: "ini", md: "markdown" };
const extensions = { mjs: "javascript", cjs: "javascript", mts: "typescript", cts: "typescript", json: "json", css: "css", scss: "scss", less: "less", sql: "sql", java: "java", go: "go", rs: "rust", rb: "ruby", php: "php", cs: "csharp", h: "c", cpp: "cpp", hpp: "cpp", kt: "kotlin", m: "objectivec", swift: "swift", pl: "perl", r: "r", bash: "bash", zsh: "bash" };
const entities = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#x27;": "'" };
const decode = (text) => text.replace(/&(?:amp|lt|gt|quot|#x27);/g, (entity) => entities[entity]);
const plainLines = (text) => text.split("\n").map((line) => line ? [{ text: line, className: "", start: 0, end: line.length }] : []);

export function syntaxLanguage(language = "", path = "") {
  const name = String(language).toLowerCase();
  const known = aliases[name] || name;
  if (hljs.getLanguage(known)) return known;
  const extension = path.split(".").at(-1)?.toLowerCase();
  const inferred = aliases[extension] || extensions[extension] || extension;
  return hljs.getLanguage(inferred || "") ? inferred : null;
}

export function highlightedLines(text = "", language, path) {
  const grammar = syntaxLanguage(language, path);
  if (!grammar || !text) return plainLines(text);
  try {
    // Parse only markup emitted by the highlighter. Source always becomes React text,
    // including literal HTML/script tags; no source HTML is inserted into the DOM.
    const html = hljs.highlight(text, { language: grammar, ignoreIllegals: true }).value;
    const lines = [[]];
    const stack = [];
    let offset = 0;
    for (const piece of html.split(/(<span class="[^"]+">|<\/span>)/g)) {
      if (piece.startsWith('<span class="')) {
        stack.push(piece.slice(13, -2));
      } else if (piece === "</span>") {
        stack.pop();
      } else {
        const parts = decode(piece).split("\n");
        for (let index = 0; index < parts.length; index++) {
          if (index) { lines.push([]); offset = 0; }
          const content = parts[index];
          if (content) lines.at(-1).push({ text: content, className: stack.join(" "), start: offset, end: offset + content.length });
          offset += content.length;
        }
      }
    }
    return lines.map((line) => line.map((token) => token.text).join("")).join("\n") === text ? lines : plainLines(text);
  } catch {
    return plainLines(text);
  }
}

export function sliceTokens(tokens = [], start = 0, end = Infinity) {
  return tokens.filter((token) => token.end > start && token.start < end).map((token) => ({
    ...token,
    text: token.text.slice(Math.max(0, start - token.start), Math.min(token.text.length, end - token.start)),
    start: Math.max(start, token.start),
    end: Math.min(end, token.end),
  }));
}
