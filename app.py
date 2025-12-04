from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, timezone
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import google.cloud.firestore
# Corrected import for aggregation
import google.cloud.firestore_v1.aggregation
import os
from dotenv import load_dotenv
load_dotenv()
import smtplib
from email.message import EmailMessage
from firebase_admin import credentials
from google.oauth2 import service_account
import firebase_admin

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE_NAME = "fintera-478211-7e06412c47a4.json"

# Construct the full absolute path
CREDENTIALS_PATH = os.path.join(BASE_DIR, CREDENTIALS_FILE_NAME)

# Use the absolute path to initialize the certificate
cred = credentials.Certificate(CREDENTIALS_PATH)
firebase_admin.initialize_app(cred)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_fallback_key')

#sendermail = os.getenv('MAIL_USERNAME')
senderpass = os.getenv('MAIL_PASSWORD')
sendermail = "priyanshsingh3rdid@gmail.com" 
senderpass = "senderpass"
receiver = os.getenv('RECEIVING_EMAIL')
print(f"DEBUG: Sender Mail: {sendermail}")
print(f"DEBUG: Receiver Mail: {receiver}")

try:
    firestore_creds = service_account.Credentials.from_service_account_file(CREDENTIALS_PATH)
    db = google.cloud.firestore.Client(credentials=firestore_creds)
    print("Firestore client initialized successfully.")
except Exception as e:
    print(f"Error initializing Firestore: {type(e).__name__}: {e}")
    db = None


login = LoginManager()
login.init_app(app)
login.login_view = 'log'
login.login_message = "You must be logged in to access this page."

class User(UserMixin):
    
    def __init__(self, user_id, user_data):
        self.id = user_id  
        self.user_data = user_data

    def get_id(self):
        return str(self.id)
    
    @property
    def password(self):
        # Good practice: The password should never be stored in plaintext. 
        # For a production app, use a secure hash function (e.g., bcrypt)
        return self.user_data.get('Password')

    @property
    def email(self):
        return self.user_data.get('Email')
    
    @property
    def contact(self):
        return self.user_data.get('Contact')

@login.user_loader
def load_user(user_id):
    if not db:
        return None
    try:
        doc = db.collection('users').document(user_id).get()
        if doc.exists:
            return User(user_id, doc.to_dict())
        return None
    except Exception as e:
        print(f"Error loading user {user_id}: {e}")
        return None

def send_feedback_email(subject, body, user_email=None):
    if not sendermail or not senderpass or not receiver:
        print("Email environment variables are not set. Skipping email sending.")
        return

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sendermail
    msg['To'] = receiver
    msg.set_content(body, charset='utf-8')
    if user_email:
        msg['Reply-To'] = user_email
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sendermail, senderpass)
            server.sendmail(msg['From'],[msg['To']],msg.as_string())
        print("Feedback email sent successfully.")
        
    except Exception as e:
        print(f"Failed to send email: {e}")


@app.route('/')
def new_htt():
    return render_template('index.html')

@app.route('/data')
def new_data():
    if not db:
        return "Firestore is not connected.", 500
    
    users_ref = db.collection('users').stream()
    all_data = []
    for user_doc in users_ref:
        user_data = user_doc.to_dict()
        # In a real app, DO NOT send the Password field to the template.
        user_data['doc_id'] = user_doc.id 
        all_data.append(user_data)
        
    return render_template('data.html', alldata=all_data)

@app.route('/ui')
@login_required
def ui():
    return render_template('ui.html')

@app.route('/login', methods=['GET', 'POST'])
def log():
    if current_user.is_authenticated:
        return redirect(url_for('ui'))

    if request.method == 'POST':
        userid_from_form = request.form['user']
        passw_from_form = request.form['passw']

        if not userid_from_form or not passw_from_form:
            error_msg = "Both UserID and password are required"
            return render_template('login.html', error=error_msg)
        
        if not db:
            error_msg = "Database connection error."
            return render_template('login.html', error=error_msg)
    
        try:
            doc_ref = db.collection('users').document(userid_from_form)
            doc = doc_ref.get()

            if doc.exists:
                user_data = doc.to_dict()
                if user_data.get('Password') == passw_from_form:
                    # Authentication successful
                    user_obj = User(doc.id, user_data)
                    login_user(user_obj)
                    return redirect(url_for('ui'))
                else:
                    error_msg = "Invalid UserID or password"
                    return render_template('login.html', error=error_msg)
            else:
                error_msg = "Invalid UserID or password"
                return render_template('login.html', error=error_msg)
        except Exception as e:
            print(f"Login error: {e}")
            error_msg = "An error occurred during login."
            return render_template('login.html', error=error_msg)

    return render_template('login.html')

@app.route('/logout')
@login_required 
def logout():
    logout_user()
    return redirect(url_for('log'))

@app.route('/mod', methods=['GET', 'POST'])
@login_required
def mod_page():
    if not db:
        return "Firestore is not connected.", 500
        
    user_id = current_user.get_id()
    transactions_ref = db.collection('users').document(user_id).collection('transactions')

    if request.method == 'POST':
        try:
            category_from_form = request.form['category']
            amt = int(request.form['amount'])
            desc = request.form['desc']
            date = request.form['date']
            transdate_iso = datetime.strptime(date, '%Y-%m-%d').date().isoformat()

            data_to_add = {
                'Category': category_from_form,
                'Amount': amt,
                'Desc': desc,
                'TransactionDate': transdate_iso, 
                'date_created': datetime.now(timezone.utc)
            }
            transactions_ref.add(data_to_add)
            
            return redirect(url_for('mod_page'))
        except Exception as e:
            print(f"Error adding transaction: {e}")
            flash("Error adding transaction. Check input values.", 'error')
            pass
    
    try:
        docs_stream = transactions_ref.stream()
        
        all_transc = []
        category_totals = {}
        total_spending = 0

        for doc in docs_stream:
            data = doc.to_dict()
            data['sno2'] = doc.id  
            try:
                date_obj = datetime.fromisoformat(data['TransactionDate']).date()
                data['TransactionDateDisplay'] = date_obj.strftime('%Y-%m-%d') # Format for display
            except:
                data['TransactionDateDisplay'] = data.get('TransactionDate', 'N/A')

            all_transc.append(data)
            
            amount = int(data.get('Amount', 0))
            category = data.get('Category')
            
            total_spending += amount
            if category:
                category_totals[category] = category_totals.get(category, 0) + amount

        labels3 = list(category_totals.keys())
        values3 = list(category_totals.values())

        return render_template(
            'modify.html', 
            alltransc=all_transc, 
            labels3=labels3, 
            values3=values3, 
            totalspending=total_spending
        )

    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return render_template('modify.html', alltransc=[], labels3=[], values3=[], totalspending=0, error="Could not load data.")


@app.route('/register', methods=['GET', 'POST'])
def reg_page():
    if current_user.is_authenticated:
        return redirect(url_for('ui'))

    if request.method == 'POST':
        user = request.form['userNew']
        passw = request.form['passwNew']
        contact = request.form['cont']
        email = request.form['email']

        if not user or not passw or not contact or not email:
            error_msg = "All fields are required"
            return render_template('register.html', error=error_msg)
        
        if not db:
            error_msg = "Database connection error."
            return render_template('register.html', error=error_msg)

        try:
            doc_ref = db.collection('users').document(user)
            doc = doc_ref.get()

            if doc.exists:
                error_msg = "UserID already taken, please choose a new one."
                return render_template('register.html', error=error_msg)
            
            data_to_set = {
                'UserID': user,
                # WARNING: In a production app, HASH the password before storing it!
                'Password': passw, 
                'Contact': contact,
                'Email': email,
                'date_created': datetime.now(timezone.utc)
            }
            doc_ref.set(data_to_set)
            
            return redirect(url_for('log'))
        
        except Exception as e:
            print(f"Registration error: {e}")
            error_msg = "An error occurred during registration."
            return render_template('register.html', error=error_msg)

    return render_template('register.html')

@app.route('/analysis')
@login_required
def ana():
    if not db:
        return "Firestore is not connected.", 500
        
    user_id = current_user.get_id()
    
    # --- Transactions Analysis (Spending) ---
    transactions_ref = db.collection('users').document(user_id).collection('transactions')
    # Order by date to ensure proper timeline for charts
    trans_docs = transactions_ref.order_by('TransactionDate').stream() 
    
    trans_by_date = {}
    for doc in trans_docs:
        data = doc.to_dict()
        date_str = data.get('TransactionDate')
        amount = int(data.get('Amount', 0))
        if date_str:
            trans_by_date[date_str] = trans_by_date.get(date_str, 0) + amount
            
    labels = list(trans_by_date.keys())
    values = list(trans_by_date.values())
    
    # --- Funds Analysis (Income/Savings) ---
    funds_ref = db.collection('users').document(user_id).collection('funds')
    # Order by date to ensure proper timeline for charts
    funds_docs = funds_ref.order_by('TransacDate').stream()
    
    funds_by_date = {}
    for doc in funds_docs:
        data = doc.to_dict()
        date_str = data.get('TransacDate')
        amount = int(data.get('Amount', 0))
        if date_str:
            funds_by_date[date_str] = funds_by_date.get(date_str, 0) + amount

    labels2 = list(funds_by_date.keys())
    values2 = list(funds_by_date.values())

    return render_template( 'analysis.html',labels2=labels2,values2=values2,labels1=labels,values1=values)

@app.route('/addfunds', methods=['GET', 'POST'])
@login_required
def add():
    if not db:
        return "Firestore is not connected.", 500
        
    user_id = current_user.get_id()
    funds_ref = db.collection('users').document(user_id).collection('funds')

    if request.method == 'POST':
        try:
            Categ = request.form['cat']  
            amount = int(request.form['amt'])
            Desc = request.form['desc']
            date = request.form['date']
            Transc_iso = datetime.strptime(date, '%Y-%m-%d').date().isoformat()

            data_to_add = {
                'Category': Categ,
                'Amount': amount,
                'Description': Desc,
                'TransacDate': Transc_iso, # Store as ISO format string
                'date_created': datetime.now(timezone.utc)
            }
            funds_ref.add(data_to_add)
            
            return redirect(url_for('add'))
        except Exception as e:
            print(f"Error adding funds: {e}")
            flash("Error adding funds. Check input values.", 'error')
            pass

    try:
        # CORRECTED AGGREGATION USAGE
        # Calculate total funds using Sum aggregation
        money = 0
        aggregation_query = funds_ref.aggregate(total_amount=google.cloud.firestore_v1.aggregation('Amount'))
        result = aggregation_query.get()
        if result and result[0].value is not None:
            money = result[0].value
        
        docs_stream = funds_ref.stream()
        allfunds = []
        for doc in docs_stream:
            data = doc.to_dict()
            data['sno3'] = doc.id
            allfunds.append(data)
            
        return render_template('funds.html', allfunds=allfunds, allmoney=money)
    
    except Exception as e:
        print(f"Error fetching funds: {e}")
        return render_template('funds.html', allfunds=[], allmoney=0, error="Could not load data.")

@app.route('/summary')
@login_required
def summ():
    if not db:
        return "Firestore is not connected.", 500
        
    user_id = current_user.get_id()
    
    try:
        # CORRECTED AGGREGATION USAGE
        # Calculate total funds
        funds_ref = db.collection('users').document(user_id).collection('funds')
        funds_agg_query = funds_ref.aggregate(total=google.cloud.firestore_v1.aggregation('Amount'))
        funds_result = funds_agg_query.get()
        money = 0
        if funds_result and funds_result[0].value is not None:
            money = funds_result[0].value
            
        # CORRECTED AGGREGATION USAGE
        # Calculate total spending
        trans_ref = db.collection('users').document(user_id).collection('transactions')
        trans_agg_query = trans_ref.aggregate(total=google.cloud.firestore_v1.aggregation('Amount'))
        trans_result = trans_agg_query.get()
        spending = 0
        if trans_result and trans_result[0].value is not None:
            spending = trans_result[0].value

        Total_Savings = money - spending
        
        return render_template(
            'summary.html', 
            totalspending=spending, 
            allmoney=money, 
            savings=Total_Savings
        )
    except Exception as e:
        print(f"Error generating summary: {e}")
        return render_template('summary.html', totalspending=0, allmoney=0, savings=0, error="Could not load data.")
    

@app.route('/feedback', methods = ['GET', 'POST'])
@login_required
def feed():
    if not db:
        flash("Database connection error. Feedback cannot be submitted.", 'error')
        # Redirecting to a safe page if db is down
        return redirect(url_for('log')) 
        
    is_logged_in = current_user.is_authenticated
    
    user_id = current_user.get_id() if is_logged_in else 'Anonymous'
    user_email_for_template = current_user.email if is_logged_in else ''
    
    if request.method == 'POST':
        feedback = request.form.get('feedback_msg')
        
        if is_logged_in:
            user_email_for_db = current_user.email
        else:
            # Note: This route is @login_required, so this 'else' block for anonymous 
            # submission will never be hit unless you remove the decorator.
            user_email_for_db = request.form.get('email_anon') 
            
        
        if not feedback:
            flash("Feedback message cannot be empty.", 'error')
            return render_template('feedback.html', 
                                   is_logged_in=is_logged_in, user_email=user_email_for_template)
            
        try:
            email_display = user_email_for_db if user_email_for_db else 'N/A'
            
            feedback_data = {
                'UserID': user_id,
                'Email': email_display,
                'Message': feedback,
                'is_logged_in': is_logged_in,
                'date_submitted': datetime.now(timezone.utc)
            }
            db.collection('feedback').add(feedback_data)
            flash("Thank you for your feedback!", 'success')
            
            email_identifier = user_email_for_db if user_email_for_db else user_id
            subject = f"New Feedback ({'Logged-in' if is_logged_in else 'Anonymous'}) from {email_identifier}"
            
            body = (
                f"User ID: {user_id}\n"
                f"Email: {email_display}\n"
                f"Feedback:\n---\n{feedback}\n---\n"
                f"Submitted on: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
            
            send_feedback_email(subject, body, user_email_for_db)
            
            return redirect(url_for('feed')) 
        
        except Exception as e:
            print(f"Error processing feedback: {e}")
            flash("An error occurred while submitting feedback.", 'error')
            return render_template('feedback.html', 
                                   is_logged_in=is_logged_in, user_email=user_email_for_template)

    return render_template('feedback.html', 
                           is_logged_in = is_logged_in, user_email=user_email_for_template)


if __name__ == "__main__":
    app.run(debug=True)