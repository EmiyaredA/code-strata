import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Search, X } from "lucide-react";

export function CodeSearch({ value, onChange, hasResults, active, children }) {
  const anchor = useRef(null), input = useRef(null), popup = useRef(null);
  const [expanded, setExpanded] = useState(false), [open, setOpen] = useState(false), [position, setPosition] = useState(null);
  const visible = active && open && value.trim() && hasResults;
  function close() { setOpen(false); setExpanded(false); }
  function focus() {
    setExpanded(true); setOpen(true);
    requestAnimationFrame(() => input.current?.focus());
  }
  function keyboard(event) {
    if (event.key === "Escape") {
      event.stopPropagation(); event.preventDefault(); close();
      anchor.current?.querySelector('button')?.focus();
    }
  }
  useEffect(() => {
    if (!active) close();
  }, [active]);
  useEffect(() => {
    if (!expanded && !open) return;
    function outside(event) {
      if (!anchor.current?.contains(event.target) && !popup.current?.contains(event.target)) close();
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("focusin", outside); };
  }, [expanded, open]);
  useLayoutEffect(() => {
    if (!visible) { setPosition(null); return; }
    function place() {
      const rect = anchor.current.getBoundingClientRect(), width = Math.min(380, window.innerWidth - 24);
      setPosition({ position: "fixed", top: rect.bottom + 6, left: Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)),
        right: "auto", width, maxHeight: Math.max(100, Math.min(360, window.innerHeight - rect.bottom - 18)) });
    }
    place();
    const observer = new ResizeObserver(place);
    observer.observe(anchor.current.closest('.workspace-canvas-toolbar'));
    window.addEventListener("resize", place); window.addEventListener("scroll", place, true);
    return () => { observer.disconnect(); window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [visible]);
  return <>
    <div ref={anchor} className={`code-search ${expanded ? "is-expanded" : ""} ${value ? "has-value" : ""}`} onKeyDown={keyboard}>
      <button type="button" className="code-search-trigger" aria-label="展开函数查找" title="查找函数或变量" onClick={focus}><Search size={14}/></button>
      <input ref={input} aria-label="查找函数或变量" placeholder="查找函数或变量" value={value}
        onFocus={() => { setExpanded(true); setOpen(true); }} onChange={event => { onChange(event.target.value); setOpen(true); }}/>
      {value && <button type="button" className="code-search-clear" aria-label="清除查找" title="清除查找" onClick={() => { onChange(""); input.current?.focus(); }}><X size={12}/></button>}
    </div>
    {visible && position && createPortal(<div ref={popup} className="code-search-results" style={position} role="region" aria-label="函数与变量查找结果" onKeyDown={keyboard} onClick={event => { if (event.target.closest('button')) close(); }}>{children}</div>, document.body)}
  </>;
}
