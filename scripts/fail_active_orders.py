#!/usr/bin/env python3
"""Fail pending/processing Kaling orders — hoàn coin + ghi chú model mới."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from user_order_notes import USER_NOTE_MODEL_UPDATED

ACTIVE_STATUSES = ("pending", "processing")


def _init_db():
    cred = credentials.Certificate(ROOT / "serviceAccountKey.json")
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(cred)
    return firestore.client()


@firestore.transactional
def _fail_one(transaction, order_ref, user_ref, cost_coins: int):
    snap = order_ref.get(transaction=transaction)
    if not snap.exists:
        return "missing"
    data = snap.to_dict() or {}
    if data.get("status") not in ACTIVE_STATUSES:
        return "skip"
    if cost_coins > 0 and user_ref is not None:
        transaction.update(user_ref, {"coins": firestore.Increment(cost_coins)})
    transaction.update(
        order_ref,
        {
            "status": "failed",
            "adminNote": firestore.DELETE_FIELD,
            "systemNote": USER_NOTE_MODEL_UPDATED,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        },
    )
    return "failed"


def main():
    db = _init_db()
    failed = skipped = errors = 0
    coins_refunded = 0

    for status in ACTIVE_STATUSES:
        docs = (
            db.collection("orders")
            .where(filter=FieldFilter("status", "==", status))
            .stream()
        )
        for doc in docs:
            data = doc.to_dict() or {}
            cost = int(data.get("costCoins") or 0)
            user_id = (data.get("userId") or "").strip()
            user_ref = db.collection("users").document(user_id) if user_id else None
            try:
                result = _fail_one(db.transaction(), doc.reference, user_ref, cost)
            except Exception as e:
                errors += 1
                print(f"❌ {doc.id}: {e}")
                continue
            if result == "failed":
                failed += 1
                coins_refunded += max(cost, 0)
                print(f"✅ {doc.id} ({status}) — hoàn {cost} coin")
            elif result == "skip":
                skipped += 1
            else:
                errors += 1

    print(
        f"\n🎉 Xong: fail={failed} skip={skipped} err={errors} "
        f"| tổng coin hoàn ≈ {coins_refunded}"
    )


if __name__ == "__main__":
    main()
