"""
Extracts line items, tax, and total from a photographed receipt using
Claude's vision capability. Returns structured data for the user to review
and correct before a bill is created — OCR on real-world receipts is never
perfect, so this is designed as a first-pass extraction, not a final answer.
"""

import os
import json
import base64
import anthropic

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

_SYSTEM_PROMPT = """You extract structured data from photos of restaurant \
receipts. Look carefully at the image and identify every line item, its \
price, and quantity, plus the tax and total charged.

Respond with ONLY valid JSON, no other text, no markdown fences, in this \
exact shape:
{
  "restaurant_name": "<string, or 'Receipt' if not legible>",
  "items": [
    {"name": "<item name>", "price": <number, price for this line as shown on the receipt>, "quantity": <integer, default 1>}
  ],
  "subtotal": <number, sum before tax and tip>,
  "tax": <number>,
  "total": <number, as printed on the receipt, before any tip>
}

Rules:
- price is the line's total price (already multiplied by quantity if the receipt shows it that way)
- If a field is illegible or missing, make your best reasonable estimate and don't leave numbers null
- Do not include tip/gratuity as a line item — tip is handled separately by the app
- If the image isn't a receipt at all, return {"error": "This doesn't appear to be a receipt."}
"""


def extract_receipt(image_bytes, media_type="image/jpeg"):
    """
    image_bytes: raw image bytes (jpeg/png/webp)
    Returns: dict matching the schema above, or {"error": "..."} on failure
    """
    b64_image = base64.b64encode(image_bytes).decode("utf-8")

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": b64_image},
                        },
                        {"type": "text", "text": "Extract the receipt data as JSON."},
                    ],
                }
            ],
        )
        raw_text = response.content[0].text.strip()

        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        parsed = json.loads(raw_text)

        if "error" in parsed:
            return parsed

        # Basic sanity defaults in case the model omits a field
        parsed.setdefault("restaurant_name", "Receipt")
        parsed.setdefault("items", [])
        parsed.setdefault("subtotal", sum(i.get("price", 0) for i in parsed["items"]))
        parsed.setdefault("tax", 0)
        parsed.setdefault("total", parsed["subtotal"] + parsed["tax"])

        return parsed

    except json.JSONDecodeError:
        return {"error": "Could not parse the receipt. Try a clearer photo or enter items manually."}
    except (anthropic.APIError, IndexError, KeyError) as e:
        return {"error": f"Receipt scan failed ({type(e).__name__}). Try again or enter items manually."}
