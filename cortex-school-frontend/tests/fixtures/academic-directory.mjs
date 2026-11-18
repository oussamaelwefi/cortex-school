export const directoryYears = [
  { id: "year-current", name: "2026–2027", status: "active" },
  { id: "year-old", name: "2025–2026", status: "closed" },
];
export const directoryMembers = [
  { id: "user_salma", name: "Salma Mansour", email: "salma@example.test" },
  { id: "user_mehdi", name: "Mehdi Trabelsi", email: "mehdi@example.test" },
];
const attendance = (present, late, absent, excused = 0) => ({
  present,
  late,
  absent,
  excused,
  recorded_days: present + late + absent + excused,
  rate:
    present + late + absent + excused
      ? ((present + late) / (present + late + absent + excused)) * 100
      : null,
});
export const directoryFixture = {
  year_id: "year-current",
  year_name: "2026–2027",
  year_status: "active",
  school_date: "2026-11-18",
  roster_date: "2026-11-18",
  attendance_from: "2026-09-15",
  attendance_through: "2026-11-18",
  classrooms: [
    {
      id: "class-6a",
      name: "6A",
      student_ids: ["student-1", "student-2"],
      teachers: [
        {
          id: "assignment-1",
          teacher_workos_user_id: "user_salma",
          role: "lead",
          effective_from: "2026-09-15",
          effective_until: null,
        },
        {
          id: "assignment-2",
          teacher_workos_user_id: "user_mehdi",
          role: "assistant",
          effective_from: "2026-09-15",
          effective_until: null,
        },
      ],
    },
    {
      id: "class-6b",
      name: "6B",
      student_ids: ["student-3"],
      teachers: [
        {
          id: "assignment-3",
          teacher_workos_user_id: "user_mehdi",
          role: "lead",
          effective_from: "2026-09-15",
          effective_until: null,
        },
      ],
    },
    { id: "class-empty", name: "7A", student_ids: [], teachers: [] },
  ],
  students: [
    {
      id: "student-1",
      guardian_ids: ["user_guardian1"],
      first_name: "Yasmine",
      last_name: "Ben Ali",
      enrollment_id: "enrollment-1",
      placement_id: "placement-1",
      classroom_id: "class-6a",
      attendance: attendance(18, 1, 1),
    },
    {
      id: "student-2",
      guardian_ids: ["user_guardian1"],
      first_name: "Adam",
      last_name: "Trabelsi",
      enrollment_id: "enrollment-2",
      placement_id: "placement-2",
      classroom_id: "class-6a",
      attendance: attendance(0, 0, 0),
    },
    {
      id: "student-3",
      guardian_ids: ["user_guardian2"],
      first_name: "Lina",
      last_name: "Haddad",
      enrollment_id: "enrollment-3",
      placement_id: "placement-3",
      classroom_id: "class-6b",
      attendance: attendance(20, 0, 0),
    },
    {
      id: "student-4",
      guardian_ids: ["user_teacher3"],
      first_name: "Omar",
      last_name: "Mansour",
      enrollment_id: "enrollment-4",
      placement_id: null,
      classroom_id: null,
      attendance: attendance(0, 0, 0),
    },
    {
      id: "student-5",
      guardian_ids: [],
      first_name: "Nour",
      last_name: "Saidi",
      enrollment_id: null,
      placement_id: null,
      classroom_id: null,
      attendance: attendance(0, 0, 0),
    },
  ],
};
export const oldDirectoryFixture = {
  ...directoryFixture,
  year_id: "year-old",
  year_name: "2025–2026",
  year_status: "closed",
  roster_date: "2026-06-30",
  attendance_from: "2025-09-15",
  attendance_through: "2026-06-30",
  classrooms: [
    { id: "class-old", name: "5A", student_ids: ["student-1"], teachers: [] },
  ],
  students: [{ ...directoryFixture.students[0], classroom_id: "class-old" }],
};
