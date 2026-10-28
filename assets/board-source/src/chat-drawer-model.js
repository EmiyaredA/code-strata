export const CHAT_WIDTH_KEY = "code-strata:chat-drawer-width";
export const CHAT_OVERLAY_BREAKPOINT = 1040;

export function chatDrawerLayout(viewport, preferred) {
  const screen = Math.max(0, Number(viewport) || 0);
  const overlay = screen < CHAT_OVERLAY_BREAKPOINT;
  const fullScreen = screen <= 760;
  const min = Math.min(360, screen);
  const max = Math.max(min, Math.min(720, overlay ? screen : screen - 640));
  const initial = Math.min(max, Math.max(min, Math.round(screen / 3)));
  const chosen = Number(preferred);
  const width = fullScreen ? screen : Math.min(max, Math.max(min, Number.isFinite(chosen) && chosen >= 360 ? chosen : initial));
  return { width, min, max, initial, overlay, fullScreen };
}
