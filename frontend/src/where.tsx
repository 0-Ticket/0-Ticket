import { useLocation } from "react-router";

// Test helper: shows the router location so tests can assert navigation.
export function Where() {
  const location = useLocation();
  return (
    <output data-testid="where">{location.pathname + location.search}</output>
  );
}
