import os
import subprocess
import re
import pickle
import joblib
import numpy as np

from fastapi import FastAPI, Form, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.hash import bcrypt

from database import SessionLocal, User
from pydantic import BaseModel

app = FastAPI()

# --- CORS for frontend-backend communication ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- File Mounts ---
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/templates", StaticFiles(directory="templates"), name="templates")
templates = Jinja2Templates(directory="templates")

# --- Database Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -------------------------
# USER AUTHENTICATION ROUTES
# -------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/signinup", response_class=HTMLResponse)
def show_form(request: Request, next: str = "/services"):
    return templates.TemplateResponse("signinup.html", {"request": request, "next": next})

@app.post("/auth")
def auth(
    request: Request,
    name: str = Form(None),
    email: str = Form(...),
    password: str = Form(...),
    signup: str = Form(None),
    signin: str = Form(None),
    next: str = Form("/services"),
    db: Session = Depends(get_db)
):
    if signup:
        if not name:
            return templates.TemplateResponse("signinup.html", {"request": request, "error": "Name is required for signup.", "next": next})

        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            return templates.TemplateResponse("signinup.html", {"request": request, "error": "Email already exists!", "next": next})

        hashed_password = bcrypt.hash(password)
        new_user = User(name=name, email=email, password=hashed_password)
        db.add(new_user)
        db.commit()
        return RedirectResponse(url=f"/signinup?next={next}", status_code=302)

    if signin:
        user = db.query(User).filter(User.email == email).first()
        if not user or not bcrypt.verify(password, user.password):
            return templates.TemplateResponse("signinup.html", {"request": request, "error": "Invalid credentials!", "next": next})

        response = RedirectResponse(url=next, status_code=302)
        response.set_cookie(key="user", value=user.name, httponly=True)
        return response

    return templates.TemplateResponse("signinup.html", {"request": request, "error": "Unknown action", "next": next})

@app.get("/services", response_class=HTMLResponse)
def services(request: Request):
    username = request.cookies.get("user")
    if not username:
        return RedirectResponse(url="/signinup")
    return templates.TemplateResponse("services.html", {"request": request, "username": username})

# -------------------------
# COLLEGE MAJOR RECOMMENDER ROUTES
# -------------------------

@app.get("/recommend", response_class=HTMLResponse)
async def recommend_form():
    with open("templates/recommend.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

class PromptRequest(BaseModel):
    subjects: str
    hobbies: str
    skills: str
    goals: str
    traits: str
    notes: str = ""

def format_prompt(data: PromptRequest):
    return f"""
You are a helpful academic advisor.

Based on the following high school student information, recommend 3 suitable college majors and explain why each is a good fit.

- Favorite subjects: {data.subjects}
- Hobbies and interests: {data.hobbies}
- Strengths or skills: {data.skills}
- Career goals: {data.goals}
- Personality traits: {data.traits}
- Additional notes: {data.notes}

Respond like this:
1. Major: <Name>
   Reason: <Short explanation>

2. Major: ...
   Reason: ...

3. Major: ...
   Reason: ...
"""

def strip_ansi_codes(text):
    ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', text)

def query_model(prompt: str):
    try:
        model_path = os.path.abspath("models/mistral-7b-instruct-v0.1.Q4_K_M.gguf")
        llama_exe = os.path.abspath("llama-run.exe")

        process = subprocess.Popen(
            [llama_exe, model_path, prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(timeout=120)

        if process.returncode != 0:
            return f"Model error: {stderr.strip()}"

        cleaned_output = strip_ansi_codes(stdout.strip())
        return cleaned_output

    except subprocess.TimeoutExpired:
        process.kill()
        return "Model timed out."

    except Exception as e:
        return f"Error: {str(e)}"

@app.post("/recommend")
async def recommend_api(prompt_request: PromptRequest):
    prompt = format_prompt(prompt_request)
    raw_output = query_model(prompt)
    return {"response": raw_output}

# -------------------------
# SKILLS & GPA PREDICTORS
# -------------------------

model_dir = os.path.join(os.path.dirname(__file__), "models")

with open(os.path.join(model_dir, "model.pkl"), "rb") as f:
    skills_model = pickle.load(f)

with open(os.path.join(model_dir, "mlb.pkl"), "rb") as f:
    mlb = pickle.load(f)

gpa_model = joblib.load(os.path.join(model_dir, "best_rf_model.pkl"))
pipeline = joblib.load(os.path.join(model_dir, "preprocessing_pipeline.pkl"))

all_skills = mlb.classes_

@app.get("/skills", response_class=HTMLResponse)
async def skills_form(request: Request):
    return templates.TemplateResponse("form.html", {"request": request, "skills": all_skills})

@app.post("/skills/predict", response_class=HTMLResponse)
async def skills_predict(request: Request, selected_skills: list[str] = Form(...)):
    input_vector = mlb.transform([selected_skills])
    prediction = skills_model.predict(input_vector)[0]
    return templates.TemplateResponse("result.html", {
        "request": request,
        "prediction": prediction,
        "selected_skills": selected_skills
    })

@app.get("/gpa", response_class=HTMLResponse)
async def gpa_form(request: Request):
    return templates.TemplateResponse("gpa_form.html", {"request": request})

@app.post("/gpa/predict")
async def gpa_predict(
    request: Request,
    Study_Hours_Per_Day: float = Form(...),
    Extracurricular_Hours_Per_Day: float = Form(...),
    Sleep_Hours_Per_Day: float = Form(...),
    Social_Hours_Per_Day: float = Form(...),
    Physical_Activity_Hours_Per_Day: float = Form(...),
    Stress_Level: str = Form(...)
):
    stress_map = {"Low": 0, "Moderate": 1, "High": 2}
    stress_encoded = stress_map.get(Stress_Level, 1)

    input_data = np.array([[Study_Hours_Per_Day, Extracurricular_Hours_Per_Day, Sleep_Hours_Per_Day,
                            Social_Hours_Per_Day, Physical_Activity_Hours_Per_Day, stress_encoded]])
    input_processed = pipeline.transform(input_data)
    prediction = gpa_model.predict(input_processed)[0]

    if prediction >= 3.5:
        gpa_class = "High"
    elif prediction >= 2.0:
        gpa_class = "Moderate"
    else:
        gpa_class = "Low"

    return JSONResponse(content={"gpa": round(prediction, 2), "gpa_class": gpa_class})

# -------------------------
# MAIN ENTRY POINT
# -------------------------

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
