/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type Username = string;
export type DisplayName = string;
export type Role = "admin" | "analyst";
export type MustChangePassword = boolean;
export type Permissions = string[];

export interface Me {
  id: Id;
  username: Username;
  display_name: DisplayName;
  role: Role;
  must_change_password: MustChangePassword;
  permissions: Permissions;
}
