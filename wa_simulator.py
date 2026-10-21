import os
import time
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    raise ValueError("DATABASE_URL is not set in .env file")

engine = create_engine(DB_URL)

# test security config
IS_TEST_MODE = True

env_numbers = os.getenv("TEST_PHONE_NUMBERS", "")
WHITELISTED_NUMBERS = [num.strip() for num in env_numbers.split(",") if num.strip()]

print("🤖 Broadcast Simulator is Running...")
if IS_TEST_MODE:
    if not WHITELISTED_NUMBERS:
         print("⚠️  PERINGATAN: SAFE MODE AKTIF tapi TEST_PHONE_NUMBERS di .env kosong!")
    else:
         print(f"⚠️  SAFE MODE ACTIVE: Messages will ONLY be sent to {WHITELISTED_NUMBERS}\n")
else:
    print("🔴 PRODUCTION MODE ACTIVE: Messages will be sent to ALL numbers in the database!\n")

while True:
    try:
        with engine.begin() as conn:
            # 1. Fetch pending scheduled messages
            pending_messages = conn.execute(text("""
                SELECT id, message, attachment_type 
                FROM broadcast_schedules 
                WHERE status = 'pending' AND scheduled_time <= NOW()
            """)).fetchall()

            for msg in pending_messages:
                msg_id = msg[0]
                print(f"==================================================")
                print(f"[!] Found Broadcast ID #{msg_id} due for sending!")
                
                # 2. Fetch all contacts
                employee_list = conn.execute(text("SELECT full_name, whatsapp_number FROM employees")).fetchall()
                
                if not employee_list:
                    print("    -> Warning: Employees table is empty.")
                
                # 3. Simulate sending message
                for emp in employee_list:
                    emp_name = emp[0]
                    emp_phone = emp[1]
                    
                    if IS_TEST_MODE and emp_phone not in WHITELISTED_NUMBERS:
                        print(f"    -> [SKIPPED] {emp_name} ({emp_phone}) ignored (Not in Whitelist).")
                        continue
                    
                    print(f"    -> [SENDING] 🟢 Simulating WA to {emp_name} ({emp_phone})...")
                
                # 4. Update status to success
                conn.execute(text("UPDATE broadcast_schedules SET status = 'sukses' WHERE id = :id"), {"id": msg_id})
                
                print(f"[v] Done! Broadcast ID #{msg_id} marked as 'Terkirim'.")
                print(f"==================================================\n")

    except Exception as e:
        print(f"Database error occurred: {e}")

    time.sleep(10)