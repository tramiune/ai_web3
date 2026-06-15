"""AnimAI Studio Internal API client (ai.tool98.com). Standalone — not wired to web bots."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests

try:
  import imageio_ffmpeg
except ImportError:
  imageio_ffmpeg = None  # type: ignore[assignment]

DEFAULT_BASE_URL = "https://ai.tool98.com"
VIDEO_PROFILES = ("gen_01", "gen_02", "gen_03")
MAX_DURATION_BY_RESOLUTION = {"1080P": 7, "720P": 15, "480P": 15}


class Tool98ApiError(RuntimeError):
  def __init__(self, message: str, *, status: int | None = None, payload: Any = None):
    super().__init__(message)
    self.status = status
    self.payload = payload


class Tool98Client:
  def __init__(self, license_key: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 120):
    key = (license_key or "").strip()
    if not key:
      raise Tool98ApiError("Missing license key")
    self.license_key = key
    self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
    self.timeout = timeout
    self.session = requests.Session()
    self.session.headers.update(
      {
        "Authorization": f"Bearer {self.license_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
      }
    )

  def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{self.base_url}{path}"
    try:
      response = self.session.post(url, json=body or {}, timeout=self.timeout)
    except requests.RequestException as exc:
      raise Tool98ApiError(f"Network error: {exc}") from exc

    data: dict[str, Any]
    try:
      data = response.json()
    except ValueError as exc:
      raise Tool98ApiError(
        f"Invalid JSON (HTTP {response.status_code}): {response.text[:300]}",
        status=response.status_code,
      ) from exc

    if response.status_code >= 400 or data.get("ok") is False:
      raise Tool98ApiError(
        str(data.get("error") or data.get("message") or f"HTTP {response.status_code}"),
        status=response.status_code,
        payload=data,
      )
    return data.get("result") or {}

  def jobs_list(self, *, include_params: bool = False) -> dict[str, Any]:
    return self._post("/api/v1/internal/jobs/list", {"include_params": include_params})

  def jobs_get(self, job_id: str, *, include_input_media: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {"job_id": job_id}
    if include_input_media:
      body["include_input_media"] = True
    return self._post("/api/v1/internal/jobs/get", body)

  def jobs_cancel(self, job_id: str) -> dict[str, Any]:
    return self._post("/api/v1/internal/jobs/cancel", {"job_id": job_id})

  def motion_copy(
    self,
    image: dict[str, str],
    video: dict[str, str],
    *,
    resolution: str = "720P",
    duration_seconds: int = 5,
    aspect_ratio: str | None = None,
    profile: str = "gen_01",
    workspace: str = "internal",
  ) -> dict[str, Any]:
    body: dict[str, Any] = {
      "image": image,
      "video": video,
      "resolution": resolution,
      "duration_seconds": duration_seconds,
      "profile": profile,
      "workspace": workspace,
    }
    if aspect_ratio:
      body["aspect_ratio"] = aspect_ratio
    return self._post("/api/v1/internal/videos/motion-copy", body)

  def download_media(self, media: dict[str, Any], out_path: Path) -> Path:
    download_url = str(media.get("download_url") or media.get("url") or "").strip()
    if not download_url:
      raise Tool98ApiError("Media result has no download_url")

    headers: dict[str, str] = {}
    if download_url.startswith("/"):
      download_url = f"{self.base_url}{download_url}"
      headers["Authorization"] = f"Bearer {self.license_key}"

    try:
      response = self.session.get(download_url, headers=headers, timeout=self.timeout, allow_redirects=True)
    except requests.RequestException as exc:
      raise Tool98ApiError(f"Download failed: {exc}") from exc

    if response.status_code >= 400:
      raise Tool98ApiError(f"Download HTTP {response.status_code}", status=response.status_code)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(response.content)
    return out_path


def guess_mime(path: Path) -> str:
  mime, _ = mimetypes.guess_type(path.name)
  if mime:
    return mime
  ext = path.suffix.lower()
  if ext in {".jpg", ".jpeg"}:
    return "image/jpeg"
  if ext == ".png":
    return "image/png"
  if ext == ".webp":
    return "image/webp"
  if ext == ".mp4":
    return "video/mp4"
  if ext == ".mov":
    return "video/quicktime"
  return "application/octet-stream"


def _filename_from_url(url: str, *, default: str = "media.bin") -> str:
  parsed = urlparse(url)
  query = parse_qs(parsed.query, keep_blank_values=True)
  file_param = (query.get("file") or [None])[0]
  if file_param:
    name = Path(unquote(file_param)).name
    if name:
      return name
  name = Path(parsed.path).name
  if name:
    return name
  return default


def _suffix_from_url(url: str, *, default: str = ".mp4") -> str:
  name = _filename_from_url(url, default="")
  if name:
    suffix = Path(name).suffix
    if suffix:
      return suffix
  return default


def file_to_media_object(path: Path) -> dict[str, str]:
  if not path.is_file():
    raise Tool98ApiError(f"File not found: {path}")
  mime = guess_mime(path)
  encoded = base64.b64encode(path.read_bytes()).decode("ascii")
  return {"filename": path.name, "data": f"data:{mime};base64,{encoded}"}


def load_media_input(source: str, session: requests.Session | None = None) -> dict[str, str]:
  source = (source or "").strip()
  if not source:
    raise Tool98ApiError("Empty media path or URL")

  if source.startswith(("http://", "https://")):
    sess = session or requests.Session()
    try:
      response = sess.get(source, timeout=120)
    except requests.RequestException as exc:
      raise Tool98ApiError(f"Failed to download {source}: {exc}") from exc
    if response.status_code >= 400:
      raise Tool98ApiError(f"Failed to download {source}: HTTP {response.status_code}")

    mime = (response.headers.get("Content-Type") or "").split(";")[0].strip() or "application/octet-stream"
    name = _filename_from_url(source)
    if mime == "application/octet-stream":
      guessed = guess_mime(Path(name))
      if guessed != "application/octet-stream":
        mime = guessed
    encoded = base64.b64encode(response.content).decode("ascii")
    return {"filename": name, "data": f"data:{mime};base64,{encoded}"}

  path = Path(source)
  return file_to_media_object(path)


def normalize_resolution(resolution: str) -> str:
  value = (resolution or "720P").strip().upper()
  if value in MAX_DURATION_BY_RESOLUTION:
    return value
  raise Tool98ApiError(f"Resolution không hỗ trợ: {resolution}")


def max_duration_for_resolution(resolution: str) -> int:
  return MAX_DURATION_BY_RESOLUTION[normalize_resolution(resolution)]


def _read_mp4_mvhd_duration(data: bytes) -> float | None:
  moov_idx = data.rfind(b"moov")
  if moov_idx >= 4:
    start = moov_idx - 4
    size = struct.unpack(">I", data[start : start + 4])[0]
    if 8 <= size <= len(data) - start:
      parsed = _read_mp4_mvhd_duration(data[start + 8 : start + size])
      if parsed is not None:
        return parsed

  offset = 0
  while offset + 8 <= len(data):
    size = struct.unpack(">I", data[offset : offset + 4])[0]
    atom_type = data[offset + 4 : offset + 8]
    if size < 8:
      break
    if atom_type == b"moov":
      parsed = _read_mp4_mvhd_duration(data[offset + 8 : offset + size])
      if parsed is not None:
        return parsed
    elif atom_type == b"mvhd":
      version = data[offset + 8]
      if version == 0:
        timescale = struct.unpack(">I", data[offset + 20 : offset + 24])[0]
        duration = struct.unpack(">I", data[offset + 24 : offset + 28])[0]
      else:
        timescale = struct.unpack(">I", data[offset + 20 : offset + 24])[0]
        duration = struct.unpack(">Q", data[offset + 24 : offset + 32])[0]
      if timescale:
        return duration / timescale
      return None
    offset += size
  return None


def _probe_video_duration_with_ffprobe(path: Path) -> float | None:
  try:
    output = subprocess.check_output(
      [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
      ],
      stderr=subprocess.DEVNULL,
      timeout=30,
    )
    payload = json.loads(output.decode("utf-8"))
    duration = payload.get("format", {}).get("duration")
    return float(duration) if duration is not None else None
  except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
    return None


def probe_video_duration_seconds(source: str, session: requests.Session | None = None) -> float | None:
  source = (source or "").strip()
  if not source:
    return None

  temp_path: Path | None = None
  try:
    if source.startswith(("http://", "https://")):
      sess = session or requests.Session()
      try:
        response = sess.get(source, timeout=120)
      except requests.RequestException:
        return None
      if response.status_code >= 400:
        return None
      suffix = _suffix_from_url(source)
      with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        handle.write(response.content)
        temp_path = Path(handle.name)
      path = temp_path
    else:
      path = Path(source)
      if not path.is_file():
        return None

    duration = _probe_video_duration_with_ffprobe(path)
    if duration is None:
      duration = _read_mp4_mvhd_duration(path.read_bytes())
    return duration
  finally:
    if temp_path is not None:
      temp_path.unlink(missing_ok=True)


def resolve_motion_duration_seconds(
  video_source: str,
  *,
  resolution: str = "720P",
  requested: int | None = None,
  session: requests.Session | None = None,
) -> int:
  max_allowed = max_duration_for_resolution(resolution)
  if requested is not None and requested > 0:
    return max(1, min(int(requested), max_allowed))

  probed = probe_video_duration_seconds(video_source, session=session)
  if probed is None:
    return max_allowed
  seconds = max(1, min(int(round(probed)), max_allowed))
  return seconds


def _ffmpeg_executable() -> str | None:
  if imageio_ffmpeg is not None:
    try:
      return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
      pass
  import shutil

  return shutil.which("ffmpeg")


def trim_video_to_seconds(source: Path, *, max_seconds: float, output: Path | None = None) -> Path:
  if not source.is_file():
    raise Tool98ApiError(f"File not found: {source}")

  ffmpeg = _ffmpeg_executable()
  if not ffmpeg:
    raise Tool98ApiError("Cần ffmpeg hoặc imageio-ffmpeg để cắt video (pip install imageio-ffmpeg)")

  out_path = output
  if out_path is None:
    fd, path = tempfile.mkstemp(suffix=source.suffix or ".mp4")
    os.close(fd)
    out_path = Path(path)
  cmd = [ffmpeg, "-y", "-i", str(source), "-t", str(max_seconds), "-c", "copy", str(out_path)]
  result = subprocess.run(cmd, capture_output=True, text=True)
  if result.returncode != 0:
    cmd = [
      ffmpeg,
      "-y",
      "-i",
      str(source),
      "-t",
      str(max_seconds),
      "-c:v",
      "libx264",
      "-preset",
      "fast",
      "-crf",
      "18",
      "-c:a",
      "aac",
      "-movflags",
      "+faststart",
      str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
      raise Tool98ApiError(f"Không cắt được video: {(result.stderr or result.stdout)[-300:]}")

  return out_path


def _run_ffmpeg(cmd: list[str], *, err_label: str) -> None:
  result = subprocess.run(cmd, capture_output=True, text=True)
  if result.returncode != 0:
    raise Tool98ApiError(
      f"{err_label}: {(result.stderr or result.stdout)[-400:]}"
    )


def extract_video_segment(
  source: Path,
  *,
  start_sec: float,
  duration_sec: float,
  output: Path | None = None,
) -> Path:
  """Cắt đoạn video [start_sec, start_sec + duration_sec]."""
  if not source.is_file():
    raise Tool98ApiError(f"File not found: {source}")
  ffmpeg = _ffmpeg_executable()
  if not ffmpeg:
    raise Tool98ApiError("Cần ffmpeg hoặc imageio-ffmpeg để cắt video (pip install imageio-ffmpeg)")

  out_path = output
  if out_path is None:
    fd, path = tempfile.mkstemp(suffix=source.suffix or ".mp4")
    os.close(fd)
    out_path = Path(path)

  start_sec = max(0.0, float(start_sec))
  duration_sec = max(0.1, float(duration_sec))
  cmd = [
    ffmpeg, "-y",
    "-ss", str(start_sec),
    "-i", str(source),
    "-t", str(duration_sec),
    "-c", "copy",
    "-movflags", "+faststart",
    str(out_path),
  ]
  try:
    _run_ffmpeg(cmd, err_label="Không cắt được đoạn video")
  except Tool98ApiError:
    cmd = [
      ffmpeg, "-y",
      "-ss", str(start_sec),
      "-i", str(source),
      "-t", str(duration_sec),
      "-c:v", "libx264",
      "-preset", "fast",
      "-crf", "18",
      "-c:a", "aac",
      "-movflags", "+faststart",
      str(out_path),
    ]
    _run_ffmpeg(cmd, err_label="Không cắt được đoạn video")
  return out_path


def concat_video_files(parts: list[Path], output: Path) -> Path:
  """Ghép nhiều MP4 thành một file (ffmpeg concat demuxer)."""
  if len(parts) < 2:
    raise Tool98ApiError("Cần ít nhất 2 file để ghép")
  for p in parts:
    if not p.is_file():
      raise Tool98ApiError(f"File không tồn tại: {p}")

  ffmpeg = _ffmpeg_executable()
  if not ffmpeg:
    raise Tool98ApiError("Cần ffmpeg hoặc imageio-ffmpeg để ghép video")

  fd, list_path = tempfile.mkstemp(suffix=".txt")
  os.close(fd)
  list_file = Path(list_path)
  try:
    lines = []
    for p in parts:
      safe = str(p.resolve()).replace("'", "'\\''")
      lines.append(f"file '{safe}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
      ffmpeg, "-y",
      "-f", "concat",
      "-safe", "0",
      "-i", str(list_file),
      "-c", "copy",
      "-movflags", "+faststart",
      str(output),
    ]
    try:
      _run_ffmpeg(cmd, err_label="Không ghép được video")
    except Tool98ApiError:
      cmd = [
        ffmpeg, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        "-movflags", "+faststart",
        str(output),
      ]
      _run_ffmpeg(cmd, err_label="Không ghép được video")
    return output
  finally:
    try:
      list_file.unlink(missing_ok=True)
    except OSError:
      pass


def prepare_motion_video_source(
  video_source: str,
  *,
  resolution: str = "720P",
  session: requests.Session | None = None,
) -> tuple[str, Path | None]:
  """Return path/URL to use for motion-copy. Local files may be trimmed to API max."""
  max_seconds = max_duration_for_resolution(resolution)
  probed = probe_video_duration_seconds(video_source, session=session)
  if probed is None or probed <= max_seconds + 0.25:
    return video_source, None

  if video_source.startswith(("http://", "https://")):
    sess = session or requests.Session()
    try:
      response = sess.get(video_source, timeout=120)
    except requests.RequestException as exc:
      raise Tool98ApiError(f"Failed to download {video_source}: {exc}") from exc
    if response.status_code >= 400:
      raise Tool98ApiError(f"Failed to download {video_source}: HTTP {response.status_code}")
    suffix = _suffix_from_url(video_source)
    fd, in_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    temp_in = Path(in_path)
    temp_in.write_bytes(response.content)
    fd, out_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    temp_out = Path(out_path)
    trim_video_to_seconds(temp_in, max_seconds=max_seconds, output=temp_out)
    temp_in.unlink(missing_ok=True)
    return str(temp_out), temp_out

  source_path = Path(video_source)
  fd, out_path = tempfile.mkstemp(suffix=source_path.suffix or ".mp4")
  os.close(fd)
  temp_out = Path(out_path)
  trim_video_to_seconds(source_path, max_seconds=max_seconds, output=temp_out)
  return str(temp_out), temp_out
