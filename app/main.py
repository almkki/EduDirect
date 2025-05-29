from fastapi import FastAPI, Form, Request, Depends
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import SessionLocal, User
from passlib.hash import bcrypt
import pickle
import joblib
import numpy as np
import os


app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- User Authentication Routes ---

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
        if not user:
            return templates.TemplateResponse("signinup.html", {"request": request, "error": "User not found!", "next": next})

        if not bcrypt.verify(password, user.password):
            return templates.TemplateResponse("signinup.html", {"request": request, "error": "Invalid password!", "next": next})

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

# --- AI Model Integration ---

# Define the models directory (relative to this script)
model_dir = os.path.join(os.path.dirname(__file__), "models")

# Load skills prediction model and MultiLabelBinarizer
with open(os.path.join(model_dir, "model.pkl"), "rb") as f:
    skills_model = pickle.load(f)

with open(os.path.join(model_dir, "mlb.pkl"), "rb") as f:
    mlb = pickle.load(f)

# Load GPA prediction model and preprocessing pipeline
gpa_model = joblib.load(os.path.join(model_dir, "best_rf_model.pkl"))
pipeline = joblib.load(os.path.join(model_dir, "preprocessing_pipeline.pkl"))

# --- Skills Prediction Routes ---
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

# --- GPA Prediction Routes ---

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
