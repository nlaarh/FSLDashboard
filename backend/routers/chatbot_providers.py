"""Chatbot LLM provider API calls — OpenAI, Anthropic, Google."""

import requests as _requests


def _call_openai(api_key: str, model: str, messages: list) -> str:
    resp = _requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "max_tokens": 2048, "temperature": 0.3},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_anthropic(api_key: str, model: str, messages: list) -> str:
    system_msg = ""
    user_msgs = []
    for m in messages:
        if m["role"] == "system":
            system_msg = m["content"]
        else:
            user_msgs.append(m)
    resp = _requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2048,
            "system": system_msg,
            "messages": user_msgs,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_google(api_key: str, model: str, messages: list) -> str:
    system_text = ""
    parts = []
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"]
        else:
            role = "user" if m["role"] == "user" else "model"
            parts.append({"role": role, "parts": [{"text": m["content"]}]})
    body = {"contents": parts}
    if system_text:
        body["systemInstruction"] = {"parts": [{"text": system_text}]}
    body["generationConfig"] = {"maxOutputTokens": 2048, "temperature": 0.3}
    resp = _requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        headers={"Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
