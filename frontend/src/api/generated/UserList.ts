/* Generated. Do not edit. Run pnpm contracts. */

export type Id = string;
export type Username = string;
export type DisplayName = string;
export type Role = ("admin" | "analyst") | null;
export type Status = "pending" | "active" | "rejected" | "disabled";
export type MustChangePassword = boolean;
export type Permissions = string[];
export type CreatedAt = number;
export type ApprovedAt = number | null;
export type Items = UserItem[];
export type NextCursor = string | null;

export interface UserList {
  items: Items;
  next_cursor: NextCursor;
}
export interface UserItem {
  id: Id;
  username: Username;
  display_name: DisplayName;
  role: Role;
  status: Status;
  must_change_password: MustChangePassword;
  permissions: Permissions;
  created_at: CreatedAt;
  approved_at: ApprovedAt;
}
