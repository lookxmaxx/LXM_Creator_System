from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from pushbullet import Pushbullet
import os
import io
import pandas as pd
from werkzeug.utils import secure_filename
from flask_cors import CORS
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse
import csv
import logging

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)

UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Allowed Extensions for CSV
ALLOWED_EXTENSIONS = {'csv'}

# Load environment variables
load_dotenv()
app.secret_key = os.getenv("SECRET_KEY")
MANAGER_PASSWORD = os.getenv("MANAGER_PASSWORD")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS

# Load Pushbullet API Key from environment variable
PUSHBULLET_API_KEY = "o.xO7PqwaZwbkTRUVsrupPjifLOkTlWsn4"
pb = Pushbullet(PUSHBULLET_API_KEY)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    
def normalize_url(url):
    parsed_url = urlparse(url)
    normalized_url = parsed_url._replace(scheme='https', netloc=parsed_url.netloc.lower(), path=parsed_url.path.rstrip('/'))
    return urlunparse(normalized_url)

# Example usage before saving URLs
# normalized_url = normalize_url(your_url)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def normalize_url(url):
    parsed_url = urlparse(url)
    normalized_url = parsed_url._replace(scheme="https", netloc=parsed_url.netloc.lower(), path=parsed_url.path.rstrip('/'))
    return normalized_url.geturl()

def generate_dashboard_link(creator_id):
    script_url = "https://script.google.com/macros/s/AKfycbwJ775U48Q2EwS3g7TabdVPS1mzM6s3f8NVPazj7PZY1lIw08QwiN9ZZNuOuHca-xSHSw/exec"  # Replace with your deployed Google Apps Script URL
    params = {'creatorId': creator_id}
    
    response = requests.get(script_url, params=params)
    
    if response.status_code == 200:
        return response.text.strip()  # Returns the link to the filtered view
    else:
        print("Failed to generate link:", response.status_code, response.text)
        return "Error Generating Link"

from datetime import datetime

def determine_month_range(date_string):
    # Define possible date formats to handle your stored format
    date_formats = ['%Y-%m-%d %I:%M %p', '%m/%d/%Y', '%Y-%m-%d', '%m/%d/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S']
    date = None

    # Attempt to parse the date with each possible format
    for fmt in date_formats:
        try:
            date = datetime.strptime(date_string, fmt)
            break  # If parsing is successful, exit the loop
        except ValueError:
            continue

    if not date:
        print(f"Invalid date format: {date_string}")
        return "Invalid Date"

    day = date.day
    month = date.month
    year = date.year

    if day < 10:
        previous_month = month - 1 if month > 1 else 12
        previous_year = year - 1 if previous_month == 12 else year
        start_date = datetime(previous_year, previous_month, 10)
        end_date = datetime(year, month, 10)
    else:
        start_date = datetime(year, month, 10)
        end_date = datetime(year, (month % 12) + 1, 10)

    start_month_name = start_date.strftime('%B')
    end_month_name = end_date.strftime('%B')
    
    return f"{start_month_name} {start_date.year} - {end_month_name} {end_date.year}"

def sync_to_google_sheets():
    try:
        sheet = connect_to_google_sheets()
        all_data = sheet.get_all_values()

        if len(all_data) > 1:
            sheet.delete_rows(2, len(all_data))
        
        conn = sqlite3.connect('submissions.db')
        cursor = conn.cursor()

        cursor.execute('''SELECT creators.username, submissions.reel_link, submissions.views, submissions.earnings, 
                          submissions.creator_id, submissions.status, submissions.submission_time
                          FROM submissions 
                          JOIN creators ON submissions.creator_id = creators.id''')
        all_submissions = cursor.fetchall()
        
        rows_to_add = []
        for row in all_submissions:
            rows_to_add.append(list(row))
        
        if rows_to_add:
            sheet.insert_rows(rows_to_add, row=2)
            print("Google Sheets updated successfully.")

        conn.close()
    except Exception as e:
        print(f"Error syncing with Google Sheets: {e}")

def process_csv(file):
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()

    try:
        df = pd.read_csv(file)
        
        for index, row in df.iterrows():
            reel_link = row['Link']
            views = int(row['Views'])

            cursor.execute('''UPDATE submissions 
                              SET views = ?, earnings = views * CPM / 1000
                              WHERE reel_link = ?''', (views, reel_link))
        
        conn.commit()
        print("CSV processed successfully.")
        
    except Exception as e:
        print(f"Error processing CSV: {e}")
    finally:
        conn.close()



def get_session_name(date_string):
    from datetime import datetime
    date = datetime.strptime(date_string, '%Y-%m-%d %I:%M %p')
    month = date.month
    year = date.year

    if month in [3, 4]:
        return f"March-April {year}"
    elif month in [5, 6]:
        return f"May-June {year}"
    elif month in [7, 8]:
        return f"July-August {year}"
    elif month in [9, 10]:
        return f"September-October {year}"
    elif month in [11, 12]:
        return f"November-December {year}"
    else:
        return f"January-February {year}"
        
def connect_to_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"), scopes=scope)
    client = gspread.authorize(creds)
    sheet = client.open("LXM Creator Data").worksheet("Earnings")
    return sheet

def initialize_database():
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS creators (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            cpm INTEGER NOT NULL,
            email TEXT,
            dashboard_link TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reel_link TEXT NOT NULL,
            submission_time TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            rejection_reason TEXT DEFAULT '',
            creator_id TEXT NOT NULL,
            views INTEGER DEFAULT 0,
            earnings REAL DEFAULT 0.0,
            FOREIGN KEY (creator_id) REFERENCES creators(id)
        )
    ''')

    conn.commit()
    conn.close()

initialize_database()

@app.errorhandler(500)
def internal_error(error):
    logging.error(f"Server Error: {error}, route: {request.url}")
    return "Internal Server Error", 500

@app.errorhandler(Exception)
def unhandled_exception(e):
    logging.error(f"Unhandled Exception: {e}, route: {request.url}")
    return "Internal Server Error", 500
    
@app.route('/submit/<creator_id>', methods=['GET', 'POST'])
def submit(creator_id):
    if request.method == 'POST':
        reel_link = request.form['reel_link']
        submission_time = datetime.now().strftime("%Y-%m-%d %I:%M %p")

        conn = sqlite3.connect('submissions.db')
        cursor = conn.cursor()

        try:
            cursor.execute("INSERT INTO submissions (reel_link, submission_time, creator_id) VALUES (?, ?, ?)",
                           (reel_link, submission_time, creator_id))
            conn.commit()
            
            # Properly call the sync function AFTER committing data
            sync_to_google_sheets()

            # Render your enhanced success page instead of returning plain text
            return render_template('success.html', creator_id=creator_id)
        except Exception as e:
            print(f"Error during submission: {e}")
            return "Submission Failed. Please try again.", 500
        finally:
            conn.close()
    return render_template('submit.html', creator_id=creator_id)



@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)
    
    file = request.files['file']
    
    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):  # Check if the file is allowed
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Process the CSV file here
        process_csv(filepath)
        flash('File successfully uploaded')
        
        # Trigger sync to Google Sheets
        sync_to_google_sheets()
        
        return redirect(url_for('manager'))
    
    flash('Allowed file types are csv')
    return redirect(request.url)

    # Run the query to get all submission dates
    cursor.execute("SELECT submission_time FROM submissions;")
    results = cursor.fetchall()
    
    conn.close()

    # Display results in a readable format
    return str(results)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == MANAGER_PASSWORD:  # Ensure you have this set in your `.env` file
            session['logged_in'] = True
            return redirect(url_for('manager'))
        else:
            return "Invalid password, try again.", 403
    return render_template('login.html')
    
@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)

    file = request.files['file']

    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)

    if file and allowed_file(file.filename):  # Define `allowed_file()` if not already defined
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Process CSV file here (existing code for updating views/earnings)
        process_csv(filepath)
        flash('File uploaded and processed successfully')

        # Syncing to Google Sheets after CSV processing
        sync_to_google_sheets()

        return redirect(url_for('manager'))

    flash('Invalid file format')
    return redirect(request.url)


# Home Route
@app.route('/')
def home():
    return "LXM Creator System is Live!"




# Success Page Route

# Route for Creator Dashboard
@app.route('/dashboard/<creator_id>')
def dashboard(creator_id):
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()

    # Fetch Creator's Submissions
    cursor.execute("SELECT reel_link, submission_time, status, rejection_reason, views, earnings FROM submissions WHERE creator_id = ?", (creator_id,))
    submissions = cursor.fetchall()

    # Fetch Creator's CPM
    cursor.execute("SELECT cpm FROM creators WHERE id = ?", (creator_id,))
    cpm_row = cursor.fetchone()
    cpm = cpm_row[0] if cpm_row else 0

    # Calculate Total Earnings
    total_earnings = sum(submission[5] for submission in submissions)

    # Fetch Announcements
    cursor.execute("SELECT message, timestamp FROM announcements ORDER BY timestamp DESC")
    announcements = cursor.fetchall()

    conn.close()

    return render_template('dashboard.html', submissions=submissions, creator_id=creator_id, cpm=cpm, total_earnings=total_earnings, announcements=announcements)
@app.route('/manager', methods=['GET', 'POST'])
def manager():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, username, cpm FROM creators")
    creators = cursor.fetchall()

    cursor.execute('''SELECT submissions.id, submissions.reel_link, submissions.submission_time, 
                      submissions.status, submissions.rejection_reason, submissions.views, submissions.earnings, 
                      creators.username, submissions.creator_id 
                      FROM submissions 
                      JOIN creators ON submissions.creator_id = creators.id''')
    submissions = cursor.fetchall()
    
    conn.close()
    
    return render_template('manager.html', creators=creators, submissions=submissions)

# Route for Updating CPM
@app.route('/update_cpm', methods=['POST'])
def update_cpm():
    creator_id = request.form['creator_id']
    new_cpm = int(request.form['new_cpm'])
    
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()
    
    cursor.execute("UPDATE creators SET cpm = ? WHERE id = ?", (new_cpm, creator_id))
    conn.commit()
    conn.close()
    
    return redirect(url_for('manager'))


@app.route('/update_submission', methods=['POST'])
def update_submission():
    submission_id = request.form['submission_id']
    action = request.form['action']
    rejection_reason = request.form.get('rejection_reason', '')
    
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()
    
    try:
        if action == 'approve':
            cursor.execute(
                "UPDATE submissions SET status = 'Approved', rejection_reason = '' WHERE id = ?",
                (submission_id,)
            )
        
        elif action == 'reject':
            cursor.execute(
                "UPDATE submissions SET status = 'Rejected', rejection_reason = ? WHERE id = ?",
                (rejection_reason, submission_id)
            )
        
        elif action == 're-review':
            cursor.execute(
                "UPDATE submissions SET status = 'Pending', rejection_reason = '' WHERE id = ?",
                (submission_id,)
            )
        
        conn.commit()
        
        # Properly call the sync function AFTER committing data
        sync_to_google_sheets()
        
    except sqlite3.Error as e:
        print(f"Database error occurred: {e}")
    
    finally:
        conn.close()

    return redirect(url_for('manager'))






# Route for Adding New Creators
@app.route('/add_creator', methods=['POST'])
def add_creator():
    creator_id = request.form['creator_id']
    username = request.form['username']
    cpm = int(request.form['cpm'])
    
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()
    
    # Generate the submission link
    submission_link = f"/submit/{creator_id}"
    
    # Generate the dashboard link by calling the Google Apps Script
    dashboard_link = generate_dashboard_link(creator_id)  # We'll define this function below
    
    # Insert new creator into the database, including the dashboard link
    cursor.execute("INSERT OR REPLACE INTO creators (id, username, cpm, dashboard_link) VALUES (?, ?, ?, ?)",
                   (creator_id, username, cpm, dashboard_link))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('manager'))  # Redirect back to the manager dashboard

@app.route('/success/<creator_id>')
def success(creator_id):
    return render_template('success.html', creator_id=creator_id)

if __name__ == "__main__":
    app.run(debug=True)
