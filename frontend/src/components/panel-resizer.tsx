import { useRef } from "react";

// Drag handle on the left edge of a right-side panel. Drag, or focus it and use the arrow keys;
// double-click puts the width back.
export function PanelResizer({
  width,
  initial,
  onChange,
}: {
  width: number;
  initial: number;
  onChange: (width: number) => void;
}) {
  const dragging = useRef(false);
  return (
    <div
      className="panel-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="패널 너비 조절"
      aria-valuenow={width}
      tabIndex={0}
      onPointerDown={(e) => {
        dragging.current = true;
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (dragging.current) onChange(window.innerWidth - e.clientX);
      }}
      onPointerUp={() => {
        dragging.current = false;
      }}
      onDoubleClick={() => onChange(initial)}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") onChange(width + 24);
        else if (e.key === "ArrowRight") onChange(width - 24);
        else return;
        e.preventDefault();
      }}
    />
  );
}
