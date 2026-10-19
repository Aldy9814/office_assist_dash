from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text
import os
import json
from dotenv import load_dotenv
import uvicorn

load_dotenv()

DB_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:password_mysql_kamu@localhost:3306/officeassist_db")
engine = create_engine(DB_URL)

app = FastAPI(title="OfficeAssist Dashboard")
templates = Jinja2Templates(directory="templates")

def serialize_row(row):
    d = dict(row._mapping)
    for k, v in d.items():
        if hasattr(v, 'isoformat'):
            d[k] = v.strftime("%Y-%m-%d %H:%M:%S")
    return d

@app.get("/", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    with engine.connect() as conn:
        total_karyawan = conn.execute(text("SELECT COUNT(*) FROM karyawan")).scalar() or 0
        total_inventaris = conn.execute(text("SELECT COUNT(*) FROM inventaris")).scalar() or 0
        total_interaksi = conn.execute(text("SELECT COUNT(*) FROM audit_log WHERE DATE(waktu) = CURDATE()")).scalar() or 0
        
        query_logs = text("SELECT waktu, nomor_wa, pesan_masuk, intent_terdeteksi, status_response FROM audit_log ORDER BY waktu DESC LIMIT 10")
        audit_logs = [serialize_row(row) for row in conn.execute(query_logs).fetchall()]

    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "total_karyawan": total_karyawan,
            "total_inventaris": total_inventaris,
            "total_interaksi": total_interaksi,
            "audit_logs_json": json.dumps(audit_logs)
        }
    )

@app.get("/karyawan", response_class=HTMLResponse)
async def view_karyawan(request: Request):
    with engine.connect() as conn:
        query = text("SELECT id_karyawan, nama_lengkap, nomor_wa, divisi, role FROM karyawan LIMIT 100")
        karyawan_list = [serialize_row(row) for row in conn.execute(query).fetchall()]
    return templates.TemplateResponse(
        request=request, 
        name="karyawan.html", 
        context={"karyawan_list_json": json.dumps(karyawan_list)}
    )

@app.get("/inventaris", response_class=HTMLResponse)
async def view_inventaris(request: Request):
    with engine.connect() as conn:
        query = text("""
            SELECT i.kode_barang, i.nama_barang, i.kategori, i.kondisi, COALESCE(k.nama_lengkap, '-') AS pemegang
            FROM inventaris i
            LEFT JOIN karyawan k ON i.id_karyawan = k.id_karyawan
            LIMIT 100
        """)
        inventaris_list = [serialize_row(row) for row in conn.execute(query).fetchall()]
    return templates.TemplateResponse(
        request=request, 
        name="inventaris.html", 
        context={"inventaris_list_json": json.dumps(inventaris_list)}
    )

@app.get("/audit-log", response_class=HTMLResponse)
async def view_audit_log(request: Request):
    with engine.connect() as conn:
        query = text("SELECT waktu, nomor_wa, pesan_masuk, intent_terdeteksi, status_response FROM audit_log ORDER BY waktu DESC LIMIT 100")
        logs_list = [serialize_row(row) for row in conn.execute(query).fetchall()]
    return templates.TemplateResponse(
        request=request, 
        name="audit_log.html", 
        context={"logs_list_json": json.dumps(logs_list)}
    )

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8080, reload=True)