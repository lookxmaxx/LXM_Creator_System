from flask import Flask, render_template, request, flash, redirect, url_for, session
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
import requests

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
    sheet = connect_to_google_sheets()
    all_data = sheet.get_all_values()
    
    # Do not clear entire data - only overwrite updated rows
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()

    cursor.execute('''SELECT creators.username, submissions.reel_link, submissions.views, submissions.earnings, 
                      submissions.creator_id, submissions.status, submissions.submission_time
                      FROM submissions 
                      LEFT JOIN creators ON submissions.creator_id = creators.id''')
    all_submissions = cursor.fetchall()
    
    rows_to_add = []
    for row in all_submissions:
        rows_to_add.append([
            row[0],  # Username
            row[1],  # Reel Link
            row[2],  # Views
            row[3],  # Earnings
            row[4],  # Creator ID
            row[5],  # Status
            row[6],  # Date Submitted
        ])
    
    if rows_to_add:
        try:
            sheet.insert_rows(rows_to_add, row=2)
            print("Google Sheets updated successfully.")
        except Exception as e:
            print(f"Failed to update Google Sheets: {e}")

    conn.close()

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

def init_db():
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

    conn.commit()
    conn.close()

init_db()

def sync_from_google_sheets():
    sheet = connect_to_google_sheets()
    all_data = sheet.get_all_values()[1:]  # Skip the header row
    
    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()
    
    # Fetch existing creators from the database
    cursor.execute("SELECT id FROM creators")
    existing_creators = {row[0] for row in cursor.fetchall()}

    for row in all_data:
        try:
            username, reel_link, views, earnings, creator_id, status, submission_time, month_range = row
            
            # If the creator is not in the database, add them
            if creator_id not in existing_creators:
                cursor.execute('''INSERT OR IGNORE INTO creators (id, username, cpm) 
                                  VALUES (?, ?, ?)''', (creator_id, username, 0))  # Default CPM is set to 0
                
                # Also, add submissions from Google Sheets that are not in the database
                cursor.execute('''INSERT OR IGNORE INTO submissions (reel_link, submission_time, creator_id, status) 
                                  VALUES (?, ?, ?, ?)''', (reel_link, submission_time, creator_id, status))
            
        except Exception as e:
            print(f"Error syncing from Google Sheets: {e}")
    
    conn.commit()
    conn.close()
    
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

@app.route('/delete_creator', methods=['POST'])
def delete_creator():
    try:
        creator_id = request.form.get('creator_id')
        
        if not creator_id:
            return "Creator ID is missing.", 400  # Bad request if no creator ID is provided

        conn = sqlite3.connect('submissions.db')
        cursor = conn.cursor()

        # Check if the creator exists before deleting
        cursor.execute("SELECT id FROM creators WHERE id = ?", (creator_id,))
        result = cursor.fetchone()
        
        if result is None:
            conn.close()
            return "Creator not found.", 404  # Creator doesn't exist

        # Delete the creator and their submissions
        cursor.execute("DELETE FROM creators WHERE id = ?", (creator_id,))
        cursor.execute("DELETE FROM submissions WHERE creator_id = ?", (creator_id,))
        conn.commit()
        conn.close()

        try:
            # Attempt to sync Google Sheets
            sync_to_google_sheets()
        except Exception as e:
            print(f"Google Sheets sync failed: {e}")
        
        return redirect(url_for('manager'))

    except Exception as e:
        print(f"Error deleting creator: {e}")
        return "An error occurred while deleting the creator.", 500
        
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
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            file.save(filepath)
            
            # Process the CSV file here
            # process_csv(filepath)
            flash('File successfully uploaded and processed')
            
            # Sync to Google Sheets if necessary
            # sync_to_google_sheets()
            
            return redirect(url_for('manager'))
        
        except Exception as e:
            flash(f"An error occurred: {str(e)}")
            return redirect(request.url)
    
    flash('Allowed file types are csv')
    return redirect(request.url)

# Home Route
@app.route('/')
def home():
    return "LXM Creator System is Live!"



@app.route('/update_earnings', methods=['GET', 'POST'])
def update_earnings():
    if request.method == 'POST':
        username = request.form['username']
        views = int(request.form['views'])
        reel_link = request.form['reel_link']
        
        # Connect to Google Sheets
        sheet = connect_to_google_sheets()
        creators_sheet = sheet.worksheet('Creators')
        earnings_sheet = sheet.worksheet('Earnings')

        # Fetch CPM for the given username
        creators_data = creators_sheet.get_all_values()
        cpm = None

        for row in creators_data[1:]:  # Skip the header row
            if row[0].strip().lower() == username.strip().lower():
                cpm = int(row[1])
                break

        if cpm is None:
            return "CPM not found for the provided username.", 400

        # Calculate earnings
        earnings = (views / 1000) * cpm

        # Update the Earnings Sheet
        earnings_sheet.append_row([username, reel_link, views, earnings, 'Approved', datetime.now().strftime("%Y-%m-%d %I:%M %p")])
        
        return redirect(url_for('manager'))

    return render_template('update_earnings.html')

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
    
    # Ensure creators are being fetched correctly
    cursor.execute("SELECT id, username, cpm FROM creators")
    creators = cursor.fetchall()

    # Check if creators were properly retrieved
    if not creators:
        print("No creators found in the database.")
    
    cursor.execute('''SELECT submissions.id, submissions.reel_link, submissions.submission_time, 
                      submissions.status, submissions.rejection_reason, submissions.views, submissions.earnings, 
                      creators.username, submissions.creator_id 
                      FROM submissions 
                      LEFT JOIN creators ON submissions.creator_id = creators.id''')
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
    import requests  # Make sure this import is present

    creator_id = request.form.get('creator_id')
    username = request.form.get('username')
    cpm = request.form.get('cpm')

    if not creator_id or not username or not cpm:
        return "All fields are required.", 400

    try:
        cpm = int(cpm)
    except ValueError:
        return "Invalid CPM value. Must be a number.", 400

    conn = sqlite3.connect('submissions.db')
    cursor = conn.cursor()
    
    try:
        submission_link = f"/submit/{creator_id}"
        
        # Generate the dashboard link by calling the Google Apps Script
        dashboard_link = generate_dashboard_link(creator_id)
        
        cursor.execute('''
            INSERT OR REPLACE INTO creators (id, username, cpm, dashboard_link) 
            VALUES (?, ?, ?, ?)
        ''', (creator_id, username, cpm, dashboard_link))
        
        conn.commit()
        
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Database error occurred: {e}")
        return "An error occurred while adding the creator. Please try again.", 500
    
    finally:
        conn.close()
    
    return redirect(url_for('manager'))

@app.route('/success/<creator_id>')
def success(creator_id):
    return render_template('success.html', creator_id=creator_id)

if __name__ == "__main__":
    app.run(debug=True)
