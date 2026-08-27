"""
================================================================================
 FAIRSHARE — VERCEL ENTRYPOINT (at the repository root's api/ folder)
================================================================================
 The FairShare Flask app lives in the Code/ subdirectory of this repository.
 Vercel's Flask framework detection looks for a `Flask` instance named `app`
 at the project root or inside api/ — this file sits at api/index.py of the
 REPOSITORY root, so even a default Vercel import (no custom Root Directory
 setting) finds the app and wires every request to the Flask function.

 Recommended setup: set the Vercel project's Root Directory to `Code` and
 deploy — Vercel then serves the CSS/JS from public/ straight off its CDN.
 This file is a fallback that keeps the site working even when that setting
 is left at the repository root (static assets are then served by Flask's
 own static route, which works but is a little slower).

 IB HL CS: a thin *adapter layer* — it adjusts the import path so the
 existing app object is reused without any change to main.py.
"""
import os
import sys

# Make the Code/ package importable no matter what working directory Vercel
# uses when it imports this entrypoint.
# api/index.py lives one level BELOW the repository root, and Code/ is a
# sibling of api/ — so go up twice: api/ -> repo root -> Code/.
_CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Code')
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

# Re-export the real Flask app (Vercel imports this module and picks up `app`).
from main import app  # noqa: E402
