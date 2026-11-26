"""
Firestore-compatible Supabase PostgREST + RPC adapter for all 3 satellite sites:
  - kaling (kaling.cloud)       -> kaling_* tables  (env: KALING_BACKEND=supabase)
  - motion (motionaistudio.cloud) -> motion_* tables (env: MOTION_BACKEND=supabase)
  - nhay   (nhay.cloud)         -> nhay_* tables    (env: NHAY_BACKEND=supabase)

Designed so /root/multibot (multi_bot.py, site_bot.py, xiaoyang_motion.py,
roboneo_motion.py, site_shared.py, api_server.py) and /root/ai_web3/batch_channel.py
can run 100% on shared Supabase with ZERO Firebase connections.
"""

from __future__ import annotations

import datetime
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

import requests

try:
    from firebase_admin import firestore as _fs
    _SERVER_TIMESTAMP = _fs.SERVER_TIMESTAMP
    _DELETE_FIELD = _fs.DELETE_FIELD
    _INCREMENT_CLS = _fs.Increment
except Exception:
    _SERVER_TIMESTAMP = object()
    _DELETE_FIELD = object()
    _INCREMENT_CLS = None


def _is_server_timestamp(val: Any) -> bool:
    if val is _SERVER_TIMESTAMP:
        return True
    return type(val).__name__ in ("Sentinel", "_ServerTimestamp") and "SERVER_TIMESTAMP" in repr(val)


def _is_delete_field(val: Any) -> bool:
    if val is _DELETE_FIELD:
        return True
    return "DELETE_FIELD" in repr(val)


def _extract_increment(val: Any) -> float | None:
    if _INCREMENT_CLS is not None and isinstance(val, _INCREMENT_CLS):
        return float(getattr(val, "value", 0))
    if type(val).__name__ == "Increment" and hasattr(val, "value"):
        return float(val.value)
    return None


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _parse_dt(val: Any) -> Any:
    if not val or not isinstance(val, str):
        return val
    try:
        s = val.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        return val


def _load_dotenv_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ---------------------------------------------------------------------------
# Bidirectional Collection & Field Maps (Firestore camelCase <-> Supabase snake_case)
# ---------------------------------------------------------------------------

COLLECTION_SUFFIX_MAP = {
    "users": ("users", "id"),
    "orders": ("orders", "id"),
    "topups": ("topups", "id"),
    "bots": ("bots", "id"),
    "referralAllowlist": ("referral_allowlist", "email"),
    "referralCodes": ("referral_codes", "code"),
    "referralEarnings": ("referral_earnings", "id"),
    "batchChannelAllowlist": ("batch_channel_allowlist", "email"),
    "batchChannelConfig": ("batch_channel_config", "id"),
    "batchChannelRuns": ("batch_channel_runs", "id"),
}

# Backwards-compatible default for kaling
COLLECTION_TABLE_MAP = {
    col: (f"kaling_{suffix}", pk)
    for col, (suffix, pk) in COLLECTION_SUFFIX_MAP.items()
}

SITE_ID_PREFIX = {
    "kaling": "kl_",
    "motion": "ms_",
    "nhay": "nh_",
}

SITE_BACKEND_ENV = {
    "kaling": "KALING_BACKEND",
    "motion": "MOTION_BACKEND",
    "nhay": "NHAY_BACKEND",
}

BASE_FIELD_MAPS: dict[str, dict[str, str]] = {
    "users": {
        "email": "email",
        "displayName": "display_name",
        "photoURL": "photo_url",
        "coins": "coins",
        "role": "role",
        "apiKey": "api_key",
        "referralCode": "referral_code",
        "referredBy": "referred_by",
        "promo1CoinCount": "promo_1_coin_count",
        "promo1CoinLastDay": "promo_1_coin_last_day",
        "createdAt": "created_at",
        "updatedAt": "updated_at",
    },
    "orders": {
        "userId": "user_id",
        "userEmail": "user_email",
        "userName": "user_name",
        "packageName": "package_name",
        "status": "status",
        "modelId": "model_id",
        "renderProvider": "render_provider",
        "maxVideoSec": "max_video_sec",
        "qualityMode": "quality_mode",
        "quality": "quality",
        "aspectRatio": "aspect_ratio",
        "vaeResolution": "vae_resolution",
        "vaeDurationSec": "vae_duration_sec",
        "serviceType": "service_type",
        "serviceLabel": "service_label",
        "characterImageLink": "character_image_link",
        "referenceVideoLink": "reference_video_link",
        "resultLink": "result_link",
        "costCoins": "cost_coins",
        "promo1Coin": "promo_1_coin",
        "roboneoTrial": "roboneo_trial",
        "roboneoAccountEmail": "roboneo_account_email",
        "roboneoRoomId": "roboneo_room_id",
        "roboneoTaskId": "roboneo_task_id",
        "aidancingJobId": "aidancing_job_id",
        "videoaieasyJobId": "videoaieasy_job_id",
        "videoaieasyAccount": "videoaieasy_account",
        "videoaieasyAccountEmail": "videoaieasy_account_email",
        "isBatchChannel": "is_batch_channel",
        "batchChannelRunId": "batch_channel_run_id",
        "batchSourceVideoId": "batch_source_video_id",
        "clientVersion": "client_version",
        "referer": "referer",
        "adminNote": "admin_note",
        "systemNote": "system_note",
        "error_message": "error_message",
        "submittedAt": "submitted_at",
        "createdAt": "created_at",
        "updatedAt": "updated_at",
    },
    "topups": {
        "userId": "user_id",
        "userEmail": "user_email",
        "userName": "user_name",
        "packageId": "package_id",
        "packageName": "package_name",
        "coins": "coins",
        "amount": "amount",
        "currency": "currency",
        "transferContent": "transfer_content",
        "status": "status",
        "isAutomated": "is_automated",
        "gateway": "gateway",
        "createdAt": "created_at",
        "updatedAt": "updated_at",
    },
    "bots": {
        "name": "name",
        "displayName": "display_name",
        "hostname": "hostname",
        "enabled": "enabled",
        "activeProvider": "active_provider",
        "activeRenderProvider": "active_render_provider",
        "engineBalances": "engine_balances",
        "engineBalancesUpdatedAt": "engine_balances_updated_at",
        "updatedBy": "updated_by",
        "startedAt": "started_at",
        "createdAt": "created_at",
        "updatedAt": "updated_at",
    },
    "referralAllowlist": {
        "email": "email",
        "addedBy": "added_by",
        "addedAt": "added_at",
    },
    "referralCodes": {
        "uid": "uid",
        "createdAt": "created_at",
    },
    "referralEarnings": {
        "topupId": "topup_id",
        "referrerId": "referrer_id",
        "referrerName": "referrer_name",
        "referrerEmail": "referrer_email",
        "referredUserId": "referred_user_id",
        "referredUserEmail": "referred_user_email",
        "referredUserName": "referred_user_name",
        "baseCoins": "base_coins",
        "baseAmount": "base_amount",
        "commissionCoins": "commission_coins",
        "commissionAmount": "commission_amount",
        "commissionRate": "commission_rate",
        "currency": "currency",
        "gateway": "gateway",
        "payoutStatus": "payout_status",
        "createdAt": "created_at",
    },
    "batchChannelAllowlist": {
        "email": "email",
        "addedBy": "added_by",
        "addedAt": "added_at",
    },
    "batchChannelConfig": {
        "channelUrl": "channel_url",
        "channelUsername": "channel_username",
        "sourceMode": "source_mode",
        "templateImageUrl": "template_image_url",
        "wardrobeReplace": "wardrobe_replace",
        "batchModelKey": "batch_model_key",
        "modelId": "model_id",
        "renderProvider": "render_provider",
        "serviceLabel": "service_label",
        "costCoins": "cost_coins",
        "maxVideoSec": "max_video_sec",
        "vaeDurationSec": "vae_duration_sec",
        "vaeResolution": "vae_resolution",
        "cronHour": "cron_hour",
        "frameSec": "frame_sec",
        "enabled": "enabled",
        "selectedOrderIds": "selected_order_ids",
        "activeRunId": "active_run_id",
        "activeRunPhase": "active_run_phase",
        "activeRunStatus": "active_run_status",
        "activeRunVideosFound": "active_run_videos_found",
        "activeRunOrdersCreated": "active_run_orders_created",
        "activeRunErrors": "active_run_errors",
        "runNowRequestedAt": "run_now_requested_at",
        "runNowHandledAt": "run_now_handled_at",
        "runNowMode": "run_now_mode",
        "lastRunAt": "last_run_at",
        "lastRunStatus": "last_run_status",
        "lastRunMessage": "last_run_message",
        "lastDailyCronDateVN": "last_daily_cron_date_vn",
        "yesterdayVideoCount": "yesterday_video_count",
        "createdBy": "created_by",
        "createdByEmail": "created_by_email",
        "createdByName": "created_by_name",
        "startedAt": "started_at",
        "updatedAt": "updated_at",
    },
    "batchChannelRuns": {
        "configId": "config_id",
        "userId": "user_id",
        "channelUsername": "channel_username",
        "dateVN": "date_vn",
        "sourceMode": "source_mode",
        "status": "status",
        "isManualTest": "is_manual_test",
        "testLatest": "test_latest",
        "videosFound": "videos_found",
        "yesterdayVideoCount": "yesterday_video_count",
        "ordersCreated": "orders_created",
        "items": "items",
        "errors": "errors",
        "startedAt": "started_at",
        "finishedAt": "finished_at",
    },
}

NHAY_EXTRA_FIELDS: dict[str, dict[str, str]] = {
    "users": {
        "authProvider": "auth_provider",
        "promoLastDate": "promo_last_date",
        "promoTodayCount": "promo_today_count",
        "promoTotalCount": "promo_total_count",
    },
    "orders": {
        "dailyPromo": "daily_promo",
        "promoDate": "promo_date",
        "roboneoRefPlan": "roboneo_ref_plan",
    },
}

TABLES_WITH_EXTRA = {"users", "orders", "topups", "batchChannelConfig"}

TIMESTAMP_SNAKE_COLS = {
    "created_at", "updated_at", "submitted_at", "started_at", "finished_at",
    "added_at", "last_run_at", "run_now_requested_at", "run_now_handled_at",
    "engine_balances_updated_at",
}


def get_field_map(site_id: str, col: str) -> dict[str, str]:
    fmap = dict(BASE_FIELD_MAPS.get(col, {}))
    if site_id == "nhay" and col in NHAY_EXTRA_FIELDS:
        fmap.update(NHAY_EXTRA_FIELDS[col])
    return fmap


def row_to_firestore_dict(col: str, row: dict[str, Any], site_id: str = "kaling") -> dict[str, Any]:
    fmap = get_field_map(site_id, col)
    rev = {v: k for k, v in fmap.items()}
    out: dict[str, Any] = {}
    extra = row.get("extra")
    if isinstance(extra, dict):
        out.update(extra)
    for k, v in row.items():
        if k in ("id", "site", "auth_user_id", "extra"):
            continue
        fs_key = rev.get(k, k)
        if k in TIMESTAMP_SNAKE_COLS and isinstance(v, str):
            out[fs_key] = _parse_dt(v)
        elif v is not None:
            out[fs_key] = v
    if col == "users":
        out["uid"] = row.get("id", "")
        if "coins" in out:
            out["coins"] = float(out["coins"])
    if col == "orders" and "costCoins" in out:
        out["costCoins"] = float(out["costCoins"])
    return out


def firestore_payload_to_row(
    col: str,
    payload: dict[str, Any],
    existing_extra: dict[str, Any] | None = None,
    site_id: str = "kaling",
) -> tuple[dict[str, Any], float | None]:
    fmap = get_field_map(site_id, col)
    row: dict[str, Any] = {}
    extra_updates: dict[str, Any] = dict(existing_extra or {})
    extra_touched = False
    coin_increment: float | None = None

    for k, v in payload.items():
        if k == "uid" and col == "users":
            continue
        inc = _extract_increment(v)
        if inc is not None and col == "users" and k == "coins":
            coin_increment = inc
            continue
        if _is_server_timestamp(v):
            v = _now_iso()
        elif isinstance(v, datetime.datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=datetime.timezone.utc)
            v = v.isoformat()

        if _is_delete_field(v):
            if k in fmap:
                row[fmap[k]] = None
            elif col in TABLES_WITH_EXTRA:
                extra_updates.pop(k, None)
                extra_touched = True
            continue

        if k in fmap:
            row[fmap[k]] = v
        elif col in TABLES_WITH_EXTRA:
            extra_updates[k] = v
            extra_touched = True

    if extra_touched and col in TABLES_WITH_EXTRA:
        row["extra"] = extra_updates
    return row, coin_increment


# ---------------------------------------------------------------------------
# Firestore-compatible Snapshot / Change / DocumentReference / Query classes
# ---------------------------------------------------------------------------

class FakeDocumentChange:
    def __init__(self, doc: "SupabaseDocSnapshot", change_type: str = "MODIFIED"):
        self.document = doc
        self.type = type("ChangeType", (), {"name": change_type})()


class SupabaseDocSnapshot:
    def __init__(self, ref: "SupabaseDocRef", row: dict[str, Any] | None):
        self.reference = ref
        self.id = ref.id
        self.exists = row is not None
        self._row = row
        self._dict = row_to_firestore_dict(ref.col_name, row, site_id=ref._client.site_id) if row is not None else None

    def to_dict(self) -> dict[str, Any] | None:
        if self._dict is None:
            return None
        return dict(self._dict)


class SupabaseWatchHandle:
    def __init__(self, stop_event: threading.Event):
        self._stop = stop_event

    def unsubscribe(self) -> None:
        self._stop.set()


class SupabaseDocRef:
    def __init__(self, client: "SiteSupabaseClient", col_name: str, doc_id: str):
        self._client = client
        self.col_name = col_name
        self.id = doc_id

    @property
    def _table_pk(self) -> tuple[str, str]:
        return self._client._table_pk(self.col_name)

    def get(self, transaction=None) -> SupabaseDocSnapshot:
        table, pk = self._table_pk
        rows = self._client._select(table, {pk: f"eq.{self.id}", "limit": "1"})
        return SupabaseDocSnapshot(self, rows[0] if rows else None)

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        table, pk = self._table_pk
        existing_extra = None
        if merge and self.col_name in TABLES_WITH_EXTRA:
            snap = self.get()
            if snap.exists and snap._row and isinstance(snap._row.get("extra"), dict):
                existing_extra = snap._row["extra"]
        row, coin_inc = firestore_payload_to_row(
            self.col_name, payload, existing_extra=existing_extra, site_id=self._client.site_id
        )
        row[pk] = self.id
        if self.col_name in ("users", "orders", "topups", "bots") and "site" not in row:
            row["site"] = self._client.site_id
        self._client._upsert(table, pk, row)
        if coin_inc is not None:
            self._client.adjust_coins(self.id, coin_inc, require_sufficient=False)

    def update(self, payload: dict[str, Any]) -> None:
        table, pk = self._table_pk
        existing_extra = None
        fmap = get_field_map(self._client.site_id, self.col_name)
        needs_extra = self.col_name in TABLES_WITH_EXTRA and any(
            k not in fmap and not (self.col_name == "users" and k == "uid") for k in payload.keys()
        )
        if needs_extra:
            snap = self.get()
            if snap.exists and snap._row and isinstance(snap._row.get("extra"), dict):
                existing_extra = snap._row["extra"]
        row, coin_inc = firestore_payload_to_row(
            self.col_name, payload, existing_extra=existing_extra, site_id=self._client.site_id
        )
        if row:
            self._client._patch(table, {pk: f"eq.{self.id}"}, row)
        if coin_inc is not None:
            self._client.adjust_coins(self.id, coin_inc, require_sufficient=False)

    def delete(self) -> None:
        table, pk = self._table_pk
        self._client._delete(table, {pk: f"eq.{self.id}"})

    def on_snapshot(self, callback) -> SupabaseWatchHandle:
        stop_ev = threading.Event()
        poll_sec = float(os.environ.get("KALING_SUPABASE_BOT_POLL_SEC", "5") or "5")

        def _loop():
            last_sig = None
            while not stop_ev.is_set():
                try:
                    snap = self.get()
                    sig = snap._row if snap.exists else None
                    if sig != last_sig:
                        last_sig = sig
                        callback([snap], [FakeDocumentChange(snap, "MODIFIED")], _now_iso())
                except Exception as e:
                    print(f"⚠️ [SupabaseWatch {self._client.site_id}/{self.col_name}/{self.id}] {e}")
                stop_ev.wait(poll_sec)

        t = threading.Thread(
            target=_loop, daemon=True, name=f"sb-watch-{self._client.site_id}-{self.col_name}-{self.id}"
        )
        t.start()
        return SupabaseWatchHandle(stop_ev)


class SupabaseQuery:
    def __init__(self, client: "SiteSupabaseClient", col_name: str, filters=None, limit_n: int | None = None, order_by=None):
        self._client = client
        self.col_name = col_name
        self._filters: list[tuple[str, str, Any]] = list(filters or [])
        self._limit = limit_n
        self._order_by: list[tuple[str, str]] = list(order_by or [])

    def where(self, field_path=None, op_string=None, value=None, *, filter=None) -> "SupabaseQuery":
        if filter is not None:
            field_path = getattr(filter, "field_path", field_path)
            op_string = getattr(filter, "op_string", op_string)
            value = getattr(filter, "value", value)
        return SupabaseQuery(
            self._client,
            self.col_name,
            filters=self._filters + [(str(field_path), str(op_string), value)],
            limit_n=self._limit,
            order_by=self._order_by,
        )

    def limit(self, n: int) -> "SupabaseQuery":
        return SupabaseQuery(self._client, self.col_name, self._filters, limit_n=int(n), order_by=self._order_by)

    def order_by(self, field_path: str, direction: str = "ASCENDING") -> "SupabaseQuery":
        d = "desc" if "DESC" in str(direction).upper() else "asc"
        return SupabaseQuery(self._client, self.col_name, self._filters, self._limit, self._order_by + [(field_path, d)])

    def _build_params(self) -> tuple[dict[str, str], list[tuple[str, str, Any]]]:
        fmap = get_field_map(self._client.site_id, self.col_name)
        params: dict[str, str] = {}
        post_filters: list[tuple[str, str, Any]] = []
        op_map = {"==": "eq", "!=": "neq", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}
        for fp, op, val in self._filters:
            if fp in fmap and op in op_map:
                col = fmap[fp]
                if isinstance(val, bool):
                    vstr = "true" if val else "false"
                elif isinstance(val, datetime.datetime):
                    vstr = val.isoformat()
                else:
                    vstr = str(val)
                params[col] = f"{op_map[op]}.{vstr}"
            else:
                post_filters.append((fp, op, val))
        if self._order_by:
            orders = []
            for fp, d in self._order_by:
                col = fmap.get(fp, fp)
                orders.append(f"{col}.{d}")
            params["order"] = ",".join(orders)
        if self._limit is not None and not post_filters:
            params["limit"] = str(self._limit)
        return params, post_filters

    def stream(self):
        table, pk = self._client._table_pk(self.col_name)
        params, post_filters = self._build_params()
        rows = self._client._select(table, params)
        snaps: list[SupabaseDocSnapshot] = []
        for r in rows:
            ref = SupabaseDocRef(self._client, self.col_name, str(r[pk]))
            snap = SupabaseDocSnapshot(ref, r)
            if post_filters:
                d = snap.to_dict() or {}
                ok = True
                for fp, op, val in post_filters:
                    cur = d.get(fp)
                    if op == "==" and cur != val:
                        ok = False
                    elif op != "==" and op == "!=" and cur == val:
                        ok = False
                    if not ok:
                        break
                if not ok:
                    continue
            snaps.append(snap)
            if self._limit is not None and len(snaps) >= self._limit:
                break
        return snaps

    def on_snapshot(self, callback) -> SupabaseWatchHandle:
        stop_ev = threading.Event()
        poll_sec = float(os.environ.get("KALING_SUPABASE_ORDER_POLL_SEC", "3") or "3")

        def _loop():
            prev_map: dict[str, tuple[Any, SupabaseDocSnapshot]] = {}
            while not stop_ev.is_set():
                try:
                    snaps = self.stream()
                    curr_map: dict[str, tuple[Any, SupabaseDocSnapshot]] = {}
                    changes: list[FakeDocumentChange] = []
                    for s in snaps:
                        sig = (s._row.get("status"), s._row.get("updated_at"), s._row.get("result_link"))
                        curr_map[s.id] = (sig, s)
                        if s.id not in prev_map:
                            changes.append(FakeDocumentChange(s, "ADDED"))
                        elif prev_map[s.id][0] != sig:
                            changes.append(FakeDocumentChange(s, "MODIFIED"))
                    for old_id, (_, old_snap) in prev_map.items():
                        if old_id not in curr_map:
                            removed_snap = SupabaseDocSnapshot(old_snap.reference, None)
                            changes.append(FakeDocumentChange(removed_snap, "REMOVED"))
                    prev_map = curr_map
                    if changes:
                        callback(snaps, changes, _now_iso())
                except Exception as e:
                    print(f"⚠️ [SupabaseQueryWatch {self._client.site_id}/{self.col_name}] {e}")
                stop_ev.wait(poll_sec)

        t = threading.Thread(
            target=_loop, daemon=True, name=f"sb-qwatch-{self._client.site_id}-{self.col_name}"
        )
        t.start()
        return SupabaseWatchHandle(stop_ev)


class SupabaseCollectionRef(SupabaseQuery):
    def __init__(self, client: "SiteSupabaseClient", col_name: str):
        super().__init__(client, col_name)

    def document(self, doc_id: str | None = None) -> SupabaseDocRef:
        if not doc_id:
            pfx = SITE_ID_PREFIX.get(self._client.site_id, "kl_")
            doc_id = pfx + secrets.token_hex(10)
        return SupabaseDocRef(self._client, self.col_name, str(doc_id))


# ---------------------------------------------------------------------------
# Main Multi-Site Client
# ---------------------------------------------------------------------------

class SiteSupabaseClient:
    is_supabase_compat = True

    def __init__(self, url: str, service_role_key: str, site_id: str = "kaling"):
        site_clean = str(site_id or "kaling").strip().lower()
        if site_clean not in ("kaling", "motion", "nhay"):
            raise ValueError(f"Unsupported site_id: {site_id}")
        self.site_id = site_clean
        self.url = url.rstrip("/")
        self.key = service_role_key
        self._session = requests.Session()
        self._session.headers.update({
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        })

    def _table_pk(self, col_name: str) -> tuple[str, str]:
        if col_name not in COLLECTION_SUFFIX_MAP:
            raise KeyError(f"Unsupported Supabase collection for {self.site_id}: {col_name}")
        suffix, pk = COLLECTION_SUFFIX_MAP[col_name]
        return f"{self.site_id}_{suffix}", pk

    @classmethod
    def from_env(cls, site_id: str = "kaling") -> "SiteSupabaseClient":
        url = (os.environ.get("SUPABASE_URL") or "").strip()
        key = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        if not url or not key:
            for env_path in (
                Path("/root/multibot/.env"),
                Path("/opt/all_ai/backend/.env"),
                Path("/root/ai_web3/.env"),
            ):
                vals = _load_dotenv_file(env_path)
                url = url or vals.get("SUPABASE_URL", "")
                key = key or vals.get("SUPABASE_SERVICE_ROLE_KEY", "")
                if url and key:
                    break
        if not url or not key:
            raise RuntimeError(f"Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY for {site_id}")
        return cls(url, key, site_id=site_id)

    def collection(self, col_name: str) -> SupabaseCollectionRef:
        if col_name not in COLLECTION_SUFFIX_MAP:
            raise KeyError(f"Unsupported Supabase collection for {self.site_id}: {col_name}")
        return SupabaseCollectionRef(self, col_name)

    def _select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        r = self._session.get(f"{self.url}/rest/v1/{table}", params=params, timeout=25)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []

    def _upsert(self, table: str, pk: str, row: dict[str, Any]) -> None:
        r = self._session.post(
            f"{self.url}/rest/v1/{table}",
            params={"on_conflict": pk},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=row,
            timeout=25,
        )
        r.raise_for_status()

    def _patch(self, table: str, params: dict[str, str], row: dict[str, Any]) -> None:
        r = self._session.patch(
            f"{self.url}/rest/v1/{table}",
            params=params,
            headers={"Prefer": "return=minimal"},
            json=row,
            timeout=25,
        )
        r.raise_for_status()

    def _delete(self, table: str, params: dict[str, str]) -> None:
        r = self._session.delete(f"{self.url}/rest/v1/{table}", params=params, timeout=25)
        r.raise_for_status()

    def rpc(self, fn_name: str, payload: dict[str, Any]) -> Any:
        r = self._session.post(f"{self.url}/rest/v1/rpc/{fn_name}", json=payload, timeout=25)
        r.raise_for_status()
        return r.json() if r.content else None

    # --- Atomic site-scoped RPC convenience methods ---

    def fail_order_and_refund(self, order_id: str, system_note: str = "") -> dict[str, Any]:
        return self.rpc(f"{self.site_id}_fail_order_and_refund", {
            "p_order_id": str(order_id),
            "p_system_note": str(system_note or ""),
        }) or {}

    def adjust_coins(self, user_id: str, delta: float, require_sufficient: bool = False) -> dict[str, Any]:
        return self.rpc(f"{self.site_id}_service_adjust_coins", {
            "p_user_id": str(user_id),
            "p_delta": round(float(delta), 2),
            "p_require_sufficient": bool(require_sufficient),
        }) or {}

    def partner_create_order(
        self,
        api_key: str,
        model_id: str,
        char_url: str,
        ref_video_url: str,
        quality: str = "720p",
        order_id: str | None = None,
    ) -> dict[str, Any]:
        return self.rpc("kaling_partner_create_order", {
            "p_api_key": api_key,
            "p_model_id": model_id,
            "p_char_url": char_url,
            "p_ref_video_url": ref_video_url,
            "p_quality": quality,
            "p_order_id": order_id,
        }) or {}


# Backwards-compatible alias for Kaling callers
class KalingSupabaseClient(SiteSupabaseClient):
    def __init__(self, url: str, service_role_key: str):
        super().__init__(url, service_role_key, site_id="kaling")

    @classmethod
    def from_env(cls, site_id: str = "kaling") -> "SiteSupabaseClient":
        return super().from_env(site_id=site_id)


def site_backend_is_supabase(site_id: str) -> bool:
    key = SITE_BACKEND_ENV.get(str(site_id or "").strip().lower())
    if not key:
        return False
    val = (os.environ.get(key) or "").strip().lower()
    if not val:
        for env_path in (Path("/root/multibot/.env"), Path("/root/ai_web3/.env")):
            vals = _load_dotenv_file(env_path)
            if vals.get(key):
                val = vals[key].strip().lower()
                break
    return val == "supabase"


def kaling_backend_is_supabase() -> bool:
    return site_backend_is_supabase("kaling")
