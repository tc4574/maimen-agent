"""Structured input shared by UI buttons and a future language-model parser."""
from typing import Literal
from pydantic import Field, model_validator
from .contracts import DTO


class RecommendationRequest(DTO):
    city: str = Field(default="上海", min_length=1, max_length=60)
    location: str = Field(default="麦当劳总部", min_length=1, max_length=100)
    store_code: str = Field(default="1450398", pattern=r"^[0-9]{1,20}$")
    people: Literal[1] = 1
    order_type: Literal[1] = 1
    be_type: Literal[1] = 1
    budget_cents: int = Field(default=3000, ge=1, le=100000)
    main_category: Literal["burger", "chicken", "any"] = "burger"
    drink: Literal["any", "no_sugar", "none"] = "no_sugar"
    goal: Literal["balanced", "lower_price", "higher_protein", "lower_energy", "fitness"] = "balanced"
    max_energy_kcal: float | None = Field(default=None, ge=1, le=10000, allow_inf_nan=False)
    min_protein_g: float | None = Field(default=None, ge=0, le=500, allow_inf_nan=False)
    keep_codes: list[str] = Field(default_factory=list, max_length=6)
    exclude_codes: list[str] = Field(default_factory=list, max_length=30)
    exclude_words: list[str] = Field(default_factory=list, max_length=15)
    avoid_card_ids: list[str] = Field(default_factory=list, max_length=30)
    allergies: list[str] = Field(default_factory=list, max_length=10)
    use_coupons: bool = True
    # Self-report is retained but cannot turn an unverified paid-card offer into an entitlement.
    reported_gold_card: Literal["unknown", "yes", "no"] = "unknown"
    seed: int = Field(default=0, ge=0, le=2147483647)

    @model_validator(mode="after")
    def bounded_terms(self):
        for name in ("keep_codes", "exclude_codes", "exclude_words", "avoid_card_ids", "allergies"):
            values = getattr(self, name)
            if any(not value.strip() or len(value) > 80 for value in values):
                raise ValueError("nonempty_short_terms_required")
        if set(self.keep_codes) & set(self.exclude_codes):
            raise ValueError("keep_and_exclude_conflict")
        return self


class RecommendationFeedback(DTO):
    run_id: str = Field(min_length=1, max_length=80)
    changes: dict[str, object] = Field(default_factory=dict, max_length=15)
    reject_card_ids: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def allowed_changes(self):
        allowed = {"budget_cents", "main_category", "drink", "goal", "max_energy_kcal", "min_protein_g",
                   "keep_codes", "exclude_codes", "exclude_words", "use_coupons", "reported_gold_card", "seed"}
        if set(self.changes) - allowed:
            raise ValueError("unsupported_feedback_change")
        return self
