from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse,RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import create_engine, text
import os
import json
import jwt
import datetime
from typing import Optional
from dotenv import load_dotenv
import uvicorn

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASS = os.getenv("ADMIN_PASS")

if not DB_URL:
    raise ValueError("DATABASE_URL is not set in .env file!")

engine = create_engine(DB_URL)
app = FastAPI(title="OfficeAssist Dashboard")
templates = Jinja2Templates(directory="templates")

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    public_paths = ["/login", "/api/login", "/api/logout"]
    if request.url.path in public_paths or request.url.path.startswith("/static"):
        return await call_next(request)

    token = request.cookies.get("access_token")
    if not token:
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"pesan": "Akses ditolak."})
        return RedirectResponse(url="/login")

    try:
        jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return RedirectResponse(url="/login")
    except jwt.InvalidTokenError:
        return RedirectResponse(url="/login")

    return await call_next(request)

class LoginData(BaseModel):
    username: str
    password: str

@app.get("/login", response_class=HTMLResponse)    
async def view_login(request: Request):
    return templates.TemplateResponse(request= request, name="login.html")

@app.post("/api/login")
async def process_login(data: LoginData):
    if data.username == ADMIN_USER and data.password == ADMIN_PASS:
        expire = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        token = jwt.encode({"sub": data.username, "exp": expire}, SECRET_KEY, algorithm="HS256")
        
        response = JSONResponse(content={"status": "success", "pesan": "Login berhasil"})
        response.set_cookie(key="access_token", value=token, httponly=True, max_age=86400)
        return response
    
    return JSONResponse(status_code=401, content={"status": "error", "pesan": "Username atau Password salah."})

@app.post("/api/logout")
async def process_logout():
    response= JSONResponse(content={"status": "success", "pesan": "Logout berhasil."})
    response.delete_cookie("access_token")
    return response

def format_wa_number(phone: str) -> str:
    cleaned = ''.join(filter(str.isdigit, phone))
    if cleaned.startswith("0"):
        cleaned = "62" + cleaned[1:]
    return cleaned

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

class EmployeeUpdate(BaseModel):
    full_name: str
    whatsapp_number: str
    division: str
    role: str

@app.put("/api/employees/{employee_id}")
async def update_employee(employee_id: str, emp: EmployeeUpdate):
    with engine.begin() as conn:
        wa_check = conn.execute(text("""
            SELECT employee_id FROM employees
            WHERE whatsapp_number = :wa AND employee_id != :id
        """), {"wa": emp.whatsapp_number, "id": employee_id}).fetchone()

        if wa_check:
            return JSONResponse(status_code=400, content={"status": "error", "pesan": "Nomor WhatsApp ini sudah terdaftar pada karyawan lain!"})

        conn.execute(text("""
            UPDATE employees
            SET full_name = :name, whatsapp_number = :wa, division = :div, role = :role
            WHERE employee_id = :id
        """), {
            "name": emp.full_name,
            "wa": emp.whatsapp_number,
            "div": emp.division,
            "role": emp.role,
            "id": employee_id
        })
    return JSONResponse(content={"status": "success", "pesan": f"Data karyawan {employee_id} berhasil diperbarui."})
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