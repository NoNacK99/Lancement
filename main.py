# ==========================================================
# 1. IMPORTS (Nettoyés)
# ==========================================================
import httpx
print(f"--- DIAGNOSTIC: Version de httpx réellement installée: {httpx.__version__} ---")

# Imports pour FastAPI
from fastapi import FastAPI, Request, HTTPException, Depends, File, UploadFile, Form, BackgroundTasks
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles

# Imports pour les autres fonctionnalités
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import psycopg
from psycopg import AsyncConnection
import os
import jwt
from datetime import datetime, timedelta
import uuid
import json
from passlib.context import CryptContext
from supabase import create_client, Client

# Import du module d'analyse IA
from ai_analyzer import extract_text_from_file, analyze_business_plan, generate_formatted_report

# ==========================================================
# 2. CONFIGURATION ET INITIALISATION DE FastAPI
# ==========================================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(
    title="Plans d'Affaires API",
    description="API pour soumission et analyse de plans d'affaires avec IA",
    version="2.1.0"
)

# Configuration du dossier des templates (pour les pages HTML)
templates = Jinja2Templates(directory="templates")

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration Sécurité, DB et Supabase
security = HTTPBearer()
SECRET_KEY = os.getenv("JWT_SECRET", "your-secret-key-change-in-prod")
ALGORITHM = "HS256"
DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ==========================================================
# 3. MODÈLES PYDANTIC (Inchangé)
# ==========================================================
class ProfessorLogin(BaseModel):
    email: EmailStr
    password: str

class ProfessorResponse(BaseModel):
    id: str
    email: str
    name: str
    course: str

class SubmissionCreate(BaseModel):
    student_name: str
    student_email: EmailStr
    professor_id: str
    project_title: str

class SubmissionResponse(BaseModel):
    id: str
    student_name: str
    student_email: str
    project_title: str
    status: str
    submission_date: datetime
    file_name: Optional[str]
    score: Optional[int] = None

class AnalysisResponse(BaseModel):
    id: str
    submission_id: str
    report_content: str
    score_global: int
    generated_at: datetime
    processing_time_seconds: Optional[int]


# ==========================================================
# 4. FONCTIONS UTILITAIRES (DB, JWT, IA - Inchangé)
# ==========================================================
async def get_db_connection():
    conn = await AsyncConnection.connect(DATABASE_URL)
    try:
        yield conn
    finally:
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
            raise HTTPException(status_code=401, detail="Token invalide")
        return professor_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

async def process_submission_with_ai(submission_id: str):
    start_time = datetime.now()
    async with await AsyncConnection.connect(DATABASE_URL) as conn:
        try:
            query = "SELECT file_url FROM submissions WHERE id = %s"
            cursor = await conn.execute(query, (submission_id,))
            submission = await cursor.fetchone()
            if not submission: return
            
            file_url = submission[0]
            text = await extract_text_from_file(file_url) 
            # ... la suite de la fonction reste identique
        except Exception as e:
            print(f"❌ Erreur analyse pour {submission_id}: {str(e)}")

# ==========================================================
# 5. ROUTES API
# ==========================================================

# --- A. ROUTES POUR SERVIR LES PAGES HTML (LA BONNE FAÇON) ---

@app.get("/", tags=["Pages HTML"])
async def serve_student_page_at_root(request: Request):
    """Sert la page des étudiants par défaut quand on visite la racine du site."""
    return templates.TemplateResponse("student.html", {"request": request})

@app.get("/student", tags=["Pages HTML"])
async def serve_student_page(request: Request):
    """Sert la page HTML pour la soumission des étudiants."""
    return templates.TemplateResponse("student.html", {"request": request})

@app.get("/api/professors", response_model=List[ProfessorResponse], tags=["Données"])
async def get_all_professors(conn: AsyncConnection = Depends(get_db_connection)):
    """
    Récupère la liste de tous les professeurs depuis la base de données
    pour peupler les menus déroulants sur le frontend.
    """
    try:
        query = "SELECT id, email, name, course FROM professors"
        cursor = await conn.execute(query)
        professors = await cursor.fetchall()
        
        # Convertir les résultats en une liste de dictionnaires
        professors_list = [
            {
                "id": str(row[0]),
                "email": row[1],
                "name": row[2],
                "course": row[3]
            } for row in professors
        ]
        return professors_list
    except Exception as e:
        # En cas d'erreur de base de données, renvoyer une erreur 500
        print(f"❌ Erreur lors de la récupération des professeurs: {e}")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur lors de la récupération des professeurs.")


# --- B. ROUTES POUR LA LOGIQUE MÉTIER (API) ---

@app.post("/auth/login", tags=["Authentification"])
async def login_professor(professor_data: ProfessorLogin, conn: AsyncConnection = Depends(get_db_connection)):
    # ... votre code de login ici ...
    # Pour l'exemple, on retourne une réponse simple
    # Assurez-vous que votre logique de vérification de mot de passe est ici
    return {"access_token": "un_vrai_token_jwt_serait_genere_ici", "token_type": "bearer"}

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
    """Créer une nouvelle soumission, téléverser le fichier sur Supabase et lancer l'analyse IA."""
    if not file.filename.endswith(('.pdf', '.doc', '.docx')):
        raise HTTPException(status_code=400, detail="Format de fichier non supporté. Utilisez PDF ou DOCX.")
    if file.size > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 15MB)")
    
    file_content = await file.read()
    file_extension = file.filename.split('.')[-1]
    unique_filename_in_bucket = f"{uuid.uuid4()}.{file_extension}"
    
    try:
        supabase.storage.from_("lancement").upload(
            path=unique_filename_in_bucket,
            file=file_content,
            file_options={"content-type": file.content_type}
        )
        public_url = supabase.storage.from_("lancement").get_public_url(unique_filename_in_bucket)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du téléversement du fichier: {str(e)}")

    query = """
    INSERT INTO submissions (student_name, student_email, professor_id, project_title, file_url, file_name, file_size, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id, student_name, student_email, project_title, status, submission_date, file_name
    """
    cursor = await conn.execute(
        query, 
        (student_name, student_email, professor_id, project_title, public_url, file.filename, len(file_content), 'pending')
    )
    submission = await cursor.fetchone()
    await conn.commit()
    
    submission_dict = {
        'id': str(submission[0]),
        'student_name': submission[1],
        'student_email': submission[2],
        'project_title': submission[3],
        'status': submission[4],
        'submission_date': submission[5],
        'file_name': submission[6]
    }
    
    background_tasks.add_task(process_submission_with_ai, submission_dict['id'])
    
    return SubmissionResponse(**submission_dict)

# ... (le reste de vos routes, comme /professor/dashboard, etc., restent ici)


# ==========================================================
# 6. LANCEMENT DE L'APPLICATION
# ==========================================================
if __name__ == "__main__":
    import uvicorn
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("SUPABASE_URL"):
        print("⚠️  ATTENTION: Des variables d'environnement sont manquantes (OPENAI_API_KEY, SUPABASE_URL, SUPABASE_KEY)!")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)

