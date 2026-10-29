import React, { useMemo, useRef } from "react";
import { FileCode2, Folder, ChevronDown, ChevronRight } from "lucide-react";
import { makeTree, parents } from "./model.js";
import { inventoryFiles } from "./InventoryPanels.jsx";
function Tree({ data, expanded, setExpanded, linked, focusId, onFile, includeConfigs = false, hiddenFiles = [] }) {
  const ref = useRef(null), tree = useMemo(() => makeTree((includeConfigs ? (data.inventory || data.files) : inventoryFiles(data)).filter(f=>!hiddenFiles.includes(f.id))), [data, includeConfigs, hiddenFiles.join("|")]);
  function toggle(id) {
    setExpanded((old) => {
      const next = new Set(old);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }
  function keyDown(e, item) {
    const rows = [...ref.current.querySelectorAll('[role="treeitem"]')], at = rows.indexOf(e.currentTarget);
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      const i = e.key === "Home" ? 0 : e.key === "End" ? rows.length - 1 : Math.max(
        0,
        Math.min(
          rows.length - 1,
          at + (e.key === "ArrowDown" ? 1 : -1)
        )
      );
      rows[i]?.focus();
    }
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      item.file ? onFile(item.id) : toggle(item.id);
    }
    if (e.key === "ArrowRight" && !item.file) {
      e.preventDefault();
      if (!expanded.has(item.id)) toggle(item.id);
      else rows[at + 1]?.focus();
    }
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      if (!item.file && expanded.has(item.id)) toggle(item.id);
      else
        ref.current.querySelector(
          `[data-tree-id="${CSS.escape(parents(item.id).at(-1) || "")}"]`
        )?.focus();
    }
  }
  function render(branch, depth = 0) {
    return [...branch.children.values()].sort(
      (a, b) => Boolean(a.file) - Boolean(b.file) || a.name.localeCompare(b.name)
    ).map((item) => {
      const selected = linked.has(item.id), isFocus = focusId === item.id;
      return <React.Fragment key={item.id}>
            <div
        role="treeitem"
        tabIndex={0}
        aria-label={`${item.file ? "文件" : "目录"} ${item.id}`}
        aria-level={depth + 1}
        aria-expanded={item.file ? void 0 : expanded.has(item.id)}
        aria-selected={item.file ? selected : void 0}
        data-tree-id={item.id}
        className={`tree-row ${selected ? "is-linked" : ""} ${isFocus ? "is-focused" : ""} ${item.file && !selected && linked.size ? "is-muted" : ""}`}
        style={{ paddingLeft: 16 + depth * 16 }}
        title={item.id}
        onKeyDown={(e) => keyDown(e, item)}
        onClick={() => item.file ? onFile(item.id) : toggle(item.id)}
      >
              {!item.file ? expanded.has(item.id) ? <ChevronDown size={13} /> : <ChevronRight size={13} /> : <span className="tree-spacer" />}
              {item.file ? <FileCode2 size={15} /> : <Folder size={15} />}
              <span className="tree-name">{item.name}</span>
              {isFocus && <span className="focus-mark" />}
            </div>
            {!item.file && expanded.has(item.id) && render(item, depth + 1)}
          </React.Fragment>;
    });
  }
  return <div
    className="tree-scroll"
    role="tree"
    aria-label="项目代码结构"
    ref={ref}
  >
      {render(tree)}
    </div>;
}
export {
  Tree
};
