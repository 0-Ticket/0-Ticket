import { useState } from "react";

export const MIN_PANEL = 360;
const SIDEBAR = 224;
// Widest a side panel may be: it must never cover the 224px menu (plus a 16px gap).
// Below 900px the menu is a top bar, so the panel may use the whole width.
export function maxPanel() {
  return window.innerWidth > 900
    ? window.innerWidth - SIDEBAR - 16
    : window.innerWidth;
}
export function usePanelWidth(key: string, initial: number) {
  const [width, setWidth] = useState(() => {
    try {
      const saved = Number(localStorage.getItem(key));
      return saved >= MIN_PANEL ? saved : initial;
    } catch {
      return initial; // storage blocked: the width just is not remembered
    }
  });
  function change(next: number) {
    const clamped = Math.round(
      Math.min(Math.max(next, MIN_PANEL), Math.max(MIN_PANEL, maxPanel())),
    );
    setWidth(clamped);
    try {
      localStorage.setItem(key, String(clamped));
    } catch {
      /* not remembered */
    }
  }
  return [width, change] as const;
}
