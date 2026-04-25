from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from typing import List, Dict

from fastapi import FastAPI,Depends, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
from openai import OpenAI
import os
import json

app = FastAPI()

class UserResponse(BaseModel):
    Answer_1: str 
    Answer_2: str 
    Answer_3: str 
    Answer_4: str 

class QAItem(BaseModel):
    question_1: str
    answer_1: str
    question_2: str
    answer_2: str
    question_3: str
    answer_3: str
    question_4: str
    answer_4: str


class Inputdata(BaseModel):
    qa_pairs: list[QAItem]
    user_response: list[UserResponse]




@app.post("/process-input/")
async def process_input(input_data: Inputdata):
    user_responses=input_data.user_response
    ai_qa_pairs= input_data.qa_pairs
    # Set up the model
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        response_format={ "type": "json_object" },
        messages=[
            {
            "role": "system",
            "content": "You are a helpful technical assistant. Your job is to help the user to improve his answers based on the model-generated answers. Based on the comparison, Write strengths and improvements to the user so that the user can improve his response. Please keep the suggestion specific it shouldn't be very long."
            },
            {
            "role": "user",
            "content": f"""Output should be a json.Generate a json with the title ""Strengths_and_Improvements_in_user_response" containing the strengths and Improvements for each answers. The overall format should be:\n
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
            model answers:{ai_qa_pairs}\n\n
            user answer:{user_responses}"""
            }
        ],
        temperature=0.2,
        max_tokens=1024,
        top_p=1
        )

    user_response_improvements =json.loads(response.choices[0].message.content)
    print(f"user_response_improvements = {user_response_improvements}")

    return user_response_improvements

  




# Run the application
# Use `uvicorn filename:app --reload` to run this app where filename.py is the name of this Python script
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=9000)