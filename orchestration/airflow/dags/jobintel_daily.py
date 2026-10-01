from datetime import datetime
try:
    from airflow import DAG
    from airflow.operators.python import PythonOperator
except ImportError:
    DAG = None

def validate_jobs():
    print("Validate, deduplicate, normalize and aggregate job data")

if DAG:
    with DAG("jobintel_daily", start_date=datetime(2026,1,1), schedule="0 2 * * *", catchup=False) as dag:
        PythonOperator(task_id="validate_jobs", python_callable=validate_jobs)
