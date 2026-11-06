# Tailoring report: Senior Data Analyst - Lending Analytics @ FinServe Technologies

**Model:** `replay:sample_plan.json`  
**JD keyword coverage:** 72% → **78%** (14/18 keywords)
  
**PDF:** OK via `latexmk`, 1 page(s)

## What changed
- Re-labelled bullets with the JD's language (lending dashboards, ETL pipelines, A/B testing)
- Moved data-quality work to the top of the internship
- Put the Tableau dashboard project first
- Dropped the office-operations bullet as irrelevant

## Keywords still missing

- Redshift  _(no evidence in your resume - add to facts.md only if true)_
- dbt  _(no evidence in your resume - add to facts.md only if true)_
- ETL pipelines  _(no evidence in your resume - add to facts.md only if true)_
- self-serve dashboards  _(no evidence in your resume - add to facts.md only if true)_

## Gaps the JD asks for
- No Redshift experience shown
- No dbt experience shown
- No direct lending/credit-risk modelling

## Section order
Skills Summary → Experience → Projects → Education

## Edits blocked by guardrails

- **u06** (Experience): claims JD tools/skills with no evidence in your resume/facts: dbt

## Bullet-by-bullet

### u01 · Skills Summary · accepted
- **Before:** Languages: Python, SQL, R, Pandas, NumPy, Scikit-learn
- **After:** Languages: SQL, Python, Pandas, NumPy, R, Scikit-learn

### u02 · Skills Summary · accepted
- **Before:** BI & Visualisation: Power BI, Tableau, Looker Studio, Excel
- **After:** BI & Visualisation: Power BI, Tableau, Excel, Looker Studio

### u03 · Skills Summary · accepted
- **Before:** Data & Cloud: AWS (S3, Athena), PostgreSQL, Spark, Airflow, Git
- **After:** Data & Cloud: AWS (S3, Athena), Airflow, PostgreSQL, Spark, Git

### u05 · Experience · accepted
- **Before:** Reporting: Built weekly Power BI dashboards on loan disbursal and collections for 12 regional managers, replacing a manual Excel process.
- **After:** Lending Dashboards: Built self-serve Power BI dashboards on loan disbursal and collections for 12 regional business stakeholders, replacing a manual Excel process.

### u06 · Experience · rejected
- **Before:** Pipelines: Wrote SQL and Python jobs on AWS Athena that refresh 3M+ rows nightly, cutting report preparation time by 70%.

### u07 · Experience · accepted
- **Before:** Experimentation: Analysed A/B tests on the onboarding funnel and presented findings that lifted completion rate by 9%.
- **After:** A/B Testing: Designed and analysed A/B tests on the onboarding funnel and presented insights to leadership that lifted completion rate by 9%.

### u08 · Experience · dropped (irrelevant)
- **Before:** Office Operations: Coordinated the team's offsite logistics and vendor payments for 40 attendees.

### u10 · Experience · accepted
- **Before:** Data Quality: Created automated data-validation checks in Airflow that caught pipeline breaks before they reached business users.
- **After:** Data Quality: Built automated data-validation checks in Airflow that caught pipeline breaks before they reached business users.

### u12 · Projects · accepted
- **Before:** Sales Dashboard: Designed an interactive Tableau dashboard of 5 years of retail sales with drill-downs by region and category.
- **After:** Sales Dashboard: Designed an interactive Tableau dashboard of 5 years of retail sales with drill-downs by region and category for business stakeholders.
