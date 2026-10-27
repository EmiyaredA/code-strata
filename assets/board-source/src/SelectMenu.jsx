import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";

// Keep focus on the trigger so the enclosing dialog retains its keyboard trap.
export function SelectMenu({ label, value, options, onChange }) {
  const id = useId();
  const trigger = useRef(null);
  const popup = useRef(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [position, setPosition] = useState(null);
  const selected = options.find((option) => option.value === value) || options[0];
  function show() {
    setActive(Math.max(0, options.findIndex((option) => option.value === value)));
    setOpen(true);
  }
  function choose(option) {
    onChange(option.value);
    setOpen(false);
    trigger.current?.focus();
  }
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const rect = trigger.current.getBoundingClientRect();
      const desired = Math.min(248, options.length * 36 + 8);
      const below = innerHeight - rect.bottom - 12;
      const above = rect.top - 12;
      const upward = below < desired && above > below;
      const height = Math.min(desired, Math.max(64, upward ? above : below));
      const width = Math.min(Math.max(rect.width, 220), innerWidth - 24);
      setPosition({ left: Math.max(12, Math.min(rect.left, innerWidth - width - 12)),
        top: upward ? Math.max(12, rect.top - height - 5) : rect.bottom + 5,
        width, maxHeight: height });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open, options.length]);
  useEffect(() => {
    if (!open) return;
    function outside(event) {
      if (!trigger.current?.contains(event.target) && !popup.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  useEffect(() => {
    if (open) popup.current?.querySelector(`[id="${CSS.escape(`${id}-${active}`)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active, id]);
  function keyboard(event) {
    if (event.key === "Escape" && open) {
      event.preventDefault(); event.stopPropagation(); setOpen(false); return;
    }
    if (event.key === "Tab") { setOpen(false); return; }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      if (!open) show();
      else setActive((index) => event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 :
        (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open && options[active]) choose(options[active]); else show();
      return;
    }
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      const index = options.findIndex((option) => option.label.toLowerCase().startsWith(event.key.toLowerCase()));
      if (index >= 0) { event.preventDefault(); setOpen(true); setActive(index); }
    }
  }
  return <>
    <button ref={trigger} type="button" role="combobox" className="stats-select-trigger" aria-label={label}
      aria-expanded={open} aria-haspopup="listbox" aria-controls={open ? id : undefined}
      aria-activedescendant={open ? `${id}-${active}` : undefined}
      onClick={() => open ? setOpen(false) : show()} onKeyDown={keyboard}
      onBlur={() => setOpen(false)}>
      <span>{selected?.label}</span>{selected?.detail != null && <small>{selected.detail}</small>}<ChevronDown size={14} />
    </button>
    {open && position && createPortal(<div ref={popup} id={id} role="listbox" aria-label={label}
      className="stats-select-popup" style={position} onMouseDown={(event) => event.preventDefault()}>
      {options.map((option, index) => <div key={option.value} id={`${id}-${index}`} role="option"
        aria-selected={option.value === value} className={index === active ? "is-active" : ""}
        onPointerMove={() => setActive(index)} onClick={() => choose(option)}>
        <span>{option.label}</span>{option.detail != null && <small>{option.detail}</small>}
        {option.value === value ? <Check size={14} /> : <span className="stats-select-check-space" />}
      </div>)}
    </div>, document.body)}
  </>;
}
