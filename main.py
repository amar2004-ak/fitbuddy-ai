from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from google import genai
from google.genai.errors import ClientError
import os
import logging
from io import BytesIO
from dotenv import load_dotenv

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors

from project.database import engine, SessionLocal
from project.models import Base, UserPlan


# ---------------- LOGGING ----------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------- ENV ----------------
load_dotenv()

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
logger.info("API KEY loaded: %s", bool(os.environ.get("GEMINI_API_KEY")))


# ---------------- FASTAPI SETUP ----------------
app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

Base.metadata.create_all(bind=engine)


# ---------------- DATABASE ----------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------- HOME ----------------
@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


# ---------------- GENERATE PLAN ----------------
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

    logger.info("Plan generation starts")

    # -------- CACHE CHECK --------
    existing_plan = db.query(UserPlan).filter(
        UserPlan.age == age,
        UserPlan.weight == weight,
        UserPlan.height == height,
        UserPlan.goal == goal,
        UserPlan.activity == activity_level
    ).first()

    if existing_plan:
        logger.info("Returning cached plan")
        return RedirectResponse(url=f"/plan/{existing_plan.id}", status_code=303)

    try:

        prompt = f"""
Act as an expert fitness coach.

User details:
Age: {age}
Weight: {weight} kg
Height: {height} cm
Goal: {goal}
Activity Level: {activity_level}

Create a structured 7-day workout plan including:

1. Short motivating introduction
2. Weekly workout schedule with sets and reps
3. Nutrition tips
4. Recovery tips
5. Safety precautions
6. Encouraging conclusion

Format using markdown headings and lists.
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        plan_content = response.text

        logger.info("Plan generation success")

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

    except ClientError as e:

        logger.error(f"Gemini API error: {str(e)}")

        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            raise HTTPException(
                status_code=429,
                detail="AI service quota exceeded. Please try later."
            )

        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:

        logger.error(f"Unexpected error: {str(e)}")

        raise HTTPException(
            status_code=500,
            detail="Failed to generate fitness plan"
        )


# ---------------- VIEW PLAN ----------------
@app.get("/plan/{plan_id}", response_class=HTMLResponse)
async def view_plan(request: Request, plan_id: int, db: Session = Depends(get_db)):

    db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()

    if not db_obj:
        raise HTTPException(status_code=404, detail="Plan not found")

    return templates.TemplateResponse(
        "plan.html",
        {
            "request": request,
            "plan": db_obj.plan_text,
            "plan_id": db_obj.id
        }
    )


# ---------------- FEEDBACK REGENERATE ----------------
@app.post("/feedback", response_class=HTMLResponse)
async def regenerate_plan(
    request: Request,
    plan_id: int = Form(...),
    feedback_text: str = Form(...),
    db: Session = Depends(get_db)
):

    logger.info("Feedback regeneration starts")

    try:

        db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()

        if not db_obj:
            raise HTTPException(status_code=404, detail="Plan not found")

        old_plan = db_obj.plan_text

        prompt = f"""
Previous workout plan:

{old_plan}

User feedback:

{feedback_text}

Generate an improved 7-day workout plan.
"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        new_plan = response.text

        db_obj.plan_text = new_plan
        db.commit()

        logger.info("Plan regenerated")

        return RedirectResponse(url=f"/plan/{db_obj.id}", status_code=303)

    except Exception as e:

        logger.error(f"Regeneration error: {str(e)}")

        raise HTTPException(
            status_code=500,
            detail="Failed to regenerate plan"
        )


# ---------------- DOWNLOAD PDF ----------------
@app.get("/download/{plan_id}")
async def download_plan(plan_id: int, db: Session = Depends(get_db)):

    db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()

    if not db_obj:
        raise HTTPException(status_code=404, detail="Plan not found")

    buffer = BytesIO()

    doc = SimpleDocTemplate(buffer, pagesize=letter)

    elements = []

    styles = getSampleStyleSheet()
    normal_style = styles["Normal"]

    lines = db_obj.plan_text.split("\n")

    for line in lines:

        if "|" in line and "---" not in line:

            cells = [cell.strip() for cell in line.split("|") if cell.strip()]

            table = Table([cells])

            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]))

            elements.append(table)

        else:

            elements.append(Paragraph(line, normal_style))

        elements.append(Spacer(1, 10))

    doc.build(elements)

    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=fitbuddy_plan_{plan_id}.pdf"
        }
    )