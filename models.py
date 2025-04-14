import sqlite3

DATABASE = 'data/quiz.db'

def create_tables():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS quizzes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    )
    ''')
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
        quiz_id INTEGER,
        score INTEGER,
        total_questions INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_id INTEGER,
        question TEXT,
        option1 TEXT,
        option2 TEXT,
        option3 TEXT,
        option4 TEXT,
        option5 TEXT,
        answer INTEGER,
        image TEXT,
        multiple TEXT,
        FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_progress (
        user_id INTEGER,
        quiz_id INTEGER,
        question_id INTEGER,
        answer INTEGER,
        PRIMARY KEY (user_id, quiz_id, question_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (quiz_id) REFERENCES quizzes (id),
        FOREIGN KEY (question_id) REFERENCES questions (id)
    )
    ''')
    conn.commit()
    conn.close()

if __name__ == '__main__':
    create_tables()
