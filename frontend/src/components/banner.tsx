import type { ReactNode } from "react";
import { LineIcon } from "./line-icon";

// Design "Banner": icon + bold title + body. Errors are announced; the other tones are status text.
export function Banner({
  tone,
  title,
  children,
}: {
  tone: "error" | "success" | "info" | "warn";
  title: string;
  children?: ReactNode;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`banner banner-${tone}`}
    >
      <LineIcon
        name={
          tone === "success"
            ? "circle-check"
            : tone === "info"
              ? "info"
              : "circle-alert"
        }
      />
      <div className="banner-text">
        <strong>{title}</strong>
        {children && <p>{children}</p>}
      </div>
    </div>
  );
}
