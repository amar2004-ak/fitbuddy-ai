from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from google import genai  # Ensure you ran: pip install google-genai
import os
import logging
import time
from io import BytesIO

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter

from dotenv import load_dotenv

# Assuming these are in your local directory
from project.database import engine, SessionLocal
from project.models import Base, UserPlan

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Database session dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI()

# Create tables
Base.metadata.create_all(bind=engine)

# Static files & Templates
# Ensure these folders exist in your project root!
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Gemini client initialization
api_key = os.environ.get("GOOGLE_API_KEY")
if not api_key:
    logger.error("GOOGLE_API_KEY not found in environment variables!")
client = genai.Client(api_key=api_key)

# --- Logic Functions ---

def generate_with_retry(prompt: str):
    """Retries the Gemini API call with exponential backoff."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Note: For the 'google-genai' SDK, the syntax is client.models.generate
            response = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt
            )
            
            if not response.text:
                raise ValueError("Empty response from Gemini")
                
            return response.text

        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                # Wait longer each time (10s, 20s)
                time.sleep(10 * (attempt + 1))
            else:
                logger.error("All Gemini retries exhausted.")
                raise e

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/generate", response_class=HTMLResponse)
async def generate_plan(
    request: Request,
    age: int = Form(...),
    weight: float = Form(...),
    height: float = Form(...),
    goal: str = Form(...),
    activity_level: str = Form(...),
    db: Session = Depends(get_db)
):
    prompt = f"""
    Create a detailed 7-day fitness plan for a {age} year old.
    Stats: {weight}kg, {height}cm. Goal: {goal}. Activity Level: {activity_level}.
    Format the response clearly with headings for each day. 
    Include specific workouts, diet tips, and recovery advice.
    """

    try:
        plan_content = generate_with_retry(prompt)

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
        logger.error(f"Error generating plan: {e}")
        # Return a more descriptive error to the user
        raise HTTPException(status_code=500, detail=f"AI Service Error: {str(e)}")

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
    elements = []
    styles = getSampleStyleSheet()

    # Simple text to PDF conversion
    for line in db_obj.plan_text.split("\n"):
        if line.strip():
            elements.append(Paragraph(line, styles["Normal"]))
            elements.append(Spacer(1, 10))

    doc.build(elements)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=fitbuddy_plan.pdf"}
    )