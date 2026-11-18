export type AttendanceRecord = {
  attendance_record_id: string; school_date: string; classroom_name: string; academic_year_name?: string;
  status: "present" | "late" | "absent" | "excused"; note: string | null; updated_at: string;
};

export function attendancePeriod(schoolDate: string) {
  const start = new Date(`${schoolDate}T12:00:00Z`);
  start.setUTCDate(start.getUTCDate() - 29);
  return { from: start.toISOString().slice(0, 10), to: schoolDate };
}

export function summarizeAttendance(records: AttendanceRecord[], period: { from: string; to: string }) {
  const days = new Map<string, AttendanceRecord>();
  for (const record of records) {
    if (record.school_date < period.from || record.school_date > period.to ||
      !["present", "late", "absent", "excused"].includes(record.status)) continue;
    const previous = days.get(record.school_date);
    const updatedAt = Date.parse(record.updated_at) || 0;
    const previousUpdatedAt = previous ? Date.parse(previous.updated_at) || 0 : 0;
    // A transfer can leave records in two classes on one date. Count the day
    // once, using its most recently updated attendance record.
    if (!previous || updatedAt > previousUpdatedAt ||
      (updatedAt === previousUpdatedAt && record.attendance_record_id > previous.attendance_record_id)) {
      days.set(record.school_date, record);
    }
  }
  const history = Array.from(days.values()).sort((a, b) => b.school_date.localeCompare(a.school_date));
  const counts = { present: 0, late: 0, absent: 0, excused: 0 };
  for (const day of history) counts[day.status] += 1;
  return { counts, history, recorded: history.length,
    rate: history.length ? (counts.present + counts.late) / history.length * 100 : null };
}
