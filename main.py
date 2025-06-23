# 🚀 API FastAPI - Plateforme Plans d'Affaires
# Version avec IA réelle intégrée !

from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form, BackgroundTasks
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
import json

# Import du module d'analyse IA
from ai_analyzer import extract_text_from_file, analyze_business_plan, generate_formatted_report

# 🔧 Configuration
app = FastAPI(
    title="Plans d'Affaires API",
    description="API pour soumission et analyse de plans d'affaires avec IA",
    version="2.0.0"
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
    score: Optional[int] = None

class AnalysisResponse(BaseModel):
    id: str
    submission_id: str
    report_content: str
    score_global: int
    generated_at: datetime
    processing_time_seconds: Optional[int]

# 🔌 Connexion base de données
async def get_db_connection():
    conn = await AsyncConnection.connect(DATABASE_URL)
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
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

# 🤖 Fonction d'analyse IA en arrière-plan
async def process_submission_with_ai(submission_id: str):
    """Traiter une soumission avec l'IA en arrière-plan"""
    start_time = datetime.now()
    
    async with await AsyncConnection.connect(DATABASE_URL) as conn:
        try:
            # Récupérer les infos de la soumission
            query = """
            SELECT student_name, student_email, project_title, file_url, professor_id
            FROM submissions
            WHERE id = %s
            """
            cursor = await conn.execute(query, (submission_id,))
            submission = await cursor.fetchone()
            
            if not submission:
                print(f"Soumission {submission_id} non trouvée")
                return
            
            student_name, student_email, project_title, file_url, professor_id = submission
            
            # Mettre à jour le statut
            await conn.execute(
                "UPDATE submissions SET status = 'processing' WHERE id = %s",
                (submission_id,)
            )
            await conn.commit()
            
            # Extraire le texte du document
            text = await extract_text_from_file(file_url)
            
            # Analyser avec OpenAI
            analysis = await analyze_business_plan(text, student_name, project_title)
            
            # Calculer le temps de traitement
            processing_time = int((datetime.now() - start_time).total_seconds())
            
            # Générer le rapport formaté
            report_html = generate_formatted_report(analysis, student_name, project_title, processing_time)
            
            # Sauvegarder l'analyse
            await conn.execute(
                """
                INSERT INTO analyses (
                    submission_id, 
                    report_content, 
                    score_global,
                    scores_details,
                    processing_time_seconds, 
                    ai_model_used
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    submission_id, 
                    report_html,
                    analysis.get('score_global', 0),
                    json.dumps(analysis.get('scores', {})),
                    processing_time, 
                    "gpt-3.5-turbo"
                )
            )
            
            # Mettre à jour la soumission avec le score
            await conn.execute(
                """
                UPDATE submissions 
                SET status = 'completed', score = %s 
                WHERE id = %s
                """,
                (analysis.get('score_global', 0), submission_id)
            )
            
            await conn.commit()
            print(f"✅ Analyse terminée pour {submission_id} - Score: {analysis.get('score_global')}/100")
            
        except Exception as e:
            print(f"❌ Erreur analyse pour {submission_id}: {str(e)}")
            # En cas d'erreur, marquer comme échoué
            await conn.execute(
                "UPDATE submissions SET status = 'failed' WHERE id = %s",
                (submission_id,)
            )
            await conn.commit()

# 🌟 Routes API

@app.get("/")
async def root():
    return {
        "message": "🚀 API Plans d'Affaires avec IA - Version 2.0",
        "status": "✅ Opérationnelle",
        "ai_enabled": True,
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
    openai_configured = bool(os.getenv("OPENAI_API_KEY"))
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow(),
        "openai_configured": openai_configured
    }

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

# 🔐 Authentification
@app.post("/auth/login")
async def login_professor(
    professor_data: ProfessorLogin,
    conn: AsyncConnection = Depends(get_db_connection)
):
    """Login professeur"""
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
    
    # Vérifier le mot de passe
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

# 📋 Soumissions avec analyse IA automatique
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
    """Créer une nouvelle soumission et lancer l'analyse IA"""
    
    # Valider le fichier
    if not file.filename.endswith(('.pdf', '.doc', '.docx')):
        raise HTTPException(status_code=400, detail="Format de fichier non supporté. Utilisez PDF ou DOCX.")
    
    if file.size > 15 * 1024 * 1024:  # 15MB
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 15MB)")
    
    # Générer nom de fichier unique
    file_extension = file.filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    
    # Sauvegarder le fichier
    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = f"{upload_dir}/{unique_filename}"
    
    async with aiofiles.open(file_path, 'wb') as f:
        content = await file.read()
        await f.write(content)
    
    # Insérer en base
    query = """
    INSERT INTO submissions (student_name, student_email, professor_id, project_title, file_url, file_name, file_size, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id, student_name, student_email, project_title, status, submission_date, file_name
    """
    cursor = await conn.execute(
        query, 
        (student_name, student_email, professor_id, project_title, file_path, file.filename, len(content), 'pending')
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

@app.get("/professor/dashboard")
async def get_professor_dashboard(
    professor_id: str = Depends(get_current_professor),
    conn: AsyncConnection = Depends(get_db_connection)
):
    """Dashboard professeur avec toutes ses soumissions"""
    query = """
    SELECT 
        s.id,
        s.student_name,
        s.student_email,
        s.project_title,
        s.status,
        s.submission_date,
        s.file_name,
        s.score,
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
            'submission_date': s[5].isoformat() if s[5] else None,
            'file_name': s[6],
            'score': s[7],
            'analysis_completed_at': s[8].isoformat() if s[8] else None,
            'processing_time_seconds': s[9]
        })
    
    # Stats
    total = len(submissions_list)
    completed = len([s for s in submissions_list if s['status'] == 'completed'])
    processing = len([s for s in submissions_list if s['status'] == 'processing'])
    failed = len([s for s in submissions_list if s['status'] == 'failed'])
    
    # Calculer la moyenne des scores
    scores = [s['score'] for s in submissions_list if s['score'] is not None]
    average_score = round(sum(scores) / len(scores)) if scores else 0
    
    return {
        "stats": {
            "total_submissions": total,
            "completed_analyses": completed,
            "processing": processing,
            "failed": failed,
            "average_score": average_score
        },
        "submissions": submissions_list
    }

@app.get("/submissions/{submission_id}/analysis")
async def get_analysis(
    submission_id: str,
    professor_id: str = Depends(get_current_professor),
    conn: AsyncConnection = Depends(get_db_connection)
):
    """Récupérer l'analyse d'une soumission"""
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
    SELECT id, submission_id, report_content, score_global, generated_at, processing_time_seconds
    FROM analyses 
    WHERE submission_id = %s
    """
    cursor_analysis = await conn.execute(query_analysis, (submission_id,))
    analysis = await cursor_analysis.fetchone()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analyse non disponible. Elle peut être en cours de traitement.")
    
    # Convertir en dict
    analysis_dict = {
        'id': str(analysis[0]),
        'submission_id': str(analysis[1]),
        'report_content': analysis[2],
        'score_global': analysis[3],
        'generated_at': analysis[4],
        'processing_time_seconds': analysis[5]
    }
    
    return AnalysisResponse(**analysis_dict)

# 📊 Professeurs disponibles (pour frontend)
@app.get("/professors")
async def get_professors(conn: AsyncConnection = Depends(get_db_connection)):
    """Liste des professeurs pour le dropdown frontend"""
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

# 🔄 Route pour relancer une analyse (en cas d'échec)
@app.post("/submissions/{submission_id}/retry-analysis")
async def retry_analysis(
    submission_id: str,
    background_tasks: BackgroundTasks,
    professor_id: str = Depends(get_current_professor),
    conn: AsyncConnection = Depends(get_db_connection)
):
    """Relancer l'analyse IA d'une soumission échouée"""
    # Vérifier que la soumission appartient au professeur et est en échec
    query = """
    SELECT id, status FROM submissions 
    WHERE id = %s AND professor_id = %s
    """
    cursor = await conn.execute(query, (submission_id, professor_id))
    submission = await cursor.fetchone()
    
    if not submission:
        raise HTTPException(status_code=404, detail="Soumission non trouvée")
    
    if submission[1] == 'completed':
        raise HTTPException(status_code=400, detail="Cette soumission a déjà été analysée avec succès")
    
    if submission[1] == 'processing':
        raise HTTPException(status_code=400, detail="Une analyse est déjà en cours pour cette soumission")
    
    # Supprimer l'ancienne analyse si elle existe
    await conn.execute("DELETE FROM analyses WHERE submission_id = %s", (submission_id,))
    
    # Réinitialiser le statut
    await conn.execute(
        "UPDATE submissions SET status = 'pending', score = NULL WHERE id = %s",
        (submission_id,)
    )
    await conn.commit()
    
    # Relancer l'analyse
    background_tasks.add_task(process_submission_with_ai, submission_id)
    
    return {"message": "Analyse relancée avec succès", "submission_id": submission_id}

# 📊 Route pour obtenir les statistiques globales
@app.get("/stats/global")
async def get_global_stats(
    professor_id: str = Depends(get_current_professor),
    conn: AsyncConnection = Depends(get_db_connection)
):
    """Obtenir des statistiques globales pour le professeur"""
    # Statistiques par mois
    query_monthly = """
    SELECT 
        DATE_TRUNC('month', submission_date) as month,
        COUNT(*) as submissions,
        AVG(score) as avg_score
    FROM submissions
    WHERE professor_id = %s AND submission_date > NOW() - INTERVAL '6 months'
    GROUP BY month
    ORDER BY month DESC
    """
    cursor_monthly = await conn.execute(query_monthly, (professor_id,))
    monthly_stats = await cursor_monthly.fetchall()
    
    # Top projets
    query_top = """
    SELECT 
        student_name,
        project_title,
        score
    FROM submissions
    WHERE professor_id = %s AND score IS NOT NULL
    ORDER BY score DESC
    LIMIT 5
    """
    cursor_top = await conn.execute(query_top, (professor_id,))
    top_projects = await cursor_top.fetchall()
    
    return {
        "monthly_stats": [
            {
                "month": stat[0].isoformat() if stat[0] else None,
                "submissions": stat[1],
                "avg_score": round(stat[2]) if stat[2] else 0
            }
            for stat in monthly_stats
        ],
        "top_projects": [
            {
                "student_name": proj[0],
                "project_title": proj[1],
                "score": proj[2]
            }
            for proj in top_projects
        ]
    }

if __name__ == "__main__":
    import uvicorn
    
    # Vérifier la configuration
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  ATTENTION: OPENAI_API_KEY n'est pas configurée!")
        print("   L'analyse IA ne fonctionnera pas sans cette clé.")
        print("   Configurez-la dans vos variables d'environnement.")
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
