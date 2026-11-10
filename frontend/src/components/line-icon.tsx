// Outline icons (24-unit grid, 2px stroke) for the shapes the design names but the exported set lacks.
const shapes = {
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  "circle-alert":
    '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
  "circle-check": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  lock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  users:
    '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  sliders:
    '<path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4"/>',
  "log-out":
    '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
  "chevron-right": '<path d="m9 18 6-6-6-6"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  "server-off":
    '<path d="M7 2h13a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-5M2 2l20 20M5 5a2 2 0 0 0-1 2v4a2 2 0 0 0 2 2h8M2 14h12a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-4"/>',
  spinner: '<path d="M21 12a9 9 0 1 1-6.22-8.56"/>',
};
export type LineIconName = keyof typeof shapes;
export function LineIcon({
  name,
  size = 16,
}: {
  name: LineIconName;
  size?: number;
}) {
  return (
    <svg
      className="line-icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      // Constants above only; no outside string ever reaches this.
      dangerouslySetInnerHTML={{ __html: shapes[name] }}
    />
  );
}
