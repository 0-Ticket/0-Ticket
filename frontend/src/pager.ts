import { useSearchParams } from "react-router";

// Cursor paging kept in the URL. Repeated `trail` parameters keep the opaque cursors of earlier
// pages, so refresh and back/forward keep working. The list APIs have no page total.
export function usePager(nextCursor: string | null | undefined) {
  const [search, setSearch] = useSearchParams();
  const trail = search.has("cursor")
    ? search.has("trail")
      ? search.getAll("trail")
      : [""]
    : [];
  function page(direction: "previous" | "next") {
    const next = new URLSearchParams(search);
    next.delete("selected");
    next.delete("trail");
    const history = [...trail];
    if (direction === "next") {
      if (!nextCursor) return;
      history.push(search.get("cursor") ?? "");
      next.set("cursor", nextCursor);
    } else {
      const previous = history.pop();
      if (previous) next.set("cursor", previous);
      else next.delete("cursor");
    }
    history.forEach((cursor) => next.append("trail", cursor));
    setSearch(next);
  }
  return { search, setSearch, current: trail.length + 1, page };
}
