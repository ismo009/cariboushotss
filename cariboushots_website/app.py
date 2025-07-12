from flask import Flask, render_template, request, redirect, url_for, flash
import os
import logging # For basic logging configuration

# --- Import Google Drive Service ---
from gdrive_service import get_drive_service, list_folders, list_photos_in_folder, get_folder_details

def enrich_folders_with_photo_data(drive_service, folders):
    """
    Enriches folder data with first photo and photo count information.
    
    Args:
        drive_service: Authenticated Google Drive service object
        folders: List of folder objects from Google Drive API
        
    Returns:
        List of enriched folder objects with first_photo and photo_count
    """
    enriched_folders = []
    
    for folder in folders:
        enriched_folder = folder.copy()  # Copy original folder data
        
        try:
            # Get photos in this folder
            photos_in_folder = list_photos_in_folder(drive_service, folder['id'])
            
            # Add photo count
            enriched_folder['photo_count'] = len(photos_in_folder)
            
            # Add first photo if available
            if photos_in_folder:
                first_photo = photos_in_folder[0]  # First photo in the list
                enriched_folder['first_photo'] = {
                    'id': first_photo.get('id'),
                    'name': first_photo.get('name'),
                    'thumbnailLink': first_photo.get('thumbnailLink'),
                    'webViewLink': first_photo.get('webViewLink'),
                    'webContentLink': first_photo.get('webContentLink')
                }
            else:
                enriched_folder['first_photo'] = None
                
            app.logger.debug(f"Folder '{folder['name']}': {len(photos_in_folder)} photos, first_photo: {'Yes' if photos_in_folder else 'No'}")
            
        except Exception as e:
            app.logger.warning(f"Error enriching folder '{folder['name']}': {e}")
            # Set default values in case of error
            enriched_folder['photo_count'] = 0
            enriched_folder['first_photo'] = None
            
        enriched_folders.append(enriched_folder)
    
    return enriched_folders

app = Flask(__name__)

# --- Configuration ---
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev_secret_key_change_me')
# Google Drive specific configurations
app.config['GOOGLE_DRIVE_MAIN_FOLDER_ID'] = os.environ.get('GOOGLE_DRIVE_MAIN_FOLDER_ID', '1jseNSB8rSM-kvz1rYLJiFyqXVR6tZ4-M')
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
INSTANCE_PATH = os.path.join(APP_ROOT, 'instance')
app.config['GOOGLE_DRIVE_CREDENTIALS_PATH'] = os.path.join(INSTANCE_PATH, 'service_account_credentials.json')

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
if app.debug:
    logging.getLogger().setLevel(logging.DEBUG)

# Ensure the instance folder exists
try:
    os.makedirs(INSTANCE_PATH, exist_ok=True)
except OSError as e:
    app.logger.error(f"CRITICAL: Error creating instance folder during app startup: {e}", exc_info=True)

# --- Routes ---
@app.route('/')
def index():
    return render_template("index.html", club_name="Caribou'Shots")

@app.route('/gallery/')
@app.route('/gallery/<folder_id>')
def gallery(folder_id=None):
    drive_service = get_drive_service(credentials_path=app.config['GOOGLE_DRIVE_CREDENTIALS_PATH'])
    if not drive_service:
        app.logger.error("Failed to get Google Drive service in /gallery route.")
        flash('Error connecting to Google Drive. Please try again later or contact support.', 'danger')
        return render_template("gallery.html", folders=[], photos=[], current_folder_name='Error',
                               parent_folder_id=None, current_folder_id=None,
                               MAIN_CLUB_FOLDER_ID=app.config['GOOGLE_DRIVE_MAIN_FOLDER_ID'])

    main_club_folder_id = app.config['GOOGLE_DRIVE_MAIN_FOLDER_ID']
    current_folder_id_to_list = folder_id if folder_id else main_club_folder_id

    app.logger.info(f"Listing gallery content for folder ID: {current_folder_id_to_list}")
    folders_in_current_view = list_folders(drive_service, current_folder_id_to_list)
    photos_in_current_view = list_photos_in_folder(drive_service, current_folder_id_to_list)

    # Enrich folders with photo data (first photo and count)
    enriched_folders = enrich_folders_with_photo_data(drive_service, folders_in_current_view)
    app.logger.info(f"Enriched {len(enriched_folders)} folders with photo data")

    current_folder_details = get_folder_details(drive_service, current_folder_id_to_list, main_club_folder_id)
    current_folder_name = "Main Gallery"
    parent_folder_id_for_nav = None

    if current_folder_details:
        current_folder_name = current_folder_details.get('name', 'Gallery')
        app.logger.debug(f"Current folder details: {current_folder_details}")
        if current_folder_details.get('parents'):
            potential_parent = current_folder_details['parents'][0]
            if current_folder_id_to_list != main_club_folder_id:
                if potential_parent == main_club_folder_id:
                    parent_folder_id_for_nav = None
                else:
                    parent_folder_id_for_nav = potential_parent
                app.logger.debug(f"Determined parent for navigation: {parent_folder_id_for_nav}")
    else:
        app.logger.warning(f"Could not retrieve details for folder ID: {current_folder_id_to_list}. Displaying as root or with default name.")
        if current_folder_id_to_list == main_club_folder_id:
            current_folder_name = "Main Gallery"
        else:
            current_folder_name = "Unknown Folder"

    for photo in photos_in_current_view:
        if not photo.get('thumbnailLink'):
            photo['thumbnailLink'] = url_for('static', filename='images/placeholder_image.png')
        if not photo.get('webViewLink'):
             photo['webViewLink'] = '#'

    return render_template("gallery.html",
                           folders=enriched_folders,
                           photos=photos_in_current_view,
                           current_folder_name=current_folder_name,
                           current_folder_id=current_folder_id_to_list,
                           parent_folder_id=parent_folder_id_for_nav,
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
