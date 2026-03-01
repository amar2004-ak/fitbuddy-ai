from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from google import genai
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

@app.get("/", response_class=HTMLResponse)
async def read_item(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={}
    )

@app.post("/generate", response_class=HTMLResponse)
async def generate_plan(
    request: Request,
    age: int = Form(...),
    weight: float = Form(...),
    height: float = Form(...),
    goal: str = Form(...),
    activity_level: str = Form(...)
):
    try:
        prompt = f"""
        Act as an expert fitness coach. Create a customized, highly detailed fitness plan using markdown formatting based on the following user details:
        - Age: {age}
        - Weight: {weight} kg
        - Height: {height} cm
        - Objective: {goal}
        - Current Activity Level: {activity_level}

        The plan should include:
        1.  A brief motivating introduction.
        2.  A weekly workout schedule with specific exercises, sets, and reps.
        3.  Nutritional guidelines and suggestions.
        4.  Tips for recovery and consistency.
        5.  A concluding encouraging message.

        Use structured markdown elements such as headings, lists, bold text, and tables to make the plan easy to read and visually appealing.
        """

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        plan_content = response.text

    except Exception as e:
        plan_content = f"An error occurred while generating the plan: {str(e)}"
        print(f"Error: {e}")

    return templates.TemplateResponse(
        request=request, name="plan.html", context={"plan": plan_content}
    )
    @app.get("/")
  def home():
    return {"message": "FitBuddy AI is running 🚀"}
