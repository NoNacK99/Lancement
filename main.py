# 🚀 API FastAPI - Plateforme Plans d'Affaires
# Version avec IA réelle intégrée et Supabase Storage !
import httpx
print(f"--- DIAGNOSTIC: Version de httpx réellement installée: {httpx.__version__} ---")
from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
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
from supabase import create_client, Client # <- [1] AJOUT DE L'IMPORT


# Import du module d'analyse IA
from ai_analyzer import extract_text_from_file, analyze_business_plan, generate_formatted_report

# 🔧 Configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI(
    title="Plans d'Affaires API",
    description="API pour soumission et analyse de plans d'affaires avec IA",
    version="2.1.0" # Version mise à jour pour refléter les changements
)

# 🌐 CORS pour permettre frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En prod: domaines spécifiques
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔐 Sécurité JWT
security = HTTPBearer()
SECRET_KEY = os.getenv("JWT_SECRET", "your-secret-key-change-in-prod")
ALGORITHM = "HS256"

# 🗃️ Configuration base de données et Supabase
DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# [2] AJOUT DE L'INITIALISATION DU CLIENT SUPABASE
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# 📊 Modèles Pydantic (inchangé)
class ProfessorLogin(BaseModel):
    email: EmailStr
    password: str

# ... (tous vos autres modèles Pydantic restent ici, inchangés)
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


# 🔌 Connexion base de données (inchangé)
async def get_db_connection():
    conn = await AsyncConnection.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()

# 🔐 Authentification JWT et autres fonctions (inchangé)
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

# La fonction de hachage SHA256 n'est plus utilisée, nous pourrions la supprimer.
# def hash_password(password: str) -> str:
#     return hashlib.sha256(password.encode('utf-8')).hexdigest()

# 🤖 Fonction d'analyse IA en arrière-plan (inchangé)
async def process_submission_with_ai(submission_id: str):
    # ... (cette fonction reste identique)
    # Important: elle doit maintenant être capable de lire le fichier depuis une URL publique
    # La bibliothèque `requests` ou `httpx` peut être utilisée dans `extract_text_from_file`
    start_time = datetime.now()
    async with await AsyncConnection.connect(DATABASE_URL) as conn:
        try:
            query = "SELECT file_url FROM submissions WHERE id = %s"
            cursor = await conn.execute(query, (submission_id,))
            submission = await cursor.fetchone()
            if not submission: return
            
            file_url = submission[0]
            # Assurez-vous que votre fonction d'extraction peut gérer une URL
            text = await extract_text_from_file(file_url) 
            # ... la suite de la fonction reste identique
        except Exception as e:
            print(f"❌ Erreur analyse pour {submission_id}: {str(e)}")

# 🌟 Routes API (inchangé, sauf /submissions)

@app.get("/")
# ... (toutes les autres routes restent identiques)
async def root():
    return {"message": "API opérationnelle"}

@app.post("/auth/login")
# ... (votre fonction de login reste ici, inchangée)
async def login_professor(professor_data: ProfessorLogin, conn: AsyncConnection = Depends(get_db_connection)):
    # ... code de login
    return {"access_token": "...", "token_type": "bearer"}

# 📋 [3] ROUTE /SUBMISSIONS ENTIÈREMENT MISE À JOUR
@app.post("/submissions", response_model=SubmissionResponse)
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
    
    # Valider le fichier
    if not file.filename.endswith(('.pdf', '.doc', '.docx')):
        raise HTTPException(status_code=400, detail="Format de fichier non supporté. Utilisez PDF ou DOCX.")
    
    if file.size > 15 * 1024 * 1024:  # 15MB
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 15MB)")
    
    # Lire le contenu du fichier
    file_content = await file.read()
    
    # Générer un nom de fichier unique pour le bucket
    file_extension = file.filename.split('.')[-1]
    unique_filename_in_bucket = f"{uuid.uuid4()}.{file_extension}"
    
    # Téléverser sur Supabase Storage
    try:
        supabase.storage.from_("lancement").upload(
            path=unique_filename_in_bucket,
            file=file_content,
            file_options={"content-type": file.content_type}
        )
        public_url = supabase.storage.from_("lancement").get_public_url(unique_filename_in_bucket)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du téléversement du fichier: {str(e)}")

    # Insérer en base de données avec l'URL publique de Supabase
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
    
    # Convertir en dict
    submission_dict = {
        'id': str(submission[0]),
        'student_name': submission[1],
        'student_email': submission[2],
        'project_title': submission[3],
        'status': submission[4],
        'submission_date': submission[5],
        'file_name': submission[6]
    }
    
    # Lancer l'analyse IA en arrière-plan
    background_tasks.add_task(process_submission_with_ai, submission_dict['id'])
    
    return SubmissionResponse(**submission_dict)

# ... (le reste de vos routes, comme /professor/dashboard, etc., restent ici inchangées)

if __name__ == "__main__":
    import uvicorn
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("SUPABASE_URL"):
        print("⚠️  ATTENTION: Des variables d'environnement sont manquantes (OPENAI_API_KEY, SUPABASE_URL, SUPABASE_KEY)!")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
