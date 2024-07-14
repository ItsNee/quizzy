from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import random
import os
import pandas as pd

app = Flask(__name__)
app.secret_key = os.urandom(24)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Use relative paths for database and upload folder
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_DIR = os.path.join(BASE_DIR, 'data')
DATABASE = os.path.join(DATABASE_DIR, 'quiz.db')
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
ALLOWED_EXTENSIONS = {'csv'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the data and upload directories exist
os.makedirs(DATABASE_DIR, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Add .gitkeep files to the data and uploads directories to ensure they are tracked by git
gitkeep_data_path = os.path.join(DATABASE_DIR, '.gitkeep')
gitkeep_uploads_path = os.path.join(UPLOAD_FOLDER, '.gitkeep')

with open(gitkeep_data_path, 'w') as f:
    pass

with open(gitkeep_uploads_path, 'w') as f:
    pass

def create_empty_db():
    if not os.path.exists(DATABASE):
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            score INTEGER,
            total_questions INTEGER,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            option1 TEXT,
            option2 TEXT,
            option3 TEXT,
            option4 TEXT,
            option5 TEXT,
            answer INTEGER,
            image TEXT
        )
        ''')
        conn.commit()
        conn.close()

create_empty_db()

def get_db():
    try:
        db = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        return db
    except sqlite3.OperationalError as e:
        print(f"Error opening database: {e}")
        return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    if db:
        user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        if user:
            return User(user['id'], user['username'], user['password'])
    return None

class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

@app.route('/')
@login_required
def quiz():
    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('SELECT * FROM questions')
        questions = cursor.fetchall()
        random.shuffle(questions)
        return render_template('quiz.html', questions=questions)
    else:
        flash('Error connecting to the database.', 'error')
        return render_template('quiz.html', questions=[])

@app.route('/submit', methods=['POST'])
@login_required
def submit():
    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('SELECT * FROM questions')
        questions = cursor.fetchall()

        correct_answers = {q['id']: q['answer'] for q in questions}
        user_answers = {int(k[1:]): int(v) for k, v in request.form.items()}

        if len(user_answers) != len(correct_answers):
            flash('Please answer all questions before submitting.', 'error')
            return redirect(url_for('quiz'))

        score = sum(1 for q_id, ans in user_answers.items() if ans == correct_answers[q_id])
        total_questions = len(correct_answers)

        cursor.execute('INSERT INTO results (user_id, score, total_questions) VALUES (?, ?, ?)', (current_user.id, score, total_questions))
        db.commit()

        return render_template('result.html', score=score, total=total_questions)
    else:
        flash('Error connecting to the database.', 'error')
        return redirect(url_for('quiz'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        if db:
            user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if user and check_password_hash(user['password'], password):
                login_user(User(user['id'], user['username'], user['password']))
                return redirect(url_for('quiz'))
            flash('Invalid username or password', 'error')
        else:
            flash('Error connecting to the database.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        if db:
            user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if user:
                flash('Username already exists', 'error')
            else:
                hashed_password = generate_password_hash(password, method='sha256')
                db.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
                db.commit()
                flash('Registration successful, please log in', 'success')
                return redirect(url_for('login'))
        else:
            flash('Error connecting to the database.', 'error')
    return render_template('register.html')

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_file():
    if current_user.username != 'admin':
        flash('You do not have permission to access this page.', 'error')
        return redirect(url_for('quiz'))
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            load_csv_to_db(file_path)
            flash('File successfully uploaded and database updated.', 'success')
            return redirect(url_for('quiz'))
    return render_template('upload.html')

def load_csv_to_db(file_path):
    db = get_db()
    if db:
        df = pd.read_csv(file_path)
        for _, row in df.iterrows():
            db.execute('''
            INSERT INTO questions (question, option1, option2, option3, option4, option5, answer, image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (row['Question'], row['1'], row['2'], row['3'], row['4'], row['5'], row['Answer'], row['Image']))
        db.commit()
    else:
        flash('Error connecting to the database.', 'error')

if __name__ == '__main__':
    app.run(debug=True)
