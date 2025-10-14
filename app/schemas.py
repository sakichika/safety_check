from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime


# --- Public ---
class ReportIn(BaseModel):
    email: Optional[str] = None # if no magic token flow
    status: str = Field(pattern="^(safe|evacuating|need_help|unknown)$")
    shelter_name: Optional[str] = None
    shelter_type: Optional[str] = None
    shelter_addr: Optional[str] = None
    shelter_lat: Optional[float] = None
    shelter_lng: Optional[float] = None
    damage_level: Optional[str] = None
    damage_notes: Optional[str] = None


class ReportOut(BaseModel):
    incident_id: str
    user_id: str
    status: str
    updated_at: datetime


# --- Admin ---
class IncidentCreate(BaseModel):
    code: str
    title: str
    description: Optional[str] = None
    kind: str = "live"


class IncidentOut(BaseModel):
    id: str
    code: str
    title: str
    status: str
    started_at: datetime


class UserIn(BaseModel):
    email: str
    name: str
    dept: Optional[str] = None
    phone: Optional[str] = None
    group_name: Optional[str] = None
    is_active: bool = True


class Absentee(BaseModel):
    id: str
    name: str
    email: str
    group_name: Optional[str] = None


class SummaryItem(BaseModel):
    status: str
    n: int


class SummaryOut(BaseModel):
    total_roster: int
    counts: List[SummaryItem]
    by_group: Dict[str, List[SummaryItem]]