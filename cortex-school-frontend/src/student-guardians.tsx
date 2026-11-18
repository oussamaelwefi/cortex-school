import { createContext, useContext } from "react";
import { t } from "./i18n";
import type { SchoolMemberIdentity } from "./types";

export type StudentGuardianSource = {
  enabled: boolean;
  students: { id: string; guardian_ids?: string[] }[] | null;
  members: SchoolMemberIdentity[] | null;
  loading: boolean;
  error: string;
};
export const StudentGuardianContext = createContext<StudentGuardianSource>({
  enabled: false,
  students: null,
  members: null,
  loading: false,
  error: "",
});

export function StudentGuardians({
  studentId,
  guardianIds,
  details = false,
}: {
  studentId: string;
  guardianIds?: string[];
  details?: boolean;
}) {
  const source = useContext(StudentGuardianContext);
  if (!source.enabled) return null;
  const ids =
    guardianIds ??
    source.students?.find((student) => student.id === studentId)?.guardian_ids;
  if (ids?.length === 0)
    return <span className="sg-empty">{t("No guardian linked")}</span>;
  if (!ids || (source.loading && !source.members))
    return (
      <span className="sg-empty">
        {t(
          source.loading
            ? "Loading guardians…"
            : "Guardian information unavailable",
        )}
      </span>
    );
  return (
    <ul className="student-guardians">
      {ids.map((id) => {
        const guardian = source.members?.find((member) => member.id === id);
        return (
          <li key={id}>
            <strong>
              {guardian?.name ??
                t(
                  source.loading
                    ? "Loading guardians…"
                    : "Guardian profile unavailable",
                )}
            </strong>
            {details && guardian?.email && (
              <a href={`mailto:${guardian.email}`}>{guardian.email}</a>
            )}
          </li>
        );
      })}
    </ul>
  );
}
