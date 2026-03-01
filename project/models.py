from sqlalchemy import Column, Integer, String, Text
from project.database import Base
class UserPlan(Base):
    __tablename__ = "user_plans"

    id = Column(Integer, primary_key=True, index=True)
    age = Column(Integer)
    weight = Column(Integer)
    height = Column(Integer)
    goal = Column(String)
    activity = Column(String)
    plan_text = Column(Text)