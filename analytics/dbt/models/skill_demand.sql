-- Starter dbt model for the advanced analytics profile.
select lower(trim(skill)) as skill, count(*) as demand
from raw_job_skills
group by 1
order by 2 desc
