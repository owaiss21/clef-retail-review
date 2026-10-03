"""The questions asked about every clip.

Whole-clip checks look at everything and answer what happened. Moment checks look at a short
window and answer what is happening right then; asked across the clip they say when.
"""

STATE = (
    "Frames from a store security camera. Answer only from what is visible. "
    "The answers decide whether a person should look at this clip; they are not an accusation."
)

CLIP_CHECKS = {
    "picked_up": {
        "type": "noul",
        "label": "Picked up an item",
        "instructions": "Does the shopper pick up or hold a product from the store?",
    },
    "put_back": {
        "type": "noul",
        "label": "Put it back",
        "instructions": "Does the shopper put the product back on the shelf, rack or table?",
    },
    "concealed": {
        "type": "noul",
        "label": "Hid it",
        "instructions": "Does the shopper hide a product in a bag, a pocket, or under their clothing?",
    },
}

MOMENT_CHECKS = {
    "taking": {
        "type": "noul",
        "label": "Taking",
        "instructions": "In these frames, is the shopper reaching into a shelf, rack or counter and taking a product?",
    },
    "in_hand": {
        "type": "noul",
        "label": "In hand",
        "instructions": "Is the shopper holding a product in their hands in these frames?",
    },
    "hiding": {
        "type": "noul",
        "label": "Hiding",
        "instructions": "In these frames, is the shopper putting a product into a bag, a pocket, or under their clothing?",
    },
    "returning": {
        "type": "noul",
        "label": "Putting back",
        "instructions": "In these frames, is the shopper placing a product back on a shelf, rack or table?",
    },
}


def wire(checks: dict) -> dict:
    """The schema the model sees: everything except our display labels."""
    return {key: {k: v for k, v in q.items() if k != "label"} for key, q in checks.items()}


def flag(answers: dict[str, float]) -> float:
    """Flag for review when the item was hidden and not put back."""
    return answers["concealed"] * (1.0 - answers["put_back"])
