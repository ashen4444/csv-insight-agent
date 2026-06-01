# backend/app/services/llm_client.py

from openai import OpenAI

from app.core.config import settings


client = OpenAI(api_key=settings.OPENAI_API_KEY)


def generate_text(prompt: str) -> str:
    response = client.responses.create(
        model=settings.OPENAI_MODEL,
        input=prompt,
        temperature=0,
    )

    return response.output_text.strip()