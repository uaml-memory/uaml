#!/usr/bin/env python3
"""Launch script for UAML Customer Portal.

Starts the portal on 127.0.0.1:8791 for reverse-proxying via nginx.
DB file lives next to this script by default.
"""
import sys
from pathlib import Path

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from uaml.customer import CustomerDB, CustomerPortal

HOST = "127.0.0.1"
PORT = 8791
DB_PATH = str(Path(__file__).resolve().parent / "customers.db")

if __name__ == "__main__":
    db = CustomerDB(db_path=DB_PATH)
    portal = CustomerPortal(customer_db=db, host=HOST, port=PORT)
    print(f"Starting UAML Customer Portal — DB: {DB_PATH}")
    portal.serve()
