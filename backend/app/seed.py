from sqlalchemy.orm import Session
from .models import Job, Application

def seed(db: Session):
    if db.query(Job).count() == 0:
        db.add_all([
            Job(title="Data Engineer", company="Bosch", location="Stuttgart", skills="Python,AWS,SQL,Kafka,Airflow", match_score=91),
            Job(title="Backend Engineer", company="Zalando", location="Berlin (Hybrid)", skills="Python,FastAPI,Kubernetes,AWS", match_score=88),
            Job(title="Automation Engineer", company="Siemens", location="Munich (Hybrid)", skills="Python,Docker,Playwright,SQL", match_score=86),
            Job(title="Data Platform Engineer", company="Example GmbH", location="Berlin", skills="Python,Kafka,Airflow,Terraform,dbt", match_score=84),
        ])
    if db.query(Application).count() == 0:
        db.add_all([
            Application(company="SAP", role="Data Engineer", status="Applied", match_score=84, cv_version="Data Engineer CV v3"),
            Application(company="Bosch", role="Backend Engineer", status="Interview", match_score=88, cv_version="Backend CV v2"),
            Application(company="Example GmbH", role="Data Platform Engineer", status="Screening", match_score=82, cv_version="Data Engineer CV v3"),
        ])
    db.commit()
