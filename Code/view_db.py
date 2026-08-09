"""
Quick script to view all tables and their data in the FairShare database.
"""
import sqlite3
import os

def view_database():
    # Direct path to database (bypassing config which requires SECRET_KEY)
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(BASE_DIR, 'data', 'fairshare.db')
    print(f"Database: {db_path}\n")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cursor.fetchall()
    
    for table in tables:
        table_name = table['name']
        print(f"\n{'='*60}")
        print(f"TABLE: {table_name}")
        print(f"{'='*60}")
        
        # Get column info
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        col_names = [col['name'] for col in columns]
        print(f"Columns: {', '.join(col_names)}")
        
        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"Rows: {count}\n")
        
        # Show first 10 rows
        if count > 0:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 10")
            rows = cursor.fetchall()
            for row in rows:
                print(dict(row))
                print("-" * 40)
    
    conn.close()

if __name__ == '__main__':
    view_database()
