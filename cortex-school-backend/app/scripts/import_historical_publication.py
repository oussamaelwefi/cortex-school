"""Import a dated publication directly using the backend's configured database.

Run from /app in the Railway backend service:
    python -m scripts.import_historical_publication
    python -m scripts.import_historical_publication --apply

The first command only previews. Repeating the import does not create a duplicate.
"""

import argparse
import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, text

from core.db import SessionLocal, utcnow
from modules.attendance.services import _current_school_date
from modules.classrooms.models import Classroom
from modules.publications import services as publication_services
from modules.publications.models import PublicationRecipient, SchoolPublication
from modules.publications.schemas import PublicationTarget
from modules.schools.models import School


TITLE = "Sortie pédagogique du 25 novembre — autorisation parentale"
BODY = """Chères familles, chers enseignants,

Une sortie pédagogique est prévue le 25 novembre 2026.

Merci aux responsables familiaux de remettre l’autorisation parentale signée au plus tard le 18 novembre 2026 à 18 h.

Les modalités de participation sont précisées dans le document « Règlement des sorties scolaires », à consulter dans les consignes de l’établissement.

La lecture de cette publication dans Cortex School ne remplace pas l’autorisation parentale signée. Pour toute question concernant le document ou son retour, contactez l’administration.

L’administration"""
PUBLISHED_AT = "2026-11-18T09:00:00+01:00"


async def import_publication(
    session,
    *,
    organization_id=None,
    classroom_name="6e A",
    author_id=None,
    published_at=None,
    apply=False,
):
    published_at = published_at or datetime.fromisoformat(PUBLISHED_AT)
    if published_at.tzinfo is None or published_at >= utcnow():
        raise ValueError("La date doit être passée et préciser le fuseau horaire.")
    if organization_id is None:
        organizations = (await session.scalars(select(School.organization_id))).all()
        if len(organizations) != 1:
            raise ValueError(
                "Précisez --organization-id : aucun établissement unique ne peut être sélectionné."
            )
        organization_id = organizations[0]
    school = await session.get(School, organization_id)
    if school is None:
        raise ValueError("Établissement introuvable.")
    classrooms = (
        await session.scalars(
            publication_services._current_classes(
                organization_id, _current_school_date(school)
            ).where(Classroom.name == classroom_name)
        )
    ).all()
    if len(classrooms) != 1:
        raise ValueError(
            "Précisez --classroom-name : la classe doit être unique et actuellement active."
        )
    classroom_id = str(classrooms[0].id)
    members = await publication_services._members(organization_id)
    administrators = sorted(
        item["id"] for item in members if "school_admin" in item["roles"]
    )
    if author_id is None:
        if not administrators:
            raise ValueError(
                "Aucun administrateur actif trouvé dans cet établissement."
            )
        author_id = administrators[0]
    if author_id not in administrators:
        raise ValueError(
            "L’auteur doit être un administrateur actif de cet établissement."
        )

    target = PublicationTarget(kind="classrooms", ids=[classroom_id])
    recipients, missing, _ = await publication_services._resolve_audience(
        session, target, organization_id
    )
    # Audience membership is current: the original historical recipient list
    # cannot be inferred from a publication date alone.
    identity = {
        "organization": organization_id,
        "classroom": classroom_id,
        "title": TITLE,
        "body": BODY,
        "published_at": published_at.astimezone(timezone.utc).isoformat(),
    }
    payload_hash = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode()
    ).hexdigest()
    publication_id = uuid.uuid5(
        uuid.NAMESPACE_URL, f"cortex-school:historical-publication:{payload_hash}"
    )
    summary = {
        "database_host": session.bind.url.host,
        "organization_id": organization_id,
        "classroom": classroom_name,
        "title": TITLE,
        "body": BODY,
        "published_at": published_at.isoformat(),
        "author_user_id": author_id,
        "recipient_count": len(recipients),
        "guardian_count": sum("guardian" in item["roles"] for item in recipients),
        "teacher_count": sum("teacher" in item["roles"] for item in recipients),
        "students_without_guardians": missing,
        "publication_id": str(publication_id),
        "status": "preview",
    }
    # Release the read transaction before opening the atomic import transaction.
    await session.rollback()
    if not apply:
        return summary
    async with session.begin():
        # Serialize repeated executions, including simultaneous CLI runs.

        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {
                "key": int.from_bytes(publication_id.bytes[:8], "big", signed=True),
            },
        )
        existing = await session.get(SchoolPublication, publication_id)
        if existing is not None:
            if (
                existing.organization_id != organization_id
                or existing.payload_hash != payload_hash
            ):
                raise ValueError(
                    "L’identifiant d’import est déjà utilisé par une autre publication."
                )
            return {
                **summary,
                "status": "already_imported",
                "recipient_count": existing.recipient_count,
            }
        now = utcnow()
        session.add(
            SchoolPublication(
                id=publication_id,
                organization_id=organization_id,
                author_user_id=author_id,
                idempotency_key=publication_id,
                payload_hash=payload_hash,
                title=TITLE,
                body=BODY,
                target_kind="classrooms",
                target_ids=[classroom_id],
                recipient_count=len(recipients),
                created_at=published_at,
                updated_at=now,
            )
        )
        await session.flush()
        session.add_all(
            [
                PublicationRecipient(
                    publication_id=publication_id,
                    user_id=item["id"],
                    name=item["name"],
                    roles=item["roles"],
                    student_ids=item["student_ids"],
                    created_at=published_at,
                    updated_at=now,
                    read_at=None,
                )
                for item in recipients
            ]
        )
        await session.flush()
    return {**summary, "status": "imported"}


async def main():
    parser = argparse.ArgumentParser(
        description="Importer la publication sur l’autorisation de sortie pédagogique du 18 novembre 2026."
    )
    parser.add_argument(
        "--organization-id",
        help="Facultatif si la base contient un seul établissement.",
    )
    parser.add_argument("--classroom-name", default="6e A")
    parser.add_argument(
        "--author-id", help="Identifiant WorkOS d’un administrateur actif (facultatif)."
    )
    parser.add_argument("--published-at", default=PUBLISHED_AT)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Enregistrer la publication ; sans cette option, aperçu uniquement.",
    )
    args = parser.parse_args()
    async with SessionLocal() as session:
        result = await import_publication(
            session,
            organization_id=args.organization_id,
            classroom_name=args.classroom_name,
            author_id=args.author_id,
            published_at=datetime.fromisoformat(args.published_at),
            apply=args.apply,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        # Provider response bodies and connection credentials stay out of output.
        detail = (
            str(exc)
            if isinstance(exc, ValueError)
            else exc.detail
            if isinstance(exc, HTTPException)
            else "Échec de l’import. Vérifiez la connexion du backend et les migrations."
        )
        raise SystemExit(detail) from None
