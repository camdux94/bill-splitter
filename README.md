# Bill Splitter

Scan a receipt (or enter items manually), share a link, and let everyone
claim what they had. Tax splits proportionally by what each person claimed;
tip is set individually per person. Generates one-tap Venmo/Cash App payment
links plus Zelle info for whoever's collecting.

## How it works

- `receipt_ocr.py` — Claude Vision extracts line items, tax, and total from
  a photographed receipt.
- `split_logic.py` — computes each person's subtotal (their claimed item
  shares, split evenly when an item is shared), their proportional tax
  share, and combines it with their self-set tip.
- `app.py` — Flask app: bill creation, item claiming, tip setting, paid
  status, and live tally, backed by SQLite.
- `templates/create.html` — bill creation page (scan or manual entry).
- `templates/bill.html` — the shared link page where people claim items,
  set their tip, and see the live tally + payment links.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
python3 app.py
```

Then open `http://localhost:5000`.
