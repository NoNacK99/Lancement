# ==========================================================
# 1. IMPORTS
# ==========================================================
import httpx
import os
import jwt
import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# --- Imports FastAPI ---
from fastapi import FastAPI, Request, HTTPException, Depends, File, UploadFile, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# --- Imports Base de Données & Supabase ---
import psycopg
from psycopg import AsyncConnection
from supabase import create_client, Client

# --- Imports Sécurité & Utilitaires ---
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext

# --- Import du module d'analyse IA ---
from ai_analyzer import extract_text_from_file, analyze_business_plan, generate_formatted_report

# ==========================================================
# 2. CONFIGURATION ET INITIALISATION DE FastAPI
# ==========================================================
print("--- INFO: Démarrage de l'application FastAPI ---")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(
    title="Plans d'Affaires API",
    description="API pour soumission et analyse de plans d'affaires avec IA",
    version="3.1.0" # Version finale avec dashboard
)

templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()
SECRET_KEY = os.getenv("JWT_SECRET", "une-cle-secrete-tres-forte-a-changer")
ALGORITHM = "HS256"
DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("--- INFO: Client Supabase initialisé avec succès. ---")
except Exception as e:
    print(f"--- ERREUR CRITIQUE: Impossible d'initialiser Supabase. {e} ---")


# ==========================================================
# 3. MODÈLES PYDANTIC
# ==========================================================
class ProfessorLogin(BaseModel):
    email: EmailStr
    password: str

class ProfessorResponse(BaseModel):
    id: str
    email: str
    name: str
    course: str

class SubmissionResponse(BaseModel):
    id: str
    student_name: str
    student_email: str
    project_title: str
    status: str
    submission_date: datetime
    file_name: Optional[str] = None
    score: Optional[int] = None
# Ajoutez simplement ceci à la fin de votre section de modèles
class AnalysisReportResponse(BaseModel):
    report_html: str
# ==========================================================
# 4. FONCTIONS UTILITAIRES
# ==========================================================
async def get_db_connection():
    try:
        conn = await AsyncConnection.connect(DATABASE_URL)
        yield conn
    finally:
        if 'conn' in locals() and conn and not conn.closed:
            await conn.close()

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_professor(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        professor_id: str = payload.get("sub")
        if professor_id is None:
            raise HTTPException(status_code=401, detail="Token invalide ou expiré")
        return professor_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")

async def process_submission_with_ai(submission_id: str):
    start_time = datetime.now()
    async with await AsyncConnection.connect(DATABASE_URL) as conn:
        try:
            query = "SELECT file_url, student_name, project_title FROM submissions WHERE id = %s"
            cursor = await conn.execute(query, (submission_id,))
            submission = await cursor.fetchone()
            if not submission: return

            file_url, student_name, project_title = submission
            text = await extract_text_from_file(file_url)
            analysis_results = await analyze_business_plan(text, student_name, project_title)

            processing_time = (datetime.now() - start_time).seconds
            report_content = generate_formatted_report(analysis_results, student_name, project_title, processing_time)
            
            score = analysis_results.get('score_global', 0)
            analysis_id = str(uuid.uuid4())

            insert_query = """
                INSERT INTO analyses (id, submission_id, report_content, score_global, generated_at, processing_time_seconds)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            await conn.execute(insert_query, (analysis_id, submission_id, report_content, score, datetime.now(), processing_time))
            
            update_query = "UPDATE submissions SET status = 'completed', score = %s WHERE id = %s"
            await conn.execute(update_query, (score, submission_id))
            await conn.commit()
            print(f"--- INFO: Analyse pour {submission_id} terminée avec succès. ---")

        except Exception as e:
            print(f"--- ERREUR CRITIQUE dans la tâche de fond pour {submission_id}: {e} ---")
            update_query = "UPDATE submissions SET status = 'error' WHERE id = %s"
            await conn.execute(update_query, (submission_id,))
            await conn.commit()

# ==========================================================
# 5. ROUTES API
# ==========================================================
# --- NOUVELLE ROUTE POUR LE RAPPORT D'ANALYSE ---
@app.get("/api/analysis/{submission_id}", response_model=AnalysisReportResponse, tags=["Rapport d'Analyse"])
async def get_analysis_report(
    submission_id: str,
    conn: AsyncConnection = Depends(get_db_connection),
    professor_id: str = Depends(get_current_professor) # Route protégée
):
    """
    Récupère le rapport d'analyse HTML pour une soumission spécifique.
    Vérifie que la soumission appartient bien au professeur connecté.
    """
    try:
        # 1. Sécurité : On vérifie que le professeur connecté a bien le droit de voir ce rapport
        check_query = "SELECT id FROM submissions WHERE id = %s AND professor_id = %s"
        cursor = await conn.execute(check_query, (submission_id, professor_id))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Rapport non trouvé ou accès non autorisé.")

        # 2. On récupère le contenu du rapport depuis la table 'analyses'
        report_query = "SELECT report_content FROM analyses WHERE submission_id = %s"
        cursor = await conn.execute(report_query, (submission_id,))
        report = await cursor.fetchone()
        
        if not report or not report[0]:
            raise HTTPException(status_code=404, detail="Le rapport d'analyse n'est pas encore disponible.")
            
        return {"report_html": report[0]}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Erreur récupération du rapport pour {submission_id}: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.")
# --- A. ROUTES POUR SERVIR LES PAGES HTML ---
@app.get("/", tags=["Pages HTML"])
async def serve_student_page_at_root(request: Request):
    return templates.TemplateResponse("student.html", {"request": request})

@app.get("/student", tags=["Pages HTML"])
async def serve_student_page(request: Request):
    return templates.TemplateResponse("student.html", {"request": request})

@app.get("/professor", tags=["Pages HTML"])
async def serve_professor_page(request: Request):
    return templates.TemplateResponse("professor.html", {"request": request})

# --- B. ROUTES POUR LES DONNÉES ET ACTIONS ---
@app.get("/api/professors", response_model=List[ProfessorResponse], tags=["Données"])
async def get_all_professors(conn: AsyncConnection = Depends(get_db_connection)):
    try:
        cursor = await conn.execute("SELECT id, email, name, course FROM professors")
        professors = await cursor.fetchall()
        return [{"id": str(row[0]), "email": row[1], "name": row[2], "course": row[3]} for row in professors]
    except Exception as e:
        raise HTTPException(status_code=500, detail="Erreur interne du serveur")

@app.post("/auth/login", tags=["Authentification"])
async def login_professor(professor_data: ProfessorLogin, conn: AsyncConnection = Depends(get_db_connection)):
    """Authentifie le professeur et renvoie un token JWT."""
    try:
        print(f"🔍 Tentative de login pour: {professor_data.email}")
        auth_response = supabase.auth.sign_in_with_password({
            "email": professor_data.email, "password": professor_data.password
        })

        if not auth_response or not auth_response.user:
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect via Supabase Auth")

        print(f"✅ User authentifié via Supabase: {auth_response.user.email}")
        
        query = "SELECT id, name, course FROM professors WHERE email = %s"
        cursor = await conn.execute(query, (professor_data.email,))
        professor = await cursor.fetchone()
        
        if not professor:
            raise HTTPException(status_code=404, detail="Professeur non trouvé dans la base de données locale")
        
        professor_id = str(professor[0])
        access_token = create_access_token(data={"sub": professor_id})
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "professor": {
                "id": professor_id,
                "email": professor_data.email,
                "name": professor[1],
                "course": professor[2]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Erreur login: {str(e)}")
        raise HTTPException(status_code=401, detail=f"Erreur d'authentification: {e}")

# --- LA ROUTE POUR LE TABLEAU DE BORD ---
@app.get("/api/professor/dashboard", tags=["Tableau de Bord Professeur"])
async def get_professor_dashboard(
    conn: AsyncConnection = Depends(get_db_connection),
    professor_id: str = Depends(get_current_professor)
):
    """Récupère toutes les soumissions associées au professeur connecté."""
    try:
        query = """
            SELECT s.id, s.student_name, s.student_email, s.project_title, s.submission_date, s.status, s.score
            FROM submissions s
            WHERE s.professor_id = %s
            ORDER BY s.submission_date DESC;
        """
        cursor = await conn.execute(query, (professor_id,))
        submissions = await cursor.fetchall()
        return [{"id": str(row[0]), "student_name": row[1], "student_email": row[2], "project_title": row[3], "submission_date": row[4], "status": row[5], "score": row[6]} for row in submissions]
    except Exception as e:
        print(f"❌ Erreur récupération tableau de bord: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.")

@app.post("/submissions", response_model=SubmissionResponse, tags=["Soumissions"])
async def create_submission(
    background_tasks: BackgroundTasks,
    student_name: str = Form(...),
    student_email: str = Form(...),
    professor_id: str = Form(...),
    project_title: str = Form(...),
    file: UploadFile = File(...),
    conn: AsyncConnection = Depends(get_db_connection)
):
    if not file.filename.endswith(('.pdf', '.doc', '.docx')):
        raise HTTPException(status_code=400, detail="Format de fichier non supporté.")
    if file.size > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 15MB)")
    
    file_content = await file.read()
    file_extension = file.filename.split('.')[-1]
    unique_filename_in_bucket = f"{uuid.uuid4()}.{file_extension}"
    
    public_url = ""
    try:
        supabase.storage.from_("lancement").upload(
            path=unique_filename_in_bucket, file=file_content, file_options={"content-type": file.content_type}
        )
        public_url = supabase.storage.from_("lancement").get_public_url(unique_filename_in_bucket)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur Supabase: {str(e)}")

    try:
        query = """
        INSERT INTO submissions (student_name, student_email, professor_id, project_title, file_url, file_name, file_size, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, student_name, student_email, project_title, status, submission_date, file_name, score
        """
        cursor = await conn.execute(
            query, (student_name, student_email, professor_id, project_title, public_url, file.filename, len(file_content), 'pending')
        )
        submission = await cursor.fetchone()
        await conn.commit()
        
        submission_dict = {
            'id': str(submission[0]), 'student_name': submission[1], 'student_email': submission[2],
            'project_title': submission[3], 'status': submission[4], 'submission_date': submission[5],
            'file_name': submission[6], 'score': submission[7]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur base de données: {str(e)}")

    background_tasks.add_task(process_submission_with_ai, submission_dict['id'])
    return SubmissionResponse(**submission_dict)

# ==========================================================
# 6. POINT D'ENTRÉE POUR LE LANCEMENT
# ==========================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
