from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from google import genai
import os
import logging
import time
from io import BytesIO

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter

from dotenv import load_dotenv

from project.database import engine, SessionLocal
from project.models import Base, UserPlan

# logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

Base.metadata.create_all(bind=engine)

# Gemini client
client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
logger.info("API KEY loaded: %s", bool(os.environ.get("GOOGLE_API_KEY")))


# Home
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


# Gemini retry wrapper
def generate_with_retry(prompt: str):

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt
            )
            return response.text

        except Exception as e:
            logger.error(f"Gemini error: {e}")
            time.sleep(15)

    raise Exception("Gemini API failed after retries")


# Generate plan
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
Create a 7 day fitness plan.

Age: {age}
Weight: {weight}
Height: {height}
Goal: {goal}
Activity level: {activity_level}

Include workouts, diet tips and recovery advice.
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
        raise HTTPException(status_code=500, detail=str(e))


# View plan
@app.get("/plan/{plan_id}", response_class=HTMLResponse)
async def view_plan(request: Request, plan_id: int, db: Session = Depends(get_db)):

    db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()

    if not db_obj:
        raise HTTPException(status_code=404)

    return templates.TemplateResponse(
        "plan.html",
        {"request": request, "plan": db_obj.plan_text, "plan_id": db_obj.id}
    )


# Regenerate plan
@app.post("/feedback", response_class=HTMLResponse)
async def regenerate_plan(
    request: Request,
    plan_id: int = Form(...),
    feedback_text: str = Form(...),
    db: Session = Depends(get_db)
):

    db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()

    if not db_obj:
        raise HTTPException(status_code=404)

    prompt = f"""
Previous plan:
{db_obj.plan_text}

User feedback:
{feedback_text}

Generate improved 7 day workout plan.
"""

    new_plan = generate_with_retry(prompt)

    db_obj.plan_text = new_plan
    db.commit()

    return RedirectResponse(url=f"/plan/{db_obj.id}", status_code=303)


# Download PDF
@app.get("/download/{plan_id}")
async def download_plan(plan_id: int, db: Session = Depends(get_db)):

    db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()

    if not db_obj:
        raise HTTPException(status_code=404)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)

    elements = []
    styles = getSampleStyleSheet()

    for line in db_obj.plan_text.split("\n"):

        if "|" in line and "---" not in line:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            table = Table([cells])
            table.setStyle(TableStyle([
                ('GRID', (0,0), (-1,-1), 1, colors.black)
            ]))
            elements.append(table)
            elements.append(Spacer(1,10))

        else:
            elements.append(Paragraph(line, styles["Normal"]))
            elements.append(Spacer(1,10))

    doc.build(elements)

    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=fitbuddy_{plan_id}.pdf"
        }
    )