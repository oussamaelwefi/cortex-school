const schoolDate = "2026-11-18";
export const familyFixture = {
  school_date: schoolDate, school_timezone: "Africa/Tunis",
  children: [
    { id: "child-1", first_name: "Yasmine", last_name: "Ben Ali", placement: { state: "current", classroom_id: "class-6a", classroom_name: "6A", academic_year_name: "2026–2027" }, attendance: { today: { state: "submitted", status: "present", school_date: schoolDate, note: null }, latest_submitted: { state: "submitted", status: "present", school_date: schoolDate, note: null } }, unread_update_count: 2, needs_response_count: 1, latest_update: { recipient_id: "recipient-1", title: "Classroom reading project", author_label: "Amira Mansour", occurred_at: "2026-11-17T09:00:00Z", needs_response: true } },
    { id: "child-2", first_name: "Adam", last_name: "Ben Ali", placement: { state: "current", classroom_id: "class-3b", classroom_name: "3B", academic_year_name: "2026–2027" }, attendance: { today: { state: "submitted", status: "present", school_date: schoolDate, note: null }, latest_submitted: { state: "submitted", status: "present", school_date: schoolDate, note: null } }, unread_update_count: 0, needs_response_count: 0, latest_update: { recipient_id: "recipient-2", title: "This week in our classroom", author_label: "Sami Trabelsi", occurred_at: "2026-11-16T09:00:00Z", needs_response: false } },
  ],
  registration_requests: [{ id: "registration-1", child_first_name: "Lina", child_last_name: "Ben Ali", academic_year_name: "2026–2027", status: "pending", rejection_reason: null }],
};
export function attendanceFixture(studentId) {
  const records = [];
  const current = new Date(`${schoolDate}T12:00:00Z`);
  while (records.length < 20) {
    if (current.getUTCDay() !== 0 && current.getUTCDay() !== 6) {
      const date = current.toISOString().slice(0, 10);
      const index = records.length;
      records.push({ attendance_record_id: `${studentId}-record-${index}`, student_id: studentId, school_date: date, classroom_name: studentId === "child-1" ? "6A" : "3B", status: index === 4 ? "late" : index === 8 && studentId === "child-1" ? "absent" : "present", note: null, updated_at: `${date}T09:00:00Z` });
    }
    current.setUTCDate(current.getUTCDate() - 1);
  }
  return records;
}
