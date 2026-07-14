/** أنواع عقد DOC-05 v1.1 — الغلاف الموحد {data, meta} / {error:{code,...}} */

export interface Envelope<T> {
  data: T;
  meta: Record<string, unknown> & { total?: number; page?: number; per_page?: number; unread?: number };
}

export interface MdfError {
  code: string;
  message_ar: string;
  message_en: string;
  details: Record<string, unknown>;
}

export interface SessionUser {
  id: string;
  full_name: string;
  role: "admin" | "doctor";
  facility_id: string;
  facility_name: string;
  facility_status: "active" | "suspended" | "archived";
}

export interface Me extends SessionUser {
  username: string;
  email: string | null;
  specialty: string | null;
  clinic_id: string | null;
  clinic_name: string | null;
}

export interface Clinic {
  id: string;
  name: string;
  archived_at: string | null;
  doctors_count: number;
}

export interface Doctor {
  id: string;
  full_name: string;
  username: string;
  specialty: string | null;
  clinic_id: string | null;
  clinic_name: string | null;
  is_active: boolean;
  visits_count: number;
}

export interface SubscriptionInfo {
  plan: string;
  seats_total: number;
  seats_used: number;
  seats_available: number;
  seat_events: { id: string; delta: number; reason: string; at: string }[];
}

export interface Invoice {
  id: string;
  number: string;
  period_start: string;
  period_end: string;
  amount_sar: string;
  vat_sar: string;
  total_sar: string;
  status: "due" | "paid" | "overdue" | "void";
  issued_at: string;
  paid_at: string | null;
}

export interface CodingSystemAdmin {
  id: string;
  system: "ICD10AM" | "ACHI" | "SBS" | "SFDA";
  version: string;
  is_active: boolean;
}

export interface IntegrationInfo {
  endpoint_url: string | null;
  mode: "test" | "live";
  has_secret: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
}

export interface Patient {
  id: string;
  hospital_mrn: string;
  display_name: string;
  dob: string | null;
  gender: string | null;
  synced_at: string;
}

export interface TemplateSection {
  section_key: string;
  title: string;
  instructions: string;
}

export interface Template {
  id: string;
  name: string;
  specialty: string | null;
  visit_type: string | null;
  structure: { sections: TemplateSection[] };
  origin: "system" | "reverse_built";
  is_default: boolean;
  is_personal: boolean;
  archived_at: string | null;
}

export type VisitState =
  | "draft" | "recording" | "transcribed" | "summarized"
  | "in_review" | "approved" | "uploaded" | "upload_failed" | "cancelled";

export interface VisitRow {
  id: string;
  state: VisitState;
  created_at: string;
  patient_name: string;
  patient_mrn: string;
  template_name: string;
  upload_status: "queued" | "sent" | "confirmed" | "failed" | null;
  upload_attempts: number;
}

export interface PatientContext {
  problems?: string[];
  medications?: (string | { name: string; note?: string })[];
  allergies?: string[];
  last_results?: string[];
  vitals_history?: { date: string; bp: string }[];
  last_visit?: string;
  source?: string;
}

export interface CreatedVisit {
  id: string;
  state: VisitState;
  patient: { id: string; display_name: string; hospital_mrn: string };
  template: { id: string; name: string };
  context_snapshot: PatientContext;
}

export interface GuidanceItem {
  id: string;
  kind: "clinical_dx" | "clinical_rx" | "clinical_procedure" | "coding_match";
  suggestion_text: string;
  code_system: string | null;
  code_value: string | null;
  evidence_source: "patient_file" | "current_visit";
  evidence_ref: string | null;
  safety_flag: boolean;
  status: "pending" | "accepted" | "rejected" | "modified";
}

export interface SummarySection {
  id: string;
  section_key: string;
  position: number;
  content_current: string;
  content_original: string;
  is_edited: boolean;
  guidance: GuidanceItem[];
}

export interface ApprovalRecord {
  approved_by: string;
  approved_at: string;
  summary_hash: string;
  codes_hash: string;
}

export interface VisitSummary {
  visit_id: string;
  state: VisitState;
  model_ref: string;
  generated_at: string;
  sections: SummarySection[];
  pending_guidance_count: number;
  etag: string;
  approval: ApprovalRecord | null;
}

export interface TranscriptSegment {
  id: string;
  text: string;
  t0: number;
  t1: number;
}

export interface UploadStatus {
  visit_id: string;
  state: VisitState;
  status: "queued" | "sent" | "confirmed" | "failed";
  attempts_count: number;
  attempts: { started_at: string; result: string | null; error_code: string | null }[];
}

export interface NotificationRow {
  id: string;
  kind: string;
  payload: Record<string, unknown> & { priority?: "normal" | "important" | "critical" };
  created_at: string;
  read_at: string | null;
}

export interface AuditRow {
  id: string;
  at: string;
  actor: string;
  action: string;
  entity: string;
  entity_id: string | null;
  meta: Record<string, unknown> | null;
}

export interface FailedUploadRow {
  job_id: string;
  visit_id: string;
  doctor: string;
  attempts_count: number;
  error_code: string | null;
  failed_at: string;
}

export interface UsageDashboard {
  total_visits: number;
  by_doctor: { doctor: string; visits: number }[];
  by_clinic: { clinic: string; visits: number }[];
  by_state: Partial<Record<VisitState, number>>;
}

export interface QualityDashboard {
  summaries_total: number;
  approved_without_edit_pct: number | null;
  guidance_by_status: Partial<Record<GuidanceItem["status"], number>>;
  guidance_accept_rate_pct: number | null;
  edits_by_channel: Partial<Record<"typing" | "voice" | "ai_chat", number>>;
}

export interface ChatPatch {
  section_id: string;
  section_key: string;
  old_content: string;
  new_content: string;
}
