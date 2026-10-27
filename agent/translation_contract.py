"""Shared translation response contract. Never assume English when detection is missing."""
from pydantic import BaseModel,Field,AliasChoices,field_validator

class TranslationResult(BaseModel):
    text:str=Field(min_length=1)
    language:str=Field(validation_alias=AliasChoices("language","source_language","detected_language"),pattern=r"^[a-z]{2,3}$")
    confidence:float=Field(ge=0,le=1,allow_inf_nan=False)
    notes:str=""

    @field_validator("language",mode="before")
    @classmethod
    def normalize_language(cls,value):
        if not isinstance(value,str):return value
        value=value.strip().lower()
        names={"english":"en","spanish":"es","german":"de","french":"fr","hindi":"hi"}
        return names.get(value,value)

    @field_validator("text")
    @classmethod
    def nonempty_text(cls,value):
        if not value.strip():raise ValueError("Translation is empty")
        return value
