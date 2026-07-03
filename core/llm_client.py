import json
import os

import httpx

API_KEY = os.getenv("LLM_API_KEY", "AQVNwqXsNnE8tVQMkNq5f-6-oGBiduFg7FLxHqFv")
FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "b1ggusvist6c2sia1dno")
MODEL_URI = f"gpt://{FOLDER_ID}/yandexgpt/latest"


async def ask_llm_json(system_prompt: str, user_text: str) -> str:
    url = "https://llm.api.cloud.yandex.net/v1/chat/completions"
    headers = {"Authorization": f"Api-Key {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL_URI,
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_text}],
        "temperature": 0.1,
        "max_tokens": 4000,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, headers=headers, json=payload, timeout=60.0)
            if response.status_code == 200:
                res_json = response.json()
                text = res_json["choices"][0]["message"]["content"]

                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0].strip()
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0].strip()

                return text
        except Exception:
            pass
    return "{}"
