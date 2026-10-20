from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import create_engine, text
import os
import json
from dotenv import load_dotenv
import uvicorn
from typing import Optional

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    raise ValueError("DB_URL not found!")

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

class KaryawanCreate(BaseModel):
    id_karyawan: str 
    auto_id: bool
    nama_lengkap: str
    nomor_wa: str
    divisi: str
    role: str

@app.get("/karyawan", response_class=HTMLResponse)
async def view_karyawan(request: Request):
    with engine.connect() as conn:
        query = text("SELECT id_karyawan, nama_lengkap, nomor_wa, divisi, role FROM karyawan ORDER BY id_karyawan ASC")
        karyawan_list = [serialize_row(row) for row in conn.execute(query).fetchall()]
    return templates.TemplateResponse(
        request=request,
        name="karyawan.html",
        context={"karyawan_list_json": json.dumps(karyawan_list)}
    )

@app.post("/api/karyawan")
async def createKaryawan(karyawan: KaryawanCreate):
    with engine.begin() as conn:
        wa_check = conn.execute(text("SELECT id_karyawan FROM karyawan WHERE nomor_wa = :wa"), {"wa": karyawan.nomor_wa}).fetchone()
        if wa_check:
            return JSONResponse(status_code=400, content={"status": "error", "pesan": "Nomor WhatsApp ini sudah terdaftar."})

        final_id = karyawan.id_karyawan
        
        if karyawan.auto_id:
            last_id_row = conn.execute(text("SELECT id_karyawan FROM karyawan WHERE id_karyawan LIKE 'EMP-%' ORDER BY CAST(SUBSTRING(id_karyawan, 5) AS UNSIGNED) DESC LIMIT 1")).fetchone()
            if last_id_row:
                last_number = int(last_id_row[0].split('-')[1])
                final_id = f"EMP-{last_number + 1:03d}"
            else:
                final_id = "EMP-001"
        else:
            id_check = conn.execute(text("SELECT id_karyawan FROM karyawan WHERE id_karyawan = :id"), {"id": final_id}).fetchone()
            if id_check:
                return JSONResponse(status_code=400, content={"status": "error", "pesan": f"ID Karyawan {final_id} sudah digunakan."})

        query = text("""
            INSERT INTO karyawan (id_karyawan, nama_lengkap, nomor_wa, divisi, role)
            VALUES (:id_kary, :nama, :wa, :divisi, :role)
        """)
        conn.execute(
            query, {
                "id_kary": final_id,
                "nama": karyawan.nama_lengkap,
                "wa": karyawan.nomor_wa,
                "divisi": karyawan.divisi,
                "role": karyawan.role
            }
        )
    return JSONResponse(content={ "status": "success", "pesan": "Karyawan berhasil ditambahkan." })

@app.delete("/api/karyawan/{id_karyawan}")
async def delete_karyawan(id_karyawan: str):
    with engine.begin() as conn:
        cek_id = conn.execute(text("SELECT id_karyawan FROM karyawan WHERE id_karyawan = :id"), {"id": id_karyawan}).fetchone()
        if not cek_id:
            return JSONResponse(status_code=404, content={"status": "error", "pesan": "Data karyawan tidak ditemukan."})

        conn.execute(text("DELETE FROM karyawan WHERE id_karyawan = :id"), {"id": id_karyawan})
    
    return JSONResponse(content={"status": "sukses", "pesan": f"Karyawan dengan ID {id_karyawan} berhasil dihapus."})

class BroadcastCreate(BaseModel):
    waktu_kirim: str
    pesan: str
    tipe_lampiran: str
    file_path: Optional[str] = None

@app.get("/broadcast", response_class=HTMLResponse)
async def view_broadcast(request: Request):
    with engine.connect() as conn:

        query = text("SELECT id, waktu_kirim, pesan, tipe_lampiran, file_path, status_kirim FROM jadwal_pesan ORDER BY waktu_kirim DESC")
        broadcast_list = [serialize_row(row) for row in conn.execute(query).fetchall()]
    return templates.TemplateResponse(
        request=request, 
        name="broadcast.html", 
        context={"broadcast_list_json": json.dumps(broadcast_list)}
    )

@app.post("/api/broadcast")
async def create_broadcast(bc: BroadcastCreate):
    with engine.begin() as conn:
        query = text("""
            INSERT INTO jadwal_pesan (waktu_kirim, pesan, tipe_lampiran, file_path, status_kirim)
            VALUES (:waktu, :pesan, :tipe, :path, 'pending')
        """)
        conn.execute(query, {
            "waktu": bc.waktu_kirim,
            "pesan": bc.pesan,
            "tipe": bc.tipe_lampiran,
            "path": bc.file_path or ""
        })
    return JSONResponse(content={"status": "sukses", "pesan": "Jadwal broadcast berhasil ditambahkan!"})

@app.delete("/api/broadcast/{id_pesan}")
async def delete_broadcast(id_pesan: int):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM jadwal_pesan WHERE id = :id"), {"id": id_pesan})
    return JSONResponse(content={"status": "sukses", "pesan": "Jadwal pesan berhasil dihapus."})

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8080, reload=True)