from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import create_engine, text
import os
import json
from typing import Optional
from dotenv import load_dotenv
import uvicorn

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise ValueError("DATABASE_URL is not set in .env file!")

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
async def view_dashboard(request: Request):
    with engine.connect() as conn:
        total_employees = conn.execute(text("SELECT COUNT(*) FROM employees")).scalar() or 0
        total_inventory = conn.execute(text("SELECT COUNT(*) FROM inventory")).scalar() or 0
        total_interactions = conn.execute(text("SELECT COUNT(*) FROM audit_logs WHERE DATE(timestamp) = CURDATE()")).scalar() or 0
        
        query_logs = text("SELECT timestamp, whatsapp_number, incoming_message, detected_intent, response_status FROM audit_logs ORDER BY timestamp DESC LIMIT 10")
        audit_logs = [serialize_row(row) for row in conn.execute(query_logs).fetchall()]

    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "total_employees": total_employees,
            "total_inventory": total_inventory,
            "total_interactions": total_interactions,
            "audit_logs_json": json.dumps(audit_logs)
        }
    )

# Employee
class EmployeeCreate(BaseModel):
    employee_id: str
    auto_id: bool
    full_name: str
    whatsapp_number: str
    division: str
    role: str

@app.get("/karyawan", response_class=HTMLResponse)
async def view_employees(request: Request):
    with engine.connect() as conn:
        query = text("SELECT employee_id, full_name, whatsapp_number, division, role FROM employees ORDER BY employee_id ASC")
        employee_list = [serialize_row(row) for row in conn.execute(query).fetchall()]
    return templates.TemplateResponse(
        request=request,
        name="karyawan.html",
        context={"employee_list_json": json.dumps(employee_list)}
    )

@app.post("/api/employees")
async def create_employee(emp: EmployeeCreate):
    with engine.begin() as conn:
        wa_check = conn.execute(text("SELECT employee_id FROM employees WHERE whatsapp_number = :wa"), {"wa": emp.whatsapp_number}).fetchone()
        if wa_check:
            return JSONResponse(status_code=400, content={"status": "error", "pesan": "Nomor WhatsApp ini sudah terdaftar."})

        final_id = emp.employee_id
        if emp.auto_id:
            last_id_row = conn.execute(text("SELECT employee_id FROM employees WHERE employee_id LIKE 'EMP-%' ORDER BY CAST(SUBSTRING(employee_id, 5) AS UNSIGNED) DESC LIMIT 1")).fetchone()
            if last_id_row:
                last_number = int(last_id_row[0].split('-')[1])
                final_id = f"EMP-{last_number + 1:03d}"
            else:
                final_id = "EMP-001"
        else:
            id_check = conn.execute(text("SELECT employee_id FROM employees WHERE employee_id = :id"), {"id": final_id}).fetchone()
            if id_check:
                return JSONResponse(status_code=400, content={"status": "error", "pesan": f"ID Karyawan {final_id} sudah digunakan."})

        query = text("""
            INSERT INTO employees (employee_id, full_name, whatsapp_number, division, role)
            VALUES (:emp_id, :name, :wa, :div, :role)
        """)
        conn.execute(query, {
            "emp_id": final_id,
            "name": emp.full_name,
            "wa": emp.whatsapp_number,
            "div": emp.division,
            "role": emp.role
        })
    return JSONResponse(content={ "status": "success", "pesan": "Karyawan berhasil ditambahkan." })

@app.delete("/api/employees/{employee_id}")
async def delete_employee(employee_id: str):
    with engine.begin() as conn:
        cek_id = conn.execute(text("SELECT employee_id FROM employees WHERE employee_id = :id"), {"id": employee_id}).fetchone()
        if not cek_id:
            return JSONResponse(status_code=404, content={"status": "error", "pesan": "Data karyawan tidak ditemukan."})

        conn.execute(text("DELETE FROM employees WHERE employee_id = :id"), {"id": employee_id})
    return JSONResponse(content={"status": "sukses", "pesan": f"Karyawan {employee_id} berhasil dihapus."})


#Broadcast
class BroadcastCreate(BaseModel):
    scheduled_time: str
    message: str
    attachment_type: str
    file_path: Optional[str] = None

@app.get("/broadcast", response_class=HTMLResponse)
async def view_broadcast(request: Request):
    with engine.connect() as conn:
        query = text("SELECT id, scheduled_time, message, attachment_type, file_path, status FROM broadcast_schedules ORDER BY scheduled_time DESC")
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
            INSERT INTO broadcast_schedules (scheduled_time, message, attachment_type, file_path, status)
            VALUES (:time, :msg, :type, :path, 'pending')
        """)
        conn.execute(query, {
            "time": bc.scheduled_time,
            "msg": bc.message,
            "type": bc.attachment_type,
            "path": bc.file_path or ""
        })
    return JSONResponse(content={"status": "sukses", "pesan": "Jadwal broadcast berhasil ditambahkan!"})

@app.delete("/api/broadcast/{broadcast_id}")
async def delete_broadcast(broadcast_id: int):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM broadcast_schedules WHERE id = :id"), {"id": broadcast_id})
    return JSONResponse(content={"status": "sukses", "pesan": "Jadwal pesan berhasil dihapus."})

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8080, reload=True)