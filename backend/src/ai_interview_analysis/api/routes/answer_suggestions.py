from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import json

from ai_interview_analysis.core.settings import get_settings


router = APIRouter()


class AIQA(BaseModel):
    question_1: str | None = None
    answer_1: str | None = None
    question_2: str | None = None
    answer_2: str | None = None
    question_3: str | None = None
    answer_3: str | None = None
    question_4: str | None = None
    answer_4: str | None = None


class UserResponse(BaseModel):
    ans_1: str | None = None
    ans_2: str | None = None
    ans_3: str | None = None
    ans_4: str | None = None


@router.post("/suggest-improvements-in-user's-response")
async def suggest_improvements(user_responses: UserResponse, ai_qa_pairs: AIQA):
    settings = get_settings()
    if not settings.use_openai_legacy_answer_suggestions:
        raise HTTPException(status_code=404, detail="Legacy answer suggestions endpoint disabled.")
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not set")

    client = OpenAI(api_key=settings.openai_api_key)

    ai_qa_pairs_filtered = {k: v for k, v in ai_qa_pairs.model_dump().items() if v is not None}
    user_responses_filtered = {k: v for k, v in user_responses.model_dump().items() if v is not None}

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful technical assistant. Your job is to help the user to improve his answers "
                "based on the model-generated answers. Based on the comparison, Write strengths and improvements "
                "to the user so that the user can improve his response. Please keep the suggestion specific it "
                "shouldn't be very long."
            ),
        },
        {
            "role": "user",
            "content": f"""
Output should be a json. Generate a json with the title "Strengths_and_Improvements_in_user_response" containing the strengths and Improvements for each answers.

model answers: {ai_qa_pairs_filtered}

user answer: {user_responses_filtered}
""",
        },
    ]

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        response_format={"type": "json_object"},
        messages=messages,
        temperature=0.2,
        max_tokens=1024,
        top_p=1,
    )

    return json.loads(response.choices[0].message.content)

