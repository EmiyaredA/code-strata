import React, { useMemo } from "react";
import { highlightedLines } from "./syntax.js";

export function SyntaxText({ tokens = [] }) {
  return <>{tokens.map((token, index) => token.className
    ? <span key={index} className={token.className}>{token.text}</span>
    : token.text)}</>;
}

export function SyntaxCode({ text = "", language, path, className = "" }) {
  const lines = useMemo(() => highlightedLines(text, language, path), [text, language, path]);
  return <code className={`syntax-code ${className}`}>{lines.map((tokens, index) => <React.Fragment key={index}>{index > 0 && "\n"}<SyntaxText tokens={tokens} /></React.Fragment>)}</code>;
}
