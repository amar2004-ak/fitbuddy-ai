import os
import logging
import time
from io import BytesIO

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from google import genai
from google.genai import types  # Required for API versioning fix
from dotenv import load_dotenv

# PDF Generation Imports
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter

# Local Project Imports
from project.database import engine, SessionLocal
from project.models import Base, UserPlan

# Initialize Environment and Logging
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create Database Tables
Base.metadata.create_all(bind=engine)

app = FastAPI()

# Mount Static and Templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- CRITICAL FIX: FORCING STABLE API VERSION ---
# This resolves the 404 NOT_FOUND error seen in Render logs
client = genai.Client(
    api_key=os.environ.get("GOOGLE_API_KEY"),
    http_options=types.HttpOptions(api_version='v1')
)

# Database Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Gemini Generation with Retry Logic
def generate_with_retry(prompt: str):
    """Attempts to generate content with a brief delay on failure."""
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-1.5-flash", 
                contents=prompt
            )
            if response.text:
                return response.text
        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed: {e}")
            # Short sleep to prevent Render timeout during retries
            time.sleep(2) 
            
    raise Exception("Gemini API failed after 3 attempts. Please check your API key and quota.")

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/generate")
async def generate_plan(
    age: int = Form(...),
    weight: float = Form(...),
    height: float = Form(...),
    goal: str = Form(...),
    activity_level: str = Form(...),
    db: Session = Depends(get_db)
):
    prompt = (
        f"Create a professional 7-day fitness plan for a {age} year old. "
        f"Stats: {weight}kg, {height}cm. Goal: {goal}. Activity Level: {activity_level}. "
        f"Include specific workouts and daily nutrition tips."
    )
    
    try:
        # Generate plan from AI
        plan_content = generate_with_retry(prompt)

        # Save to Database
        db_obj = UserPlan(
            age=age,
            weight=weight,
            height=height,
            goal=goal,
            activity=activity_level,
            plan_text=plan_content
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)

        return RedirectResponse(url=f"/plan/{db_obj.id}", status_code=303)

    except Exception as e:
        logger.error(f"Generation error: {e}")
        # Return the error message to the UI
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/plan/{plan_id}", response_class=HTMLResponse)
async def view_plan(request: Request, plan_id: int, db: Session = Depends(get_db)):
    db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Plan not found")

    return templates.TemplateResponse(
        "plan.html", 
        {"request": request, "plan": db_obj.plan_text, "plan_id": db_obj.id}
    )

@app.get("/download/{plan_id}")
async def download_plan(plan_id: int, db: Session = Depends(get_db)):
    db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()
    if not db_obj:
        raise HTTPException(status_code=404)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    
    elements = [Paragraph(f"FitBuddy: 7-Day {db_obj.goal} Plan", styles['Title'])]
    
    # Format the text for the PDF
    for line in db_obj.plan_text.split('\n'):
        if line.strip():
            elements.append(Paragraph(line, styles['Normal']))
            elements.append(Spacer(1, 10))

    doc.build(elements)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=fitbuddy_plan_{plan_id}.pdf"}
    )