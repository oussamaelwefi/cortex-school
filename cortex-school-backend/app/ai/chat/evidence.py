import hashlib
import json
from dataclasses import dataclass, field

from ai.chat.schemas import SchoolDataQuery


def lookup_fingerprint(result):
    def stable(value):
        if isinstance(value, dict):
            return {key: stable(item) for key, item in value.items() if key != "source_id"}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    # Source IDs are allocated per answer. The current date alone doesn't change access.
    data = {key: value for key, value in result.items() if key != "as_of"}
    encoded = json.dumps(stable(data), ensure_ascii=False, default=str, sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass
class ChatEvidence:
    revision: int | None = None
    lookups: list[dict] = field(default_factory=list)

    def record(self, result, *, query: SchoolDataQuery | None = None, keywords=None):
        if result.get("status") != "ok":
            return
        lookup = {"fingerprint": lookup_fingerprint(result)}
        if query is not None:
            lookup["query"] = query.model_dump(mode="json", exclude_none=True)
        else:
            lookup["keywords"] = keywords
        self.lookups.append(lookup)
