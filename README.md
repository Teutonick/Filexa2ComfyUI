[English](README.md) | [Русский](README.ru.md)

# Filexa2ComfyUI Connector

Connects ComfyUI to Filexa local generation so Telegram users can run T2I, I2I, T2V, and I2V jobs
on this PC through saved ComfyUI workflows.

Bot: https://t.me/FilexaAIBot

Not affiliated with, endorsed by, or sponsored by ComfyUI.

## Layout

- `__init__.py` and `filexa2comfyui.py` - ComfyUI custom node backend and Filexa worker.
- `web/` - ComfyUI browser panel.
- `API_CONTRACT.md` - bot-side API contract for compatible servers.
- `README.md` - installation and usage guide.
- `README.ru.md` - Russian installation and usage guide.
- `LICENSE` - source code license.
- `NOTICE.md` - legal notices and disclaimers.
- `SECURITY.md` - vulnerability reporting policy.
- `requirements.txt` - optional dependency hint for ComfyUI managers.

Prebuilt binaries are not distributed in this repository.

## Install

1. Install ComfyUI from the official project:
   https://github.com/comfyanonymous/ComfyUI
2. Start ComfyUI once and verify that your target image and/or video workflow runs manually.
3. Install the connector using one of these methods:

   Recommended, through the ComfyUI interface if ComfyUI-Manager is available:

   - open `Manager` -> `Custom Nodes Manager` or `Install via Git URL`;
   - install from `https://github.com/Teutonick/Filexa2ComfyUI`;
   - restart ComfyUI after installation.

   Manual Git install:

   ```powershell
   cd ComfyUI\custom_nodes
   git clone https://github.com/Teutonick/Filexa2ComfyUI
   ```

   Manual copy from this Filexa repository is also possible for development:

   `external_soft/comfyui` -> `ComfyUI/custom_nodes/Filexa2ComfyUI`

4. If your ComfyUI environment does not already include `requests`, install:
   `pip install -r ComfyUI/custom_nodes/Filexa2ComfyUI/requirements.txt`
5. Restart ComfyUI.
6. Open the ComfyUI web UI and click the `Filexa` button in the lower-right corner.
7. Paste the Filexa API URL and token shown by the Telegram bot, then click `Connect / Save`.
8. Open your image workflow and click `Capture Current Workflow` in `Image Workflow`.
9. Open your video workflow and click `Capture Current Workflow` in `Video Workflow` if you want
   local T2V/I2V.
10. Keep ComfyUI running.

The connector stores configuration and snapshots in:

`ComfyUI/custom_nodes/Filexa2ComfyUI/data/`

The token is hidden after saving. Write it down if you plan to reuse it; otherwise create a new
token from the Filexa bot when needed.

## Snapshot Model

Filexa2ComfyUI uses two saved API workflows:

- `data/image_snapshot.json`
- `data/video_snapshot.json`

Each snapshot contains:

- the full ComfyUI API workflow;
- the optional UI workflow metadata for PNG info;
- saved date;
- node count;
- detected prompt binding;
- detected image-input binding;
- a short model/workflow hint reported back to Filexa captions.

Prompt detection prefers text-like inputs on `CLIPTextEncode`, prompt, text, or conditioning nodes.

Reference detection looks for `LoadImage` or compatible image-input nodes and stores the first
matching input. If no image-input node is found, the snapshot is treated as text-only.

Capture can be repeated at any time. A new capture replaces the previous snapshot for that media
kind.

## Task Behavior

Image tasks use the Image Workflow snapshot:

- `image` -> T2I, prompt injected into the detected prompt node;
- `image_edit` -> I2I, prompt injected and first Filexa reference uploaded to ComfyUI, then placed
  into the detected image input.

Video tasks use the Video Workflow snapshot:

- `video` without references -> T2V;
- `video` with one reference -> I2V, prompt injected and the reference placed into the detected
  image input.

The workflow itself owns model selection, sampler settings, video nodes, dimensions, output format,
and save nodes. After changing a workflow, capture it again.

## Outputs

The connector reads ComfyUI `/history/{prompt_id}`, finds the first generated media item, downloads
it through `/view`, and sends it to Filexa.

Supported direct result types:

- images: PNG, JPEG, WebP;
- videos: MP4, WebM, MOV.

Images use the same network fallbacks as Filexa2Wan2GP:

- direct raw upload capped at 40 MiB;
- optional JPEG conversion before upload;
- binary chunks of 50 KiB for compressed results up to 3 MiB;
- JSON/base64 chunks of 8 KiB and then 4 KiB safe mode;
- local-only completion if the result is still too large or upload cannot work.

Videos are direct-upload only and capped at 50 MiB. If a video is too large or direct upload fails,
the file stays in the ComfyUI output folder and Filexa receives a neutral local-only completion.

## Advanced Task Overrides

The normal Filexa bot does not need these. Compatible servers can send optional fields in
`task.params`:

- `comfyui_workflow`: full API workflow override for one task;
- `prompt_binding`: `{ "node_id": "6", "input": "text" }`;
- `image_binding`: `{ "node_id": "10", "input": "image" }`;
- `reference_bindings`: map `"node_id.input"` or `"node_id.inputs.input"` to `"first"`, `"all"`,
  an index, or a list of indexes.

Without explicit reference bindings, the connector uses the detected image-input binding and the
first Filexa reference.

## Troubleshooting

### The panel does not appear.

Check that the folder is exactly:

`ComfyUI/custom_nodes/Filexa2ComfyUI`

Then restart ComfyUI and check the terminal for import errors.

### Capture says the prompt node was not found.

Make sure the workflow has an API-visible text prompt input, usually `CLIPTextEncode.text`.

### I2I or I2V says no image input was found.

Add a `LoadImage` or compatible image-input node, connect it to the workflow, and capture the
snapshot again.

### The result does not return to Filexa.

Open the Filexa2ComfyUI panel and check Status and Diagnostics. If the network is unstable, the
connector will switch to chunk fallback for images. Oversized images/videos stay in the ComfyUI
output folder and Filexa receives a local-only completion.

### Everything is stuck.

Cancel the task in Filexa with `/cancel`, click `Cancel active task` in the panel, then restart
ComfyUI if the queue is still blocked.

## Legal Notice

This repository contains only the Filexa2ComfyUI Connector source code.

The connector is licensed under the MIT License. The Filexa bot/API service is provided under
separate Filexa Terms of Use and Privacy Policy:
https://teutonick.github.io/bot-legal-docs/privacy

Users are solely responsible for installing ComfyUI, installing custom nodes, selecting and
licensing models, securing their API tokens, operating their local computer, reviewing generated
outputs, and complying with applicable laws and third-party terms.

The connector makes outbound HTTP/HTTPS requests to the configured Filexa API endpoint and calls
the configured local ComfyUI API URL. It does not require exposing the user's ComfyUI port to the
public internet.

Security issues should be reported privately according to `SECURITY.md`.
