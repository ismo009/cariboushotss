from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename # For securely handling filenames
import os

from flask import Flask, render_template, request, redirect, url_for, flash
from markupsafe import Markup # Import Markup from markupsafe
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import logging # For basic logging configuration

# --- Import Google Drive Service ---
from gdrive_service import get_drive_service, upload_photo_to_drive, find_or_create_folder, \
                           list_folders, list_photos_in_folder, get_folder_details
                           # MAIN_CLUB_FOLDER_ID removed from here, will be in app.config

app = Flask(__name__)

# --- Configuration ---
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev_secret_key_change_me')
# Google Drive specific configurations
app.config['GOOGLE_DRIVE_MAIN_FOLDER_ID'] = os.environ.get('GOOGLE_DRIVE_MAIN_FOLDER_ID', '1jseNSB8rSM-kvz1rYLJiFyqXVR6tZ4-M') # User provided ID
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
INSTANCE_PATH = os.path.join(APP_ROOT, 'instance')
app.config['GOOGLE_DRIVE_CREDENTIALS_PATH'] = os.path.join(INSTANCE_PATH, 'service_account_credentials.json')
LOCAL_TEMP_UPLOAD_FOLDER = os.path.join(INSTANCE_PATH, 'temp_uploads')
app.config['LOCAL_TEMP_UPLOAD_FOLDER'] = LOCAL_TEMP_UPLOAD_FOLDER

# --- Logging Setup ---
# Configure basic logging if not already configured by Flask/Gunicorn
logging.basicConfig(level=logging.INFO) # Default level
if app.debug:
    logging.getLogger().setLevel(logging.DEBUG)
# Flask's app.logger will be used where context is available. For gdrive_service, it uses its own logger.

# Ensure the instance and temp upload folders exist
try:
    os.makedirs(INSTANCE_PATH, exist_ok=True)
    os.makedirs(LOCAL_TEMP_UPLOAD_FOLDER, exist_ok=True)
except OSError as e:
    # Use a basic print here if app.logger is not yet available during initial module load
    # However, Flask usually sets up its logger early enough.
    # If this runs before app context is fully up, app.logger might not be ideal.
    # For robustness at this very early stage, a direct print or standard logger might be seen.
    # But typically, this should be fine.
    app.logger.error(f"CRITICAL: Error creating instance or temp_uploads folders during app startup: {e}", exc_info=True)


# --- Flask-Login Setup ---

# Configure a folder for temporary local uploads before sending to Google Drive
# This UPLOAD_FOLDER is for temporary storage on the server.
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
INSTANCE_PATH = os.path.join(APP_ROOT, 'instance')
LOCAL_TEMP_UPLOAD_FOLDER = os.path.join(INSTANCE_PATH, 'temp_uploads')
app.config['LOCAL_TEMP_UPLOAD_FOLDER'] = LOCAL_TEMP_UPLOAD_FOLDER

# Ensure the instance and temp upload folders exist
try:
    os.makedirs(INSTANCE_PATH, exist_ok=True)
    os.makedirs(LOCAL_TEMP_UPLOAD_FOLDER, exist_ok=True)
except OSError as e:
    # In a real app, use proper logging
    print(f"Error creating instance or temp upload folders: {e}")


# --- Flask-Login Setup ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # Name of the login route
login_manager.login_message_category = 'info' # Flash category for login messages

# --- User Model & Dummy Database ---
# In a real app, this would be a database model (e.g., SQLAlchemy)
class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)

# Dummy user store (replace with a database in a real application)
# For demonstration, let's create one user: username 'member', password 'caribou'
hashed_password = generate_password_hash('caribou', method='pbkdf2:sha256')
users = {
    "1": User(id="1", username="member", password_hash=hashed_password)
}

@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

# --- Routes ---
@app.route('/')
def index():
    return render_template("index.html", club_name="Caribou'Shots")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Find user by username (simple iteration for our dict)
        user_obj = None
        for user_in_db in users.values():
            if user_in_db.username == username:
                user_obj = user_in_db
                break

        if user_obj and user_obj.verify_password(password):
            login_user(user_obj)
            flash('Logged in successfully!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template("login.html")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'photo' not in request.files:
            flash('No photo file part in the request.', 'danger')
            return redirect(request.url)

        file = request.files['photo']
        if file.filename == '':
            flash('No photo selected for uploading.', 'warning')
            return redirect(request.url)

        if file: # Basic check if file exists
            filename = secure_filename(file.filename) # Sanitize filename
            # Save locally temporarily
            local_temp_path = os.path.join(app.config['LOCAL_TEMP_UPLOAD_FOLDER'], filename)

            try:
                file.save(local_temp_path)
                app.logger.info(f"Temporarily saved file '{filename}' to '{local_temp_path}' for user '{current_user.username}'.")

                drive_service = get_drive_service(credentials_path=app.config['GOOGLE_DRIVE_CREDENTIALS_PATH'])
                if not drive_service:
                    app.logger.error("Failed to get Google Drive service in /upload route.")
                    flash('Error connecting to Google Drive. Please try again later or contact support.', 'danger')
                    return redirect(request.url)

                main_club_folder_id = app.config['GOOGLE_DRIVE_MAIN_FOLDER_ID']
                target_folder_id = main_club_folder_id
                gdrive_folder_name = request.form.get('folder_name', '').strip()

                if gdrive_folder_name:
                    app.logger.info(f"User specified subfolder: '{gdrive_folder_name}'")
                    subfolder_id = find_or_create_folder(drive_service, gdrive_folder_name, main_club_folder_id)
                    if subfolder_id:
                        target_folder_id = subfolder_id
                        app.logger.info(f"Using subfolder ID '{subfolder_id}' for upload.")
                    else:
                        app.logger.warning(f"Could not find or create Google Drive subfolder '{gdrive_folder_name}'. Uploading to main gallery ID '{main_club_folder_id}'.")
                        flash(f"Warning: Could not use subfolder '{gdrive_folder_name}'. Photo will be uploaded to the main gallery.", 'warning')

                uploaded_file_details = upload_photo_to_drive(drive_service, local_temp_path, filename, target_folder_id)

                if uploaded_file_details and uploaded_file_details.get('id'):
                    app.logger.info(f"Successfully uploaded '{filename}' to Drive ID '{uploaded_file_details.get('id')}' by user '{current_user.username}'.")
                    view_link = uploaded_file_details.get('webViewLink', '#')
                    flash(Markup(f"Photo '{filename}' uploaded successfully! <a href='{view_link}' target='_blank' class='alert-link'>View on Drive</a>"), 'success')
                else:
                    app.logger.error(f"Failed to upload '{filename}' to Google Drive for user '{current_user.username}'. Drive service returned: {uploaded_file_details}")
                    flash(f"Failed to upload photo '{filename}' to Google Drive. Please check server logs or try again.", 'danger')

            except Exception as e:
                app.logger.error(f"Exception during file upload process for '{filename}': {e}", exc_info=True)
                flash(f"An unexpected error occurred during upload. Please try again. Error: {e}", 'danger')
            finally:
                if os.path.exists(local_temp_path):
                    os.remove(local_temp_path)

            return redirect(url_for('upload')) # Redirect back to upload page (or gallery)

    # For GET request
    return render_template("upload.html")


@app.route('/gallery/')
@app.route('/gallery/<folder_id>')
# @login_required # Decide if gallery needs login
def gallery(folder_id=None):
    drive_service = get_drive_service(credentials_path=app.config['GOOGLE_DRIVE_CREDENTIALS_PATH'])
    if not drive_service:
        app.logger.error("Failed to get Google Drive service in /gallery route.")
        flash('Error connecting to Google Drive. Please try again later or contact support.', 'danger')
        # Pass MAIN_CLUB_FOLDER_ID even in error case for template consistency if it tries to use it
        return render_template("gallery.html", folders=[], photos=[], current_folder_name='Error',
                               parent_folder_id=None, current_folder_id=None,
                               MAIN_CLUB_FOLDER_ID=app.config['GOOGLE_DRIVE_MAIN_FOLDER_ID'])

    main_club_folder_id = app.config['GOOGLE_DRIVE_MAIN_FOLDER_ID']
    current_folder_id_to_list = folder_id if folder_id else main_club_folder_id

    app.logger.info(f"Listing gallery content for folder ID: {current_folder_id_to_list}")
    folders_in_current_view = list_folders(drive_service, current_folder_id_to_list)
    photos_in_current_view = list_photos_in_folder(drive_service, current_folder_id_to_list)

    current_folder_details = get_folder_details(drive_service, current_folder_id_to_list, main_club_folder_id)
    current_folder_name = "Main Gallery"
    parent_folder_id_for_nav = None # Renamed to avoid conflict with folder_id param

    if current_folder_details:
        current_folder_name = current_folder_details.get('name', 'Gallery')
        app.logger.debug(f"Current folder details: {current_folder_details}")
        if current_folder_details.get('parents'):
            potential_parent = current_folder_details['parents'][0]
            if current_folder_id_to_list != main_club_folder_id:
                if potential_parent == main_club_folder_id:
                    parent_folder_id_for_nav = None # Indicates back to root
                else:
                    parent_folder_id_for_nav = potential_parent
                app.logger.debug(f"Determined parent for navigation: {parent_folder_id_for_nav}")
    else:
        app.logger.warning(f"Could not retrieve details for folder ID: {current_folder_id_to_list}. Displaying as root or with default name.")
        if current_folder_id_to_list == main_club_folder_id:
            current_folder_name = "Main Gallery"
        else:
            current_folder_name = "Unknown Folder" # Or fetch name differently if details failed partially

    for photo in photos_in_current_view:
        if not photo.get('thumbnailLink'):
            photo['thumbnailLink'] = url_for('static', filename='images/placeholder_image.png')
        if not photo.get('webViewLink'):
             photo['webViewLink'] = '#'

    return render_template("gallery.html",
                           folders=folders_in_current_view,
                           photos=photos_in_current_view,
                           current_folder_name=current_folder_name,
                           current_folder_id=current_folder_id_to_list,
                           parent_folder_id=parent_folder_id_for_nav, # Use the renamed variable
                           MAIN_CLUB_FOLDER_ID=main_club_folder_id)


# Context processor to make current_year available to all templates
import datetime
@app.context_processor
def inject_current_year():
    return {'current_year': datetime.datetime.now().year}

# Context processor to inject club_name (if needed globally, or pass per route)
@app.context_processor
def inject_club_name():
    return {'club_name': "Caribou'shots"}


if __name__ == '__main__':
    # The LOCAL_TEMP_UPLOAD_FOLDER creation is handled near the top of the script.
    app.run(debug=True, host='0.0.0.0', port=5001)
