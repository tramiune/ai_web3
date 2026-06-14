"""Ghi chú đơn hàng hiển thị cho khách (không lộ engine nội bộ)."""

from __future__ import annotations

USER_NOTE_MODERATION = (
    "Ảnh/video không qua kiểm duyệt. Coin đã hoàn. Vui lòng thử lại với file khác."
)
USER_NOTE_TECHNICAL = (
    "Gặp sự cố kỹ thuật khi tạo video. Coin đã hoàn. Thử đặt lại sau ít phút."
)
USER_NOTE_VAE_OVERLOAD = (
    "Server quá tải, hãy thử lại sau vài phút. Coin đã hoàn."
)
USER_NOTE_FILES_MISSING = (
    "Ảnh/video không hợp lệ hoặc link hỏng. Coin đã hoàn. Tải lại file và đặt đơn mới."
)
USER_NOTE_VIDEO_INVALID = (
    "Video chưa đúng yêu cầu (khoảng 5–30s, có người, chuyển động rõ). Coin đã hoàn."
)
USER_NOTE_SUBMIT_FAILED = (
    "Tạm thời không gửi được đơn vào hàng xử lý. Thử lại sau hoặc liên hệ hỗ trợ."
)
USER_NOTE_ORDER_FAILED = USER_NOTE_TECHNICAL

_MODERATION_MARKERS = (
    "nhạy cảm", "kiểm duyệt", "moderation", "policy", "censored", "vi phạm",
    "nsfw", "sensitive", "blocked", "content", "unsafe", "rejected",
)
_TECHNICAL_MARKERS = (
    "sự cố kỹ thuật", "technical", "upstream", "timeout", "overloaded",
    "maintenance", "bảo trì", "expired", "e_upstream", "no result", "503", "502",
)
_VAE_TECHNICAL_MARKERS = _TECHNICAL_MARKERS + (
    "kỹ thuật", "quá tải", "overload", "busy", "timed out", "hết thời gian",
    "500", "504", "429", "unavailable", "rate limit", "thử lại sau",
    "server error", "http 5",
)


def user_note_for_render_failure(err: str | None) -> str:
    low = (err or "").lower()
    if any(m in low for m in _TECHNICAL_MARKERS):
        return USER_NOTE_TECHNICAL
    if any(m in low for m in _MODERATION_MARKERS):
        return USER_NOTE_MODERATION
    return USER_NOTE_MODERATION


def user_note_for_videoaieasy_failure(err: str | None) -> str:
    low = (err or "").lower()
    if any(m in low for m in _MODERATION_MARKERS):
        return USER_NOTE_MODERATION
    if any(m in low for m in _VAE_TECHNICAL_MARKERS):
        return USER_NOTE_VAE_OVERLOAD
    return USER_NOTE_VAE_OVERLOAD


def user_note_for_media_validation(err: str | None) -> str:
    low = (err or "").lower()
    if "quá ngắn" in low or "quá dài" in low or "motion quá" in low:
        return USER_NOTE_VIDEO_INVALID
    return USER_NOTE_FILES_MISSING
