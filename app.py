from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from pushbullet import Pushbullet
import os
import requests
from flask_cors import CORS
from dotenv import load_dotenv
from urllib.parse import urlparse
import pandas as pd 
import csv
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
ALLOWED_EXTENSIONS = {'csv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Load environment variables from the .env file
load_dotenv()

app = Flask(__name__)
CORS(app)

# Load secret key for sessions
app.secret_key = os.getenv("SECRET_KEY")
# Load manager password from environment variable
MANAGER_PASSWORD = os.getenv("MANAGER_PASSWORD")
# Load Pushbullet API Key from environment variable
PUSHBULLET_API_KEY = "o.xO7PqwaZwbkTRUVsrupPjifLOkTlWsn4"
pb = Pushbullet(PUSHBULLET_API_KEY)

# Load Google Application Credentials Path
credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if not credentials_path:
    raise ValueError("GOOGLE_APPLICATION_CREDENTIALS is not set in the environment variables.")

# This line ensures your credentials file is accessible
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path

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
    sheet = connect_to_google_sheets()
    all_data = sheet.get_all_values()
    
    # Clear existing data (except header)
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
        submission_date = row[6]  # Date Submitted
        try:
            month_range = determine_month_range(submission_date)  # Get the Month Range
        except:
            month_range = "Invalid Date"
        
        rows_to_add.append([
            row[0],  # Username
            row[1],  # Reel Link
            row[2],  # Views
            row[3],  # Earnings
            row[4],  # Creator ID
            row[5],  # Status
            row[6],  # Date Submitted
            month_range  # Add calculated Month Range here
        ])
    
    if rows_to_add:
        try:
            sheet.insert_rows(rows_to_add, row=2)
            print("Google Sheets updated successfully with Month Range.")
        except Exception as e:
            print(f"Failed to update Google Sheets: {e}")

    conn.close()



def process_csv(file_path):
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()

    with open(file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row in reader:
            reel_link = row['Link'].strip().lower()
            views = int(row['Views'].replace(",", "").strip())
            
            cursor.execute('''UPDATE submissions 
                              SET views = ?, earnings = ? 
                              WHERE LOWER(reel_link) = ?''', 
                           (views, calculate_earnings(views), reel_link))
        
    conn.commit()
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

# Create Database
def create_database():
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()

    # Submissions Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reel_link TEXT NOT NULL,
            submission_time TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            rejection_reason TEXT DEFAULT '',
            creator_id TEXT NOT NULL
        )
    ''')

    # Creators Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS creators (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            cpm INTEGER NOT NULL,
            email TEXT,
            dashboard_link TEXT
        )
    ''')

    # Announcements Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    ''')

    # Notifications Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id TEXT,
            message TEXT,
            timestamp TEXT,
            FOREIGN KEY (creator_id) REFERENCES creators(id)
        )
    ''')

    conn.commit()
    conn.close()

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


# Define the Success Route
@app.route('/success/<creator_id>')
def success(creator_id):
    return f"Submission Successful! You can now go back to your dashboard, Creator ID: {creator_id}"
    
@app.route('/check_submission_dates')
def check_submission_dates():
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()

    # Run the query to get all submission dates
    cursor.execute("SELECT submission_time FROM submissions;")
    results = cursor.fetchall()
    
    conn.close()

    # Display results in a readable format
    return str(results)

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    if 'file' not in request.files:
        print("No file part found in request.")
        return "No file part", 400

    file = request.files['file']
    
    if file.filename == '':
        print("No selected file.")
        return "No selected file", 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Save file to server
        file.save(file_path)
        
        try:
            # Process the CSV file
            process_csv(file_path)
            
            # Sync Google Sheets (🔥 CRUCIAL 🔥)
            sync_to_google_sheets()
            
            print("CSV Processing and Google Sheets sync completed successfully.")
            return redirect(url_for('manager'))
        
        except Exception as e:
            print(f"Error during CSV processing or syncing: {e}")
            return f"Error during processing: {str(e)}", 500
    
    return "Invalid file type. Only CSV files are allowed.", 400

# Route for Adding Announcements
@app.route('/add_announcement', methods=['POST'])
def add_announcement():
    message = request.form['message']
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()

    cursor.execute("INSERT INTO announcements (message, timestamp) VALUES (?, ?)", (message, timestamp))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('manager'))


# Route for Deleting a Creator (And All Their Data)
@app.route('/delete_creator', methods=['POST'])
def delete_creator():
    creator_id = request.form['creator_id']
    
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM creators WHERE id = ?", (creator_id,))
    cursor.execute("DELETE FROM submissions WHERE creator_id = ?", (creator_id,))
    conn.commit()
    conn.close()

    sync_to_google_sheets()  # Sync after deleting a creator

    return redirect(url_for('manager'))


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





if __name__ == "__main__":
    app.run(debug=True)
