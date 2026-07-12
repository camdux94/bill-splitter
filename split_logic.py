"""
Computes what each person owes on a shared bill:
  - Each person's subtotal = sum of their share of every item they claimed
    (items claimed by multiple people split evenly among claimers)
  - Tax is split proportionally based on each person's share of the subtotal
  - Tip is NOT split proportionally — each person sets their own tip amount
    or percentage, calculated against their own subtotal
"""


def compute_tally(items, claims, bill_tax, tips):
    """
    items: list of {"item_id": str, "name": str, "price": float, "quantity": int}
    claims: list of {"item_id": str, "person": str} — one row per person per
        item they claimed a share of. An item claimed by 2 people appears
        as two rows with the same item_id and different person names.
    bill_tax: float, total tax on the bill
    tips: dict of {person_name: tip_amount} — person-supplied tip in dollars.
        A person not present in this dict is treated as tip=0 for now (they
        haven't set one yet).

    Returns: dict of {person_name: {subtotal, tax_share, tip, total, tip_percent}}
        plus a "_bill_subtotal" key with the overall item subtotal for reference.
    """
    item_by_id = {i["item_id"]: i for i in items}

    # Group claims by item to know how many people are splitting each one
    claimers_by_item = {}
    for c in claims:
        claimers_by_item.setdefault(c["item_id"], []).append(c["person"])

    # Each person's raw subtotal from their claimed item shares
    person_subtotals = {}
    for item_id, claimers in claimers_by_item.items():
        item = item_by_id.get(item_id)
        if not item or not claimers:
            continue
        share = item["price"] / len(claimers)
        for person in claimers:
            person_subtotals[person] = person_subtotals.get(person, 0) + share

    bill_subtotal = sum(i["price"] for i in items)

    results = {}
    for person, subtotal in person_subtotals.items():
        tax_share = (subtotal / bill_subtotal * bill_tax) if bill_subtotal > 0 else 0
        tip = tips.get(person, 0)
        tip_percent = (tip / subtotal * 100) if subtotal > 0 else 0
        total = subtotal + tax_share + tip

        results[person] = {
            "subtotal": round(subtotal, 2),
            "tax_share": round(tax_share, 2),
            "tip": round(tip, 2),
            "tip_percent": round(tip_percent, 1),
            "total": round(total, 2),
        }

    results["_bill_subtotal"] = round(bill_subtotal, 2)
    return results


def payment_links(handles, amount, note="Bill split"):
    """
    handles: dict with optional keys "venmo", "cashapp", "zelle" (each a
        username/handle string, or None if not provided)
    amount: float, amount owed
    note: str, memo to attach where the platform supports it

    Returns: dict of {"venmo": url_or_None, "cashapp": url_or_None,
        "zelle": display_info_or_None}
    """
    import urllib.parse

    amount_str = f"{amount:.2f}"
    encoded_note = urllib.parse.quote(note)
    links = {}

    venmo_handle = handles.get("venmo")
    links["venmo"] = (
        f"https://venmo.com/{venmo_handle}?txn=pay&amount={amount_str}&note={encoded_note}"
        if venmo_handle else None
    )

    cashapp_handle = handles.get("cashapp")
    if cashapp_handle:
        cashapp_handle = cashapp_handle.lstrip("$").strip()
    links["cashapp"] = (
        {"handle": cashapp_handle, "amount": amount_str, "profile_url": f"https://cash.app/${cashapp_handle}"}
        if cashapp_handle else None
    )

    # Neither Cash App nor Zelle can be reliably deep-linked with a
    # pre-filled amount from a third-party site anymore. Cash App replaced
    # its old cashtag/amount URL trick with an in-app "Payment Links"
    # feature (launched Feb 2026) that must be generated from inside the
    # app itself, not constructed externally — so the old URL format no
    # longer prefills. Zelle has never had a public deep-link scheme since
    # it's bank-integrated rather than a standalone wallet. Both now just
    # surface the handle + amount for the payer to enter manually.
    zelle_handle = handles.get("zelle")
    links["zelle"] = (
        {"handle": zelle_handle, "amount": amount_str} if zelle_handle else None
    )

    return links
