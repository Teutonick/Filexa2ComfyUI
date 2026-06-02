# Changelog

## 0.3.1 - 2026-06-02

- Increased workflow snapshot value tails in the ComfyUI panel from 15 to 30 characters so long
  model filenames remain recognizable.
- Reduced workflow snapshot detail text by 1 px to fit dense route cards more comfortably.

## 0.3.0 - 2026-06-02

Stable minor release for Comfy Registry and GitHub distribution.

- Promoted Filexa2ComfyUI from the 0.2.x public release series to stable 0.3.0.
- Added an inline I2I demo GIF to both English and Russian plugin READMEs.
- Standardized manual Git and development install paths on `ComfyUI/custom_nodes/Filexa2ComfyUI`
  to match the Registry package identity and remove legacy prefixed folder examples.

## 0.2.8 - 2026-06-02

- Added synthetic ComfyUI generation progress fallback so Filexa percentages keep moving when `/ws` progress events are unavailable.
- Added clearer local-connector setup guidance in Filexa settings, including a bold list of supported engines.
- Expanded the post-consent welcome message with guest-chat and local-generation hints.
- Increased local image and image-edit task timeout multiplier to `x2`; local video remains `x3`.

## 0.2.7 - 2026-06-01

- Added ComfyUI websocket progress tracking so Filexa receives live generation percentages when ComfyUI exposes `/ws` events.
- Preserved the last known progress percentage during result polling instead of replacing it with an empty placeholder.
- Added `websocket-client` as a runtime dependency for Registry and Manager installs.

## 0.2.6 - 2026-06-01

- Disabled automatic GitHub update checks for Comfy Registry and non-Git installations.
- Kept GitHub update checks and `git pull --ff-only` updates only for real Git checkout installs.
- Made automatic update-check network failures silent so the panel does not open with a scary error.

## 0.2.5 - 2026-06-01

- Improved package description for Comfy Registry and GitHub, making the @FilexaAIBot Telegram workflow explicit.
- Switched license metadata to `MIT License` text for clearer Registry display.
- Added automated Registry `Updates` panel population from `CHANGELOG.md` during the publish workflow.
- Kept GitHub Actions publishing manual-only and added a `publish_node` switch for changelog-only maintenance.
- Replaced the Comfy publish action wrapper with direct Comfy CLI publishing on Node 24-compatible GitHub actions.

## 0.2.4 - 2026-06-01

- Improved Comfy Registry and GitHub package descriptions to explain the @FilexaAIBot Telegram workflow.
- Added `CHANGELOG.md` with the initial public release notes.
- Added the Filexa Telegram bot URL to package metadata links.
- Switched package license metadata from a file reference to `MIT License` text for clearer Registry display.

## 0.2.3 - 2026-06-01

Initial public release for Comfy Registry and GitHub.

- Added the Filexa2ComfyUI floating ComfyUI panel with connection status, diagnostics, and reference previews.
- Added T2I, I2I, T2V, and I2V workflow snapshot capture with prompt/reference input detection.
- Added Filexa local connector polling, ComfyUI `/prompt` execution, result download, image upload fallbacks, and video direct upload.
- Added route readiness indicators, last-failed route highlighting, and terminal error reporting back to Filexa.
- Added GitHub update check and manual GitHub update action for Git installations.
