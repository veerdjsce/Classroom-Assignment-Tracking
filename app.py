import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, session,
    flash, jsonify, abort, g, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import DB_PATH, init_db

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'classroom-secure-secret-key-2026-xyz')

# Uploads Configuration — use persistent disk on Render, local static folder otherwise
_DATA_DIR = os.environ.get('RENDER_DATA_DIR', os.path.join(app.root_path, 'static', 'uploads', 'assignments'))
UPLOAD_FOLDER = _DATA_DIR if os.environ.get('RENDER_DATA_DIR') else os.path.join(app.root_path, 'static', 'uploads', 'assignments')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 # 50 MB limit

# Ensure DB is initialized
init_db()

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=30.0)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        try:
            db.close()
        except Exception:
            pass

# ----------------- Decorators & Helpers -----------------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def approved_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        conn = get_db()
        user = conn.execute('SELECT status, role FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        # conn.close()

        if not user:
            session.clear()
            return redirect(url_for('login'))

        if user['role'] != 'admin' and user['status'] != 'approved':
            return redirect(url_for('pending_approval'))
        
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in as an administrator.', 'warning')
            return redirect(url_for('login'))
        
        # Verify role directly from database to guarantee security
        conn = get_db()
        user = conn.execute('SELECT role, status FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if not user or user['role'] != 'admin' or user['status'] != 'approved':
            flash('Access Denied: Only administrators have permission to approve, suspend, or manage user access.', 'danger')
            return redirect(url_for('student_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def log_activity(user_id, action_type, details, assignment_id=None, db_conn=None):
    try:
        conn = db_conn if db_conn else get_db()
        conn.execute('''
            INSERT INTO activity_logs (user_id, action_type, assignment_id, details, is_read_by_admin)
            VALUES (?, ?, ?, ?, 0)
        ''', (user_id, action_type, assignment_id, details))
        conn.commit()
    except Exception as e:
        print(f"Error logging activity: {e}")

@app.context_processor
def inject_global_data():
    user = None
    unread_admin_notifications = 0
    upcoming_student_deadlines = 0

    if 'user_id' in session:
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        
        if user and user['role'] == 'admin':
            row = conn.execute('SELECT COUNT(*) FROM activity_logs WHERE is_read_by_admin = 0').fetchone()
            unread_admin_notifications = row[0] if row else 0
        elif user and user['status'] == 'approved':
            # Count unmarked assignments whose deadline is within 48 hours or overdue
            row = conn.execute('''
                SELECT COUNT(*) FROM assignments a
                LEFT JOIN user_assignments ua ON a.id = ua.assignment_id AND ua.user_id = ?
                WHERE (ua.is_completed IS NULL OR ua.is_completed = 0)
                AND a.deadline <= datetime('now', '+2 days')
            ''', (session['user_id'],)).fetchone()
            upcoming_student_deadlines = row[0] if row else 0

        # conn.close()

    return {
        'current_user': user,
        'unread_admin_notifications': unread_admin_notifications,
        'upcoming_student_deadlines': upcoming_student_deadlines,
        'now': datetime.now()
    }

# Custom template filters for dates
@app.template_filter('format_datetime')
def format_datetime(value):
    if not value:
        return 'No deadline'
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', ''))
        return dt.strftime('%b %d, %Y at %I:%M %p')
    except Exception:
        return str(value)

@app.template_filter('is_overdue')
def is_overdue(value):
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', ''))
        return dt < datetime.now()
    except Exception:
        return False

@app.template_filter('format_filesize')
def format_filesize(value):
    if not value:
        return ''
    try:
        bytes_val = float(value)
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_val < 1024.0:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024.0
        return f"{bytes_val:.1f} TB"
    except Exception:
        return str(value)

# ----------------- Auth Routes -----------------

@app.route('/')
def index():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('student_dashboard'))

    if request.method == 'POST':
        identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')

        if not identifier or not password:
            flash('Please enter both username/email and password.', 'danger')
            return render_template('login.html')

        conn = get_db()
        user = conn.execute('''
            SELECT * FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)
        ''', (identifier, identifier)).fetchone()
        # conn.close()

        if not user or not check_password_hash(user['password_hash'], password):
            flash('Invalid username/email or password.', 'danger')
            return render_template('login.html')

        # Check account status
        if user['role'] != 'admin':
            if user['status'] == 'suspended':
                flash('Your account access has been suspended by the administrator.', 'danger')
                return render_template('login.html')
            elif user['status'] == 'rejected':
                flash('Your registration request was declined by the administrator.', 'danger')
                return render_template('login.html')

        # Store session
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        session['full_name'] = user['full_name']

        if user['role'] == 'admin':
            flash(f'Welcome back, Administrator {user["full_name"]}!', 'success')
            return redirect(url_for('admin_dashboard'))
        
        if user['status'] == 'pending':
            return redirect(url_for('pending_approval'))

        flash(f'Welcome back, {user["full_name"]}!', 'success')
        return redirect(url_for('student_dashboard'))

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))

    conn = get_db()
    batches = conn.execute('SELECT * FROM batches ORDER BY name ASC').fetchall()
    # conn.close()

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        batch_id = request.form.get('batch_id')
        join_reason = request.form.get('join_reason', '').strip()

        # Validation
        if not full_name or not username or not email or not password:
            flash('Please fill in all required fields.', 'danger')
            return render_template('register.html', batches=batches)

        if len(password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return render_template('register.html', batches=batches)

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html', batches=batches)

        conn = get_db()
        existing_user = conn.execute('''
            SELECT id FROM users WHERE LOWER(username) = LOWER(?) OR LOWER(email) = LOWER(?)
        ''', (username, email)).fetchone()

        if existing_user:
            # conn.close()
            flash('Username or email already registered. Please log in or use another username.', 'warning')
            return render_template('register.html', batches=batches)

        password_hash = generate_password_hash(password)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (username, email, password_hash, full_name, role, status, batch_id, join_reason)
            VALUES (?, ?, ?, ?, 'student', 'pending', ?, ?)
        ''', (username, email, password_hash, full_name, batch_id if batch_id else None, join_reason))
        new_user_id = cursor.lastrowid
        conn.commit()

        # Log activity for admin
        batch_name = "No Batch Assigned"
        if batch_id:
            b_row = conn.execute('SELECT name FROM batches WHERE id = ?', (batch_id,)).fetchone()
            if b_row:
                batch_name = b_row['name']

        conn.execute('''
            INSERT INTO activity_logs (user_id, action_type, details, is_read_by_admin)
            VALUES (?, 'user_registered', ?, 0)
        ''', (new_user_id, f"New student '{full_name}' (@{username}) requested to join batch '{batch_name}'."))
        conn.commit()
        # conn.close()

        # Automatically log in with pending status
        session['user_id'] = new_user_id
        session['username'] = username
        session['role'] = 'student'
        session['full_name'] = full_name

        flash('Registration submitted successfully! Your account is now pending admin approval.', 'info')
        return redirect(url_for('pending_approval'))

    return render_template('register.html', batches=batches)

@app.route('/pending-approval')
@login_required
def pending_approval():
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    batch = None
    if user and user['batch_id']:
        batch = conn.execute('SELECT * FROM batches WHERE id = ?', (user['batch_id'],)).fetchone()
    # conn.close()

    if not user:
        session.clear()
        return redirect(url_for('login'))

    if user['role'] == 'admin' or user['status'] == 'approved':
        return redirect(url_for('student_dashboard'))

    return render_template('pending.html', user=user, batch=batch)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out safely.', 'info')
    return redirect(url_for('login'))

# ----------------- Student Views (Strictly Isolated) -----------------

@app.route('/dashboard')
@login_required
@approved_required
def student_dashboard():
    user_id = session['user_id']
    conn = get_db()

    # Get user details
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    # Get Batches
    # If user has a specific batch, highlight or show that batch, but also allow viewing other batches if needed
    batches = conn.execute('SELECT * FROM batches ORDER BY name ASC').fetchall()

    # Get current selected batch (default to user's batch, or first batch)
    selected_batch_id = request.args.get('batch_id', type=int)
    if not selected_batch_id:
        if user['batch_id']:
            selected_batch_id = user['batch_id']
        elif batches:
            selected_batch_id = batches[0]['id']

    # Get subjects for the selected batch
    subjects = []
    if selected_batch_id:
        subjects_raw = conn.execute('''
            SELECT s.*, 
                   COUNT(a.id) as total_assignments
            FROM subjects s
            LEFT JOIN assignments a ON s.id = a.subject_id
            WHERE s.batch_id = ?
            GROUP BY s.id
            ORDER BY s.name ASC
        ''', (selected_batch_id,)).fetchall()

        # Calculate completed count for the current student strictly
        for sub in subjects_raw:
            comp_row = conn.execute('''
                SELECT COUNT(*) as completed_count
                FROM assignments a
                INNER JOIN user_assignments ua ON a.id = ua.assignment_id
                WHERE a.subject_id = ? AND ua.user_id = ? AND ua.is_completed = 1
            ''', (sub['id'], user_id)).fetchone()
            
            sub_dict = dict(sub)
            sub_dict['completed_assignments'] = comp_row['completed_count'] if comp_row else 0
            sub_dict['progress_pct'] = round((sub_dict['completed_assignments'] / sub_dict['total_assignments'] * 100)) if sub_dict['total_assignments'] > 0 else 0
            subjects.append(sub_dict)

    # Announcements
    announcements = conn.execute('''
        SELECT a.*, u.full_name as author_name
        FROM announcements a
        LEFT JOIN users u ON a.created_by = u.id
        WHERE a.batch_id IS NULL OR a.batch_id = ?
        ORDER BY a.is_pinned DESC, a.created_at DESC
        LIMIT 5
    ''', (selected_batch_id,)).fetchall()

    # Active Polls
    active_polls = conn.execute('''
        SELECT p.*, 
               (SELECT COUNT(*) FROM poll_votes pv WHERE pv.poll_id = p.id AND pv.user_id = ?) as user_voted
        FROM polls p
        WHERE p.is_active = 1 AND (p.batch_id IS NULL OR p.batch_id = ?)
        ORDER BY p.created_at DESC
        LIMIT 3
    ''', (user_id, selected_batch_id)).fetchall()

    # Student personal overall completion metrics
    overall_total = conn.execute('''
        SELECT COUNT(a.id)
        FROM assignments a
        JOIN subjects s ON a.subject_id = s.id
        WHERE s.batch_id = ?
    ''', (selected_batch_id,)).fetchone()[0] if selected_batch_id else 0

    overall_completed = conn.execute('''
        SELECT COUNT(a.id)
        FROM assignments a
        JOIN subjects s ON a.subject_id = s.id
        JOIN user_assignments ua ON a.id = ua.assignment_id
        WHERE s.batch_id = ? AND ua.user_id = ? AND ua.is_completed = 1
    ''', (selected_batch_id, user_id)).fetchone()[0] if selected_batch_id else 0

    # conn.close()

    return render_template(
        'student_dashboard.html',
        batches=batches,
        selected_batch_id=selected_batch_id,
        subjects=subjects,
        announcements=announcements,
        active_polls=active_polls,
        overall_total=overall_total,
        overall_completed=overall_completed,
        overall_pct=round((overall_completed / overall_total * 100)) if overall_total > 0 else 0
    )

@app.route('/batch/<int:batch_id>/subject/<int:subject_id>')
@login_required
@approved_required
def subject_assignments(batch_id, subject_id):
    user_id = session['user_id']
    conn = get_db()

    subject = conn.execute('''
        SELECT s.*, b.name as batch_name 
        FROM subjects s 
        JOIN batches b ON s.batch_id = b.id 
        WHERE s.id = ? AND s.batch_id = ?
    ''', (subject_id, batch_id)).fetchone()

    if not subject:
        # conn.close()
        flash('Subject not found.', 'danger')
        return redirect(url_for('student_dashboard'))

    # Filters and sorting parameters
    status_filter = request.args.get('filter', 'all') # 'all', 'completed', 'incomplete', 'overdue'
    sort_by = request.args.get('sort', 'deadline_asc') # 'deadline_asc', 'deadline_desc', 'title_asc'
    search_query = request.args.get('q', '').strip()

    # Query assignments with strictly current user's completion status
    query = '''
        SELECT a.*, 
               COALESCE(ua.is_completed, 0) as is_completed,
               ua.completed_at
        FROM assignments a
        LEFT JOIN user_assignments ua ON a.id = ua.assignment_id AND ua.user_id = ?
        WHERE a.subject_id = ?
    '''
    params = [user_id, subject_id]

    if search_query:
        query += ' AND (a.title LIKE ? OR a.description LIKE ?)'
        params.extend([f'%{search_query}%', f'%{search_query}%'])

    if status_filter == 'completed':
        query += ' AND ua.is_completed = 1'
    elif status_filter == 'incomplete':
        query += ' AND (ua.is_completed IS NULL OR ua.is_completed = 0)'
    elif status_filter == 'overdue':
        query += " AND (ua.is_completed IS NULL OR ua.is_completed = 0) AND a.deadline < datetime('now')"

    # Sorting
    if sort_by == 'deadline_desc':
        query += ' ORDER BY a.deadline DESC'
    elif sort_by == 'title_asc':
        query += ' ORDER BY a.title ASC'
    else: # deadline_asc
        query += ' ORDER BY a.deadline ASC'

    assignments = conn.execute(query, params).fetchall()

    # Calculate overall counts for filter badges
    counts = conn.execute('''
        SELECT 
            COUNT(a.id) as total,
            SUM(CASE WHEN ua.is_completed = 1 THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN (ua.is_completed IS NULL OR ua.is_completed = 0) THEN 1 ELSE 0 END) as incomplete,
            SUM(CASE WHEN (ua.is_completed IS NULL OR ua.is_completed = 0) AND a.deadline < datetime('now') THEN 1 ELSE 0 END) as overdue
        FROM assignments a
        LEFT JOIN user_assignments ua ON a.id = ua.assignment_id AND ua.user_id = ?
        WHERE a.subject_id = ?
    ''', (user_id, subject_id)).fetchone()

    # conn.close()

    return render_template(
        'subject_assignments.html',
        subject=subject,
        assignments=assignments,
        counts=counts,
        current_filter=status_filter,
        current_sort=sort_by,
        search_query=search_query
    )

@app.route('/all-assignments')
@login_required
@approved_required
def all_student_assignments():
    """Allows student to view, sort, and filter across ALL subjects and batches"""
    user_id = session['user_id']
    conn = get_db()

    status_filter = request.args.get('filter', 'all')
    sort_by = request.args.get('sort', 'deadline_asc')
    subject_id = request.args.get('subject_id', type=int)
    search_query = request.args.get('q', '').strip()

    query = '''
        SELECT a.*, 
               s.name as subject_name, 
               s.code as subject_code,
               s.color as subject_color,
               s.batch_id,
               b.name as batch_name,
               COALESCE(ua.is_completed, 0) as is_completed,
               ua.completed_at
        FROM assignments a
        JOIN subjects s ON a.subject_id = s.id
        JOIN batches b ON s.batch_id = b.id
        LEFT JOIN user_assignments ua ON a.id = ua.assignment_id AND ua.user_id = ?
        WHERE 1=1
    '''
    params = [user_id]

    if subject_id:
        query += ' AND a.subject_id = ?'
        params.append(subject_id)

    if search_query:
        query += ' AND (a.title LIKE ? OR a.description LIKE ?)'
        params.extend([f'%{search_query}%', f'%{search_query}%'])

    if status_filter == 'completed':
        query += ' AND ua.is_completed = 1'
    elif status_filter == 'incomplete':
        query += ' AND (ua.is_completed IS NULL OR ua.is_completed = 0)'
    elif status_filter == 'overdue':
        query += " AND (ua.is_completed IS NULL OR ua.is_completed = 0) AND a.deadline < datetime('now')"

    if sort_by == 'deadline_desc':
        query += ' ORDER BY a.deadline DESC'
    elif sort_by == 'title_asc':
        query += ' ORDER BY a.title ASC'
    else:
        query += ' ORDER BY a.deadline ASC'

    assignments = conn.execute(query, params).fetchall()

    # Subjects for filter
    subjects = conn.execute('SELECT id, name, code FROM subjects ORDER BY name ASC').fetchall()

    # Counts
    counts = conn.execute('''
        SELECT 
            COUNT(a.id) as total,
            SUM(CASE WHEN ua.is_completed = 1 THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN (ua.is_completed IS NULL OR ua.is_completed = 0) THEN 1 ELSE 0 END) as incomplete,
            SUM(CASE WHEN (ua.is_completed IS NULL OR ua.is_completed = 0) AND a.deadline < datetime('now') THEN 1 ELSE 0 END) as overdue
        FROM assignments a
        LEFT JOIN user_assignments ua ON a.id = ua.assignment_id AND ua.user_id = ?
    ''', (user_id,)).fetchone()

    # conn.close()

    return render_template(
        'all_assignments.html',
        assignments=assignments,
        subjects=subjects,
        selected_subject_id=subject_id,
        counts=counts,
        current_filter=status_filter,
        current_sort=sort_by,
        search_query=search_query
    )

@app.route('/classmates')
@login_required
@approved_required
def classmates_directory():
    """Classmates directory: read-only for students, administrative controls reserved for admins only"""
    user_id = session['user_id']
    conn = get_db()
    current_u = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    batch_id = request.args.get('batch_id', type=int)
    if not batch_id and current_u and current_u['batch_id']:
        batch_id = current_u['batch_id']

    batches = conn.execute('SELECT * FROM batches ORDER BY name ASC').fetchall()

    query = '''
        SELECT u.id, u.full_name, u.username, u.role, u.is_super_admin, u.batch_id, b.name as batch_name, u.created_at
        FROM users u
        LEFT JOIN batches b ON u.batch_id = b.id
        WHERE u.status = 'approved'
    '''
    params = []
    if batch_id:
        query += ' AND u.batch_id = ?'
        params.append(batch_id)

    query += ' ORDER BY u.role DESC, u.full_name ASC'
    classmates = conn.execute(query, params).fetchall()

    return render_template(
        'classmates.html',
        classmates=classmates,
        batches=batches,
        selected_batch_id=batch_id
    )

@app.route('/assignment/<int:assignment_id>')
@login_required
@approved_required
def assignment_detail(assignment_id):
    user_id = session['user_id']
    conn = get_db()

    assignment = conn.execute('''
        SELECT a.*, 
               s.name as subject_name, 
               s.code as subject_code,
               s.color as subject_color,
               s.batch_id,
               b.name as batch_name,
               COALESCE(ua.is_completed, 0) as is_completed,
               ua.completed_at
        FROM assignments a
        JOIN subjects s ON a.subject_id = s.id
        JOIN batches b ON s.batch_id = b.id
        LEFT JOIN user_assignments ua ON a.id = ua.assignment_id AND ua.user_id = ?
        WHERE a.id = ?
    ''', (user_id, assignment_id)).fetchone()

    # conn.close()

    if not assignment:
        flash('Assignment not found.', 'danger')
        return redirect(url_for('student_dashboard'))

    return render_template('assignment_detail.html', a=assignment)

@app.route('/assignment/<int:assignment_id>/download')
@login_required
@approved_required
def download_assignment_attachment(assignment_id):
    conn = get_db()
    assignment = conn.execute('SELECT * FROM assignments WHERE id = ?', (assignment_id,)).fetchone()
    if not assignment or not assignment['attachment_filename']:
        flash('No file attached to this assignment.', 'warning')
        return redirect(url_for('assignment_detail', assignment_id=assignment_id))

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], assignment['attachment_filename'])
    if not os.path.exists(file_path):
        flash('The attached file could not be found on the server.', 'danger')
        return redirect(url_for('assignment_detail', assignment_id=assignment_id))

    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        assignment['attachment_filename'],
        as_attachment=True,
        download_name=assignment['attachment_original_name'] or assignment['attachment_filename']
    )

# ----------------- Toggle Assignment Completion (AJAX API) -----------------

@app.route('/api/assignments/<int:assignment_id>/toggle', methods=['POST'])
@login_required
@approved_required
def toggle_assignment(assignment_id):
    user_id = session['user_id']
    user_name = session.get('full_name', 'Student')
    conn = get_db()

    # Verify assignment exists
    assignment = conn.execute('''
        SELECT a.*, s.name as subject_name 
        FROM assignments a
        JOIN subjects s ON a.subject_id = s.id
        WHERE a.id = ?
    ''', (assignment_id,)).fetchone()

    if not assignment:
        # conn.close()
        return jsonify({'success': False, 'message': 'Assignment not found'}), 404

    # Check current status
    existing = conn.execute('''
        SELECT is_completed FROM user_assignments WHERE user_id = ? AND assignment_id = ?
    ''', (user_id, assignment_id)).fetchone()

    new_status = 1
    if existing and existing['is_completed'] == 1:
        new_status = 0

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if existing:
        conn.execute('''
            UPDATE user_assignments 
            SET is_completed = ?, completed_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ? AND assignment_id = ?
        ''', (new_status, now_str if new_status == 1 else None, user_id, assignment_id))
    else:
        conn.execute('''
            INSERT INTO user_assignments (user_id, assignment_id, is_completed, completed_at)
            VALUES (?, ?, ?, ?)
        ''', (user_id, assignment_id, new_status, now_str if new_status == 1 else None))

    conn.commit()

    # Log activity for Admin notification
    action_type = 'assignment_marked' if new_status == 1 else 'assignment_unmarked'
    action_text = 'completed' if new_status == 1 else 'unmarked (incomplete)'
    log_detail = f"Student '{user_name}' marked assignment '{assignment['title']}' ({assignment['subject_name']}) as {action_text}."
    
    conn.execute('''
        INSERT INTO activity_logs (user_id, action_type, assignment_id, details, is_read_by_admin)
        VALUES (?, ?, ?, ?, 0)
    ''', (user_id, action_type, assignment_id, log_detail))
    conn.commit()
    # conn.close()

    return jsonify({
        'success': True,
        'is_completed': bool(new_status),
        'completed_at': now_str if new_status == 1 else None,
        'message': f"Assignment successfully marked as {'completed' if new_status == 1 else 'incomplete'}."
    })

# ----------------- Admin Routes & Analytics -----------------

@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()

    # Key statistics
    total_students = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'student' AND status = 'approved'").fetchone()[0]
    pending_approvals = conn.execute("SELECT COUNT(*) FROM users WHERE status = 'pending'").fetchone()[0]
    total_batches = conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
    total_subjects = conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
    total_assignments = conn.execute("SELECT COUNT(*) FROM assignments").fetchone()[0]

    # Overall class completions
    total_completions = conn.execute("SELECT COUNT(*) FROM user_assignments WHERE is_completed = 1").fetchone()[0]
    total_possible = (total_students * total_assignments) if (total_students * total_assignments) > 0 else 1
    class_completion_rate = round((total_completions / total_possible) * 100, 1)

    # Recent activities (student ticks/unticks & join requests)
    recent_activities = conn.execute('''
        SELECT al.*, u.full_name as user_name, u.username, a.title as assignment_title
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.id
        LEFT JOIN assignments a ON al.assignment_id = a.id
        ORDER BY al.created_at DESC
        LIMIT 10
    ''',).fetchall()

    # Batches for filter dropdown in charts
    batches = conn.execute('SELECT * FROM batches ORDER BY name ASC').fetchall()

    # conn.close()

    return render_template(
        'admin_dashboard.html',
        total_students=total_students,
        pending_approvals=pending_approvals,
        total_batches=total_batches,
        total_subjects=total_subjects,
        total_assignments=total_assignments,
        class_completion_rate=class_completion_rate,
        recent_activities=recent_activities,
        batches=batches
    )

@app.route('/api/admin/chart-data')
@admin_required
def admin_chart_data():
    """Returns dynamic data for Chart.js: completed count vs pending count per assignment"""
    batch_id = request.args.get('batch_id', type=int)
    subject_id = request.args.get('subject_id', type=int)

    conn = get_db()

    # Total approved students in batch or overall
    if batch_id:
        total_students = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'student' AND status = 'approved' AND batch_id = ?",
            (batch_id,)
        ).fetchone()[0]
    else:
        total_students = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'student' AND status = 'approved'"
        ).fetchone()[0]

    query = '''
        SELECT a.id, a.title, s.name as subject_name,
               (SELECT COUNT(*) FROM user_assignments ua 
                JOIN users u ON ua.user_id = u.id
                WHERE ua.assignment_id = a.id AND ua.is_completed = 1
                AND u.status = 'approved'
                ''' + ('AND u.batch_id = ? ' if batch_id else '') + ''') as completed_count
        FROM assignments a
        JOIN subjects s ON a.subject_id = s.id
        WHERE 1=1
    '''
    params = []
    if batch_id:
        params.append(batch_id)
        query += ' AND s.batch_id = ?'
        params.append(batch_id)
    if subject_id:
        query += ' AND a.subject_id = ?'
        params.append(subject_id)

    query += ' ORDER BY a.created_at DESC LIMIT 15'

    rows = conn.execute(query, params).fetchall()
    # conn.close()

    labels = []
    completed_data = []
    incomplete_data = []
    completion_rates = []
    assignments_list = []

    for r in rows:
        label = f"{r['title'][:25]}... ({r['subject_name'][:12]})" if len(r['title']) > 25 else f"{r['title']} ({r['subject_name'][:12]})"
        labels.append(label)
        comp = r['completed_count']
        incomp = max(0, total_students - comp)
        rate = round((comp / total_students * 100), 1) if total_students > 0 else 0

        completed_data.append(comp)
        incomplete_data.append(incomp)
        completion_rates.append(rate)

        assignments_list.append({
            'id': r['id'],
            'title': r['title'],
            'subject': r['subject_name'],
            'completed': comp,
            'incomplete': incomp,
            'total_students': total_students,
            'rate': rate
        })

    return jsonify({
        'total_students': total_students,
        'labels': labels,
        'completed': completed_data,
        'incomplete': incomplete_data,
        'rates': completion_rates,
        'assignments': assignments_list
    })

@app.route('/admin/assignment/<int:assignment_id>/students')
@admin_required
def admin_assignment_students(assignment_id):
    """Admin drill-down: see list of all students and their completion status for an assignment"""
    conn = get_db()
    assignment = conn.execute('''
        SELECT a.*, s.name as subject_name, s.batch_id, b.name as batch_name
        FROM assignments a
        JOIN subjects s ON a.subject_id = s.id
        JOIN batches b ON s.batch_id = b.id
        WHERE a.id = ?
    ''', (assignment_id,)).fetchone()

    if not assignment:
        # conn.close()
        flash('Assignment not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    # All approved students eligible for this batch or all
    students = conn.execute('''
        SELECT u.id, u.full_name, u.username, u.email, b.name as batch_name,
               COALESCE(ua.is_completed, 0) as is_completed,
               ua.completed_at
        FROM users u
        LEFT JOIN batches b ON u.batch_id = b.id
        LEFT JOIN user_assignments ua ON u.id = ua.user_id AND ua.assignment_id = ?
        WHERE u.role = 'student' AND u.status = 'approved'
        ORDER BY ua.is_completed DESC, u.full_name ASC
    ''', (assignment_id,)).fetchall()

    # conn.close()

    return render_template(
        'admin_assignment_students.html',
        assignment=assignment,
        students=students
    )

# ----------------- Admin User Management & Approvals -----------------

@app.route('/admin/users')
@admin_required
def admin_users():
    conn = get_db()
    status_filter = request.args.get('status', 'all')
    role_filter = request.args.get('role', 'all')

    query = '''
        SELECT u.*, b.name as batch_name,
               (SELECT COUNT(*) FROM user_assignments ua WHERE ua.user_id = u.id AND ua.is_completed = 1) as completed_count
        FROM users u
        LEFT JOIN batches b ON u.batch_id = b.id
        WHERE 1=1
    '''
    params = []

    if status_filter != 'all':
        query += ' AND u.status = ?'
        params.append(status_filter)
    if role_filter != 'all':
        query += ' AND u.role = ?'
        params.append(role_filter)

    query += ' ORDER BY CASE WHEN u.status = "pending" THEN 0 ELSE 1 END, u.created_at DESC'

    users = conn.execute(query, params).fetchall()
    batches = conn.execute('SELECT * FROM batches ORDER BY name ASC').fetchall()
    # conn.close()

    return render_template(
        'admin_users.html',
        users=users,
        batches=batches,
        current_status=status_filter,
        current_role=role_filter
    )

@app.route('/admin/users/<int:user_id>/action', methods=['POST'])
@admin_required
def admin_user_action(user_id):
    action = request.form.get('action') # 'approve', 'reject', 'suspend', 'activate', 'make_admin', 'make_student', 'change_batch'
    batch_id = request.form.get('batch_id')
    admin_id = session['user_id']

    conn = get_db()
    # Confirm actor is an active verified administrator
    actor = conn.execute('SELECT * FROM users WHERE id = ?', (admin_id,)).fetchone()
    if not actor or actor['role'] != 'admin' or actor['status'] != 'approved':
        flash('Permission Denied: Only administrators have permission to approve, suspend, or assign roles.', 'danger')
        return redirect(url_for('student_dashboard'))

    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_users'))

    # Security rule 1: You cannot suspend, reject, or demote yourself
    if user_id == admin_id and action in ['make_student', 'suspend', 'reject']:
        flash('You cannot demote or suspend your own administrator account.', 'danger')
        return redirect(url_for('admin_users'))

    # Security rule 2: Primary Administrator account is fully protected from suspension or demotion
    if user['is_super_admin'] == 1 and action in ['make_student', 'suspend', 'reject']:
        flash('The Primary Administrator account is protected and cannot be suspended or demoted.', 'danger')
        return redirect(url_for('admin_users'))

    # Security rule 3: Only the Primary Admin can demote another co-admin
    if action == 'make_student' and user['role'] == 'admin' and actor['is_super_admin'] != 1:
        flash('Only the Primary Administrator can demote other administrators.', 'danger')
        return redirect(url_for('admin_users'))

    if action == 'approve':
        conn.execute('''
            UPDATE users 
            SET status = 'approved', approved_at = CURRENT_TIMESTAMP, approved_by = ?,
                batch_id = COALESCE(?, batch_id)
            WHERE id = ?
        ''', (admin_id, batch_id if batch_id else None, user_id))
        flash(f"Account for '{user['full_name']}' has been approved successfully!", 'success')
        log_activity(admin_id, 'user_approved', f"Admin '{actor['full_name']}' approved student '{user['full_name']}' (@{user['username']}).", db_conn=conn)

    elif action == 'reject':
        conn.execute("UPDATE users SET status = 'rejected' WHERE id = ?", (user_id,))
        flash(f"Account request for '{user['full_name']}' was declined.", 'warning')
        log_activity(admin_id, 'user_rejected', f"Admin '{actor['full_name']}' declined registration for '{user['full_name']}'.", db_conn=conn)

    elif action == 'suspend':
        conn.execute("UPDATE users SET status = 'suspended' WHERE id = ?", (user_id,))
        flash(f"Access for '{user['full_name']}' has been suspended.", 'warning')
        log_activity(admin_id, 'user_suspended', f"Admin '{actor['full_name']}' suspended access for '{user['full_name']}'.", db_conn=conn)

    elif action == 'activate':
        conn.execute("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
        flash(f"Access for '{user['full_name']}' has been re-activated.", 'success')
        log_activity(admin_id, 'user_activated', f"Admin '{actor['full_name']}' reactivated access for '{user['full_name']}'.", db_conn=conn)

    elif action == 'make_admin':
        conn.execute("UPDATE users SET role = 'admin', status = 'approved' WHERE id = ?", (user_id,))
        flash(f"'{user['full_name']}' has been promoted to Administrator!", 'success')
        log_activity(admin_id, 'role_changed', f"Admin '{actor['full_name']}' promoted '{user['full_name']}' to Administrator.", db_conn=conn)

    elif action == 'make_student':
        conn.execute("UPDATE users SET role = 'student' WHERE id = ?", (user_id,))
        flash(f"'{user['full_name']}' role changed to Student.", 'info')
        log_activity(admin_id, 'role_changed', f"Admin '{actor['full_name']}' changed '{user['full_name']}' role to Student.", db_conn=conn)

    elif action == 'change_batch':
        conn.execute("UPDATE users SET batch_id = ? WHERE id = ?", (batch_id if batch_id else None, user_id))
        flash(f"Batch updated for '{user['full_name']}'.", 'success')

    conn.commit()
    return redirect(url_for('admin_users'))

# ----------------- Admin Curriculum Management (Batches, Subjects, Assignments) -----------------

@app.route('/admin/curriculum')
@admin_required
def admin_curriculum():
    conn = get_db()
    batches = conn.execute('''
        SELECT b.*, 
               (SELECT COUNT(*) FROM subjects s WHERE s.batch_id = b.id) as subject_count,
               (SELECT COUNT(*) FROM users u WHERE u.batch_id = b.id AND u.status = 'approved') as student_count
        FROM batches b
        ORDER BY b.name ASC
    ''').fetchall()

    subjects = conn.execute('''
        SELECT s.*, b.name as batch_name,
               (SELECT COUNT(*) FROM assignments a WHERE a.subject_id = s.id) as assignment_count
        FROM subjects s
        JOIN batches b ON s.batch_id = b.id
        ORDER BY b.name ASC, s.name ASC
    ''').fetchall()

    assignments = conn.execute('''
        SELECT a.*, s.name as subject_name, s.code as subject_code, b.name as batch_name,
               (SELECT COUNT(*) FROM user_assignments ua WHERE ua.assignment_id = a.id AND ua.is_completed = 1) as completed_count
        FROM assignments a
        JOIN subjects s ON a.subject_id = s.id
        JOIN batches b ON s.batch_id = b.id
        ORDER BY a.deadline ASC
    ''').fetchall()

    # conn.close()
    return render_template(
        'admin_curriculum.html',
        batches=batches,
        subjects=subjects,
        assignments=assignments
    )

@app.route('/admin/batches/create', methods=['POST'])
@admin_required
def admin_create_batch():
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    description = request.form.get('description', '').strip()

    if not name:
        flash('Batch name is required.', 'danger')
        return redirect(url_for('admin_curriculum'))

    conn = get_db()
    try:
        conn.execute('INSERT INTO batches (name, code, description) VALUES (?, ?, ?)', (name, code, description))
        conn.commit()
        flash(f"Batch '{name}' created successfully!", 'success')
    except Exception as e:
        flash(f"Error creating batch: {e}", 'danger')

    return redirect(url_for('admin_curriculum'))

@app.route('/admin/batches/<int:batch_id>/delete', methods=['POST'])
@admin_required
def admin_delete_batch(batch_id):
    conn = get_db()
    conn.execute('DELETE FROM batches WHERE id = ?', (batch_id,))
    conn.commit()
    # conn.close()
    flash('Batch and its associated subjects and assignments removed.', 'info')
    return redirect(url_for('admin_curriculum'))

@app.route('/admin/subjects/create', methods=['POST'])
@admin_required
def admin_create_subject():
    batch_id = request.form.get('batch_id')
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    description = request.form.get('description', '').strip()
    color = request.form.get('color', '#4f46e5')
    icon = request.form.get('icon', 'book-open')

    if not batch_id or not name:
        flash('Batch and Subject name are required.', 'danger')
        return redirect(url_for('admin_curriculum'))

    conn = get_db()
    conn.execute('''
        INSERT INTO subjects (batch_id, name, code, description, color, icon)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (batch_id, name, code, description, color, icon))
    conn.commit()
    # conn.close()

    flash(f"Subject '{name}' added successfully!", 'success')
    return redirect(url_for('admin_curriculum'))

@app.route('/admin/subjects/<int:subject_id>/delete', methods=['POST'])
@admin_required
def admin_delete_subject(subject_id):
    conn = get_db()
    conn.execute('DELETE FROM subjects WHERE id = ?', (subject_id,))
    conn.commit()
    # conn.close()
    flash('Subject and its assignments removed.', 'info')
    return redirect(url_for('admin_curriculum'))

@app.route('/admin/assignments/create', methods=['POST'])
@admin_required
def admin_create_assignment():
    subject_id = request.form.get('subject_id')
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    deadline = request.form.get('deadline') # from datetime-local input
    admin_id = session['user_id']

    if not subject_id or not title or not deadline:
        flash('Subject, assignment title, and deadline are required.', 'danger')
        return redirect(url_for('admin_curriculum'))

    # Format deadline cleanly for sqlite
    deadline_formatted = deadline.replace('T', ' ')
    if len(deadline_formatted) == 16:
        deadline_formatted += ':00'

    # Handle optional attachment file
    attachment_filename = None
    attachment_original_name = None
    attachment_size = None
    attachment_type = None

    if 'attachment' in request.files:
        file = request.files['attachment']
        if file and file.filename.strip():
            orig_name = file.filename.strip()
            ext = os.path.splitext(orig_name)[1].lower()
            safe_base = secure_filename(os.path.splitext(orig_name)[0])
            if not safe_base:
                safe_base = "attachment"
            unique_name = f"{int(datetime.now().timestamp())}_{safe_base}{ext}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
            file.save(file_path)

            attachment_filename = unique_name
            attachment_original_name = orig_name
            attachment_size = os.path.getsize(file_path)
            attachment_type = ext.replace('.', '').upper()

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO assignments (subject_id, title, description, deadline, attachment_filename, attachment_original_name, attachment_size, attachment_type, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (subject_id, title, description, deadline_formatted, attachment_filename, attachment_original_name, attachment_size, attachment_type, admin_id))
    new_assign_id = cursor.lastrowid
    conn.commit()

    # Log activity
    sub_row = conn.execute('SELECT name FROM subjects WHERE id = ?', (subject_id,)).fetchone()
    sub_name = sub_row['name'] if sub_row else ''
    log_activity(admin_id, 'assignment_created', f"New assignment '{title}' added under '{sub_name}' with deadline {deadline_formatted}.", new_assign_id, db_conn=conn)
    conn.commit()
    # conn.close()
    flash(f"Assignment '{title}' scheduled and published with deadline successfully!", 'success')
    return redirect(url_for('admin_curriculum'))

@app.route('/admin/assignments/<int:assignment_id>/delete', methods=['POST'])
@admin_required
def admin_delete_assignment(assignment_id):
    conn = get_db()
    conn.execute('DELETE FROM assignments WHERE id = ?', (assignment_id,))
    conn.commit()
    # conn.close()
    flash('Assignment deleted successfully.', 'info')
    return redirect(url_for('admin_curriculum'))

# ----------------- Admin Real-Time Notifications Feed -----------------

@app.route('/admin/notifications')
@admin_required
def admin_notifications():
    conn = get_db()
    # Mark all as read
    conn.execute('UPDATE activity_logs SET is_read_by_admin = 1 WHERE is_read_by_admin = 0')
    conn.commit()

    activities = conn.execute('''
        SELECT al.*, u.full_name, u.username, a.title as assignment_title
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.id
        LEFT JOIN assignments a ON al.assignment_id = a.id
        ORDER BY al.created_at DESC
        LIMIT 100
    ''').fetchall()
    # conn.close()

    return render_template('admin_notifications.html', activities=activities)

@app.route('/api/admin/notifications/unread-count')
@admin_required
def admin_unread_count():
    conn = get_db()
    row = conn.execute('SELECT COUNT(*) FROM activity_logs WHERE is_read_by_admin = 0').fetchone()
    count = row[0] if row else 0
    # Also fetch the 3 latest unread items for quick toast alert
    recent = conn.execute('''
        SELECT al.*, u.full_name 
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.id
        WHERE al.is_read_by_admin = 0
        ORDER BY al.created_at DESC LIMIT 3
    ''').fetchall()
    # conn.close()

    recent_list = [{'id': r['id'], 'details': r['details'], 'time': r['created_at']} for r in recent]
    return jsonify({'unread_count': count, 'recent': recent_list})

# ----------------- Classroom Polls (Admin create & Student vote) -----------------

@app.route('/polls')
@login_required
@approved_required
def view_polls():
    user_id = session['user_id']
    user_role = session.get('role', 'student')
    conn = get_db()

    user = conn.execute('SELECT batch_id FROM users WHERE id = ?', (user_id,)).fetchone()
    batch_id = user['batch_id'] if user else None

    # Get polls
    polls_query = '''
        SELECT p.*, u.full_name as creator_name,
               (SELECT COUNT(*) FROM poll_votes pv WHERE pv.poll_id = p.id) as total_votes,
               (SELECT pv.option_id FROM poll_votes pv WHERE pv.poll_id = p.id AND pv.user_id = ?) as user_voted_option_id
        FROM polls p
        LEFT JOIN users u ON p.created_by = u.id
        WHERE p.is_active = 1
    '''
    params = [user_id]
    if user_role != 'admin' and batch_id:
        polls_query += ' AND (p.batch_id IS NULL OR p.batch_id = ?)'
        params.append(batch_id)

    polls_query += ' ORDER BY p.created_at DESC'
    polls_raw = conn.execute(polls_query, params).fetchall()

    polls = []
    for p in polls_raw:
        p_dict = dict(p)
        # Fetch options with vote counts
        options = conn.execute('''
            SELECT po.*, 
                   COUNT(pv.id) as vote_count
            FROM poll_options po
            LEFT JOIN poll_votes pv ON po.id = pv.option_id
            WHERE po.poll_id = ?
            GROUP BY po.id
            ORDER BY po.id ASC
        ''', (p['id'],)).fetchall()

        total = p_dict['total_votes']
        options_list = []
        for opt in options:
            o_dict = dict(opt)
            o_dict['pct'] = round((o_dict['vote_count'] / total * 100), 1) if total > 0 else 0
            options_list.append(o_dict)

        p_dict['options'] = options_list
        polls.append(p_dict)

    batches = conn.execute('SELECT * FROM batches ORDER BY name ASC').fetchall()
    # conn.close()

    return render_template('polls.html', polls=polls, batches=batches)

@app.route('/polls/create', methods=['POST'])
@admin_required
def create_poll():
    question = request.form.get('question', '').strip()
    batch_id = request.form.get('batch_id')
    options = request.form.getlist('options[]')
    admin_id = session['user_id']

    # Filter out empty options
    options = [opt.strip() for opt in options if opt.strip()]

    if not question or len(options) < 2:
        flash('Poll must have a question and at least 2 options.', 'danger')
        return redirect(url_for('view_polls'))

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO polls (question, batch_id, created_by)
        VALUES (?, ?, ?)
    ''', (question, batch_id if batch_id else None, admin_id))
    poll_id = cursor.lastrowid

    for opt_text in options:
        cursor.execute('''
            INSERT INTO poll_options (poll_id, option_text)
            VALUES (?, ?)
        ''', (poll_id, opt_text))

    conn.commit()
    # conn.close()

    flash('New poll published to the classroom!', 'success')
    return redirect(url_for('view_polls'))

@app.route('/polls/<int:poll_id>/vote', methods=['POST'])
@login_required
@approved_required
def vote_poll(poll_id):
    user_id = session['user_id']
    option_id = request.form.get('option_id', type=int)

    if not option_id:
        flash('Please select an option to vote.', 'warning')
        return redirect(url_for('view_polls'))

    conn = get_db()
    # Check if poll is active
    poll = conn.execute('SELECT is_active FROM polls WHERE id = ?', (poll_id,)).fetchone()
    if not poll or not poll['is_active']:
        # conn.close()
        flash('This poll is closed or not available.', 'danger')
        return redirect(url_for('view_polls'))

    try:
        conn.execute('''
            INSERT INTO poll_votes (poll_id, option_id, user_id)
            VALUES (?, ?, ?)
            ON CONFLICT(poll_id, user_id) DO UPDATE SET option_id = excluded.option_id, voted_at = CURRENT_TIMESTAMP
        ''', (poll_id, option_id, user_id))
        conn.commit()
        flash('Your vote has been recorded!', 'success')
    except Exception as e:
        flash(f'Error voting: {e}', 'danger')

    return redirect(url_for('view_polls'))

@app.route('/polls/<int:poll_id>/toggle', methods=['POST'])
@admin_required
def toggle_poll(poll_id):
    conn = get_db()
    conn.execute('UPDATE polls SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?', (poll_id,))
    conn.commit()
    # conn.close()
    flash('Poll status updated.', 'info')
    return redirect(url_for('view_polls'))

# ----------------- Classroom Broadcasts / Announcements -----------------

@app.route('/announcements')
@login_required
@approved_required
def view_announcements():
    user_id = session['user_id']
    user_role = session.get('role', 'student')
    conn = get_db()

    user = conn.execute('SELECT batch_id FROM users WHERE id = ?', (user_id,)).fetchone()
    batch_id = user['batch_id'] if user else None

    query = '''
        SELECT a.*, u.full_name as author_name, b.name as batch_name
        FROM announcements a
        LEFT JOIN users u ON a.created_by = u.id
        LEFT JOIN batches b ON a.batch_id = b.id
        WHERE 1=1
    '''
    params = []
    if user_role != 'admin' and batch_id:
        query += ' AND (a.batch_id IS NULL OR a.batch_id = ?)'
        params.append(batch_id)

    query += ' ORDER BY a.is_pinned DESC, a.created_at DESC'
    announcements = conn.execute(query, params).fetchall()
    batches = conn.execute('SELECT * FROM batches ORDER BY name ASC').fetchall()
    # conn.close()

    return render_template('announcements.html', announcements=announcements, batches=batches)

@app.route('/announcements/create', methods=['POST'])
@admin_required
def create_announcement():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    batch_id = request.form.get('batch_id')
    is_pinned = 1 if request.form.get('is_pinned') else 0
    image_url = request.form.get('image_url', '').strip()
    admin_id = session['user_id']

    if not title or not content:
        flash('Announcement title and content are required.', 'danger')
        return redirect(url_for('view_announcements'))

    conn = get_db()
    conn.execute('''
        INSERT INTO announcements (title, content, image_url, is_pinned, batch_id, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (title, content, image_url if image_url else None, is_pinned, batch_id if batch_id else None, admin_id))
    conn.commit()
    # conn.close()

    flash('Announcement broadcasted to the classroom successfully!', 'success')
    return redirect(url_for('view_announcements'))

@app.route('/announcements/<int:announcement_id>/delete', methods=['POST'])
@admin_required
def delete_announcement(announcement_id):
    conn = get_db()
    conn.execute('DELETE FROM announcements WHERE id = ?', (announcement_id,))
    conn.commit()
    # conn.close()
    flash('Announcement deleted.', 'info')
    return redirect(url_for('view_announcements'))

# ----------------- Profile / Password Change -----------------

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_id = session['user_id']
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not full_name:
            flash('Full name cannot be empty.', 'danger')
            # conn.close()
            return render_template('profile.html', user=user)

        conn.execute('UPDATE users SET full_name = ? WHERE id = ?', (full_name, user_id))
        session['full_name'] = full_name

        if new_password:
            if not check_password_hash(user['password_hash'], current_password):
                # conn.close()
                flash('Current password is incorrect.', 'danger')
                return render_template('profile.html', user=user)

            if len(new_password) < 6:
                # conn.close()
                flash('New password must be at least 6 characters long.', 'danger')
                return render_template('profile.html', user=user)

            if new_password != confirm_password:
                # conn.close()
                flash('New passwords do not match.', 'danger')
                return render_template('profile.html', user=user)

            new_hash = generate_password_hash(new_password)
            conn.execute('UPDATE users SET password_hash = ? WHERE id = ?', (new_hash, user_id))
            flash('Password updated successfully!', 'success')

        conn.commit()
        # conn.close()
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('profile'))

    # conn.close()
    return render_template('profile.html', user=user)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
