import { Link } from "react-router";
import { Button } from "./components/ui/button";
import { useCan } from "./auth/session";
import { resourcePermission } from "./constants";
import type { Resource } from "./api/client";
import type { LinkTo } from "./detail-sections";

export const INCIDENT_ID =
  /^inc_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const INTERNAL_ID =
  /^(alt|evt|raw|tkt|inc|hnt)_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function internalHref(id: string, resource: Resource) {
  if (!INTERNAL_ID.test(id)) return null;
  // Incidents have their own page; every other record opens in the side panel of its list.
  return resource === "incidents"
    ? `/incidents/${id}`
    : `/${resource}?selected=${id}`;
}

function internalLink(
  id: string,
  resource: Resource,
  label: string,
  name?: string,
) {
  const to = internalHref(id, resource);
  if (!to) return null;
  return (
    <Button key={id} variant="outline" size="sm" asChild>
      <Link to={to} aria-label={name}>
        {label}
      </Link>
    </Button>
  );
}

// A link to a screen the account cannot open is not offered.
export function useLink(): LinkTo {
  const can = useCan();
  return (id, resource, label, name) =>
    can(resourcePermission[resource])
      ? internalLink(id, resource, label, name)
      : null;
}

// The address of a record the account may open, for a row that is a link as a whole.
export function useHref() {
  const can = useCan();
  return (id: string, resource: Resource) =>
    can(resourcePermission[resource]) ? internalHref(id, resource) : null;
}
