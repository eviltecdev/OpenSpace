#!/usr/bin/env python3
"""
Vision Injector — UserPromptSubmit hook
=======================================
Checks for a recently uploaded image from My Daily Monitor's VisionPanel.
If one exists (< 5 min old), injects a context note so Claude automatically
reads and analyzes the image with the Read tool.

Flow:
  1. User uploads photo in My Daily Monitor VisionPanel
  2. Browser saves image to /tmp/mdm-vision-latest.png
  3. User sends any message here in Claude Code
  4. This hook fires and injects the image path as context
  5. Claude reads and analyzes the image with the Read tool
"""
import sys
import json
import time
from pathlib import Path

META_PATH = Path("/tmp/mdm-vision-latest.json")
IMG_PATH  = Path("/tmp/mdm-vision-latest.png")
MAX_AGE_SECONDS = 300  # 5 minutes

def main():
    try:
        sys.stdin.read()  # consume stdin (required by hook protocol)
    except Exception:
        pass

    if not IMG_PATH.exists():
        sys.exit(0)

    # Determine image age: prefer JSON metadata, fall back to PNG mtime
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text())
            saved_at = meta.get("savedAt", 0) / 1000.0
        except Exception:
            saved_at = IMG_PATH.stat().st_mtime
    else:
        saved_at = IMG_PATH.stat().st_mtime

    if time.time() - saved_at > MAX_AGE_SECONDS:
        sys.exit(0)

    # Mark as consumed so the same image isn't injected on the next message too
    # Write savedAt=0 so future calls treat the image as too old
    try:
        META_PATH.write_text(json.dumps({"savedAt": 0, "consumed": True}))
    except Exception:
        pass

    # Output plain-text context — Claude Code appends this as a system reminder
    context = (
        f"[My Daily Monitor] Der Nutzer hat gerade ein Foto hochgeladen.\n"
        f"Bild-Pfad: {IMG_PATH}\n"
        f"Bitte analysiere dieses Bild sofort mit dem Read-Tool und gib "
        f"eine detaillierte Beschreibung auf Deutsch aus, bevor du auf die "
        f"eigentliche Nachricht des Nutzers eingehst."
    )
    print(context, flush=True)
    sys.exit(0)

if __name__ == "__main__":
    main()
