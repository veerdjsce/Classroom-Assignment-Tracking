import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# On Render, use /data (persistent disk). Locally, use the project folder.
_DATA_DIR = os.environ.get('RENDER_DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
os.makedirs(_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, 'classroom.db')

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # Users Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'student', -- 'admin' or 'student'
        status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'approved', 'rejected', 'suspended'
        is_super_admin INTEGER DEFAULT 0, -- 1 = primary admin
        batch_id INTEGER,
        join_reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        approved_at TIMESTAMP,
        approved_by INTEGER,
        FOREIGN KEY (batch_id) REFERENCES batches (id) ON DELETE SET NULL,
        FOREIGN KEY (approved_by) REFERENCES users (id) ON DELETE SET NULL
    )
    ''')

    # Migration: ensure is_super_admin column exists
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_super_admin INTEGER DEFAULT 0")
    except Exception:
        pass

    # Batches Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        code TEXT UNIQUE,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Subjects Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        code TEXT,
        description TEXT,
        color TEXT DEFAULT '#4f46e5',
        icon TEXT DEFAULT 'book-open',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (batch_id) REFERENCES batches (id) ON DELETE CASCADE
    )
    ''')

    # Assignments Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        deadline TIMESTAMP NOT NULL,
        attachment_filename TEXT,
        attachment_original_name TEXT,
        attachment_size INTEGER,
        attachment_type TEXT,
        created_by INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE,
        FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE CASCADE
    )
    ''')

    # Migration: Ensure attachment columns exist on assignments table
    for col, col_type in [
        ('attachment_filename', 'TEXT'),
        ('attachment_original_name', 'TEXT'),
        ('attachment_size', 'INTEGER'),
        ('attachment_type', 'TEXT')
    ]:
        try:
            cursor.execute(f"ALTER TABLE assignments ADD COLUMN {col} {col_type}")
        except Exception:
            pass

    # User Assignments (Completion tracking - strictly 1 per user per assignment)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        assignment_id INTEGER NOT NULL,
        is_completed INTEGER NOT NULL DEFAULT 0, -- 0 = incomplete, 1 = completed
        completed_at TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, assignment_id),
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        FOREIGN KEY (assignment_id) REFERENCES assignments (id) ON DELETE CASCADE
    )
    ''')

    # Activity Logs / Admin Notifications (Tick/Untick, Approvals, etc.)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        action_type TEXT NOT NULL, -- 'assignment_marked', 'assignment_unmarked', 'user_registered', 'user_approved', etc.
        assignment_id INTEGER,
        details TEXT NOT NULL,
        is_read_by_admin INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        FOREIGN KEY (assignment_id) REFERENCES assignments (id) ON DELETE CASCADE
    )
    ''')

    # Classroom Announcements / Messages
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        image_url TEXT,
        is_pinned INTEGER DEFAULT 0,
        batch_id INTEGER, -- NULL means for all batches
        created_by INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (batch_id) REFERENCES batches (id) ON DELETE CASCADE,
        FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE CASCADE
    )
    ''')

    # Polls Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS polls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        batch_id INTEGER, -- NULL means for all batches
        created_by INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,
        FOREIGN KEY (batch_id) REFERENCES batches (id) ON DELETE CASCADE,
        FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE CASCADE
    )
    ''')

    # Poll Options Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS poll_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        poll_id INTEGER NOT NULL,
        option_text TEXT NOT NULL,
        FOREIGN KEY (poll_id) REFERENCES polls (id) ON DELETE CASCADE
    )
    ''')

    # Poll Votes Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS poll_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        poll_id INTEGER NOT NULL,
        option_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(poll_id, user_id),
        FOREIGN KEY (poll_id) REFERENCES polls (id) ON DELETE CASCADE,
        FOREIGN KEY (option_id) REFERENCES poll_options (id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    ''')

    conn.commit()

    # Seed default admin if no users exist
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
    admin_count = cursor.fetchone()[0]
    if admin_count == 0:
        cursor.execute('''
        INSERT INTO users (username, email, password_hash, full_name, role, status, is_super_admin, created_at, approved_at)
        VALUES (?, ?, ?, ?, 'admin', 'approved', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ''', (
            'admin',
            'admin@classroom.local',
            generate_password_hash('admin123'),
            'Classroom Administrator'
        ))
        conn.commit()
        print("Initialized default Admin: username='admin', password='admin123'")
    else:
        # Ensure first admin has is_super_admin = 1
        cursor.execute("UPDATE users SET is_super_admin = 1 WHERE username = 'admin' OR id = 1")
        conn.commit()

    # Seed initial sample batch and sample subjects if empty
    cursor.execute("SELECT COUNT(*) FROM batches")
    batch_count = cursor.fetchone()[0]
    if batch_count == 0:
        cursor.execute('''
        INSERT INTO batches (name, code, description)
        VALUES ('Computer Science 2024-2028', 'CS-2428', 'Class of 2024-2028 Computer Science & Engineering')
        ''')
        batch_id = cursor.lastrowid

        # Insert subjects
        subjects = [
            ('Data Structures & Algorithms', 'CS201', 'Core computer science algorithms and problem solving.', '#4f46e5', 'code'),
            ('Database Management Systems', 'CS202', 'Relational design, SQL, transactions and normalization.', '#059669', 'database'),
            ('Operating Systems', 'CS203', 'Process scheduling, concurrency, virtual memory and file systems.', '#d97706', 'cpu'),
            ('Web Development', 'CS204', 'Full-stack responsive web applications and APIs.', '#7c3aed', 'globe')
        ]
        for name, code, desc, color, icon in subjects:
            cursor.execute('''
            INSERT INTO subjects (batch_id, name, code, description, color, icon)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (batch_id, name, code, desc, color, icon))
        
        # Insert sample assignment with deadline
        cursor.execute("SELECT id FROM subjects LIMIT 1")
        first_sub_id = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        admin_id = cursor.fetchone()[0]

        cursor.execute('''
        INSERT INTO assignments (subject_id, title, description, deadline, created_by)
        VALUES (?, 'Binary Search Tree Implementation', 'Implement insert, search, and delete operations on BST in C++ or Python with test cases.', datetime('now', '+3 days'), ?)
        ''', (first_sub_id, admin_id))

        cursor.execute('''
        INSERT INTO assignments (subject_id, title, description, deadline, created_by)
        VALUES (?, 'SQL Schema Normalization Project', 'Normalize the university library dataset up to 3NF and submit SQL schema definitions.', datetime('now', '+5 days'), ?)
        ''', (first_sub_id + 1, admin_id))

        # Insert sample welcome announcement
        cursor.execute('''
        INSERT INTO announcements (title, content, is_pinned, created_by)
        VALUES ('Welcome to Classroom Tracker!', 'Welcome to our class tracker dashboard! Track all your assignments, deadlines, and stay on top of your semester coursework. Make sure to check deadlines regularly.', 1, ?)
        ''', (admin_id,))

        conn.commit()

    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
