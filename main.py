# 🚀 API FastAPI - Plateforme Plans d'Affaires
# Version finale optimisée avec corrections DB et port

from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import psycopg
from psycopg import AsyncConnection
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

# 🔌 Connexion base de données (CORRIGÉE)
async def get_db_connection():
    """Obtenir une connexion à la base de données"""
    try:
        return await AsyncConnection.connect(DATABASE_URL,autocommit=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur connexion DB: {str(e)}")

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
        "pages": {
            "student": "/student",
            "professor": "/professor"
        },
        "endpoints": {
            "login": "/auth/login",
            "submissions": "/submissions",
            "dashboard": "/professor/dashboard",
            "professors": "/professors"
        }
    }

@app.get("/health")
async def health_check():
    """Check de santé de l'API"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}

# 🌐 Routes pour servir les pages HTML
@app.get("/student")
async def student_page():
    """Page de soumission pour les étudiants"""
    if os.path.exists("student.html"):
        return FileResponse("student.html")
    else:
        raise HTTPException(status_code=404, detail="Page étudiant non trouvée")

@app.get("/professor") 
async def professor_page():
    """Page dashboard pour les professeurs"""
    if os.path.exists("professor.html"):
        return FileResponse("professor.html")
    else:
        raise HTTPException(status_code=404, detail="Page professeur non trouvée")

# 📊 Professeurs disponibles (pour frontend) - CORRIGÉ
@app.get("/professors")
async def get_professors():
    """Liste des professeurs pour le dropdown frontend"""
    conn = await get_db_connection()
    try:
        query = "SELECT id, name, course FROM professors ORDER BY name"
        cursor = await conn.execute(query)
        professors = await cursor.fetchall()
        
        professors_list = []
        for p in professors:
            professors_list.append({
                'id': str(p[0]),
                'name': p[1],
                'course': p[2]
            })
        
        return professors_list
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur DB: {str(e)}")
    finally:
        await conn.close()

# 🔐 Authentification - CORRIGÉE
@app.post("/auth/login")
async def login_professor(professor_data: ProfessorLogin):
    """Login professeur"""
    conn = await get_db_connection()
    try:
        # Vérifier le professeur
        query = """
        SELECT id, email, password_hash, name, course 
        FROM professors 
        WHERE email = %s
        """
        cursor = await conn.execute(query, (professor_data.email,))
        professor = await cursor.fetchone()
        
        if not professor:
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
        
        # Convertir en dict pour faciliter l'accès
        professor_dict = {
            'id': professor[0],
            'email': professor[1], 
            'password_hash': professor[2],
            'name': professor[3],
            'course': professor[4]
        }
        
        # Vérifier le mot de passe (simplifié pour démo)
        # En prod: utiliser bcrypt ou argon2
        password_hash = hash_password(professor_data.password)
        if professor_dict['password_hash'] != password_hash:
            raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
        
        # Créer token JWT
        access_token = create_access_token(data={"sub": str(professor_dict['id'])})
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "professor": {
                "id": str(professor_dict['id']),
                "email": professor_dict['email'],
                "name": professor_dict['name'],
                "course": professor_dict['course']
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur login: {str(e)}")
    finally:
        await conn.close()

# 📋 Soumissions - CORRIGÉE avec conversion email → UUID
@app.post("/submissions", response_model=SubmissionResponse)
async def create_submission(
    student_name: str = Form(...),
    student_email: str = Form(...),
    professor_id: str = Form(...),  # Reçoit l'email du professeur
    project_title: str = Form(...),
    file: UploadFile = File(...)
):
    """Créer une nouvelle soumission"""
    
    # Valider le fichier
    if not file.filename.endswith(('.pdf', '.doc', '.docx')):
        raise HTTPException(status_code=400, detail="Format de fichier non supporté")
    
    if file.size and file.size > 15 * 1024 * 1024:  # 15MB
        raise HTTPException(status_code=400, detail="Fichier trop volumineux")
    
    # Générer nom de fichier unique
    file_extension = file.filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    
    # Sauvegarder le fichier
    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = f"{upload_dir}/{unique_filename}"
    
    try:
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur sauvegarde fichier: {str(e)}")
    
    # Connexion base de données
    conn = await get_db_connection()
    try:
        # 🆕 NOUVELLE ÉTAPE : Convertir email professeur → UUID
        prof_query = "SELECT id FROM professors WHERE email = %s"
        prof_cursor = await conn.execute(prof_query, (professor_id,))
        professor = await prof_cursor.fetchone()
        
        if not professor:
            raise HTTPException(status_code=400, detail=f"Professeur non trouvé: {professor_id}")
        
        # Récupérer l'UUID du professeur
        actual_professor_id = str(professor[0])
        
        # Insérer la soumission avec l'UUID correct
        query = """
        INSERT INTO submissions (student_name, student_email, professor_id, project_title, file_url, file_name, file_size)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id, student_name, student_email, project_title, status, submission_date, file_name
        """
        cursor = await conn.execute(
            query, 
            (student_name, student_email, actual_professor_id, project_title, file_path, file.filename, len(content))
        )
        submission = await cursor.fetchone()
        
        if not submission:
            raise HTTPException(status_code=500, detail="Erreur création soumission")
        
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
        
        return SubmissionResponse(**submission_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur DB soumission: {str(e)}")
    finally:
        await conn.close()
# 📊 Dashboard professeur - CORRIGÉ
@app.get("/professor/dashboard")
async def get_professor_dashboard(professor_id: str = Depends(get_current_professor)):
    """Dashboard professeur avec toutes ses soumissions"""
    conn = await get_db_connection()
    try:
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
        WHERE s.professor_id = %s
        ORDER BY s.submission_date DESC
        """
        cursor = await conn.execute(query, (professor_id,))
        submissions = await cursor.fetchall()
        
        # Convertir en liste de dicts
        submissions_list = []
        for s in submissions:
            submissions_list.append({
                'id': str(s[0]),
                'student_name': s[1],
                'student_email': s[2], 
                'project_title': s[3],
                'status': s[4],
                'submission_date': s[5],
                'file_name': s[6],
                'analysis_completed_at': s[7],
                'processing_time_seconds': s[8]
            })
        
        # Stats
        total = len(submissions_list)
        completed = len([s for s in submissions_list if s['analysis_completed_at']])
        processing = len([s for s in submissions_list if s['status'] == 'processing'])
        
        return {
            "stats": {
                "total_submissions": total,
                "completed_analyses": completed,
                "processing": processing,
                "pending": total - completed - processing
            },
            "submissions": submissions_list
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur dashboard: {str(e)}")
    finally:
        await conn.close()

# 📋 Analyse individuelle - CORRIGÉE
@app.get("/submissions/{submission_id}/analysis")
async def get_analysis(submission_id: str, professor_id: str = Depends(get_current_professor)):
    """Récupérer l'analyse d'une soumission"""
    conn = await get_db_connection()
    try:
        # Vérifier que la soumission appartient au professeur
        query_check = """
        SELECT id FROM submissions 
        WHERE id = %s AND professor_id = %s
        """
        cursor_check = await conn.execute(query_check, (submission_id, professor_id))
        submission = await cursor_check.fetchone()
        if not submission:
            raise HTTPException(status_code=404, detail="Soumission non trouvée")
        
        # Récupérer l'analyse
        query_analysis = """
        SELECT id, submission_id, report_content, generated_at, processing_time_seconds
        FROM analyses 
        WHERE submission_id = %s
        """
        cursor_analysis = await conn.execute(query_analysis, (submission_id,))
        analysis = await cursor_analysis.fetchone()
        if not analysis:
            raise HTTPException(status_code=404, detail="Analyse non trouvée")
        
        # Convertir en dict
        analysis_dict = {
            'id': str(analysis[0]),
            'submission_id': str(analysis[1]),
            'report_content': analysis[2],
            'generated_at': analysis[3],
            'processing_time_seconds': analysis[4]
        }
        
        return AnalysisResponse(**analysis_dict)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur analyse: {str(e)}")
    finally:
        await conn.close()

# 🤖 Simulation analyse IA (pour test) - CORRIGÉE
@app.post("/submissions/{submission_id}/analyze")
async def trigger_analysis(submission_id: str):
    """Déclencher l'analyse IA d'une soumission"""
    conn = await get_db_connection()
    try:
        # Mettre à jour le statut
        await conn.execute(
            "UPDATE submissions SET status = 'processing' WHERE id = %s",
            (submission_id,)
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
            VALUES (%s, %s, %s, %s)
            """,
            (submission_id, fake_report, 420, "simulation")
        )
        
        # Mettre à jour le statut
        await conn.execute(
            "UPDATE submissions SET status = 'completed' WHERE id = %s",
            (submission_id,)
        )
        
        return {"message": "Analyse terminée", "submission_id": submission_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur analyse: {str(e)}")
    finally:
        await conn.close()

# 🚀 PAS de bloc if __name__ == "__main__" - Render gère le port automatiquement
