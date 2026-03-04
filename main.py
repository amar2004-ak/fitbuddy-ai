from fastapi import FastAPI, Request, Form, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session
from google import genai
import os
import logging
import io
import textwrap
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from fastapi.responses import StreamingResponse
from io import BytesIO
from dotenv import load_dotenv

from project.database import engine, SessionLocal
from project.models import Base, UserPlan

# Configure loggingv
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI()
Base.metadata.create_all(bind=engine)
client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))

@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"request": request}
    )

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
    try:
        prompt = f"""
        Act as an expert fitness coach. Create a customized, highly detailed fitness plan using markdown formatting based on the following user details:
        - Age: {age}
        - Weight: {weight} kg
        - Height: {height} cm
        - Objective: {goal}
        - Current Activity Level: {activity_level}

        The plan must include:
        1. A brief motivating introduction with clear headings.
        2. A 7-day structured workout schedule with specific exercises, sets, and reps.
        3. Nutrition tips based on the goal ({goal}).
        4. Recovery tips (e.g., sleep, stretching).
        5. Safety precautions to prevent injury.
        6. A concluding encouraging message.

        Use structured markdown elements such as headings, lists, bold text, and tables to make the plan easy to read and visually appealing.
        """

        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
        )
        plan_content = response.text
        logger.info("Plan generation succeeds")
                
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
        logger.error(f"An error occurred while generating the plan: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate fitness plan: {str(e)}")

@app.get("/plan/{plan_id}", response_class=HTMLResponse)
async def view_plan(request: Request, plan_id: int, db: Session = Depends(get_db)):
    db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()
    if not db_obj:
        raise HTTPException(status_code=404, detail="Plan not found")
        
    return templates.TemplateResponse(
        request=request, name="plan.html", context={"plan": db_obj.plan_text, "plan_id": db_obj.id}
    )

@app.post("/feedback", response_class=HTMLResponse)
async def regenerate_plan(
    request: Request,
    plan_id: int = Form(...),
    feedback_text: str = Form(...),
    db: Session = Depends(get_db)
):
    logger.info("Feedback regeneration starts")
    try:
        # Fetch the previously generated plan from SQLite
        db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()
        if not db_obj:
            raise HTTPException(status_code=404, detail="Plan not found")

        old_plan = db_obj.plan_text
        
        prompt = f"""
        Previous Workout Plan:
        {old_plan}

        User Feedback:
        {feedback_text}

        Generate an improved structured 7-day workout plan.
        """
        
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
        )
        new_plan_content = response.text
        logger.info("Feedback regeneration succeeds")
        
        # Update the database with the improved plan
        db_obj.plan_text = new_plan_content
        db.commit()
        
        # Proper redirect after regeneration
        return RedirectResponse(url=f"/plan/{db_obj.id}", status_code=303)
    except Exception as e:
        logger.error(f"An error occurred during feedback regeneration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to regenerate fitness plan based on feedback: {str(e)}")

@app.get("/download/{plan_id}")
async def download_plan(plan_id: int, db: Session = Depends(get_db)):
    db_obj = db.query(UserPlan).filter(UserPlan.id == plan_id).first()
    if not db_obj:
        return {"error": "Plan not found"}

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []

    styles = getSampleStyleSheet()
    normal_style = styles["Normal"]

    lines = db_obj.plan_text.split("\n")

    for line in lines:
        # Table row detect
        if "|" in line and "---" not in line:
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
            if cells:
                table = Table([cells])
                table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ]))
                elements.append(table)
                elements.append(Spacer(1, 10))
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
        },
    ) 
