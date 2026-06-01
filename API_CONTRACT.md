# Filexa2ComfyUI Connector API Contract

This contract describes the bot-side API a third-party bot/server must implement to reuse the
Filexa2ComfyUI Connector.

Version: 2026-06-01.

The connector has no public inbound HTTP API for bots. It polls an outbound Filexa-compatible API,
then submits tasks to the local ComfyUI HTTP API through `/prompt`.

## Required Bot API

Implement the Filexa local connector API described in:

`../../docs/LOCAL_GENERATION_CONNECTOR_API_CONTRACT.md`

The plugin calls these routes:

- `POST /local/v1/tasks/poll`
- `GET /local/v1/tasks/{job_id}/references/{index}`
- `GET /local/v1/tasks/{job_id}/references/{index}/text-chunks/{chunk_index}`
- `POST /local/v1/tasks/{job_id}/status`
- `POST /local/v1/tasks/{job_id}/result`
- `POST /local/v1/tasks/{job_id}/result/chunks/{index}`
- `POST /local/v1/tasks/{job_id}/result/text-chunks/{index}`
- `POST /local/v1/tasks/{job_id}/complete`
- `POST /local/v1/tasks/{job_id}/failure`
- `POST /local/v1/tasks/{job_id}/cancel`

All requests use `Authorization: Bearer <token>` and `X-Filexa-Connector-Version`.

## Task Contract

Supported task kinds:

- `image`
- `image_edit`
- `video`

Required task fields:

```json
{
  "job_id": "0123456789abcdef0123456789abcdef",
  "kind": "image_edit",
  "engine": "comfyui",
  "client_type": "comfyui",
  "prompt": "Add neon rain",
  "profile": "workflow",
  "model": "workflow",
  "params": {},
  "references": [],
  "deadline_at": "2026-06-01T12:00:00+00:00",
  "result_upload_url": "/local/v1/tasks/<job_id>/result",
  "result_chunk_upload_url": "/local/v1/tasks/<job_id>/result/chunks",
  "result_text_chunk_upload_url": "/local/v1/tasks/<job_id>/result/text-chunks",
  "result_complete_url": "/local/v1/tasks/<job_id>/complete",
  "status_url": "/local/v1/tasks/<job_id>/status",
  "failure_url": "/local/v1/tasks/<job_id>/failure",
  "cancel_url": "/local/v1/tasks/<job_id>/cancel"
}
```

Validation expectations:

- `job_id`: 32 hex characters.
- `prompt`: non-empty, max 8000 characters, no control characters except common whitespace.
- `engine` and `client_type`: `comfyui`.
- `params`: object.
- `references`: max four image references; Filexa currently sends one for local I2V.

## Snapshot Modes

The connector stores two snapshots in its local `data/` directory:

- `image_snapshot.json`
- `video_snapshot.json`

Each snapshot contains the full ComfyUI API workflow, optional UI workflow metadata, saved date,
node count, detected prompt binding, detected image-input binding, and model/workflow hint.

Image tasks use the image snapshot. Video tasks use the video snapshot. If a reference arrives, the
connector uploads it through ComfyUI `/upload/image` and places the resulting input filename in the
detected image-input binding.

## Advanced Task Overrides

`params.comfyui_workflow`

If present, the connector treats it as a full ComfyUI API workflow for this task only. Filexa prompt
and references are still applied afterwards.

`params.prompt_binding`

Optional object:

```json
{
  "prompt_binding": {
    "node_id": "6",
    "input": "text"
  }
}
```

`params.image_binding`

Optional object:

```json
{
  "image_binding": {
    "node_id": "10",
    "input": "image"
  }
}
```

`params.reference_bindings`

Optional object mapping ComfyUI workflow paths to reference selectors:

```json
{
  "reference_bindings": {
    "10.image": "first",
    "25.inputs.image": 0,
    "40.images": "all",
    "50.inputs.images": [0, 1]
  }
}
```

Without explicit bindings, `image_edit` and `video` tasks place the first reference in the detected
image input.

## Local ComfyUI API Used

The connector calls the configured ComfyUI URL:

- `POST /upload/image`
- `POST /prompt`
- `GET /history/{prompt_id}`
- `GET /view?filename=...&subfolder=...&type=...`
- `POST /interrupt` when cancellation is requested

The connector discovers generated results by reading `/history/{prompt_id}` and scanning output
items with a `filename`.

## Result Metadata

After successful generation, the plugin reports a short model/workflow hint detected from the
snapshot:

- Direct upload: `X-Filexa-Model-Type: <hint>`.
- Binary chunk upload: `X-Filexa-Model-Type: <hint>`.
- JSON/base64 chunk upload: `"model_type": "<hint>"`.
- Local-only completion: `"model_type": "<hint>"`.

Bots should truncate this value to 50 characters before displaying or storing it. Filexa already
does that.

## Result Handling

Images:

- direct raw PNG/JPEG/WebP upload capped at 40 MiB;
- optional JPEG conversion before upload;
- binary chunks of 50 KiB for compressed results up to 3 MiB;
- JSON/base64 chunks of 8 KiB and then 4 KiB safe mode;
- `/complete` if upload is disabled, impossible, or the file remains too large.

Videos:

- direct MP4/WebM/MOV upload capped at 50 MiB;
- no video chunk fallback;
- `/complete` if direct video upload is impossible or too large.

While upload/reference chunk-mode cache is active, the plugin shows an unstable-network notice in
the panel.

## Bot Compatibility Notes

- Return `410 Gone` when the task is no longer waiting; the plugin treats it as terminal.
- Keep task URLs on the same origin as the configured Filexa API URL.
- Do not long-poll; the plugin polls every 10 seconds.
- If the Filexa token is invalid or the Filexa API is unavailable, the plugin disables itself until
  the user manually reconnects.
- During an active task, a fatal Filexa transport/auth error is surfaced in the panel stage and
  diagnostics; the plugin then tries one `failure_url` report and one emergency `cancel_url` report
  before disabling.
- ComfyUI workflows must contain save/output nodes. The connector cannot upload a result that never
  appears in `/history/{prompt_id}`.
