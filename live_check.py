#!/usr/bin/env python
"""Live end-to-end check against a real site (no LLM key required).

Renders pages with Playwright, discovers, analyzes, detects platforms, validates,
and persists a config -- exercising the whole pipeline against the live web.
Pass a site URL and optionally a GENAI_API_KEY to enable the LLM step.
"""

import json
import os
import sys

os.environ.setdefault("SCRAPER_CONFIG_DIR", "./configs")

from app.config.settings import get_settings
from app.services import generator_service
from app.services.async_util import close_loop


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.siddhivinayakhospitals.org"
    persist = "--persist" in sys.argv
    sample_pages = int(sys.argv[sys.argv.index("--sample") + 1]) if "--sample" in sys.argv else 3

    print(f"URL={url} persist={persist} sample_pages={sample_pages}")
    result = generator_service.generate(
        url,
        persist=persist,
        sample_pages=sample_pages,
        settings=get_settings(),
    )
    close_loop()

    print("\nhost:", result["host"])
    print("platforms:", result["platforms"])
    print("confidence:", result["confidence"], result["confidence_label"])
    print("validation:", json.dumps(result["validation"]))
    print("\nselectors (%d):" % len(result["config"]["elementsToRemove"]))
    for s in result["config"]["elementsToRemove"]:
        print("  ", s)
    print("pathsToSkip:", result["config"]["pathsToSkip"])
    if persist:
        print("\nwrote:", result.get("path"))


if __name__ == "__main__":
    main()