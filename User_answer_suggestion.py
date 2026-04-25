from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict
from openai import OpenAI
import os
import json

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "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"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

class AIQA(BaseModel):
    question_1: str = None
    answer_1: str = None
    question_2: str = None
    answer_2: str = None
    question_3: str = None
    answer_3: str = None
    question_4: str = None
    answer_4: str = None

class UserResponse(BaseModel):
    ans_1: str = None
    ans_2: str = None
    ans_3: str = None
    ans_4: str = None

@app.post("/suggest-improvements-in-user's-response")
async def compare_and_suggest_improvements(user_responses: UserResponse, ai_qa_pairs: AIQA):
    ai_qa_pairs_dict = ai_qa_pairs.dict()
    user_responses_dict = user_responses.dict()
    
    # Filter out None values from the dicts
    ai_qa_pairs_filtered = {k: v for k, v in ai_qa_pairs_dict.items() if v is not None}
    user_responses_filtered = {k: v for k, v in user_responses_dict.items() if v is not None}
    
    # Prepare the messages for the API call
    messages = [
        {
            "role": "system",
            "content": "You are a helpful technical assistant. Your job is to help the user to improve his answers based on the model-generated answers. Based on the comparison, Write strengths and improvements to the user so that the user can improve his response. Please keep the suggestion specific it shouldn't be very long."
        },
        {
            "role": "user",
            "content": f"""
            Output should be a json. Generate a json with the title ""Strengths_and_Improvements_in_user_response"" containing the strengths and Improvements for each answers. The overall format should be:\n
            {{
            "Strengths_and_Improvements_in_user_response": [
                {{
                "Strengths_answer_1": "model generated strengths"
                "Improvements_answer_1": "model generated Improvements"
                }},
                 {{
                "Strengths_answer_2": "model generated strengths"
                "Improvements_answer_2": "model generated Improvements"
                }}
            ]
            }}\n.
            model answers:{ai_qa_pairs_filtered}\n\n
            user answer:{user_responses_filtered}"""
        }
    ]
    
    # Set up the model
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        response_format={ "type": "json_object" },
        messages=messages,
        temperature=0.2,
        max_tokens=1024,
        top_p=1
    )

    user_response_improvements = json.loads(response.choices[0].message.content)
    print(f"user_response_improvements = {user_response_improvements}")

    return user_response_improvements

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=9000)
