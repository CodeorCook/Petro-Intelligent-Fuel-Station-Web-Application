from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

if os.getenv('PETRO_OPERATIONAL_STORAGE') != 'postgresql':
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required; no default database credentials are provided")

# Khởi tạo engine
# Legal-profile snapshots and private document metadata must not appear as
# bound parameter values in SQL echo or database exception logs.
engine = create_engine(DATABASE_URL, echo=False, hide_parameters=True)
#Tạo sessionlocal mỗi lần ngdung vào
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Hàm dependency để các file router gọi vào xin kết nối DB
def get_db() :
    db = SessionLocal()
    try :
        yield db
    finally :
        db.close()
