"""Ghi chú đơn hàng hiển thị cho khách (không lộ engine nội bộ)."""

from __future__ import annotations

USER_NOTE_CLIENT_OUTDATED = (
    "Bạn đang dùng phiên bản web cũ. Nhấn F5 hoặc Ctrl+Shift+R để tải bản mới nhất rồi đặt lại đơn. Coin đã hoàn."
)
USER_NOTE_FILES_MISSING = (
    "Ảnh/video không hợp lệ hoặc link hỏng. Coin đã hoàn. Tải lại file JPG/PNG và đặt đơn mới."
)
USER_NOTE_FILES_INVALID = USER_NOTE_FILES_MISSING

_INVALID_MEDIA_MARKERS = (
    "cannot identify image",
    "unidentifiedimageerror",
    "broken data",
    "truncated",
    "file rỗng",
    "0 byte",
    "không đọc được",
    "không tải được ảnh/video",
    "heic",
    "ftypheic",
)


def is_invalid_order_media_error(err: object) -> bool:
    s = str(err or "").lower()
    return any(m in s for m in _INVALID_MEDIA_MARKERS)
USER_NOTE_SUBMIT_FAILED = (
    "Tạm thời không gửi được đơn vào hàng xử lý. Thử lại sau hoặc liên hệ hỗ trợ."
)
USER_NOTE_ORDER_FAILED = (
    "Ảnh hoặc video có thể nhạy cảm, không vượt qua khâu kiểm duyệt. "
    "Nếu bạn tin đây là nhầm lẫn thì vui lòng thử lại. Hệ thống đã hoàn lại coin."
)
USER_NOTE_MODEL_UPDATED = (
    "Hệ thống đã cập nhật model mới. Vui lòng tạo lại đơn hàng. Coin đã hoàn lại."
)
USER_NOTE_ROBONEO_TRIAL_INVALID = (
    "Ưu đãi RoboNeo 24h đã hết hạn hoặc không áp dụng cho tài khoản này. "
    "Vui lòng chọn gói khác và đặt lại. Coin đã hoàn."
)
USER_NOTE_VAE_FALLBACK = (
    "Gặp sự cố kỹ thuật khi tạo video. Coin đã hoàn. Thử đặt lại sau ít phút."
)


def user_note_from_vae_error(err: str | None) -> str:
    """Hiển thị đúng thông báo VAE trả về (error_message / API error)."""
    msg = " ".join(str(err or "").split())
    if msg.startswith("HTTP ") and ": " in msg:
        tail = msg.split(": ", 1)[1].strip()
        if tail and not tail.startswith("{"):
            msg = tail
    if not msg:
        return USER_NOTE_VAE_FALLBACK
    return msg[:500]
