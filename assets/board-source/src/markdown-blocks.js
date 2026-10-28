// A small, text-only block parser. Cell content is rendered by React, never as HTML.
function tableRow(line) {
  const text = line.trim(), cells = [];
  let cell = "", ticks = 0, hasPipe = false, trailingPipe = false;
  for (let i = 0; i < text.length; i++) {
    const character = text[i];
    if (character === "\\" && ["|", "\\"].includes(text[i + 1])) {
      cell += text[++i];
      trailingPipe = false;
    } else if (character === "`") {
      let count = 1;
      while (text[i + 1] === "`") { count++; i++; }
      if (!ticks) ticks = count;
      else if (ticks === count) ticks = 0;
      cell += "`".repeat(count);
      trailingPipe = false;
    } else if (character === "|" && !ticks) {
      cells.push(cell.trim()); cell = ""; hasPipe = true; trailingPipe = true;
    } else {
      cell += character;
      trailingPipe = false;
    }
  }
  cells.push(cell.trim());
  if (text.startsWith("|")) cells.shift();
  if (trailingPipe) cells.pop();
  return { cells, hasPipe };
}

export function markdownBlocks(text) {
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n"), blocks = [];
  for (let i = 0; i < lines.length; i++) {
    const fence = lines[i].match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if (fence) {
      const content = [], close = new RegExp(`^ {0,3}${fence[1][0]}{${fence[1].length},}\\s*$`);
      while (++i < lines.length && !close.test(lines[i])) content.push(lines[i]);
      blocks.push({ kind: "code", text: content.join("\n") });
      continue;
    }
    const header = tableRow(lines[i]), separator = i + 1 < lines.length ? tableRow(lines[i + 1]) : null;
    if (header.hasPipe && separator?.cells.length === header.cells.length && separator.cells.every(cell => /^:?-+:?$/.test(cell))) {
      const align = separator.cells.map(cell => cell.startsWith(":") && cell.endsWith(":") ? "center" : cell.endsWith(":") ? "right" : "left");
      const rows = [];
      i++;
      while (i + 1 < lines.length && lines[i + 1].trim()) {
        const row = tableRow(lines[i + 1]);
        if (!row.hasPipe || /^ {0,3}(`{3,}|~{3,})/.test(lines[i + 1])) break;
        rows.push(header.cells.map((_, column) => row.cells[column] || ""));
        i++;
      }
      blocks.push({ kind: "table", header: header.cells, align, rows });
    } else blocks.push({ kind: "line", text: lines[i] });
  }
  return blocks;
}
