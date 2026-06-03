from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


API_URL = "https://api.deepseek.com/chat/completions"
MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
PROMPT = "introduce your model in 20 words"


def main() -> int:
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Missing DEEPSEEK_API_KEY or OPENAI_API_KEY in environment.", file=sys.stderr)
        return 2

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": [{"type": "text", "text": PROMPT}]},
        ],
        "stream": False,
    }

    print("request_url=", API_URL)
    print("request_model=", MODEL)
    print("request_messages=", json.dumps(payload["messages"], ensure_ascii=False))

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}", file=sys.stderr)
        print(error_body, file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"request_error={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    data = json.loads(raw)
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content", "")

    print("response_id=", data.get("id"))
    print("response_model=", data.get("model"))
    print("finish_reason=", choice.get("finish_reason"))
    print("content=", content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
