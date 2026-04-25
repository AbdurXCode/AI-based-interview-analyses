from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Any

app = FastAPI()

class Input1Item(BaseModel):
    question_1: str
    answer_1: str
    question_2: str
    answer_2: str
    question_3: str
    answer_3: str
    question_4: str
    answer_4: str

class Input2Item(BaseModel):
    ans_1: str
    ans_2: str
    ans_3: str
    ans_4: str

@app.post("/suggestion")
def get_suggestion(input1: Input1Item, input2: Input2Item):
    return {"input1": input1, "input2": input2}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=8080)
