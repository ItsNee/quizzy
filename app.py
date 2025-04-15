import json
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
import sqlite3
import random
import os
import secrets
import pandas as pd
from passlib.hash import sha256_crypt
from models import create_tables  # Import the create_tables function

app = Flask(__name__)
app = Flask(__name__, static_url_path='/static', static_folder='static/')
app.secret_key = os.urandom(24)

# Setup login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.unauthorized_handler
def unauthorized():
    flash('Please log in to access this page.', 'info')
    return redirect(url_for('login'))

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

# Define the path for the registration code file
REG_CODE_FILE = os.path.join(BASE_DIR, 'registration_code.txt')

# Generate a registration code if it doesn't exist
if not os.path.exists(REG_CODE_FILE):
    with open(REG_CODE_FILE, 'w') as f:
        reg_code = secrets.token_urlsafe(16)  # Generate a secure random token
        f.write(reg_code)

# Read the registration code from the file
with open(REG_CODE_FILE, 'r') as f:
    REGISTRATION_CODE = f.read().strip()

# Initialize the database
create_tables()

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
def quizzes():
    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('SELECT * FROM quizzes')
        quizzes = cursor.fetchall()

        quizzes_list = []
        for quiz in quizzes:
            quiz_dict = dict(quiz)
            cursor.execute('''
                SELECT COUNT(*) as attempt_count FROM user_progress
                WHERE user_id = ? AND quiz_id = ?
            ''', (current_user.id, quiz['id']))
            result = cursor.fetchone()
            quiz_dict['attempted'] = result['attempt_count'] > 0
            quizzes_list.append(quiz_dict)
        return render_template('quizzes.html', quizzes=quizzes_list)
    else:
        flash('Error connecting to the database.', 'error')
        return render_template('quizzes.html', quizzes=[])

@app.route('/quiz/<int:quiz_id>/question/<int:question_num>', methods=['GET', 'POST'])
@login_required
def quiz_question(quiz_id, question_num):
    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('SELECT * FROM questions WHERE quiz_id = ?', (quiz_id,))
        all_questions = cursor.fetchall()
        questions_list = [dict(q) for q in all_questions]
        
        # Initialize question order if it doesn't exist
        quiz_key = f'quiz_{quiz_id}_order'
        if quiz_key not in session:
            # Generate a randomized question order
            question_order = list(range(len(questions_list)))
            random.shuffle(question_order)
            session[quiz_key] = question_order
            
            # Initialize dictionaries to store option orders and mappings
            option_orders = {}
            option_mappings = {}
            
            for q in questions_list:
                # Get number of valid options (some questions might not have option5)
                num_options = 4
                if q['option5']:
                    num_options = 5
                
                # Create and shuffle option order for all questions
                opt_order = list(range(1, num_options + 1))
                random.shuffle(opt_order)
                option_orders[str(q['id'])] = opt_order
                
                # Create a mapping from randomized position to original position
                mapping = {}
                for new_pos, orig_pos in enumerate(opt_order, 1):
                    mapping[str(new_pos)] = orig_pos
                option_mappings[str(q['id'])] = mapping
            
            # Store the mappings in the database
            cursor.execute('''
                INSERT OR REPLACE INTO user_quiz_state 
                (user_id, quiz_id, option_orders, option_mappings)
                VALUES (?, ?, ?, ?)
            ''', (
                current_user.id, 
                quiz_id,
                json.dumps(option_orders),
                json.dumps(option_mappings)
            ))
            db.commit()
        
        question_order = session[quiz_key]
        
        # Retrieve option orders and mappings from database
        cursor.execute('''
            SELECT option_orders, option_mappings 
            FROM user_quiz_state
            WHERE user_id = ? AND quiz_id = ?
        ''', (current_user.id, quiz_id))
        
        quiz_state = cursor.fetchone()
        if not quiz_state:
            flash('Error retrieving quiz state.', 'error')
            return redirect(url_for('quizzes'))
            
        option_orders = json.loads(quiz_state['option_orders'])
        option_mappings = json.loads(quiz_state['option_mappings'])
        
        if question_num < 1 or question_num > len(questions_list):
            flash('Invalid question number.', 'error')
            return redirect(url_for('quizzes'))
        
        # Get the question based on the randomized order
        randomized_idx = question_order[question_num - 1]
        original_question = questions_list[randomized_idx]
        question = dict(original_question)  # Create a copy to modify
        
        # Get the option order for this question
        question_id_str = str(question['id'])
        opt_order = option_orders[question_id_str]
        opt_mapping = option_mappings[question_id_str]
        
        if request.method == 'POST':
            if question['multiple'] == 1:
                # For multiple choice, get all selected options
                selected_options = request.form.getlist(f'q{question["id"]}')
                
                # Map each selected randomized option back to its original position
                original_selected = []
                for opt in selected_options:
                    # Convert back to the original option number using our mapping
                    original_opt = opt_mapping[opt]
                    original_selected.append(str(original_opt))
                
                # Sort the selected options to ensure consistent comparison
                original_selected.sort()
                answer = ''.join(original_selected)
            else:
                # For single choice questions
                selected_option = request.form.get(f'q{question["id"]}')
                if selected_option:
                    # Map the randomized option back to its original position
                    original_opt = opt_mapping[selected_option]
                    answer = str(original_opt)
                else:
                    answer = ""
            
            cursor.execute('''
                INSERT OR REPLACE INTO user_progress (user_id, quiz_id, question_id, answer)
                VALUES (?, ?, ?, ?)
                ''', (current_user.id, quiz_id, question['id'], answer))
            db.commit()
            
            if request.form['action'] == 'save':
                flash('Progress saved.', 'success')
                return redirect(url_for('quiz_question', quiz_id=quiz_id, question_num=question_num))
            
            if request.form['action'] == 'rev':
                original_answer = str(original_question['answer'])
                
                if original_question['multiple'] == 1:
                    # Handle multiple choice questions
                    correct_options = []
                    for digit in original_answer:
                        if digit.isdigit():
                            correct_options.append(int(digit))
                    
                    correct_texts = [original_question[f'option{opt}'] for opt in correct_options]
                    
                    if answer == original_answer:
                        flash(f"You are correct!", 'success')
                    else:
                        flash(f"You are wrong! The correct answers are: {' and '.join(correct_texts)}", 'danger')
                else:
                    # Handle single choice questions
                    if answer == original_answer:
                        flash(f"You are correct!", 'success')
                    else:
                        flash(f"You are wrong! The correct answer is {original_question[f'option{original_answer}']}", 'danger')
                
                return redirect(url_for('quiz_question', quiz_id=quiz_id, question_num=question_num))
            
            elif request.form['action'] == 'next':
                if question_num == len(questions_list):
                    return redirect(url_for('quiz_summary', quiz_id=quiz_id))
                else:
                    return redirect(url_for('quiz_question', quiz_id=quiz_id, question_num=question_num + 1))

        # Check if the user has already answered this question
        cursor.execute('''
            SELECT answer FROM user_progress
            WHERE user_id = ? AND quiz_id = ? AND question_id = ?
        ''', (current_user.id, quiz_id, question['id']))
        progress = cursor.fetchone()
        
        # Create a randomized version of the question for display
        randomized_question = dict(question)
        
        # Rearrange options according to the pre-generated order
        for i, opt_idx in enumerate(opt_order, 1):
            option_key = f'option{i}'
            orig_key = f'option{opt_idx}'
            if orig_key in question and question[orig_key]:  # Only copy if the option exists
                randomized_question[option_key] = question[orig_key]
        
        # Create a field to track user's previous answers in the randomized view
        user_selections = []
        if progress and question['multiple'] == 1 and progress['answer']:
            original_selected = progress['answer']
            # For each digit in the answer string, find its current position in the randomized view
            for digit in original_selected:
                if digit.isdigit():  # Ensure it's a digit before processing
                    # Find where this original option appears in the randomized order
                    for new_pos, orig_pos in opt_mapping.items():
                        if orig_pos == int(digit):
                            user_selections.append(new_pos)
        
        # Convert option_mapping values to strings for template
        template_opt_mapping = {str(k): str(v) for k, v in opt_mapping.items()}

        return render_template(
            'quiz_question.html', 
            question=randomized_question, 
            question_num=question_num, 
            total_questions=len(questions_list), 
            progress=progress, 
            quiz_id=quiz_id,
            user_selections=user_selections,
            option_mapping=template_opt_mapping
        )
    else:
        flash('Error connecting to the database.', 'error')
        return redirect(url_for('quizzes'))

@app.route('/get_answer', methods=['GET'])
def get_answer():
    answer = 2
    return '<div class="card-body"><p>Answer is, ' + str(answer) + '</p></div>'

@app.route('/resume_quiz/<int:quiz_id>', methods=['GET'])
@login_required
def resume_quiz(quiz_id):
    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('''
            SELECT question_id FROM user_progress
            WHERE user_id = ? AND quiz_id = ?
        ''', (current_user.id, quiz_id))
        progress = cursor.fetchall()

        if progress:
            answered_questions = {p['question_id'] for p in progress}
            cursor.execute('SELECT id FROM questions WHERE quiz_id = ? ORDER BY id', (quiz_id,))
            questions = cursor.fetchall()
            for i, question in enumerate(questions, start=1):
                if question['id'] not in answered_questions:
                    return redirect(url_for('quiz_question', quiz_id=quiz_id, question_num=i))
            return redirect(url_for('quiz_summary', quiz_id=quiz_id))
        else:
            return redirect(url_for('quiz_question', quiz_id=quiz_id, question_num=1))
    else:
        flash('Error connecting to the database.', 'error')
        return redirect(url_for('quizzes'))

@app.route('/restart_quiz/<int:quiz_id>', methods=['POST'])
@login_required
def restart_quiz(quiz_id):
    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('DELETE FROM user_progress WHERE user_id = ? AND quiz_id = ?', (current_user.id, quiz_id))
        cursor.execute('DELETE FROM user_quiz_state WHERE user_id = ? AND quiz_id = ?', (current_user.id, quiz_id))
        db.commit()
        
        # Clear only the question order from session
        if f'quiz_{quiz_id}_order' in session:
            session.pop(f'quiz_{quiz_id}_order')
            
        flash('Quiz has been restarted.', 'success')
    else:
        flash('Error connecting to the database.', 'error')
    return redirect(url_for('quiz_question', quiz_id=quiz_id, question_num=1))

@app.route('/quiz/<int:quiz_id>/summary', methods=['GET'])
@login_required
def quiz_summary(quiz_id):
    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('SELECT * FROM questions WHERE quiz_id = ?', (quiz_id,))
        questions = cursor.fetchall()
        
        correct_answers = {q['id']: q['answer'] for q in questions}
        cursor.execute('''
            SELECT question_id, answer FROM user_progress
            WHERE user_id = ? AND quiz_id = ?
        ''', (current_user.id, quiz_id))
        user_answers = cursor.fetchall()

        score = sum(1 for answer in user_answers if str(answer['answer']) == str(correct_answers[answer['question_id']]))
        total_questions = len(questions)

        # Save the results with timestamp
        cursor.execute('''
            INSERT OR REPLACE INTO results (user_id, quiz_id, score, total_questions, timestamp)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (current_user.id, quiz_id, score, total_questions))
        db.commit()
        
        # Clear the session data for this quiz
        if f'quiz_{quiz_id}_order' in session:
            session.pop(f'quiz_{quiz_id}_order')
            
        # Remove the quiz state from database
        cursor.execute('DELETE FROM user_quiz_state WHERE user_id = ? AND quiz_id = ?', 
                      (current_user.id, quiz_id))
        db.commit()

        return render_template('quiz_summary.html', score=score, total_questions=total_questions)
    else:
        flash('Error connecting to the database.', 'error')
        return redirect(url_for('quizzes'))

@app.route('/past_attempts', methods=['GET'])
@login_required
def past_attempts():
    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('''
            SELECT quizzes.name AS quiz_name, results.score, results.total_questions, results.timestamp
            FROM results
            JOIN quizzes ON results.quiz_id = quizzes.id
            WHERE results.user_id = ?
            ORDER BY results.timestamp DESC
        ''', (current_user.id,))
        attempts = cursor.fetchall()
        return render_template('past_attempts.html', attempts=attempts)
    else:
        flash('Error connecting to the database.', 'error')
        return redirect(url_for('quizzes'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        if db:
            user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if user and sha256_crypt.verify(password, user['password']):
                login_user(User(user['id'], user['username'], user['password']))
                return redirect(url_for('quizzes'))
            flash('Invalid username or password', 'danger')
        else:
            flash('Error connecting to the database.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    # Clear all session data
    session.clear()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        reg_code = request.form['reg_code']

        if reg_code != REGISTRATION_CODE:
            flash('Invalid registration code', 'danger')
            return render_template('register.html')

        db = get_db()
        if db:
            user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
            if user:
                flash('Username already exists', 'danger')
            else:
                hashed_password = sha256_crypt.hash(password)
                db.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
                db.commit()
                flash('Registration successful, please log in', 'success')
                return redirect(url_for('login'))
        else:
            flash('Error connecting to the database.', 'danger')
    return render_template('register.html')

@app.route('/import_quiz', methods=['GET', 'POST'])
@login_required
def import_quiz():
    if current_user.username != 'admin':
        flash('You do not have permission to access this page.', 'error')
        return redirect(url_for('quizzes'))
    
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
            quiz_name = request.form.get('quiz_name')
            load_csv_to_db(file_path, quiz_name)
            flash('File successfully uploaded and database updated.', 'success')
            return redirect(url_for('quizzes'))
    return render_template('upload.html')

def load_csv_to_db(file_path, quiz_name):
    db = get_db()
    if db:
        df = pd.read_csv(file_path)
        df.columns = df.columns.str.strip()  # Remove any leading/trailing whitespace
        df.columns = df.columns.str.lower()  # Convert to lowercase for uniformity

        # Rename columns to match the expected column names
        df = df.rename(columns={
            'question': 'question',
            '1': 'option1',
            '2': 'option2',
            '3': 'option3',
            '4': 'option4',
            '5': 'option5',
            'answer': 'answer',
            'image': 'image',
            'multiple': 'multiple'
        })
        
        # Convert 'multiple' column to INTEGER (0 or 1)
        # Handle various possible formats in the CSV
        if 'multiple' in df.columns:
            # Convert different formats to 0/1
            df['multiple'] = df['multiple'].apply(
                lambda x: 1 if str(x).lower() in ['true', '1', 't', 'yes', 'y'] else 0
            )
        else:
            # Default to single choice if not specified
            df['multiple'] = 0
        
        # Insert the quiz into the quizzes table
        cursor = db.cursor()
        cursor.execute('INSERT INTO quizzes (name) VALUES (?)', (quiz_name,))
        quiz_id = cursor.lastrowid
        
        for _, row in df.iterrows():
            # Ensure answer is TEXT
            answer = str(row['answer'])
            
            cursor.execute('''
            INSERT INTO questions (quiz_id, question, option1, option2, option3, option4, option5, answer, image, multiple)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (quiz_id, row['question'], row['option1'], row['option2'], row['option3'], row['option4'], row['option5'], answer, row['image'], row['multiple']))
        db.commit()
    else:
        flash('Error connecting to the database.', 'error')

@app.route('/delete_quiz/<int:quiz_id>', methods=['POST'])
@login_required
def delete_quiz(quiz_id):
    if current_user.username != 'admin':
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('quizzes'))
    
    db = get_db()
    if db:
        cursor = db.cursor()
        # Delete associated user_quiz_state
        cursor.execute('DELETE FROM user_quiz_state WHERE quiz_id = ?', (quiz_id,))
        # Delete associated results
        cursor.execute('DELETE FROM results WHERE quiz_id = ?', (quiz_id,))
        # Delete associated user_progress
        cursor.execute('DELETE FROM user_progress WHERE quiz_id = ?', (quiz_id,))
        # Delete associated questions
        cursor.execute('DELETE FROM questions WHERE quiz_id = ?', (quiz_id,))
        # Delete the quiz
        cursor.execute('DELETE FROM quizzes WHERE id = ?', (quiz_id,))
        db.commit()
        flash('Quiz successfully deleted.', 'success')
    else:
        flash('Error connecting to the database.', 'error')
    
    return redirect(url_for('quizzes'))

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    if current_user.username != 'admin':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('quizzes'))

    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('SELECT * FROM quizzes')
        quizzes = cursor.fetchall()
        
        cursor.execute('SELECT * FROM users')
        users = cursor.fetchall()

        if request.method == 'POST':
            if 'regenerate_code' in request.form:
                new_code = regenerate_registration_code()
                global REGISTRATION_CODE
                REGISTRATION_CODE = new_code
                flash('Registration code regenerated successfully.', 'success')
            elif 'file' in request.files:
                file = request.files['file']
                if file.filename == '':
                    flash('No selected file', 'error')
                    return redirect(request.url)
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    quiz_name = request.form.get('quiz_name')
                    load_csv_to_db(file_path, quiz_name)
                    flash('File successfully uploaded and database updated.', 'success')
                    return redirect(url_for('admin'))

        return render_template('admin.html', quizzes=quizzes, users=users, registration_code=REGISTRATION_CODE)
    else:
        flash('Error connecting to the database.', 'danger')
        return redirect(url_for('quizzes'))

def regenerate_registration_code():
    new_code = secrets.token_urlsafe(16)
    with open(REG_CODE_FILE, 'w') as f:
        f.write(new_code)
    return new_code

@app.route('/admin/quiz/<int:quiz_id>/edit', methods=['GET'])
@login_required
def edit_quiz(quiz_id):
    if current_user.username != 'admin':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('quizzes'))

    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('SELECT * FROM questions WHERE quiz_id = ?', (quiz_id,))
        questions = cursor.fetchall()

        return render_template('edit_quiz.html', questions=questions, quiz_id=quiz_id)
    else:
        flash('Error connecting to the database.', 'danger')
        return redirect(url_for('admin'))

@app.route('/admin/quiz/<int:quiz_id>/edit/<int:question_id>', methods=['GET', 'POST'])
@login_required
def edit_question(quiz_id, question_id):
    if current_user.username != 'admin':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('quizzes'))

    db = get_db()
    if db:
        cursor = db.cursor()
        if request.method == 'POST':
            question = request.form['question']
            option1 = request.form['option1']
            option2 = request.form['option2']
            option3 = request.form['option3']
            option4 = request.form['option4']
            option5 = request.form['option5']
            answer = request.form['answer']
            image = request.form['image']
            multiple = 1 if 'multiple' in request.form else 0

            cursor.execute('''
                UPDATE questions
                SET question = ?, option1 = ?, option2 = ?, option3 = ?, option4 = ?, option5 = ?, 
                    answer = ?, image = ?, multiple = ?
                WHERE id = ? AND quiz_id = ?
            ''', (question, option1, option2, option3, option4, option5, answer, image, multiple, question_id, quiz_id))
            db.commit()
            
            # Delete associated user progress to prevent inconsistencies
            cursor.execute('DELETE FROM user_progress WHERE question_id = ?', (question_id,))
            db.commit()
            
            flash('Question updated successfully.', 'success')
            return redirect(url_for('edit_quiz', quiz_id=quiz_id))

        cursor.execute('SELECT * FROM questions WHERE id = ? AND quiz_id = ?', (question_id, quiz_id))
        question = cursor.fetchone()

        return render_template('edit_question.html', question=question, quiz_id=quiz_id)
    else:
        flash('Error connecting to the database.', 'danger')
        return redirect(url_for('admin'))

@app.route('/admin/user/<int:user_id>/attempts', methods=['GET'])
@login_required
def user_attempts(user_id):
    if current_user.username != 'admin':
        flash('You do not have permission to access this page.', 'danger')
        return redirect(url_for('quizzes'))

    db = get_db()
    if db:
        cursor = db.cursor()
        cursor.execute('''
            SELECT quizzes.name AS quiz_name, results.score, results.total_questions, results.timestamp
            FROM results
            JOIN quizzes ON results.quiz_id = quizzes.id
            WHERE results.user_id = ?
            ORDER BY results.timestamp DESC
        ''', (user_id,))
        attempts = cursor.fetchall()
        
        cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()

        return render_template('user_attempts.html', attempts=attempts, username=user['username'])
    else:
        flash('Error connecting to the database.', 'danger')
        return redirect(url_for('admin'))


if __name__ == '__main__':
    print(f"Registration Code: {REGISTRATION_CODE}")
    app.run(host='0.0.0.0', port=80)