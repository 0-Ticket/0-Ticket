/* Generated. Do not edit. Run pnpm contracts. */

export type Name = string;
export type AnalystDefault = boolean;
export type Permissions = PermissionItem[];

export interface PermissionList {
  permissions: Permissions;
}
export interface PermissionItem {
  name: Name;
  analyst_default: AnalystDefault;
}
