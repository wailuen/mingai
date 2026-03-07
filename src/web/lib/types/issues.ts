export type IssueType = "bug" | "performance" | "ux" | "feature";

export type SeverityHint = "P0" | "P1" | "P2" | "P3" | "P4";

export type IssueStatus =
  | "received"
  | "triaging"
  | "triaged"
  | "investigating"
  | "fix_in_progress"
  | "fix_merged"
  | "fix_deployed"
  | "resolved"
  | "closed";

export interface IssueEvent {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface IssueReport {
  id: string;
  title: string;
  issue_type: IssueType;
  severity_hint: SeverityHint;
  status: IssueStatus;
  created_at: string;
  updated_at: string;
  github_issue_url?: string;
  events?: IssueEvent[];
}

export interface MyReportsResponse {
  items: IssueReport[];
  total: number;
  page: number;
  page_size: number;
}

export interface RegressionResponse {
  linked_report_id: string;
}
