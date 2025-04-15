import sqlite3
import os

# Use the same hardcoded path as the original
DATABASE = 'data/quiz.db'

def create_tables():
    # Ensure the data directory exists
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Create quizzes table (keeping original definition)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS quizzes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL
    )
    ''')
    
    # Create users table (keeping original definition)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    ''')
    
    # Create results table (keeping original definition)
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
    
    # Update questions table - change answer to TEXT to accommodate multiple answers
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
        answer TEXT,  -- Changed from INTEGER to TEXT to store multiple answers
        image TEXT,
        multiple INTEGER,  -- Change from TEXT to INTEGER for proper boolean handling
        FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
    )
    ''')
    
    # Update user_progress table - change answer to TEXT
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_progress (
        user_id INTEGER,
        quiz_id INTEGER,
        question_id INTEGER,
        answer TEXT,  -- Changed from INTEGER to TEXT
        PRIMARY KEY (user_id, quiz_id, question_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (quiz_id) REFERENCES quizzes (id),
        FOREIGN KEY (question_id) REFERENCES questions (id)
    )
    ''')
    
    # Add the new table for storing randomization data
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_quiz_state (
        user_id INTEGER,
        quiz_id INTEGER,
        option_orders TEXT,  -- JSON string for option orders
        option_mappings TEXT,  -- JSON string for option mappings
        PRIMARY KEY (user_id, quiz_id),
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
    )
    ''')
    
    # Try to update existing data if needed
    try:
        # Check if answer column in questions table is INTEGER
        cursor.execute("PRAGMA table_info(questions)")
        columns = cursor.fetchall()
        for col in columns:
            if col[1] == 'answer' and col[2] != 'TEXT':
                # Create a temporary backup table
                cursor.execute("CREATE TABLE questions_backup AS SELECT * FROM questions")
                
                # Drop the original table
                cursor.execute("DROP TABLE questions")
                
                # Create new table with TEXT for answer
                cursor.execute('''
                CREATE TABLE questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quiz_id INTEGER,
                    question TEXT,
                    option1 TEXT,
                    option2 TEXT,
                    option3 TEXT,
                    option4 TEXT,
                    option5 TEXT,
                    answer TEXT,
                    image TEXT,
                    multiple INTEGER,
                    FOREIGN KEY (quiz_id) REFERENCES quizzes (id)
                )
                ''')
                
                # Copy data back, converting answer to TEXT
                cursor.execute('''
                INSERT INTO questions 
                SELECT id, quiz_id, question, option1, option2, option3, option4, option5, 
                       CAST(answer AS TEXT), image, 
                       CASE WHEN multiple = 'True' THEN 1 ELSE 0 END
                FROM questions_backup
                ''')
                
                # Drop the backup table
                cursor.execute("DROP TABLE questions_backup")
                break
                
        # Check if answer column in user_progress table is INTEGER
        cursor.execute("PRAGMA table_info(user_progress)")
        columns = cursor.fetchall()
        for col in columns:
            if col[1] == 'answer' and col[2] != 'TEXT':
                # Create a temporary backup table
                cursor.execute("CREATE TABLE user_progress_backup AS SELECT * FROM user_progress")
                
                # Drop the original table
                cursor.execute("DROP TABLE user_progress")
                
                # Create new table with TEXT for answer
                cursor.execute('''
                CREATE TABLE user_progress (
                    user_id INTEGER,
                    quiz_id INTEGER,
                    question_id INTEGER,
                    answer TEXT,
                    PRIMARY KEY (user_id, quiz_id, question_id),
                    FOREIGN KEY (user_id) REFERENCES users (id),
                    FOREIGN KEY (quiz_id) REFERENCES quizzes (id),
                    FOREIGN KEY (question_id) REFERENCES questions (id)
                )
                ''')
                
                # Copy data back, converting answer to TEXT
                cursor.execute('''
                INSERT INTO user_progress 
                SELECT user_id, quiz_id, question_id, CAST(answer AS TEXT)
                FROM user_progress_backup
                ''')
                
                # Drop the backup table
                cursor.execute("DROP TABLE user_progress_backup")
                break
    except Exception as e:
        print(f"Error during data migration: {e}")
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    create_tables()