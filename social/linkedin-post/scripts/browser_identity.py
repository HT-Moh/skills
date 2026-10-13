"""Read the user's own browser identity from a HAR export, so the poster can present the same one.

LinkedIn ties a login cookie to the browser that created it. The poster's headless browser
announces itself as "HeadlessChrome" with its own brand list, and LinkedIn signs the session
out. This reads only the identity headers (user agent, client-hint brands, platform, language)
from the HAR's first www.linkedin.com request. It never copies cookies or tokens.

    python3 browser_identity.py ~/cookies/www.linkedin.com.har ~/cookies/linkedin-identity.json

Point LINKEDIN_BROWSER_IDENTITY (or --identity) at the output. Re-run it after the browser
updates, so the version the poster claims stays the version the cookie was made with.
"""
import json
import re
import sys
from pathlib import Path

HOST = "https://www.linkedin.com/"
_BRAND = re.compile(r'"([^"]+)";v="([^"]+)"')


def identity_from_har(har: dict) -> dict:
    """The identity headers of the first www.linkedin.com request that carries a user agent.
    Raises ValueError when the HAR holds no such request."""
    for entry in har["log"]["entries"]:
        request = entry["request"]
        headers = {h["name"].lower(): h["value"] for h in request["headers"]}
        if request["url"].startswith(HOST) and "user-agent" in headers and "sec-ch-ua" in headers:
            return {
                "userAgent": headers["user-agent"],
                "brands": [{"brand": b, "version": v} for b, v in _BRAND.findall(headers["sec-ch-ua"])],
                "platform": headers.get("sec-ch-ua-platform", '"Linux"').strip('"'),
                "acceptLanguage": headers.get("accept-language", "en-US,en;q=0.9"),
            }
    raise ValueError(f"no request to {HOST} with user-agent and sec-ch-ua headers in the HAR")


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        sys.exit("usage: browser_identity.py <export.har> <identity.json>")
    identity = identity_from_har(json.loads(Path(argv[0]).read_text()))
    Path(argv[1]).write_text(json.dumps(identity, indent=1) + "\n")
    print(f"{argv[1]}: {identity['userAgent']}")


if __name__ == "__main__":
    main(sys.argv[1:])
