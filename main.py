# 🚀 API FastAPI - Plateforme Plans d'Affaires
# Version basique pour commencer zen !

from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import asyncpg
import os
import hashlib
import jwt
from datetime import datetime, timedelta
import aiofiles
import uuid

# 🔧 Configuration
app = FastAPI(
    title="Plans d'Affaires API",
    description="API pour soumission et analyse de plans d'affaires",
    version="1.0.0"
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

# 🗃️ Configuration base de données - VOTRE SUPABASE
SUPABASE_URL = "https://pkzomtcfhtuwn1kgnwzl.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBrem9tdGNmaHR1d25sa2dud3psIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTAzNTIxODcsImV4cCI6MjA2NTkyODE4N30.w51J0wqAzykhVOzgWUXFCRwiidYvvnJkyq6Si7nmvwY"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBrem9tdGNmaHR1d25sa2dud3psIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1MDM1MjE4NywiZXhwIjoyMDY1OTI4MTg3fQ.ajeBbLMAnFTXsr-5MH2cqTrglFsduXFqOyrFo1asLSQ"

# Connection string - VOTRE SUPABASE COMPLÈTE
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:hxJejwD9bhIQs2ht@db.pkzomtcfhtuwn1kgnwzl.supabase.co:5432/postgres")

# 📊 Modèles Pydantic
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

class AnalysisResponse(BaseModel):
    id: str
    submission_id: str
    report_content: str
    generated_at: datetime
    processing_time_seconds: Optional[int]

# 🔌 Connexion base de données
async def get_db_connection():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()

# 🔐 Authentification JWT
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

# 🔧 Utilitaires
def hash_password(password: str) -> str:
    return hashlib.pbkdf2_hex(password.encode('utf-8'), b'salt', 100000)

# 🌟 Routes API

@app.get("/")
async def root():
    return {
        "message": "🚀 API Plans d'Affaires - Version 1.0",
        "status": "✅ Opérationnelle",
        "endpoints": {
            "login": "/auth/login",
            "submissions": "/submissions",
            "dashboard": "/professor/dashboard"
        }
    }

@app.get("/health")
async def health_check():
    """Check de santé de l'API"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}

# 🔐 Authentification
@app.post("/auth/login")
async def login_professor(professor_data: ProfessorLogin):
    """Login professeur"""
    async with get_db_connection().__anext__() as conn:
        # Vérifier le professeur
        query = """
        SELECT id, email, password_hash, name, course 
        FROM professors 
        WHERE email = $1
        """
        professor = await conn.fetchrow(query, professor_data.email)
        
        if not professor:
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
        
        # Vérifier le mot de passe (simplifié pour démo)
        # En prod: utiliser bcrypt ou argon2
        password_hash = hash_password(professor_data.password)
        if professor['password_hash'] != password_hash:
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
        
        # Créer token JWT
        access_token = create_access_token(data={"sub": str(professor['id'])})
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "professor": {
                "id": str(professor['id']),
                "email": professor['email'],
                "name": professor['name'],
                "course": professor['course']
            }
        }

# 📋 Soumissions
@app.post("/submissions", response_model=SubmissionResponse)
async def create_submission(
    student_name: str = Form(...),
    student_email: str = Form(...),
    professor_id: str = Form(...),
    project_title: str = Form(...),
    file: UploadFile = File(...)
):
    """Créer une nouvelle soumission"""
    
    # Valider le fichier
    if not file.filename.endswith(('.pdf', '.doc', '.docx')):
        raise HTTPException(status_code=400, detail="Format de fichier non supporté")
    
    if file.size > 15 * 1024 * 1024:  # 15MB
        raise HTTPException(status_code=400, detail="Fichier trop volumineux")
    
    # Générer nom de fichier unique
    file_extension = file.filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    
    # Sauvegarder le fichier (simplifié - en prod: cloud storage)
    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = f"{upload_dir}/{unique_filename}"
    
    async with aiofiles.open(file_path, 'wb') as f:
        content = await file.read()
        await f.write(content)
    
    # Insérer en base
    async with get_db_connection().__anext__() as conn:
        query = """
        INSERT INTO submissions (student_name, student_email, professor_id, project_title, file_url, file_name, file_size)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id, student_name, student_email, project_title, status, submission_date, file_name
        """
        submission = await conn.fetchrow(
            query, 
            student_name, 
            student_email, 
            professor_id, 
            project_title, 
            file_path, 
            file.filename, 
            len(content)
        )
        
        return SubmissionResponse(**dict(submission))

@app.get("/professor/dashboard")
async def get_professor_dashboard(professor_id: str = Depends(get_current_professor)):
    """Dashboard professeur avec toutes ses soumissions"""
    async with get_db_connection().__anext__() as conn:
        query = """
        SELECT 
            s.id,
            s.student_name,
            s.student_email,
            s.project_title,
            s.status,
            s.submission_date,
            s.file_name,
            a.generated_at as analysis_completed_at,
            a.processing_time_seconds
        FROM submissions s
        LEFT JOIN analyses a ON s.id = a.submission_id
        WHERE s.professor_id = $1
        ORDER BY s.submission_date DESC
        """
        submissions = await conn.fetch(query, professor_id)
        
        # Stats
        total = len(submissions)
        completed = len([s for s in submissions if s['analysis_completed_at']])
        processing = len([s for s in submissions if s['status'] == 'processing'])
        
        return {
            "stats": {
                "total_submissions": total,
                "completed_analyses": completed,
                "processing": processing,
                "pending": total - completed - processing
            },
            "submissions": [dict(s) for s in submissions]
        }

@app.get("/submissions/{submission_id}/analysis")
async def get_analysis(submission_id: str, professor_id: str = Depends(get_current_professor)):
    """Récupérer l'analyse d'une soumission"""
    async with get_db_connection().__anext__() as conn:
        # Vérifier que la soumission appartient au professeur
        query_check = """
        SELECT id FROM submissions 
        WHERE id = $1 AND professor_id = $2
        """
        submission = await conn.fetchrow(query_check, submission_id, professor_id)
        if not submission:
            raise HTTPException(status_code=404, detail="Soumission non trouvée")
        
        # Récupérer l'analyse
        query_analysis = """
        SELECT id, submission_id, report_content, generated_at, processing_time_seconds
        FROM analyses 
        WHERE submission_id = $1
        """
        analysis = await conn.fetchrow(query_analysis, submission_id)
        if not analysis:
            raise HTTPException(status_code=404, detail="Analyse non trouvée")
        
        return AnalysisResponse(**dict(analysis))

# 🤖 Simulation analyse IA (pour test)
@app.post("/submissions/{submission_id}/analyze")
async def trigger_analysis(submission_id: str):
    """Déclencher l'analyse IA d'une soumission"""
    async with get_db_connection().__anext__() as conn:
        # Mettre à jour le statut
        await conn.execute(
            "UPDATE submissions SET status = 'processing' WHERE id = $1",
            submission_id
        )
        
        # Simuler une analyse (en prod: vraie IA)
        fake_report = f"""
        # 📊 Analyse du Plan d'Affaires
        
        ## 🎯 Résumé Exécutif
        Ce plan d'affaires présente un concept solide avec un potentiel commercial intéressant.
        
        ## 💡 Points Forts
        - Proposition de valeur claire
        - Marché cible bien identifié
        - Approche méthodique
        
        ## 🔧 Axes d'Amélioration
        - Approfondir l'analyse concurrentielle
        - Développer les projections financières
        - Préciser la stratégie de lancement
        
        ## 📚 Recommandations
        1. Valider le concept avec des interviews clients
        2. Créer un prototype/MVP
        3. Affiner le modèle économique
        
        ---
        *Analyse générée automatiquement le {datetime.now().strftime('%Y-%m-%d à %H:%M')}*
        """
        
        # Insérer l'analyse
        await conn.execute(
            """
            INSERT INTO analyses (submission_id, report_content, processing_time_seconds, ai_model_used)
            VALUES ($1, $2, $3, $4)
            """,
            submission_id, fake_report, 420, "simulation"
        )
        
        # Mettre à jour le statut
        await conn.execute(
            "UPDATE submissions SET status = 'completed' WHERE id = $1",
            submission_id
        )
        
        return {"message": "Analyse terminée", "submission_id": submission_id}

# 📊 Professeurs disponibles (pour frontend)
@app.get("/professors")
async def get_professors():
    """Liste des professeurs pour le dropdown frontend"""
    async with get_db_connection().__anext__() as conn:
        query = "SELECT id, name, course FROM professors ORDER BY name"
        professors = await conn.fetch(query)
        return [dict(p) for p in professors]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)