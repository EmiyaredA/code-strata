import React, { useState } from "react";
import { FolderTree, Info, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import "./code-sidebar.css";

export function CodeSidebar({ id, open, onToggle, overlay, actions, children, panelRef, className = "", hint = "代码引用可追溯；动态调用与运行时行为不在本次扫描范围内。" }) {
  const [hintOpen, setHintOpen] = useState(false);
  function toggle() {
    onToggle();
    if (open) requestAnimationFrame(() => document.getElementById(`${id}-opener`)?.focus());
  }
  return <>
    <aside id={id} ref={panelRef} className={`code-panel code-sidebar ${className}`} hidden={!open} aria-label="代码结构">
      <div className="panel-header code-sidebar-header">
        <div className="section-title"><FolderTree size={15} className="accent"/><h2>代码结构</h2>
          <span className="sidebar-analysis-hint" onPointerEnter={() => setHintOpen(true)} onPointerLeave={event => { if (!event.currentTarget.contains(document.activeElement)) setHintOpen(false); }}>
            <button type="button" className="sidebar-analysis-trigger" aria-label="分析范围说明" aria-describedby={hintOpen ? `${id}-analysis-hint` : undefined}
              onFocus={() => setHintOpen(true)} onBlur={() => setHintOpen(false)} onClick={() => setHintOpen(true)}
              onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); setHintOpen(false); } }}><Info size={14}/></button>
            <span id={`${id}-analysis-hint`} className="sidebar-analysis-tooltip" role="tooltip" hidden={!hintOpen}>{hint}</span>
          </span>
        </div>
        <div className="panel-actions">{actions}<button className="icon-button" aria-label="收起代码结构" title="收起代码结构" aria-expanded="true" aria-controls={id} onClick={toggle}><PanelLeftClose size={15}/></button></div>
      </div>
      {children}
    </aside>
    {(!open || overlay) && <div className="code-sidebar-rail"><button id={`${id}-opener`} className="icon-button" aria-label={open ? "收起代码结构" : "展开代码结构"} title={open ? "收起代码结构" : "展开代码结构"} aria-expanded={open} aria-controls={id} onClick={toggle}><PanelLeftOpen size={16}/></button><span aria-hidden="true">代码结构</span></div>}
  </>;
}
