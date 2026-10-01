from contextlib import asynccontextmanager
from datetime import date, timedelta
from io import BytesIO
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pypdf import PdfReader

from .db import Base, engine, SessionLocal, get_db
from .models import Job, Application
from .schemas import ApplicationCreate, ApplicationUpdate, ApplicationOut, MatchRequest, AssistantRequest
from .intelligence import ats_check, match_cv_to_job, aggregate_skills, improvement_suggestions
from .seed import seed
from .assistant import answer

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try: seed(db)
    finally: db.close()
    yield

app = FastAPI(title="JobIntel AI API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health(): return {"status":"ok"}

@app.get("/api/jobs")
def jobs(db: Session = Depends(get_db)):
    return db.query(Job).order_by(Job.match_score.desc()).all()

@app.get("/api/applications", response_model=list[ApplicationOut])
def applications(db: Session = Depends(get_db)):
    return db.query(Application).order_by(Application.created_at.desc()).all()

@app.post("/api/applications", response_model=ApplicationOut)
def add_application(payload: ApplicationCreate, db: Session = Depends(get_db)):
    item = Application(**payload.model_dump())
    db.add(item); db.commit(); db.refresh(item); return item

@app.patch("/api/applications/{application_id}", response_model=ApplicationOut)
def update_application(application_id: int, payload: ApplicationUpdate, db: Session = Depends(get_db)):
    item = db.get(Application, application_id)
    if not item: raise HTTPException(404, "Application not found")
    for k,v in payload.model_dump(exclude_none=True).items(): setattr(item,k,v)
    db.commit(); db.refresh(item); return item

@app.post("/api/cv/ats")
async def cv_ats(file: UploadFile = File(...)):
    raw = await file.read()
    if file.filename and file.filename.lower().endswith(".pdf"):
        reader = PdfReader(BytesIO(raw)); text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        text = raw.decode("utf-8", errors="ignore")
    return ats_check(text)

@app.post("/api/match")
def match(payload: MatchRequest): return match_cv_to_job(payload.cv_text, payload.job_description)

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    jobs = db.query(Job).all(); apps = db.query(Application).all()
    counts = {s: sum(1 for a in apps if a.status == s) for s in ["Saved","Applied","Screening","Interview","Final","Offer","Rejected"]}
    interviews = counts["Interview"] + counts["Final"] + counts["Offer"]
    skill_data = aggregate_skills([j.skills for j in jobs])
    missing = ["kafka","terraform","airflow"]
    return {
      "summary": {"active_jobs":3428,"new_today":186,"applications":len(apps),"interviews":interviews,"offers":counts["Offer"],"ats_score":89},
      "matches": [{"id":j.id,"title":j.title,"company":j.company,"location":j.location,"skills":j.skills.split(","),"match":j.match_score} for j in sorted(jobs,key=lambda x:x.match_score, reverse=True)[:3]],
      "top_skills": skill_data,
      "pipeline": counts,
      "performance": [{"label":"Backend CV","value":36},{"label":"Data CV","value":39},{"label":"Generic CV","value":15}],
      "skill_gap": improvement_suggestions(missing),
      "interview_readiness": {"score":87,"level":"High"},
      "followups": [{"company":a.company,"role":a.role,"status":a.status,"days":5+i} for i,a in enumerate(apps[:3])],
      "ai_suggestions": [
        {"title":"Learn Kafka for higher Data Engineer match","detail":"Add an event-streaming feature to this project."},
        {"title":"Improve German toward B1","detail":"Increase access to German-speaking roles."},
        {"title":"Tailor Backend and Data CV versions","detail":"Track which version converts better."},
        {"title":"Deploy one cloud-ready architecture","detail":"Show infrastructure and operations skills."}
      ]
    }

@app.post("/api/assistant")
async def assistant(payload: AssistantRequest, db: Session = Depends(get_db)):
    context = {"applications":db.query(Application).count(),"top_missing_skills":["Kafka","Airflow","Terraform"]}
    return {"answer": await answer(payload.message, context)}
