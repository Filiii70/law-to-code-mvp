from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from database import Base

class UseCase(Base):
    __tablename__ = "usecases"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    system_name = Column(String(255))
    purpose = Column(Text)
    context = Column(Text)
    data_used = Column(Text)
    safeguards = Column(Text)
    extra_details = Column(Text)
    record_hash = Column(String(255), index=True)
