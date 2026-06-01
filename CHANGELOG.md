# Changelog

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
