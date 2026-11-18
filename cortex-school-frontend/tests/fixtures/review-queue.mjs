const common = { school_date: "2026-11-18", occurred_at: "2026-11-18T08:00:00Z", due_at: "2026-11-18T08:00:00Z", academic_year_name: "2026–2027" };
export const reviewItems = [
  { ...common, id: "acknowledgement:pickup", category: "acknowledgement", severity: "urgent", title: "Acknowledgement overdue for 6A", reason: "4 guardian acknowledgements remain outstanding.", classroom_name: "6A", outstanding_acknowledgement_count: 4, action: { type: "student_update", update_id: "pickup-update" } },
  { ...common, id: "missing_attendance:class-6b", category: "missing_attendance", severity: "urgent", title: "6B attendance is missing", reason: "Attendance has not been submitted after the school cutoff.", classroom_name: "6B", teacher_name: "Amira Mansour", action: { type: "attendance", classroom_id: "class-6b", school_date: "2026-11-18" } },
  { ...common, id: "missing_assignment:class-5a", category: "missing_assignment", severity: "urgent", title: "5A needs a teacher assignment", reason: "No active teacher assignment owns attendance for 2026-11-18.", classroom_name: "5A", affected_date_count: 3, action: { type: "classroom_assignment", classroom_id: "class-5a", academic_year_id: "year-2026" } },
  { ...common, id: "registration:request-1", category: "registration", severity: "warning", title: "Registration request for Yasmine Ben Ali", reason: "Waiting for school review.", student_name: "Yasmine Ben Ali", due_at: "2026-11-20T08:00:00Z", action: { type: "registration_request", request_id: "request-1" } },
  { ...common, id: "invitation:invite-1", category: "invitation", severity: "warning", title: "Invitation for teacher@example.test", reason: "The invitation has not been accepted within the response window.", invitation_email: "teacher@example.test", invitation_role: "teacher", due_at: "2026-11-19T08:00:00Z", academic_year_name: null, action: { type: "invitation", invitation_id: "invite-1" } },
];

export function queueResponse(items = reviewItems, params = {}) {
  const selected = items.filter((item) => (!params.category?.length || params.category.includes(item.category)) && (!params.severity?.length || params.severity.includes(item.severity)));
  const offset = params.offset ?? 0, limit = params.limit ?? 20;
  return {
    as_of: "2026-11-18T09:00:00Z", school_date: "2026-11-18", attendance_cutoff_time: "09:00:00",
    total_count: selected.length, category_counts: Object.fromEntries(["acknowledgement", "missing_attendance", "missing_assignment", "registration", "invitation"].map((key) => [key, selected.filter((item) => item.category === key).length])),
    severity_counts: { urgent: selected.filter((item) => item.severity === "urgent").length, warning: selected.filter((item) => item.severity === "warning").length },
    informational_unread_update_count: 2, items: selected.slice(offset, offset + limit), offset, limit,
    has_more: offset + limit < selected.length, next_offset: offset + limit < selected.length ? offset + limit : null,
  };
}
