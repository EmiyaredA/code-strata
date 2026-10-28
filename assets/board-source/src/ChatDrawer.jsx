import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { GripVertical } from "lucide-react";
import { CHAT_WIDTH_KEY, chatDrawerLayout } from "./chat-drawer-model.js";

export function useChatDrawer() {
  const [open, setOpen] = useState(false);
  const [viewport, setViewport] = useState(() => window.innerWidth);
  const [preferred, setPreferred] = useState(() => {
    try { return Number(localStorage.getItem(CHAT_WIDTH_KEY)) || null; } catch { return null; }
  });
  const layout = chatDrawerLayout(viewport, preferred);
  useEffect(() => {
    const resize = () => setViewport(window.innerWidth);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  function remember(width) {
    setPreferred(width);
    try { localStorage.setItem(CHAT_WIDTH_KEY, String(width)); } catch { /* optional preference */ }
  }
  return { ...layout, open, setOpen, resize: setPreferred, remember };
}

export function ChatDrawer({ active, drawer, label, onClose, children }) {
  const host = useRef(null), drag = useRef(null), priorFocus = useRef(null), wasOpen = useRef(false);
  const visible = active && drawer.open;
  const current = useRef({ drawer, onClose });
  current.current = { drawer, onClose };
  useEffect(() => {
    if (visible && !wasOpen.current) {
      priorFocus.current = document.activeElement;
      if (drawer.fullScreen) host.current?.querySelector('[data-drawer-close]')?.focus({ preventScroll: true });
    } else if (!visible && wasOpen.current && host.current?.contains(document.activeElement)) {
      const target = document.querySelector('[data-chat-opener]') || priorFocus.current;
      if (target?.isConnected) target.focus({ preventScroll: true });
    }
    wasOpen.current = visible;
  }, [visible, drawer.fullScreen]);
  useEffect(() => {
    if (!visible) return;
    function keyboard(event) {
      // Source/settings dialogs and custom menus handle Escape first.
      if (document.querySelector('[role="dialog"]:not(.chat-drawer),[role="listbox"]')) return;
      if (event.key === "Escape") {
        event.preventDefault();
        current.current.onClose();
      } else if (event.key === "Tab" && current.current.drawer.fullScreen) {
        const controls = [...host.current.querySelectorAll('button:not(:disabled),textarea:not(:disabled),input:not(:disabled),summary,[tabindex="0"]')].filter(n => n.getClientRects().length);
        const first = controls[0], last = controls.at(-1), inside = host.current.contains(document.activeElement);
        if (!inside || event.shiftKey && document.activeElement === first || !event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          (event.shiftKey ? last : first)?.focus();
        }
      }
    }
    document.addEventListener("keydown", keyboard);
    return () => document.removeEventListener("keydown", keyboard);
  }, [visible]);
  useEffect(() => {
    if (!visible || !drawer.fullScreen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [visible, drawer.fullScreen]);
  useEffect(() => {
    if (!visible) { drag.current = null; document.documentElement.classList.remove("is-resizing-chat"); }
    return () => document.documentElement.classList.remove("is-resizing-chat");
  }, [visible]);
  function end(event) {
    if (!drag.current) return;
    drag.current = null;
    document.documentElement.classList.remove("is-resizing-chat");
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    current.current.drawer.remember(current.current.drawer.width);
  }
  return createPortal(<aside ref={host} className={`explore-chat chat-drawer ${visible ? "is-open" : "is-closed"}`}
    style={{ width: drawer.width, right: visible ? 0 : -drawer.width - 16, display: active ? undefined : "none" }}
    aria-label={label} role={drawer.fullScreen ? "dialog" : "complementary"} aria-modal={visible && drawer.fullScreen || undefined}
    aria-hidden={!visible || undefined} inert={!visible ? true : undefined}>
    {!drawer.fullScreen && <div className="chat-drawer-resize" role="separator" tabIndex={0} aria-label="调整会话宽度"
      aria-orientation="vertical" aria-valuemin={drawer.min} aria-valuemax={drawer.max} aria-valuenow={Math.round(drawer.width)}
      onPointerDown={event => {
        if (event.button !== 0) return;
        event.preventDefault();
        drag.current = { x: event.clientX, width: drawer.width };
        event.currentTarget.setPointerCapture(event.pointerId);
        document.documentElement.classList.add("is-resizing-chat");
      }} onPointerMove={event => {
        if (!drag.current) return;
        drawer.resize(Math.max(drawer.min, Math.min(drawer.max, drag.current.width + drag.current.x - event.clientX)));
      }} onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end}
      onDoubleClick={() => drawer.remember(drawer.initial)} onKeyDown={event => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        drawer.remember(event.key === "Home" ? drawer.min : event.key === "End" ? drawer.max :
          Math.max(drawer.min, Math.min(drawer.max, drawer.width + (event.key === "ArrowLeft" ? 1 : -1) * (event.shiftKey ? 48 : 24))));
      }}><GripVertical size={14}/></div>}
    {children}
  </aside>, document.body);
}
