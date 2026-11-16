from pydantic import BaseModel, ConfigDict


class CustomBaseModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,  # For Alises
        from_attributes=True,  # For SQLAlchemy models
        arbitrary_types_allowed=True,  # For SQLAlchemy sessions
        extra="forbid",
    )
