import React from "react";
import { markdownBlocks } from "./markdown-blocks.js";

// React escapes every token. Markdown is deliberately rendered without raw HTML.
function Inline({ text, onSource }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g);
  return parts.map((part, i) => {
    if (part.startsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`")) {
      const value = part.slice(1, -1), source = value.match(/^(.+\.(?:py|tsx?|jsx?|mjs|cjs)):(\d+)(?:.*)?$/);
      return source ? <button key={i} className="explore-source-link" onClick={() => onSource({ path: source[1], range: { start: [+source[2], 0] } })}>{value}</button> : <code key={i}>{value}</code>;
    }
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      const source = link[2].match(/^(?:source:)?(.+\.(?:py|tsx?|jsx?|mjs|cjs))(?::|#L)(\d+)$/);
      if (source) return <button key={i} className="explore-source-link" onClick={() => onSource({ path: source[1], range: { start: [+source[2], 0] } })}>{link[1]}</button>;
      if (/^https?:\/\//.test(link[2])) return <a key={i} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    }
    return part;
  });
}
export function Markdown({ text, onSource }) {
  return <div className="explore-markdown">{markdownBlocks(text).map((block, i) => {
    if (block.kind === "code") return <pre key={i}>{block.text}</pre>;
    if (block.kind === "table") return <div key={i} className="explore-table-scroll" role="region" aria-label="回复表格" tabIndex={0}>
      <table style={{ minWidth: Math.max(280, block.header.length * 110) }}>
        <thead><tr>{block.header.map((cell, column) => <th key={column} scope="col" style={{ textAlign: block.align[column] }}><Inline text={cell} onSource={onSource}/></th>)}</tr></thead>
        <tbody>{block.rows.map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={column} style={{ textAlign: block.align[column] }}><Inline text={cell} onSource={onSource}/></td>)}</tr>)}</tbody>
      </table>
    </div>;
    const heading = block.text.match(/^#{1,4}\s+(.+)$/), bullet = block.text.match(/^(?:[-*]|\d+\.)\s+(.+)$/);
    return heading ? <h4 key={i}><Inline text={heading[1]} onSource={onSource}/></h4> :
      <p key={i} className={bullet ? "explore-bullet" : ""}><Inline text={bullet ? "• " + bullet[1] : block.text || " "} onSource={onSource}/></p>;
  })}</div>;
}
