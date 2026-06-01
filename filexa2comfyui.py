from __future__ import annotations

import base64
import copy
import json
import math
import mimetypes
import re
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

import requests
from PIL import Image

try:  # ComfyUI provides these at runtime.
    from aiohttp import web
    from server import PromptServer
except Exception:  # pragma: no cover - normal outside ComfyUI/tests.
    web = None
    PromptServer = None


CONNECTOR_NAME = "Filexa2ComfyUI Connector"
CONNECTOR_VERSION = "0.2.5"
CONNECTOR_PANEL_LABEL = "Filexa2ComfyUI"
FILEXA_ENGINE = "comfyui"
FILEXA_BOT_URL = "https://t.me/FilexaAIBot"
PLUGIN_REPO_URL = "https://github.com/Teutonick/Filexa2ComfyUI"
PLUGIN_INFO_URL = "https://raw.githubusercontent.com/Teutonick/Filexa2ComfyUI/main/plugin_info.json"
POLL_DELAY_SECONDS = 10
COMFY_POLL_SECONDS = 2
MAX_PROMPT_CHARS = 8000
MAX_REFERENCE_COUNT = 4
MAX_UPLOAD_IMAGE_BYTES = 40 * 1024 * 1024
MAX_UPLOAD_VIDEO_BYTES = 50 * 1024 * 1024
MAX_FALLBACK_IMAGE_BYTES = 3 * 1024 * 1024
BINARY_CHUNK_BYTES = 50 * 1024
TEXT_CHUNK_BYTES_FAST = 8 * 1024
TEXT_CHUNK_BYTES_SAFE = 4 * 1024
DIRECT_UPLOAD_TIMEOUT = 10
CHUNK_UPLOAD_TIMEOUT = 10
FILEXA_JSON_TIMEOUT = 15
STATUS_TIMEOUT = 4
REFERENCE_DOWNLOAD_TIMEOUT = 20
REFERENCE_DIRECT_ATTEMPTS = 2
REFERENCE_TEXT_ATTEMPTS = 3
COMFY_JSON_TIMEOUT = 20
COMFY_UPLOAD_TIMEOUT = 30
COMFY_RESULT_TIMEOUT = 60
UPDATE_CHECK_TIMEOUT = 6
UPDATE_APPLY_TIMEOUT = 120
JSON_CHUNK_FAST_DELAY = 0.5
JSON_CHUNK_SAFE_DELAY = 0.75
UPLOAD_MODE_HINT_TTL_SECONDS = 6 * 60 * 60
REFERENCE_MODE_HINT_TTL_SECONDS = 60 * 60
UPLOAD_MODE_TEXT_FAST = "text_fast"
UPLOAD_MODE_TEXT_SAFE = "text_safe"
REFERENCE_MODE_TEXT = "text"

JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{8,512}$")
SUPPORTED_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
SUPPORTED_VIDEO_MIMES = {"video/mp4", "video/webm", "video/quicktime"}
PROMPT_INPUT_NAMES = {
    "text",
    "prompt",
    "positive",
    "positive_prompt",
    "prompt_text",
    "text_positive",
    "user_prompt",
    "caption",
    "conditioning",
    "string",
    "value",
}
NON_PROMPT_INPUT_NAMES = {
    "filename",
    "filename_prefix",
    "file",
    "path",
    "output_path",
    "negative",
    "negative_prompt",
    "seed",
    "steps",
    "cfg",
    "cfg_scale",
    "width",
    "height",
    "model",
    "model_name",
    "ckpt_name",
    "vae_name",
    "image",
}
IMAGE_INPUT_NAMES = {
    "image",
    "input_image",
    "init_image",
    "reference_image",
    "source_image",
    "start_image",
}
MODEL_INPUT_NAMES = {
    "ckpt_name",
    "unet_name",
    "model_name",
    "checkpoint",
    "lora_name",
    "vae_name",
}
SNAPSHOT_TARGETS = ("t2i", "i2i", "t2v", "i2v")
SNAPSHOT_LEGACY_ALIASES = {
    "image": "t2i",
    "video": "t2v",
}
SNAPSHOT_LABELS = {
    "t2i": "Text to Image",
    "i2i": "Image to Image",
    "t2v": "Text to Video",
    "i2v": "Image to Video",
}


@dataclass
class FilexaConfig:
    enabled: bool = True
    api_url: str = ""
    token: str = ""
    comfyui_url: str = ""
    keep_result_on_pc_only: bool = False
    compress_images_before_upload: bool = True
    status: str = "configure"
    last_event: str = ""
    last_error: str = ""
    diagnostics: list[str] = field(default_factory=list)
    active_job_id: str = ""
    active_kind: str = ""
    active_prompt_preview: str = ""
    active_prompt_id: str = ""
    started_at_utc: str = ""
    updated_at_utc: str = ""
    poll_count: int = 0
    last_duration_seconds: float = 0.0
    upload_mode_hint: str = ""
    upload_mode_hint_until_utc: str = ""
    reference_download_mode_hint: str = ""
    reference_download_mode_hint_until_utc: str = ""
    snapshot_failures: dict[str, str] = field(default_factory=dict)


@dataclass
class UploadPayload:
    bytes: bytes
    mime_type: str
    label: str = ""


@dataclass
class TaskRuntime:
    task: dict[str, Any]
    temp_dir: Path
    started_at: float
    cancel_event: threading.Event = field(default_factory=threading.Event)
    reference_paths: list[str] = field(default_factory=list)
    comfy_prompt_id: str = ""


class FilexaUnauthorizedError(RuntimeError):
    pass


class FilexaHttpError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class FilexaClient:
    def __init__(self, config: FilexaConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {config.token.strip()}",
                "X-Filexa-Connector-Version": CONNECTOR_VERSION,
            }
        )

    def close(self) -> None:
        self.session.close()

    def absolute_url(self, path: str) -> str:
        base = _require_base_url(self.config.api_url)
        raw = str(path or "").strip()
        if not raw:
            raise ValueError("Filexa URL is empty")
        candidate = urlparse(raw)
        if candidate.scheme:
            resolved = raw
        else:
            resolved = urljoin(f"{base.scheme}://{base.netloc}/", raw.lstrip("/"))
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Filexa URL must use http or https")
        if not _same_origin(base, parsed):
            raise ValueError("Filexa URL origin does not match configured API URL")
        if not parsed.path.startswith("/local/v1/"):
            raise ValueError("Filexa URL path is outside /local/v1/")
        return resolved

    def post_json(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float = FILEXA_JSON_TIMEOUT,
        connection_close: bool = False,
    ) -> dict[str, Any]:
        headers = {"Connection": "close"} if connection_close else None
        response = self.session.post(
            self.absolute_url(path),
            json=body or {},
            timeout=timeout,
            headers=headers,
        )
        self._ensure_success(response)
        payload = response.json() if response.content else {}
        return payload if isinstance(payload, dict) else {}

    def get_bytes(self, path: str, *, timeout: float = REFERENCE_DOWNLOAD_TIMEOUT) -> tuple[bytes, str]:
        response = self.session.get(
            self.absolute_url(path),
            timeout=timeout,
            headers={"Connection": "close"},
        )
        self._ensure_success(response)
        mime_type = _clean_mime(response.headers.get("Content-Type") or "application/octet-stream")
        return response.content, mime_type

    def post_bytes(
        self,
        path: str,
        payload: UploadPayload,
        *,
        timeout: float,
        model_type: str = "",
    ) -> None:
        headers = {
            "Content-Type": payload.mime_type,
            "Content-Length": str(len(payload.bytes)),
            "Connection": "close",
        }
        if model_type:
            headers["X-Filexa-Model-Type"] = model_type
        response = self.session.post(
            self.absolute_url(path),
            data=payload.bytes,
            headers=headers,
            timeout=timeout,
        )
        self._ensure_success(response)

    def post_binary_chunk(
        self,
        chunk_base_path: str,
        *,
        upload_id: str,
        index: int,
        chunk_count: int,
        total_bytes: int,
        mime_type: str,
        chunk: bytes,
        model_type: str = "",
    ) -> None:
        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(chunk)),
            "X-Filexa-Upload-Id": upload_id,
            "X-Filexa-Chunk-Index": str(index),
            "X-Filexa-Chunk-Count": str(chunk_count),
            "X-Filexa-Total-Bytes": str(total_bytes),
            "X-Filexa-Image-Mime": mime_type,
            "Connection": "close",
        }
        if model_type:
            headers["X-Filexa-Model-Type"] = model_type
        response = self.session.post(
            self.absolute_url(f"{chunk_base_path.rstrip('/')}/{index}"),
            data=chunk,
            headers=headers,
            timeout=CHUNK_UPLOAD_TIMEOUT,
        )
        self._ensure_success(response)

    def _ensure_success(self, response: requests.Response) -> None:
        if 200 <= response.status_code < 300:
            return
        body = _short_text(response.text, 500)
        if response.status_code in {401, 403}:
            raise FilexaUnauthorizedError(
                f"Filexa returned {response.status_code} Unauthorized; reconnect with a new token."
            )
        raise FilexaHttpError(response.status_code, f"Filexa HTTP {response.status_code}: {body}")


class Filexa2ComfyUIConnector:
    def __init__(self, root_path: Path | None = None) -> None:
        self.root_path = Path(root_path or Path(__file__).resolve().parent)
        self.data_dir = self.root_path / "data"
        self._config_path = self.data_dir / "filexa2comfyui_config.json"
        self._snapshot_paths = {
            "t2i": self.data_dir / "t2i_snapshot.json",
            "i2i": self.data_dir / "i2i_snapshot.json",
            "t2v": self.data_dir / "t2v_snapshot.json",
            "i2v": self.data_dir / "i2v_snapshot.json",
        }
        self._legacy_snapshot_paths = {
            "t2i": self.data_dir / "image_snapshot.json",
            "t2v": self.data_dir / "video_snapshot.json",
        }
        self._config_lock = threading.RLock()
        self._config = self._load_config()
        self._worker_stop = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._active_runtime: TaskRuntime | None = None
        self._live_lock = threading.RLock()
        self._live_status = "idle"
        self._live_progress: int | None = None
        self._routes_registered = False
        self._update_lock = threading.RLock()
        self._update_thread: threading.Thread | None = None
        self._update_info: dict[str, Any] = {
            "status": "idle",
            "current_version": CONNECTOR_VERSION,
            "latest_version": "",
            "update_available": False,
            "checked_at_utc": "",
            "message": "",
            "repo_url": PLUGIN_REPO_URL,
            "restart_required": False,
        }

    def register_routes(self) -> bool:
        if self._routes_registered:
            return True
        if PromptServer is None or web is None:
            self._remember_diagnostic("ComfyUI PromptServer is unavailable; web panel routes were not registered.")
            return False
        routes = PromptServer.instance.routes

        @routes.get("/filexa2comfyui/status")
        async def status_route(_request):
            return web.json_response(self.status_payload())

        @routes.post("/filexa2comfyui/config")
        async def config_route(request):
            body = await _request_json(request)
            try:
                payload = self.save_config_from_ui(body)
            except ValueError as exc:
                raise web.HTTPBadRequest(text=str(exc)) from exc
            return web.json_response(payload)

        @routes.post("/filexa2comfyui/disconnect")
        async def disconnect_route(_request):
            return web.json_response(self.disconnect_from_ui())

        @routes.post("/filexa2comfyui/cancel")
        async def cancel_route(_request):
            return web.json_response(self.cancel_active_from_ui())

        @routes.post("/filexa2comfyui/capture")
        async def capture_route(request):
            body = await _request_json(request)
            try:
                payload = self.capture_snapshot_from_ui(body)
            except ValueError as exc:
                raise web.HTTPBadRequest(text=str(exc)) from exc
            return web.json_response(payload)

        @routes.post("/filexa2comfyui/update-check")
        async def update_check_route(_request):
            self.check_for_updates_async(force=True)
            return web.json_response(self.status_payload())

        @routes.post("/filexa2comfyui/update")
        async def update_route(_request):
            return web.json_response(self.update_from_ui())

        self._routes_registered = True
        self._remember_diagnostic("ComfyUI web routes registered.")
        self.check_for_updates_async()
        return True

    def ensure_worker(self) -> None:
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return
        self._worker_stop.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="filexa2comfyui-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def stop_worker(self) -> None:
        self._worker_stop.set()

    def status_payload(self) -> dict[str, Any]:
        config = self._config_snapshot()
        live_status, live_progress = self._live_progress_snapshot()
        return {
            "ok": True,
            "name": CONNECTOR_NAME,
            "version": CONNECTOR_VERSION,
            "panel_label": CONNECTOR_PANEL_LABEL,
            "status": config.status,
            "last_event": config.last_event,
            "last_error": config.last_error,
            "enabled": config.enabled,
            "api_url": config.api_url,
            "comfyui_url": config.comfyui_url,
            "token_saved": bool(config.token),
            "keep_result_on_pc_only": config.keep_result_on_pc_only,
            "compress_images_before_upload": config.compress_images_before_upload,
            "active_job_id": config.active_job_id,
            "active_kind": config.active_kind,
            "active_prompt_id": config.active_prompt_id,
            "active_prompt_preview": config.active_prompt_preview,
            "elapsed": _format_elapsed(config.started_at_utc),
            "live_status": live_status,
            "live_progress": live_progress,
            "poll_count": config.poll_count,
            "last_duration_seconds": config.last_duration_seconds,
            "diagnostics": list(config.diagnostics or []),
            "network_notice": self._network_fallback_notice(),
            "reference_previews": self._active_reference_previews(),
            "update": self._update_payload(),
            "snapshots": {target: self.snapshot_summary(target) for target in SNAPSHOT_TARGETS},
        }

    def _update_payload(self) -> dict[str, Any]:
        with self._update_lock:
            payload = dict(self._update_info)
        payload["current_version"] = CONNECTOR_VERSION
        payload["repo_url"] = PLUGIN_REPO_URL
        return payload

    def check_for_updates_async(self, *, force: bool = False) -> None:
        if not force and self._update_thread is not None and self._update_thread.is_alive():
            return
        self._update_thread = threading.Thread(
            target=self._check_for_updates,
            kwargs={"force": force},
            name="filexa2comfyui-update-check",
            daemon=True,
        )
        self._update_thread.start()

    def _check_for_updates(self, *, force: bool = False) -> None:
        del force
        with self._update_lock:
            if self._update_info.get("status") == "updating":
                return
            self._update_info.update(
                {
                    "status": "checking",
                    "message": "Checking GitHub for connector updates...",
                    "current_version": CONNECTOR_VERSION,
                }
            )
        try:
            response = requests.get(
                PLUGIN_INFO_URL,
                timeout=UPDATE_CHECK_TIMEOUT,
                headers={
                    "User-Agent": f"{CONNECTOR_NAME}/{CONNECTOR_VERSION}",
                    "Accept": "application/json",
                    "Connection": "close",
                },
            )
            response.raise_for_status()
            payload = response.json()
            latest_version = str(payload.get("version") or "").strip()
            if not latest_version:
                raise RuntimeError("GitHub plugin_info.json has no version field.")
            update_available = _version_newer(latest_version, CONNECTOR_VERSION)
            with self._update_lock:
                self._update_info.update(
                    {
                        "status": "available" if update_available else "current",
                        "latest_version": latest_version,
                        "update_available": update_available,
                        "checked_at_utc": _utc_now_iso(),
                        "message": (
                            f"Update available: {latest_version}"
                            if update_available
                            else "Connector is up to date."
                        ),
                        "restart_required": False,
                    }
                )
        except Exception as exc:
            with self._update_lock:
                self._update_info.update(
                    {
                        "status": "error",
                        "checked_at_utc": _utc_now_iso(),
                        "message": f"Update check failed: {_short_text(str(exc) or exc.__class__.__name__, 180)}",
                    }
                )

    def update_from_ui(self) -> dict[str, Any]:
        with self._update_lock:
            latest_version = str(self._update_info.get("latest_version") or "")
            self._update_info.update(
                {
                    "status": "updating",
                    "message": "Running git pull --ff-only...",
                    "update_available": False,
                }
            )
        try:
            if not (self.root_path / ".git").exists():
                raise RuntimeError(
                    "This connector folder is not a Git checkout. Install it through Git or "
                    "ComfyUI-Manager from the GitHub URL, then update again."
                )
            result = subprocess.run(
                ["git", "-C", str(self.root_path), "pull", "--ff-only"],
                capture_output=True,
                text=True,
                timeout=UPDATE_APPLY_TIMEOUT,
                check=False,
            )
            output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
            if result.returncode != 0:
                raise RuntimeError(output or f"git pull exited with {result.returncode}")
            message = "Update downloaded. Restart ComfyUI to load the new connector version."
            if latest_version:
                message = f"Update downloaded ({latest_version}). Restart ComfyUI to load it."
            with self._update_lock:
                self._update_info.update(
                    {
                        "status": "updated",
                        "message": message,
                        "checked_at_utc": _utc_now_iso(),
                        "update_available": False,
                        "restart_required": True,
                    }
                )
            self._remember_diagnostic(message)
        except Exception as exc:
            message = f"Update failed: {_short_text(str(exc) or exc.__class__.__name__, 240)}"
            with self._update_lock:
                self._update_info.update(
                    {
                        "status": "error",
                        "message": message,
                        "checked_at_utc": _utc_now_iso(),
                        "update_available": bool(latest_version),
                    }
                )
            self._remember_diagnostic(message)
        return self.status_payload()

    def _active_reference_previews(self) -> list[dict[str, str]]:
        runtime = self._active_runtime
        if runtime is None or not runtime.reference_paths:
            return []
        previews: list[dict[str, str]] = []
        for index, raw_path in enumerate(runtime.reference_paths[:MAX_REFERENCE_COUNT], start=1):
            path = Path(raw_path)
            try:
                with Image.open(path) as image:
                    image.thumbnail((180, 180))
                    if image.mode not in {"RGB", "L"}:
                        image = image.convert("RGB")
                    buffer = BytesIO()
                    image.save(buffer, format="JPEG", quality=82, optimize=True)
                previews.append(
                    {
                        "label": f"reference {index}",
                        "data_url": "data:image/jpeg;base64,"
                        + base64.b64encode(buffer.getvalue()).decode("ascii"),
                    }
                )
            except Exception as exc:
                self._debug(f"Reference preview skipped path={path}: {exc}")
        return previews

    def save_config_from_ui(self, body: dict[str, Any]) -> dict[str, Any]:
        api_url = str(body.get("api_url") or "").strip()
        token = str(body.get("token") or "").strip()
        comfyui_url = str(body.get("comfyui_url") or "").strip()
        enabled = bool(body.get("enabled", True))
        with self._config_lock:
            config = copy.deepcopy(self._config)
            if api_url:
                config.api_url = _clean_base_url(api_url)
            elif enabled:
                config.api_url = ""
            if comfyui_url:
                config.comfyui_url = _clean_base_url(comfyui_url)
            elif enabled and not config.comfyui_url:
                config.comfyui_url = ""
            if token:
                if not SAFE_TOKEN_RE.fullmatch(token):
                    raise ValueError("Invalid Filexa token shape.")
                config.token = token
            if enabled and (not config.api_url or not config.token or not config.comfyui_url):
                raise ValueError("Filexa API URL, token, and ComfyUI URL are required before connecting.")
            config.enabled = enabled
            config.keep_result_on_pc_only = bool(body.get("keep_result_on_pc_only", config.keep_result_on_pc_only))
            config.compress_images_before_upload = bool(
                body.get("compress_images_before_upload", config.compress_images_before_upload)
            )
            config.status = "enabled" if enabled and config.api_url and config.token and config.comfyui_url else "configure"
            config.last_event = "Configuration saved"
            config.last_error = ""
            self._config = config
            self._remember_diagnostic_locked(f"Configuration saved in {self._config_path}")
            self._save_config_locked()
        self.ensure_worker()
        return self.status_payload()

    def disconnect_from_ui(self) -> dict[str, Any]:
        runtime = self._active_runtime
        if runtime is not None:
            runtime.cancel_event.set()
            self._interrupt_comfy_safe()
        with self._config_lock:
            self._config.enabled = False
            self._config.status = "disabled"
            self._config.last_event = "Disconnected; saved token kept"
            self._config.last_error = ""
            self._clear_active_locked()
            self._save_config_locked()
        self._set_live_progress("disabled", None)
        return self.status_payload()

    def cancel_active_from_ui(self) -> dict[str, Any]:
        runtime = self._active_runtime
        if runtime is None:
            with self._config_lock:
                self._config.last_event = "No active task to cancel"
                self._save_config_locked()
            return self.status_payload()
        runtime.cancel_event.set()
        self._interrupt_comfy_safe()
        try:
            client = self._client_snapshot()
            self._report_cancel_safe(client, runtime.task, "Canceled in Filexa2ComfyUI Connector")
            client.close()
        except Exception as exc:
            self._debug(f"Cancel report skipped: {exc}")
        self._finish_runtime("canceled", "Cancel requested", runtime.started_at)
        self._active_runtime = None
        return self.status_payload()

    def capture_snapshot_from_ui(self, body: dict[str, Any]) -> dict[str, Any]:
        target = _snapshot_target(body.get("target"))
        api_workflow = _normalize_api_workflow(body.get("api_workflow"))
        if not api_workflow:
            raise ValueError("Current ComfyUI API workflow is empty.")
        ui_workflow = body.get("ui_workflow") if isinstance(body.get("ui_workflow"), dict) else {}
        snapshot = _build_snapshot(target, api_workflow, ui_workflow)
        self._save_snapshot(target, snapshot)
        issues = _snapshot_issues(target, snapshot)
        issue_suffix = f" issues={'; '.join(issues)}" if issues else ""
        with self._config_lock:
            self._config.last_event = f"Captured {target} workflow snapshot"
            self._config.last_error = ""
            self._config.snapshot_failures.pop(target, None)
            self._remember_diagnostic_locked(
                f"Captured {target} snapshot: nodes={snapshot['node_count']} "
                f"prompt={_binding_label(snapshot['bindings'].get('prompt'))} "
                f"image={_binding_label(snapshot['bindings'].get('image'))}{issue_suffix}"
            )
            self._save_config_locked()
        return self.status_payload()

    def snapshot_summary(self, target: str) -> dict[str, Any]:
        snapshot = self._load_snapshot(target)
        if not snapshot:
            target = _snapshot_target(target)
            last_failure = self._snapshot_failure(target)
            return {
                "saved": False,
                "target": target,
                "label": SNAPSHOT_LABELS[target],
                "saved_at_utc": "",
                "node_count": 0,
                "prompt_binding": None,
                "image_binding": None,
                "model_hint": "",
                "valid": False,
                "status": "failed" if last_failure else "empty",
                "issues": [last_failure] if last_failure else [],
                "last_failure": last_failure,
            }
        bindings = snapshot.get("bindings") if isinstance(snapshot.get("bindings"), dict) else {}
        target = _snapshot_target(target)
        issues = _snapshot_issues(target, snapshot)
        last_failure = self._snapshot_failure(target)
        all_issues = [*issues, *([last_failure] if last_failure else [])]
        return {
            "saved": True,
            "target": target,
            "label": SNAPSHOT_LABELS[target],
            "saved_at_utc": str(snapshot.get("saved_at_utc") or ""),
            "node_count": int(snapshot.get("node_count") or 0),
            "prompt_binding": bindings.get("prompt"),
            "image_binding": bindings.get("image"),
            "model_hint": str(snapshot.get("model_hint") or ""),
            "valid": not all_issues,
            "status": "failed" if last_failure else "invalid" if issues else "ready",
            "issues": all_issues,
            "last_failure": last_failure,
        }

    def _worker_loop(self) -> None:
        consecutive_errors = 0
        while not self._worker_stop.is_set():
            client: FilexaClient | None = None
            try:
                config = self._config_snapshot()
                if not config.enabled or not config.api_url or not config.token or not config.comfyui_url:
                    self._sleep_interruptible(POLL_DELAY_SECONDS)
                    continue
                client = FilexaClient(config)
                poll = client.post_json(
                    "/local/v1/tasks/poll",
                    {
                        "client_name": CONNECTOR_NAME,
                        "client_version": CONNECTOR_VERSION,
                        "status": self._poll_status_label(),
                    },
                    timeout=FILEXA_JSON_TIMEOUT,
                )
                consecutive_errors = 0
                with self._config_lock:
                    self._config.poll_count += 1
                    self._config.updated_at_utc = _utc_now_iso()
                    self._save_config_locked()
                task = poll.get("task") if isinstance(poll, dict) else None
                if isinstance(task, dict):
                    self._run_task(task, client)
                    client = None
                else:
                    self._set_status("enabled", "Polling Filexa")
                    self._sleep_interruptible(POLL_DELAY_SECONDS)
            except FilexaUnauthorizedError as exc:
                self._disable_after_filexa_failure(str(exc))
                self._sleep_interruptible(POLL_DELAY_SECONDS)
            except Exception as exc:
                if _is_filexa_server_unavailable(exc):
                    self._disable_after_filexa_failure(
                        "Filexa server is unavailable; check the API URL, server, network path, and connect again."
                    )
                    self._sleep_interruptible(POLL_DELAY_SECONDS)
                    continue
                consecutive_errors += 1
                self._set_error("error", f"Worker error: {exc}")
                self._sleep_interruptible(min(60, POLL_DELAY_SECONDS * max(1, consecutive_errors)))
            finally:
                if client is not None:
                    client.close()

    def _run_task(self, task: dict[str, Any], client: FilexaClient) -> None:
        self._validate_task(task, client)
        snapshot_target = _snapshot_target_for_task(task)
        started_at = time.monotonic()
        temp_dir = Path(tempfile.mkdtemp(prefix="filexa2comfyui_"))
        runtime = TaskRuntime(task=task, temp_dir=temp_dir, started_at=started_at)
        self._active_runtime = runtime
        self._set_live_progress("task received", 0)
        with self._config_lock:
            self._config.active_job_id = str(task["job_id"])
            self._config.active_kind = str(task.get("kind") or "")
            self._config.active_prompt_preview = _short_text(str(task.get("prompt") or ""), 140)
            self._config.active_prompt_id = ""
            self._config.started_at_utc = _utc_now_iso()
            self._config.updated_at_utc = self._config.started_at_utc
            self._config.status = "running"
            self._config.last_event = f"Task {task['job_id']}: received"
            self._config.last_error = ""
            self._save_config_locked()
        try:
            self._post_task_status_safe(client, task, "preparing ComfyUI workflow", 8)
            prepared = self._build_comfy_workflow(task, client, temp_dir)
            model_type = str(prepared.get("model_type") or "")
            self._post_task_status_safe(client, task, "queueing ComfyUI workflow", 12)
            prompt_id = self._queue_comfy_workflow(prepared)
            runtime.comfy_prompt_id = prompt_id
            with self._config_lock:
                self._config.active_prompt_id = prompt_id
                self._config.last_event = f"Queued ComfyUI prompt {prompt_id}"
                self._save_config_locked()
            self._post_task_status_safe(client, task, "generating in ComfyUI", 15)
            payload = self._wait_for_comfy_result(prompt_id, task, client, runtime)
            if runtime.cancel_event.is_set():
                self._report_cancel_safe(client, task, "Canceled in Filexa2ComfyUI Connector")
                self._finish_runtime("canceled", "Task canceled", started_at)
                return
            self._post_task_status_safe(client, task, "uploading result", 94)
            self._deliver_output_payload(client, task, payload, model_type=model_type)
            self._clear_snapshot_failure(snapshot_target)
            self._finish_runtime("completed", f"Task complete: {payload.label or prompt_id}", started_at)
        except FilexaUnauthorizedError as exc:
            self._abort_active_task_after_filexa_failure(client, task, started_at, exc)
            return
        except Exception as exc:
            if runtime.cancel_event.is_set():
                self._report_cancel_safe(client, task, "Canceled in Filexa2ComfyUI Connector")
                self._finish_runtime("canceled", "Task canceled", started_at)
                return
            if _is_filexa_server_unavailable(exc):
                self._abort_active_task_after_filexa_failure(client, task, started_at, exc)
                return
            error = str(exc) or exc.__class__.__name__
            self._debug(f"Task failed: {traceback.format_exc()}")
            self._interrupt_comfy_safe()
            self._post_task_status_safe(client, task, "ComfyUI task failed; notifying Filexa", 100)
            self._report_task_failure_and_cancel_safe(client, task, error)
            self._record_snapshot_failure(snapshot_target, error)
            self._finish_runtime("failed", f"Task failed: {_short_text(error, 300)}", started_at, error=error)
        finally:
            self._active_runtime = None
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _build_comfy_workflow(
        self,
        task: dict[str, Any],
        client: FilexaClient,
        temp_dir: Path,
    ) -> dict[str, Any]:
        kind = str(task.get("kind") or "")
        target = _snapshot_target_for_task(task)
        params = task.get("params") if isinstance(task.get("params"), dict) else {}
        override = params.get("comfyui_workflow") if isinstance(params.get("comfyui_workflow"), dict) else None
        if override is not None:
            workflow = _normalize_api_workflow(override)
            snapshot = _build_snapshot(target, workflow, {})
        else:
            snapshot = self._load_snapshot(target)
            if not snapshot:
                raise RuntimeError(
                    f"ComfyUI {target.upper()} workflow snapshot is missing. Open Filexa2ComfyUI, "
                    f"load the correct {SNAPSHOT_LABELS[target]} workflow, and capture it in the matching slot."
                )
            workflow = _normalize_api_workflow(snapshot.get("api_workflow"))
        if not workflow:
            raise RuntimeError("Saved ComfyUI workflow snapshot is empty or invalid.")
        bindings = snapshot.get("bindings") if isinstance(snapshot.get("bindings"), dict) else {}
        prompt_binding = _clean_binding(params.get("prompt_binding")) or _clean_binding(bindings.get("prompt"))
        if prompt_binding is None:
            prompt_binding = _detect_prompt_binding(workflow)
        if prompt_binding is None:
            raise RuntimeError(
                f"Saved {target.upper()} workflow has no prompt text input for Filexa. "
                "Add an API-visible prompt field such as CLIPTextEncode.text or a prompt/text input "
                "in your prompt node, then capture this workflow again."
            )
        _set_node_input(workflow, prompt_binding, str(task.get("prompt") or ""))

        reference_paths = self._download_task_references(task, client, temp_dir)
        if reference_paths:
            runtime = self._active_runtime
            if runtime is not None:
                runtime.reference_paths = [str(path) for path in reference_paths]
            uploaded_names = [
                self._upload_comfy_image(path, _mime_from_magic(path.read_bytes()[:16]) or "image/jpeg")
                for path in reference_paths
            ]
            reference_bindings = params.get("reference_bindings")
            if isinstance(reference_bindings, dict) and reference_bindings:
                _apply_reference_bindings(workflow, reference_bindings, uploaded_names)
            else:
                image_binding = _clean_binding(params.get("image_binding")) or _clean_binding(bindings.get("image"))
                if image_binding is None:
                    image_binding = _detect_image_binding(workflow)
                if image_binding is None:
                    raise RuntimeError(
                        f"Saved {target.upper()} workflow has no LoadImage/input-image node for Filexa references. "
                        "Add a LoadImage node connected where the Filexa reference should go, then capture "
                        "the I2I or I2V workflow again."
                    )
                _set_node_input(workflow, image_binding, uploaded_names[0])
        elif target in {"i2i", "i2v"}:
            raise RuntimeError(f"Saved {target.upper()} workflow expects an image reference, but this task has none.")
        model_type = _short_text(str(snapshot.get("model_hint") or _detect_model_hint(workflow) or "ComfyUI workflow"), 50)
        return {
            "workflow": workflow,
            "ui_workflow": snapshot.get("ui_workflow") if isinstance(snapshot.get("ui_workflow"), dict) else {},
            "model_type": model_type,
            "target": target,
        }

    def _download_task_references(
        self,
        task: dict[str, Any],
        client: FilexaClient,
        temp_dir: Path,
    ) -> list[Path]:
        references = task.get("references") if isinstance(task.get("references"), list) else []
        paths: list[Path] = []
        for index, reference in enumerate(references[:MAX_REFERENCE_COUNT]):
            if isinstance(reference, dict):
                paths.append(self._download_reference(client, reference, index, temp_dir))
        if paths:
            self._remember_diagnostic(f"Received {len(paths)} Filexa reference(s) for task {task.get('job_id')}")
        return paths

    def _download_reference(
        self,
        client: FilexaClient,
        reference: dict[str, Any],
        index: int,
        temp_dir: Path,
    ) -> Path:
        mime = _clean_mime(str(reference.get("mime_type") or "image/jpeg"))
        if mime not in SUPPORTED_IMAGE_MIMES:
            raise ValueError("Unsupported Filexa reference mime type")
        filename = _safe_filename(str(reference.get("filename") or f"reference-{index + 1}{_extension_for_mime(mime)}"))
        direct_url = str(reference.get("url") or "")
        text_chunk_url = str(reference.get("text_chunk_url") or "")
        data: bytes | None = None
        use_text_first = self._active_reference_hint() == REFERENCE_MODE_TEXT
        if not use_text_first and direct_url:
            for _attempt in range(REFERENCE_DIRECT_ATTEMPTS):
                try:
                    data, got_mime = client.get_bytes(direct_url, timeout=REFERENCE_DOWNLOAD_TIMEOUT)
                    mime = _clean_mime(got_mime or mime)
                    _validate_image_bytes(data, mime)
                    break
                except Exception as exc:
                    self._debug(f"Direct reference download failed: {exc}")
                    data = None
        if data is None and text_chunk_url:
            last_error: Exception | None = None
            for _attempt in range(REFERENCE_TEXT_ATTEMPTS):
                try:
                    data, mime = self._download_reference_text_chunks(client, text_chunk_url)
                    self._remember_reference_hint(REFERENCE_MODE_TEXT)
                    break
                except Exception as exc:
                    last_error = exc
            if data is None and last_error is not None:
                raise last_error
        if data is None:
            raise RuntimeError("Could not download Filexa reference")
        _validate_image_bytes(data, mime)
        output = temp_dir / filename
        output.write_bytes(data)
        return output

    def _download_reference_text_chunks(self, client: FilexaClient, path: str) -> tuple[bytes, str]:
        chunks: list[bytes] = []
        chunk_count: int | None = None
        total_bytes: int | None = None
        mime_type = "image/jpeg"
        for index in range(1024):
            response = client.session.get(
                client.absolute_url(f"{path.rstrip('/')}/{index}"),
                timeout=REFERENCE_DOWNLOAD_TIMEOUT,
                headers={"Connection": "close"},
            )
            client._ensure_success(response)
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Invalid reference chunk payload")
            body_index = int(payload.get("index"))
            if body_index != index:
                raise RuntimeError("Reference chunk index mismatch")
            if chunk_count is None:
                chunk_count = int(payload.get("chunk_count"))
                total_bytes = int(payload.get("total_bytes"))
                mime_type = _clean_mime(str(payload.get("mime_type") or mime_type))
            if int(payload.get("chunk_count")) != chunk_count or int(payload.get("total_bytes")) != total_bytes:
                raise RuntimeError("Reference chunk metadata mismatch")
            chunks.append(base64.b64decode(str(payload.get("data_b64") or ""), validate=True))
            if index + 1 >= chunk_count:
                data = b"".join(chunks)
                if total_bytes is None or len(data) != total_bytes:
                    raise RuntimeError("Reference chunk size mismatch")
                return data, mime_type
        raise RuntimeError("Too many reference chunks")

    def _upload_comfy_image(self, path: Path, mime_type: str) -> str:
        config = self._config_snapshot()
        base = _require_base_url(config.comfyui_url)
        safe_name = f"filexa_{uuid.uuid4().hex}_{_safe_filename(path.name)}"
        with path.open("rb") as handle:
            response = requests.post(
                _join_url(base, "/upload/image"),
                files={"image": (safe_name, handle, mime_type)},
                data={"type": "input", "overwrite": "true"},
                timeout=COMFY_UPLOAD_TIMEOUT,
            )
        response.raise_for_status()
        payload = response.json() if response.content else {}
        if not isinstance(payload, dict):
            return safe_name
        name = str(payload.get("name") or safe_name)
        subfolder = str(payload.get("subfolder") or "").strip("/")
        return f"{subfolder}/{name}" if subfolder else name

    def _queue_comfy_workflow(self, prepared: dict[str, Any]) -> str:
        config = self._config_snapshot()
        base = _require_base_url(config.comfyui_url)
        body: dict[str, Any] = {
            "client_id": f"filexa2comfyui-{uuid.uuid4().hex}",
            "prompt": prepared["workflow"],
        }
        ui_workflow = prepared.get("ui_workflow")
        if isinstance(ui_workflow, dict) and ui_workflow:
            body["extra_data"] = {"extra_pnginfo": {"workflow": ui_workflow}}
        response = requests.post(_join_url(base, "/prompt"), json=body, timeout=COMFY_JSON_TIMEOUT)
        response.raise_for_status()
        payload = response.json() if response.content else {}
        prompt_id = str(payload.get("prompt_id") or "")
        if not prompt_id:
            raise RuntimeError("ComfyUI did not return a prompt_id.")
        return prompt_id

    def _wait_for_comfy_result(
        self,
        prompt_id: str,
        task: dict[str, Any],
        client: FilexaClient,
        runtime: TaskRuntime,
    ) -> UploadPayload:
        config = self._config_snapshot()
        base = _require_base_url(config.comfyui_url)
        deadline = _parse_iso(str(task.get("deadline_at") or ""))
        if deadline.year <= 1900:
            deadline = datetime.now(timezone.utc) + timedelta(hours=1)
        last_status_at = 0.0
        while not self._worker_stop.is_set():
            if runtime.cancel_event.is_set():
                self._interrupt_comfy_safe()
                raise RuntimeError("Task canceled")
            if datetime.now(timezone.utc) > deadline:
                raise RuntimeError("ComfyUI task deadline expired")
            response = requests.get(
                _join_url(base, f"/history/{prompt_id}"),
                timeout=COMFY_JSON_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
            history_error = _history_error_message(payload, prompt_id)
            if history_error:
                raise RuntimeError(
                    "ComfyUI generation failed. Check that the saved workflow matches this Filexa task "
                    f"and that all local files/nodes are available: {_short_text(history_error, 700)}"
                )
            media = _first_history_media(payload, prompt_id, _media_target_for_task(str(task.get("kind") or "")))
            if media is not None:
                return self._download_comfy_media(base, media)
            if _history_completed_without_outputs(payload, prompt_id):
                raise RuntimeError(
                    "ComfyUI finished but did not produce a supported output file. Add a SaveImage/video "
                    "output node to the saved workflow, run it manually once, and capture the matching "
                    "T2I/I2I/T2V/I2V workflow again."
                )
            now = time.monotonic()
            if now - last_status_at >= 10:
                last_status_at = now
                self._post_task_status_safe(client, task, "waiting for ComfyUI result", None)
            time.sleep(COMFY_POLL_SECONDS)
        raise RuntimeError("Connector stopped while waiting for ComfyUI")

    def _download_comfy_media(self, base: Any, media: dict[str, Any]) -> UploadPayload:
        query = urlencode(
            {
                "filename": str(media.get("filename") or ""),
                "subfolder": str(media.get("subfolder") or ""),
                "type": str(media.get("type") or "output"),
            }
        )
        response = requests.get(
            _join_url(base, f"/view?{query}"),
            timeout=COMFY_RESULT_TIMEOUT,
            headers={"Connection": "close"},
        )
        response.raise_for_status()
        mime_type = _clean_mime(response.headers.get("Content-Type") or "")
        payload = _media_payload_from_bytes(response.content, mime_type, str(media.get("filename") or "comfyui-output"))
        if payload is None:
            raise RuntimeError("ComfyUI returned an unsupported result file. Configure the workflow to save PNG/JPEG/WebP or MP4/WebM/MOV.")
        return payload

    def _deliver_output_payload(
        self,
        client: FilexaClient,
        task: dict[str, Any],
        payload: UploadPayload,
        *,
        model_type: str = "",
    ) -> None:
        if (
            _media_target_for_task(str(task.get("kind") or "")) == "image"
            and payload.mime_type in SUPPORTED_VIDEO_MIMES
        ):
            self._post_task_status_safe(client, task, "video kept in ComfyUI", 100)
            self._report_complete(
                client,
                task,
                "ComfyUI generated a video for an image task, so the file stayed in the ComfyUI output folder. "
                "Check that the saved image workflow produces an image.",
                model_type=model_type,
            )
            return
        if self._config_snapshot().keep_result_on_pc_only:
            self._post_task_status_safe(client, task, "completed locally", 100)
            self._report_complete(client, task, model_type=model_type)
            return
        if payload.mime_type in SUPPORTED_VIDEO_MIMES:
            self._deliver_video_output(client, task, payload, model_type=model_type)
            return
        self._deliver_image_output(client, task, payload, model_type=model_type)

    def _deliver_video_output(
        self,
        client: FilexaClient,
        task: dict[str, Any],
        payload: UploadPayload,
        *,
        model_type: str = "",
    ) -> None:
        if len(payload.bytes) > MAX_UPLOAD_VIDEO_BYTES:
            self._post_task_status_safe(client, task, "video kept in ComfyUI", 100)
            self._report_complete(
                client,
                task,
                "ComfyUI generated a video, but it is larger than Filexa's 50 MB direct upload limit. "
                "The file stayed in the ComfyUI output folder.",
                model_type=model_type,
            )
            return
        try:
            self._post_task_status_safe(client, task, "uploading video result", 96)
            client.post_bytes(
                str(task.get("result_upload_url") or ""),
                payload,
                timeout=DIRECT_UPLOAD_TIMEOUT,
                model_type=model_type,
            )
        except FilexaUnauthorizedError:
            raise
        except FilexaHttpError as exc:
            if exc.status_code == 410:
                raise
            self._debug(f"Video direct upload failed: {exc}")
            self._report_complete(
                client,
                task,
                "ComfyUI generated the video, but direct upload to Filexa failed. "
                "The file stayed in the ComfyUI output folder; check the network path before retrying.",
                model_type=model_type,
            )
        except Exception as exc:
            self._debug(f"Video direct upload failed: {exc}")
            self._report_complete(
                client,
                task,
                "ComfyUI generated the video, but direct upload to Filexa failed. "
                "The file stayed in the ComfyUI output folder; check the network path before retrying.",
                model_type=model_type,
            )

    def _deliver_image_output(
        self,
        client: FilexaClient,
        task: dict[str, Any],
        payload: UploadPayload,
        *,
        model_type: str = "",
    ) -> None:
        if len(payload.bytes) > MAX_UPLOAD_IMAGE_BYTES:
            converted = self._jpeg_payload(payload)
            payload = converted if converted is not None else payload
        direct_payload = self._jpeg_payload(payload) if self._config_snapshot().compress_images_before_upload else payload
        if direct_payload is None:
            direct_payload = payload
        if len(direct_payload.bytes) <= MAX_UPLOAD_IMAGE_BYTES:
            try:
                client.post_bytes(
                    str(task.get("result_upload_url") or ""),
                    direct_payload,
                    timeout=DIRECT_UPLOAD_TIMEOUT,
                    model_type=model_type,
                )
                return
            except FilexaUnauthorizedError:
                raise
            except FilexaHttpError as exc:
                if exc.status_code == 410:
                    raise
                self._debug(f"Direct upload failed: {exc}")
            except Exception as exc:
                self._debug(f"Direct upload failed: {exc}")
        fallback = direct_payload if direct_payload.mime_type == "image/jpeg" else self._jpeg_payload(payload)
        if fallback is None or len(fallback.bytes) > MAX_FALLBACK_IMAGE_BYTES:
            self._post_task_status_safe(client, task, "completed locally", 100)
            self._report_complete(client, task, model_type=model_type)
            return
        preferred = self._active_upload_hint()
        if preferred in {UPLOAD_MODE_TEXT_FAST, UPLOAD_MODE_TEXT_SAFE}:
            self._upload_text_chunks_adaptive(client, task, fallback, preferred=preferred, model_type=model_type)
            return
        try:
            self._upload_binary_chunks(client, task, fallback, model_type=model_type)
            return
        except FilexaUnauthorizedError:
            raise
        except FilexaHttpError as exc:
            if exc.status_code == 410:
                raise
            self._debug(f"Binary chunk upload failed: {exc}")
        except Exception as exc:
            self._debug(f"Binary chunk upload failed: {exc}")
        self._upload_text_chunks_adaptive(client, task, fallback, model_type=model_type)

    def _upload_binary_chunks(
        self,
        client: FilexaClient,
        task: dict[str, Any],
        payload: UploadPayload,
        *,
        model_type: str = "",
    ) -> None:
        base_path = str(task.get("result_chunk_upload_url") or f"{str(task.get('result_upload_url') or '').rstrip('/')}/chunks")
        client.absolute_url(base_path)
        upload_id = uuid.uuid4().hex
        chunk_count = max(1, math.ceil(len(payload.bytes) / BINARY_CHUNK_BYTES))
        for index in range(chunk_count):
            offset = index * BINARY_CHUNK_BYTES
            chunk = payload.bytes[offset : offset + BINARY_CHUNK_BYTES]
            progress = 94 + min(5, int(((index + 1) / chunk_count) * 5))
            self._post_task_status_safe(client, task, "uploading chunked result", progress)
            client.post_binary_chunk(
                base_path,
                upload_id=upload_id,
                index=index,
                chunk_count=chunk_count,
                total_bytes=len(payload.bytes),
                mime_type=payload.mime_type,
                chunk=chunk,
                model_type=model_type,
            )

    def _upload_text_chunks_adaptive(
        self,
        client: FilexaClient,
        task: dict[str, Any],
        payload: UploadPayload,
        *,
        preferred: str = "",
        model_type: str = "",
    ) -> None:
        if preferred != UPLOAD_MODE_TEXT_SAFE:
            try:
                self._upload_text_chunks(client, task, payload, TEXT_CHUNK_BYTES_FAST, JSON_CHUNK_FAST_DELAY, model_type=model_type)
                self._remember_upload_hint(UPLOAD_MODE_TEXT_FAST)
                return
            except FilexaUnauthorizedError:
                raise
            except FilexaHttpError as exc:
                if exc.status_code == 410:
                    raise
                self._debug(f"Fast JSON/base64 upload failed: {exc}")
            except Exception as exc:
                self._debug(f"Fast JSON/base64 upload failed: {exc}")
        self._upload_text_chunks(client, task, payload, TEXT_CHUNK_BYTES_SAFE, JSON_CHUNK_SAFE_DELAY, model_type=model_type)
        self._remember_upload_hint(UPLOAD_MODE_TEXT_SAFE)

    def _upload_text_chunks(
        self,
        client: FilexaClient,
        task: dict[str, Any],
        payload: UploadPayload,
        chunk_bytes: int,
        delay: float,
        *,
        model_type: str = "",
    ) -> None:
        base_path = str(task.get("result_text_chunk_upload_url") or f"{str(task.get('result_upload_url') or '').rstrip('/')}/text-chunks")
        client.absolute_url(base_path)
        upload_id = uuid.uuid4().hex
        chunk_count = max(1, math.ceil(len(payload.bytes) / chunk_bytes))
        for index in range(chunk_count):
            offset = index * chunk_bytes
            chunk = payload.bytes[offset : offset + chunk_bytes]
            self._post_task_status_safe(client, task, "uploading JSON/base64 result", 94 + min(5, int(((index + 1) / chunk_count) * 5)))
            client.post_json(
                f"{base_path.rstrip('/')}/{index}",
                {
                    "upload_id": upload_id,
                    "index": index,
                    "chunk_count": chunk_count,
                    "total_bytes": len(payload.bytes),
                    "mime_type": payload.mime_type,
                    "model_type": model_type,
                    "data_b64": base64.b64encode(chunk).decode("ascii"),
                },
                timeout=CHUNK_UPLOAD_TIMEOUT,
                connection_close=True,
            )
            if index + 1 < chunk_count:
                time.sleep(delay)

    def _jpeg_payload(self, payload: UploadPayload) -> UploadPayload | None:
        try:
            with Image.open(BytesIO(payload.bytes)) as image:
                rgb = image.convert("RGB")
                output = BytesIO()
                rgb.save(output, format="JPEG", quality=80, optimize=True)
                return UploadPayload(output.getvalue(), "image/jpeg", payload.label)
        except Exception as exc:
            self._debug(f"JPEG conversion failed: {exc}")
            return None

    def _validate_task(self, task: dict[str, Any], client: FilexaClient) -> None:
        job_id = str(task.get("job_id") or "")
        if not JOB_ID_RE.fullmatch(job_id):
            raise ValueError("Invalid Filexa task id")
        if str(task.get("kind") or "") not in {"image", "image_edit", "video"}:
            raise ValueError("Unsupported Filexa task kind")
        if str(task.get("engine") or FILEXA_ENGINE).lower() != FILEXA_ENGINE:
            raise ValueError("Unsupported Filexa local connector engine")
        if str(task.get("client_type") or FILEXA_ENGINE).lower() != FILEXA_ENGINE:
            raise ValueError("Unsupported Filexa local connector client_type")
        prompt = str(task.get("prompt") or "")
        if not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS or any(ord(char) < 32 and char not in "\r\n\t" for char in prompt):
            raise ValueError("Invalid Filexa task prompt")
        if not isinstance(task.get("params"), dict):
            raise ValueError("Invalid Filexa task params")
        references = task.get("references") if isinstance(task.get("references"), list) else []
        if len(references) > MAX_REFERENCE_COUNT:
            raise ValueError("Too many Filexa references")
        for key in (
            "result_upload_url",
            "result_chunk_upload_url",
            "result_text_chunk_upload_url",
            "result_complete_url",
            "status_url",
            "failure_url",
            "cancel_url",
        ):
            value = task.get(key)
            if value:
                client.absolute_url(str(value))
        for reference in references:
            if not isinstance(reference, dict):
                raise ValueError("Invalid Filexa reference descriptor")
            client.absolute_url(str(reference.get("url") or ""))
            if reference.get("text_chunk_url"):
                client.absolute_url(str(reference.get("text_chunk_url")))

    def _report_complete(
        self,
        client: FilexaClient,
        task: dict[str, Any],
        message: str | None = None,
        *,
        model_type: str = "",
    ) -> None:
        payload = {"message": _short_text(message, 500)} if message else {}
        if model_type:
            payload["model_type"] = model_type
        client.post_json(str(task.get("result_complete_url") or ""), payload, timeout=FILEXA_JSON_TIMEOUT)

    def _report_failure_safe(self, client: FilexaClient, task: dict[str, Any], error: str) -> None:
        try:
            client.post_json(str(task.get("failure_url") or ""), {"error": _short_text(error, 1000)}, timeout=FILEXA_JSON_TIMEOUT)
        except Exception as exc:
            self._debug(f"Failure report skipped: {exc}")

    def _report_cancel_safe(self, client: FilexaClient, task: dict[str, Any], reason: str) -> None:
        try:
            client.post_json(str(task.get("cancel_url") or ""), {"reason": _short_text(reason, 300)}, timeout=FILEXA_JSON_TIMEOUT)
        except Exception as exc:
            self._debug(f"Cancel report skipped: {exc}")

    def _report_task_failure_and_cancel_safe(self, client: FilexaClient, task: dict[str, Any], error: str) -> None:
        clean = _short_text(error, 500)
        self._debug(f"Terminal ComfyUI task failure; trying failure report and emergency cancel: {clean}")
        self._report_failure_safe(client, task, clean)
        self._report_cancel_safe(client, task, f"Canceled after ComfyUI task failure: {clean}")

    def _abort_active_task_after_filexa_failure(
        self,
        client: FilexaClient,
        task: dict[str, Any],
        started_at: float,
        error: BaseException,
    ) -> None:
        raw_error = str(error) or error.__class__.__name__
        message = (
            "Filexa connection failed during active task; connector aborted the job and tried "
            f"to notify Filexa: {_short_text(raw_error, 260)}"
        )
        stage = "Filexa connection failed; aborting task"
        self._debug(f"{stage}: {raw_error}")
        self._post_task_status_safe(client, task, stage, 100)
        self._report_failure_safe(client, task, message)
        self._report_cancel_safe(client, task, "Canceled after Filexa connection failure")
        self._finish_runtime(
            "failed",
            f"Task failed: {_short_text(message, 300)}",
            started_at,
            error=message,
        )
        self._disable_after_filexa_failure(
            "Filexa server/network failed during active task; connector disabled after abort notice."
        )
        self._set_live_progress(stage, 100)

    def _post_task_status_safe(self, client: FilexaClient, task: dict[str, Any], status: str, progress: int | None) -> None:
        path = str(task.get("status_url") or "")
        clean_status = _short_text(status, 120)
        clean_progress = _coerce_progress(progress)
        self._set_live_progress(clean_status, clean_progress)
        if not path:
            return
        try:
            client.post_json(
                path,
                {"status": clean_status, "progress": clean_progress},
                timeout=STATUS_TIMEOUT,
            )
        except Exception as exc:
            self._debug(f"Status update skipped: {exc}")

    def _interrupt_comfy_safe(self) -> None:
        config = self._config_snapshot()
        if not config.comfyui_url:
            return
        try:
            base = _require_base_url(config.comfyui_url)
            requests.post(_join_url(base, "/interrupt"), json={}, timeout=5)
        except Exception as exc:
            self._debug(f"ComfyUI interrupt skipped: {exc}")

    def _client_snapshot(self) -> FilexaClient:
        return FilexaClient(self._config_snapshot())

    def _config_snapshot(self) -> FilexaConfig:
        with self._config_lock:
            return copy.deepcopy(self._config)

    def _set_status(self, status: str, event: str) -> None:
        with self._config_lock:
            self._config.status = status
            self._config.last_event = event
            self._config.updated_at_utc = _utc_now_iso()
            self._save_config_locked()

    def _set_error(self, status: str, error: str, *, disable: bool = False) -> None:
        with self._config_lock:
            if disable:
                self._config.enabled = False
            self._config.status = "disabled" if disable else status
            self._config.last_error = _short_text(error, 1000)
            self._config.last_event = _short_text(error, 300)
            self._config.updated_at_utc = _utc_now_iso()
            self._remember_diagnostic_locked(f"Worker error: {error}")
            self._save_config_locked()
        if disable:
            self._set_live_progress("disabled", None)

    def _disable_after_filexa_failure(self, message: str) -> None:
        with self._config_lock:
            self._config.enabled = False
            self._config.status = "disabled"
            self._config.last_error = ""
            self._config.last_event = _short_text(message, 300)
            self._clear_active_locked()
            self._remember_diagnostic_locked(f"Connector disabled: {message}")
            self._save_config_locked()
        self._set_live_progress("disabled", None)

    def _finish_runtime(self, status: str, event: str, started_at: float, *, error: str = "") -> None:
        with self._config_lock:
            if status in {"completed", "canceled"}:
                self._config.status = "enabled" if self._config.enabled else "disabled"
            else:
                self._config.status = status
            self._config.last_event = event
            self._config.last_error = _short_text(error, 1000)
            self._config.last_duration_seconds = round(max(0.0, time.monotonic() - started_at), 1)
            self._clear_active_locked()
            if error:
                self._remember_diagnostic_locked(f"Task failure: {error}")
            self._save_config_locked()
        self._set_live_progress("idle" if status in {"completed", "canceled"} else status, None)

    def _clear_active_locked(self) -> None:
        self._config.active_job_id = ""
        self._config.active_kind = ""
        self._config.active_prompt_preview = ""
        self._config.active_prompt_id = ""
        self._config.started_at_utc = ""
        self._config.updated_at_utc = _utc_now_iso()

    def _poll_status_label(self) -> str:
        with self._config_lock:
            if self._config.active_job_id:
                return f"working:{self._config.active_job_id}"
            return self._config.status or "polling"

    def _set_live_progress(self, status: str, progress: int | None) -> None:
        with self._live_lock:
            self._live_status = _short_text(status or "idle", 160)
            self._live_progress = _coerce_progress(progress)

    def _live_progress_snapshot(self) -> tuple[str, int | None]:
        with self._live_lock:
            return self._live_status, self._live_progress

    def _load_config(self) -> FilexaConfig:
        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return FilexaConfig()
        except Exception:
            return FilexaConfig(status="disabled", last_error="Could not read connector config")
        config = FilexaConfig()
        for key in asdict(config):
            if key in payload:
                setattr(config, key, payload[key])
        if not isinstance(config.diagnostics, list):
            config.diagnostics = []
        config.diagnostics = [_short_text(str(item), 400) for item in config.diagnostics[-8:]]
        if not isinstance(config.snapshot_failures, dict):
            config.snapshot_failures = {}
        config.snapshot_failures = {
            _snapshot_target(target): _short_text(str(error), 400)
            for target, error in config.snapshot_failures.items()
            if str(error or "").strip()
        }
        if config.active_job_id:
            config.active_job_id = ""
            config.active_prompt_id = ""
            config.status = "enabled" if config.enabled else "disabled"
            config.last_event = "Recovered after ComfyUI restart"
        return config

    def _save_config_locked(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(asdict(self._config), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_snapshot(self, target: str) -> dict[str, Any]:
        clean_target = _snapshot_target(target)
        path = self._snapshot_paths.get(clean_target)
        if path is None:
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            legacy = self._legacy_snapshot_paths.get(clean_target)
            if legacy is None:
                return {}
            try:
                payload = json.loads(legacy.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {}
            except Exception as exc:
                self._remember_diagnostic(f"Could not read legacy {target} snapshot: {exc}")
                return {}
        except Exception as exc:
            self._remember_diagnostic(f"Could not read {target} snapshot: {exc}")
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_snapshot(self, target: str, snapshot: dict[str, Any]) -> None:
        path = self._snapshot_paths[_snapshot_target(target)]
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    def _snapshot_failure(self, target: str) -> str:
        with self._config_lock:
            return str(self._config.snapshot_failures.get(_snapshot_target(target)) or "")

    def _record_snapshot_failure(self, target: str, error: str) -> None:
        clean_target = _snapshot_target(target)
        clean_error = _short_text(error, 400)
        with self._config_lock:
            self._config.snapshot_failures[clean_target] = clean_error
            self._remember_diagnostic_locked(f"{clean_target.upper()} workflow failed: {clean_error}")
            self._save_config_locked()

    def _clear_snapshot_failure(self, target: str) -> None:
        clean_target = _snapshot_target(target)
        with self._config_lock:
            if clean_target not in self._config.snapshot_failures:
                return
            self._config.snapshot_failures.pop(clean_target, None)
            self._save_config_locked()

    def _debug(self, message: str) -> None:
        with self._config_lock:
            self._remember_diagnostic_locked(message)
            self._save_config_locked()

    def _remember_diagnostic_locked(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        entry = f"{stamp} {_short_text(message, 400)}"
        diagnostics = list(self._config.diagnostics or [])
        diagnostics.append(entry)
        self._config.diagnostics = diagnostics[-8:]

    def _remember_diagnostic(self, message: str) -> None:
        with self._config_lock:
            self._remember_diagnostic_locked(message)
            self._save_config_locked()

    def _active_upload_hint(self) -> str:
        with self._config_lock:
            if _parse_iso(self._config.upload_mode_hint_until_utc) <= datetime.now(timezone.utc):
                return ""
            return self._config.upload_mode_hint

    def _remember_upload_hint(self, mode: str) -> None:
        with self._config_lock:
            self._config.upload_mode_hint = mode
            self._config.upload_mode_hint_until_utc = (
                datetime.now(timezone.utc) + timedelta(seconds=UPLOAD_MODE_HINT_TTL_SECONDS)
            ).isoformat()
            self._save_config_locked()

    def _active_reference_hint(self) -> str:
        with self._config_lock:
            if _parse_iso(self._config.reference_download_mode_hint_until_utc) <= datetime.now(timezone.utc):
                return ""
            return self._config.reference_download_mode_hint

    def _remember_reference_hint(self, mode: str) -> None:
        with self._config_lock:
            self._config.reference_download_mode_hint = mode
            self._config.reference_download_mode_hint_until_utc = (
                datetime.now(timezone.utc) + timedelta(seconds=REFERENCE_MODE_HINT_TTL_SECONDS)
            ).isoformat()
            self._save_config_locked()

    def _network_fallback_notice(self) -> str:
        if self._active_upload_hint() or self._active_reference_hint():
            return (
                "Unstable network, chunk transfer method temporarily enabled. "
                "Large files will stay in the ComfyUI output folder."
            )
        return ""

    def _sleep_interruptible(self, seconds: float) -> None:
        self._worker_stop.wait(seconds)


def _build_snapshot(target: str, api_workflow: dict[str, Any], ui_workflow: dict[str, Any]) -> dict[str, Any]:
    bindings = {
        "prompt": _detect_prompt_binding(api_workflow, ui_workflow),
        "image": _detect_image_binding(api_workflow),
    }
    return {
        "version": 1,
        "target": _snapshot_target(target),
        "saved_at_utc": _utc_now_iso(),
        "node_count": len(api_workflow),
        "api_workflow": copy.deepcopy(api_workflow),
        "ui_workflow": copy.deepcopy(ui_workflow) if isinstance(ui_workflow, dict) else {},
        "bindings": bindings,
        "model_hint": _detect_model_hint(api_workflow),
    }


def _snapshot_issues(target: str, snapshot: dict[str, Any]) -> list[str]:
    target = _snapshot_target(target)
    bindings = snapshot.get("bindings") if isinstance(snapshot.get("bindings"), dict) else {}
    issues: list[str] = []
    if _clean_binding(bindings.get("prompt")) is None:
        issues.append(
            "Prompt input was not detected. Filexa needs a visible prompt/text field, for example "
            "CLIPTextEncode.text or a Qwen prompt node input."
        )
    if target in {"i2i", "i2v"} and _clean_binding(bindings.get("image")) is None:
        issues.append(
            "Image input was not detected. I2I/I2V workflows need a connected LoadImage or compatible "
            "image input node for Filexa references."
        )
    if target in {"t2i", "t2v"} and _clean_binding(bindings.get("image")) is not None:
        issues.append(
            "This text workflow still contains an image loader. If generation repeats an old manual "
            "result, capture a pure T2I/T2V workflow or use the matching I2I/I2V slot."
        )
    return issues


def _normalize_api_workflow(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and isinstance(value.get("prompt"), dict):
        value = value["prompt"]
    if isinstance(value, dict) and isinstance(value.get("output"), dict):
        value = value["output"]
    if not isinstance(value, dict):
        return {}
    nodes: dict[str, Any] = {}
    for key, node in value.items():
        if isinstance(node, dict) and isinstance(node.get("inputs"), dict):
            nodes[str(key)] = copy.deepcopy(node)
    return nodes


def _detect_prompt_binding(workflow: dict[str, Any], ui_workflow: dict[str, Any] | None = None) -> dict[str, str] | None:
    candidates: list[tuple[int, int, str, str]] = []
    titles = _ui_node_titles(ui_workflow)
    downstream = _workflow_downstream_targets(workflow)
    output_nodes = _workflow_output_node_ids(workflow)
    for order, node_id in enumerate(_sorted_node_ids(workflow)):
        node = workflow[node_id]
        class_type = str(node.get("class_type") or "").lower()
        if "loadimage" in class_type:
            continue
        title = titles.get(node_id, "")
        class_and_title = f"{class_type} {title}".lower()
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for input_name, value in inputs.items():
            clean_name = str(input_name).strip().lower()
            if clean_name in NON_PROMPT_INPUT_NAMES or any(
                bad in clean_name for bad in ("filename", "prefix", "path", "negative", "seed")
            ):
                continue
            binding_input = str(input_name)
            score_value = value
            if not isinstance(value, str):
                source_binding = _linked_prompt_source_binding(workflow, value)
                if source_binding is None:
                    continue
                binding_input = source_binding["input"]
                score_value = _node_input_value(workflow, source_binding)
            score = 0
            if "negative" in str(score_value).strip().lower() and "positive" not in clean_name:
                score -= 20
            if clean_name in PROMPT_INPUT_NAMES:
                score += 35
            if "prompt" in clean_name:
                score += 35
            if clean_name == "text":
                score += 10
            if "cliptextencode" in class_type:
                score += 30
            if "qwen" in class_type:
                score += 15
            if "prompt" in class_and_title:
                score += 28
            if "positive" in class_and_title:
                score += 18
            if "text" in class_type or "conditioning" in class_type or "encode" in class_type:
                score += 8
            if "negative" in class_and_title:
                score -= 50
            if any(bad in class_type for bad in ("save", "preview", "note", "label", "filename")):
                score -= 25
            if output_nodes:
                if _node_reaches_any_output(node_id, downstream, output_nodes):
                    score += 45
                elif downstream.get(node_id):
                    score += 5
                else:
                    score -= 60
            elif downstream.get(node_id):
                score += 8
            if isinstance(score_value, str) and len(score_value.strip()) >= 8:
                score += 2
            if score > 0:
                binding_node_id = source_binding["node_id"] if not isinstance(value, str) else node_id
                candidates.append((-score, order, binding_node_id, binding_input))
    if not candidates:
        return None
    _score, _order, node_id, input_name = sorted(candidates)[0]
    return {"node_id": node_id, "input": input_name}


def _node_input_value(workflow: dict[str, Any], binding: dict[str, str]) -> Any:
    node = workflow.get(str(binding.get("node_id") or ""))
    inputs = node.get("inputs") if isinstance(node, dict) and isinstance(node.get("inputs"), dict) else {}
    return inputs.get(str(binding.get("input") or ""))


def _linked_prompt_source_binding(
    workflow: dict[str, Any],
    value: Any,
    seen: set[str] | None = None,
) -> dict[str, str] | None:
    source_id = _linked_node_id(value)
    if source_id is None:
        return None
    seen = seen or set()
    if source_id in seen:
        return None
    seen.add(source_id)
    node = workflow.get(source_id)
    inputs = node.get("inputs") if isinstance(node, dict) and isinstance(node.get("inputs"), dict) else {}
    string_bindings: list[tuple[int, str]] = []
    linked_values: list[Any] = []
    for input_name, input_value in inputs.items():
        clean_name = str(input_name).strip().lower()
        if clean_name in NON_PROMPT_INPUT_NAMES:
            continue
        if isinstance(input_value, str):
            score = 0
            if clean_name in PROMPT_INPUT_NAMES:
                score += 20
            if "prompt" in clean_name or "text" in clean_name:
                score += 15
            if clean_name in {"string", "value"}:
                score += 8
            if score > 0:
                string_bindings.append((-score, str(input_name)))
        elif _linked_node_id(input_value) is not None:
            linked_values.append(input_value)
    if string_bindings:
        _score, input_name = sorted(string_bindings)[0]
        return {"node_id": source_id, "input": input_name}
    for linked_value in linked_values:
        binding = _linked_prompt_source_binding(workflow, linked_value, seen)
        if binding is not None:
            return binding
    return None


def _linked_node_id(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and value:
        node_id = str(value[0] or "")
        return node_id or None
    return None


def _workflow_downstream_targets(workflow: dict[str, Any]) -> dict[str, set[str]]:
    downstream: dict[str, set[str]] = {}
    for target_id, node in workflow.items():
        inputs = node.get("inputs") if isinstance(node, dict) and isinstance(node.get("inputs"), dict) else {}
        for value in inputs.values():
            source_id = _linked_node_id(value)
            if source_id is not None:
                downstream.setdefault(source_id, set()).add(str(target_id))
    return downstream


def _workflow_output_node_ids(workflow: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for node_id, node in workflow.items():
        class_type = str(node.get("class_type") or "").strip().lower()
        compact = class_type.replace("_", "").replace(" ", "")
        if any(marker in compact for marker in ("saveimage", "previewimage", "savevideo", "videocombine")):
            result.add(str(node_id))
        elif "save" in compact and any(media in compact for media in ("image", "video", "webp", "gif")):
            result.add(str(node_id))
    return result


def _node_reaches_any_output(
    node_id: str,
    downstream: dict[str, set[str]],
    output_nodes: set[str],
) -> bool:
    queue = [str(node_id)]
    seen: set[str] = set()
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        if current in output_nodes:
            return True
        queue.extend(downstream.get(current, ()))
    return False


def _ui_node_titles(ui_workflow: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(ui_workflow, dict):
        return {}
    nodes = ui_workflow.get("nodes")
    if not isinstance(nodes, list):
        return {}
    titles: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        title = str(node.get("title") or node.get("label") or "")
        if title:
            titles[node_id] = title
    return titles


def _detect_image_binding(workflow: dict[str, Any]) -> dict[str, str] | None:
    for node_id in _sorted_node_ids(workflow):
        node = workflow[node_id]
        class_type = str(node.get("class_type") or "").lower().replace("_", "")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for input_name, value in inputs.items():
            clean_name = str(input_name).strip().lower()
            if clean_name not in IMAGE_INPUT_NAMES and clean_name != "image":
                continue
            if "loadimage" in class_type or "imageinput" in class_type or isinstance(value, str):
                return {"node_id": node_id, "input": str(input_name)}
    return None


def _detect_model_hint(workflow: dict[str, Any]) -> str:
    for node_id in _sorted_node_ids(workflow):
        node = workflow[node_id]
        inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
        for key, value in inputs.items():
            if str(key).strip().lower() in MODEL_INPUT_NAMES and isinstance(value, str) and value.strip():
                return _short_text(value.strip(), 50)
    for node_id in _sorted_node_ids(workflow):
        node = workflow[node_id]
        class_type = str(node.get("class_type") or "").strip()
        if class_type and any(hint in class_type.lower() for hint in ("checkpoint", "unet", "loader", "model")):
            return _short_text(class_type, 50)
    return "ComfyUI workflow"


def _set_node_input(workflow: dict[str, Any], binding: dict[str, str], value: Any) -> None:
    node_id = str(binding.get("node_id") or "")
    input_name = str(binding.get("input") or "")
    node = workflow.get(node_id)
    if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
        raise RuntimeError(f"ComfyUI workflow node {node_id} is missing.")
    if not input_name:
        raise RuntimeError("ComfyUI workflow binding input is missing.")
    node["inputs"][input_name] = value


def _apply_reference_bindings(
    workflow: dict[str, Any],
    bindings: dict[str, Any],
    uploaded_names: list[str],
) -> None:
    for path, selector in bindings.items():
        value = _reference_selector_value(selector, uploaded_names)
        if value is None:
            continue
        _set_workflow_path(workflow, str(path), value)


def _set_workflow_path(workflow: dict[str, Any], path: str, value: Any) -> None:
    parts = [part for part in str(path or "").replace("/", ".").split(".") if part]
    if len(parts) == 2:
        node_id, input_name = parts
        _set_node_input(workflow, {"node_id": node_id, "input": input_name}, value)
        return
    if len(parts) == 3 and parts[1] == "inputs":
        _set_node_input(workflow, {"node_id": parts[0], "input": parts[2]}, value)
        return
    raise RuntimeError(f"Unsupported ComfyUI reference binding path: {path}")


def _reference_selector_value(selector: Any, names: list[str]) -> Any | None:
    if selector == "first":
        return names[0] if names else None
    if selector == "all":
        return list(names)
    if isinstance(selector, int):
        return names[selector] if 0 <= selector < len(names) else None
    if isinstance(selector, list):
        result = []
        for item in selector:
            if isinstance(item, int) and 0 <= item < len(names):
                result.append(names[item])
        return result
    return None


def _first_history_media(payload: Any, prompt_id: str, target: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    entry = payload.get(prompt_id) if isinstance(payload.get(prompt_id), dict) else payload
    outputs = entry.get("outputs") if isinstance(entry, dict) and isinstance(entry.get("outputs"), dict) else {}
    found: list[tuple[int, dict[str, Any]]] = []
    for output in outputs.values():
        for key, item in _walk_media_items(output):
            mime = _mime_from_filename(str(item.get("filename") or ""))
            if target == "video":
                rank = 0 if mime in SUPPORTED_VIDEO_MIMES else 1 if key in {"gifs", "animated"} else 2
            else:
                rank = 0 if mime in SUPPORTED_IMAGE_MIMES else 2
            found.append((rank, item))
    if not found:
        return None
    return sorted(found, key=lambda pair: pair[0])[0][1]


def _history_error_message(payload: Any, prompt_id: str) -> str:
    if not isinstance(payload, dict):
        return ""
    entry = payload.get(prompt_id) if isinstance(payload.get(prompt_id), dict) else payload
    if not isinstance(entry, dict):
        return ""
    status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
    status_str = str(status.get("status_str") or status.get("status") or "").lower()
    completed = bool(status.get("completed")) if "completed" in status else False
    messages = status.get("messages") if isinstance(status.get("messages"), list) else []
    details: list[str] = []
    for item in messages:
        event = ""
        data: Any = None
        if isinstance(item, (list, tuple)) and item:
            event = str(item[0] or "")
            data = item[1] if len(item) > 1 else None
        elif isinstance(item, dict):
            event = str(item.get("type") or item.get("event") or "")
            data = item.get("data") if "data" in item else item
        if "error" not in event.lower() and "exception" not in event.lower():
            continue
        details.append(_history_message_data_text(data))
    if "error" in status_str or details:
        detail = "; ".join(part for part in details if part)
        return detail or status_str or "ComfyUI reported an execution error"
    if completed and status_str in {"failed", "failure"}:
        return status_str
    return ""


def _history_completed_without_outputs(payload: Any, prompt_id: str) -> bool:
    if not isinstance(payload, dict):
        return False
    entry = payload.get(prompt_id) if isinstance(payload.get(prompt_id), dict) else payload
    if not isinstance(entry, dict):
        return False
    status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
    if status and bool(status.get("completed")):
        return True
    return bool(entry.get("outputs") == {})


def _history_message_data_text(data: Any) -> str:
    if not isinstance(data, dict):
        return _short_text(str(data or ""), 500)
    parts: list[str] = []
    for key in ("exception_message", "message", "error", "node_type", "node_id"):
        value = data.get(key)
        if value:
            parts.append(f"{key}={value}")
    if not parts and data:
        parts.append(json.dumps(data, ensure_ascii=False)[:500])
    return _short_text("; ".join(parts), 500)


def _walk_media_items(value: Any, key: str = ""):
    if isinstance(value, dict):
        if isinstance(value.get("filename"), str):
            yield key, value
        for child_key, child in value.items():
            yield from _walk_media_items(child, str(child_key))
    elif isinstance(value, list):
        for item in value:
            yield from _walk_media_items(item, key)


def _clean_binding(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    node_id = str(value.get("node_id") or "").strip()
    input_name = str(value.get("input") or "").strip()
    if not node_id or not input_name:
        return None
    return {"node_id": node_id, "input": input_name}


def _binding_label(binding: Any) -> str:
    clean = _clean_binding(binding)
    if clean is None:
        return "-"
    return f"{clean['node_id']}.{clean['input']}"


def _sorted_node_ids(workflow: dict[str, Any]) -> list[str]:
    def key(value: str) -> tuple[int, Any]:
        try:
            return (0, int(value))
        except ValueError:
            return (1, value)

    return sorted((str(item) for item in workflow.keys()), key=key)


def _media_payload_from_bytes(data: bytes, mime_type: str, label: str) -> UploadPayload | None:
    clean_mime = _clean_mime(mime_type)
    if clean_mime not in SUPPORTED_IMAGE_MIMES | SUPPORTED_VIDEO_MIMES:
        clean_mime = _mime_from_magic(data[:16]) or _mime_from_filename(label)
    if clean_mime in SUPPORTED_IMAGE_MIMES:
        _validate_image_bytes(data, clean_mime)
        return UploadPayload(data, clean_mime, label)
    if clean_mime in SUPPORTED_VIDEO_MIMES:
        _validate_video_bytes(data, clean_mime)
        return UploadPayload(data, clean_mime, label)
    return None


def _is_filexa_server_unavailable(exc: BaseException) -> bool:
    if isinstance(exc, FilexaHttpError):
        return exc.status_code >= 500
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (requests.ConnectionError, requests.Timeout)):
            return True
        if isinstance(current, OSError) and getattr(current, "winerror", None) in {
            10051,
            10060,
            10061,
            11001,
        }:
            return True
        current = current.__cause__ or current.__context__
    return False


async def _request_json(request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        if web is not None:
            raise web.HTTPBadRequest(text="Invalid JSON body") from exc
        raise
    if not isinstance(payload, dict):
        if web is not None:
            raise web.HTTPBadRequest(text="JSON body must be an object")
        raise ValueError("JSON body must be an object")
    return payload


def _snapshot_target(value: Any) -> str:
    raw = str(value or "").strip().lower()
    raw = raw.replace("-", "_").replace(" ", "_")
    if raw in SNAPSHOT_LEGACY_ALIASES:
        return SNAPSHOT_LEGACY_ALIASES[raw]
    if raw in SNAPSHOT_TARGETS:
        return raw
    return "t2i"


def _snapshot_target_for_task(task: dict[str, Any]) -> str:
    kind = str(task.get("kind") or "")
    references = task.get("references") if isinstance(task.get("references"), list) else []
    has_reference = bool(references)
    if kind == "video":
        return "i2v" if has_reference else "t2v"
    if kind == "image_edit" or has_reference:
        return "i2i"
    return "t2i"


def _media_target_for_task(kind: str) -> str:
    return "video" if str(kind or "") == "video" else "image"


def _clean_base_url(value: str) -> str:
    parsed = _require_base_url(value)
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _require_base_url(value: str):
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Invalid URL")
    return parsed


def _join_url(base: Any, path: str) -> str:
    return urljoin(f"{base.scheme}://{base.netloc}/", str(path or "").lstrip("/"))


def _same_origin(left: Any, right: Any) -> bool:
    return (
        left.scheme.lower() == right.scheme.lower()
        and (left.hostname or "").lower() == (right.hostname or "").lower()
        and _effective_port(left) == _effective_port(right)
    )


def _effective_port(parsed: Any) -> int:
    if parsed.port:
        return int(parsed.port)
    return 443 if parsed.scheme.lower() == "https" else 80


def _clean_mime(value: str) -> str:
    clean = str(value or "").split(";", 1)[0].strip().lower()
    return "image/jpeg" if clean == "image/jpg" else clean


def _mime_from_magic(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "video/mp4"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "video/webm"
    return ""


def _mime_from_filename(filename: str) -> str:
    mime_type = _clean_mime(mimetypes.guess_type(filename)[0] or "")
    if mime_type == "video/quicktime" or mime_type in SUPPORTED_IMAGE_MIMES | SUPPORTED_VIDEO_MIMES:
        return mime_type
    suffix = Path(filename).suffix.lower()
    if suffix == ".mov":
        return "video/quicktime"
    return ""


def _validate_image_bytes(data: bytes, mime_type: str) -> None:
    if not data or _mime_from_magic(data[:16]) != mime_type:
        raise ValueError("Image bytes do not match declared MIME type")


def _validate_video_bytes(data: bytes, mime_type: str) -> None:
    detected = _mime_from_magic(data[:16])
    if not data or (detected != mime_type and not (mime_type == "video/quicktime" and detected == "video/mp4")):
        raise ValueError("Video bytes do not match declared MIME type")


def _extension_for_mime(mime_type: str) -> str:
    return {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(mime_type, ".bin")


def _safe_filename(value: str) -> str:
    name = Path(value).name.strip()[:120]
    name = re.sub(r"[^A-Za-z0-9_. -]", "_", name)
    return name or f"filexa-{uuid.uuid4().hex}.bin"


def _short_text(value: Any, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean[:limit]


def _coerce_progress(value: Any) -> int | None:
    if value is None:
        return None
    try:
        clean = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, clean))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_elapsed(started_at: str) -> str:
    start = _parse_iso(started_at)
    if start.year <= 1900:
        return "-"
    seconds = max(0.0, (datetime.now(timezone.utc) - start).total_seconds())
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m {rest}s"


def _version_newer(candidate: str, current: str) -> bool:
    return _version_key(candidate) > _version_key(current)


def _version_key(value: str) -> tuple[int, ...]:
    parts = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    return tuple(parts or [0])


CONNECTOR = Filexa2ComfyUIConnector()
if PromptServer is not None:
    CONNECTOR.register_routes()
    CONNECTOR.ensure_worker()
