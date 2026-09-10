"""The structured shape the vision model must return."""

from __future__ import annotations

from dataclasses import dataclass, field

# Forced tool-use gives us a schema-validated object instead of prose we would
# have to parse. Every field the matcher needs is required; the model is told
# to use null rather than to guess.
IDENTIFY_TOOL = {
    "name": "report_cards",
    "description": (
        "Report every distinct Pokemon card you can identify in the listing "
        "photos, with a calibrated confidence for each."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "description": "One entry per distinct card visible.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Pokemon/card name exactly as printed, e.g. 'Charizard' or 'Professor's Research'.",
                        },
                        "set_name": {
                            "type": ["string", "null"],
                            "description": "Printed set name if legible, else null.",
                        },
                        "set_code": {
                            "type": ["string", "null"],
                            "description": "Set symbol/code such as 'BS', 'SV1' if legible, else null.",
                        },
                        "card_number": {
                            "type": ["string", "null"],
                            "description": "Collector number as printed, e.g. '4/102'. Null if not legible.",
                        },
                        "variant": {
                            "type": ["string", "null"],
                            "enum": [
                                "normal",
                                "holofoil",
                                "reverse_holofoil",
                                "first_edition",
                                "shadowless",
                                "promo",
                                "full_art",
                                "secret_rare",
                                None,
                            ],
                            "description": "Print variant if determinable.",
                        },
                        "language": {
                            "type": ["string", "null"],
                            "description": "Card language, e.g. 'English', 'Japanese'.",
                        },
                        "condition_estimate": {
                            "type": ["string", "null"],
                            "enum": ["mint", "near_mint", "lightly_played", "moderately_played", "heavily_played", "damaged", None],
                            "description": "Visible condition. Null when the photo cannot support a judgement.",
                        },
                        "quantity": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "How many copies of this exact card are visible.",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": (
                                "Calibrated probability that this identification "
                                "(name + set + number) is correct. Use <0.5 when the "
                                "card is blurry, partially covered, or you are "
                                "inferring the set from artwork alone."
                            ),
                        },
                        "image_index": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Index of the photo this card was read from.",
                        },
                        "notes": {
                            "type": ["string", "null"],
                            "description": "Anything that affects value: damage, sleeve glare, obstruction, possible proxy/fake.",
                        },
                    },
                    "required": ["name", "quantity", "confidence", "image_index"],
                    "additionalProperties": False,
                },
            },
            "lot_summary": {
                "type": "object",
                "properties": {
                    "total_cards_visible": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Rough count of all cards visible including unidentifiable ones.",
                    },
                    "identified_fraction": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "Fraction of visible cards you were able to identify.",
                    },
                    "obstructions": {
                        "type": ["string", "null"],
                        "description": "Why cards could not be identified: stacked, sleeved, back-facing, blurry.",
                    },
                },
                "required": ["total_cards_visible", "identified_fraction"],
                "additionalProperties": False,
            },
        },
        "required": ["cards", "lot_summary"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You identify Pokemon trading cards from eBay listing photos.

Rules:
- Report only cards you can actually see in the photos. Never infer a card from
  the listing title alone; titles are frequently wrong or aspirational.
- A stack of cards where only the top card is visible is ONE identified card,
  not a stack of identified cards.
- Confidence is a calibrated probability, not enthusiasm. Reserve >0.9 for cards
  where the name, set symbol and collector number are all legible. Use 0.5-0.7
  when you read the name clearly but are inferring the set from artwork or
  border style. Use <0.4 for blurry, angled, glare-covered or partially
  occluded cards.
- Watch for reprints: the same artwork appears across base sets, Legendary
  Collection, Celebrations and various promos. If you cannot distinguish which
  printing it is, say so in notes and lower the confidence.
- Flag anything that looks like a proxy, custom, or counterfeit in notes.
- Prefer null over a guess for set_name, set_code and card_number.
"""


@dataclass
class CardIdentity:
    name: str
    quantity: int
    confidence: float
    image_index: int
    set_name: str | None = None
    set_code: str | None = None
    card_number: str | None = None
    variant: str | None = None
    language: str | None = None
    condition_estimate: str | None = None
    notes: str | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> "CardIdentity":
        return cls(
            name=payload.get("name", "").strip(),
            quantity=max(1, int(payload.get("quantity", 1) or 1)),
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            image_index=int(payload.get("image_index", 0) or 0),
            set_name=payload.get("set_name"),
            set_code=payload.get("set_code"),
            card_number=payload.get("card_number"),
            variant=payload.get("variant"),
            language=payload.get("language"),
            condition_estimate=payload.get("condition_estimate"),
            notes=payload.get("notes"),
        )


@dataclass
class LotIdentification:
    cards: list[CardIdentity] = field(default_factory=list)
    total_cards_visible: int = 0
    identified_fraction: float = 0.0
    obstructions: str | None = None
    model: str = ""
    # Populated when the vision call failed outright.
    error: str | None = None

    @property
    def min_confidence(self) -> float:
        if not self.cards:
            return 0.0
        return min(card.confidence for card in self.cards)

    @property
    def mean_confidence(self) -> float:
        if not self.cards:
            return 0.0
        total_qty = sum(card.quantity for card in self.cards)
        if total_qty == 0:
            return 0.0
        weighted = sum(card.confidence * card.quantity for card in self.cards)
        return weighted / total_qty

    @classmethod
    def from_payload(cls, payload: dict, model: str) -> "LotIdentification":
        summary = payload.get("lot_summary") or {}
        return cls(
            cards=[CardIdentity.from_payload(c) for c in payload.get("cards", [])],
            total_cards_visible=int(summary.get("total_cards_visible", 0) or 0),
            identified_fraction=float(summary.get("identified_fraction", 0.0) or 0.0),
            obstructions=summary.get("obstructions"),
            model=model,
        )
