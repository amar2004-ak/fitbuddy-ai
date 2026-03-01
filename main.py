from project.database import engine
from project.models import Base
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google import genai
import os
from dotenv import load_dotenv
from project.database import SessionLocal
from project.models import UserPlan
from fastapi import Depends
from sqlalchemy.orm import Session
import logging
from fastapi import HTTPException
from pydantic import BaseModel

# Configure logging
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

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

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
            model='gemini-2.5-flash',
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

        return templates.TemplateResponse(
            request=request, name="plan.html", context={"plan": plan_content}
        )

    except Exception as e:
        logger.error(f"An error occurred while generating the plan: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate fitness plan: {str(e)}")

class FeedbackRequest(BaseModel):
    feedback: str
    previous_plan: str

@app.post("/feedback")
async def regenerate_plan(request: FeedbackRequest):
    logger.info("Feedback regeneration starts")
    try:
        prompt = f"""
        Act as an expert fitness coach. Based on the following user feedback:
        "{request.feedback}"

        Update this previous fitness plan:
        {request.previous_plan}

        Return a revised, highly detailed fitness plan in markdown format. It must continue to include a 7-day structured workout plan, nutrition tips, recovery tips, and safety precautions.
        """
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        logger.info("Feedback regeneration succeeds")
        return {"updated_plan": response.text}
    except Exception as e:
        logger.error(f"An error occurred during feedback regeneration: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to regenerate fitness plan based on feedback: {str(e)}")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
