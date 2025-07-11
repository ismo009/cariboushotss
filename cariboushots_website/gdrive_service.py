import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Path to your service account credentials JSON file
# This assumes the file is in the 'instance' folder at the root of the Flask app
INSTANCE_FOLDER_PATH = os.path.join(os.path.dirname(__file__), 'instance') # This is correct for gdrive_service.py's location
DEFAULT_CREDENTIALS_PATH = os.path.join(INSTANCE_FOLDER_PATH, 'service_account_credentials.json') # Path relative to app.py if called from there

# MAIN_CLUB_FOLDER_ID will now be passed from app.config or used as a default if this module is run standalone.

SCOPES = ['https://www.googleapis.com/auth/drive']

# It's better to get the logger from the current app context in Flask.
# For a standalone service module, standard logging can be used.
import logging
logger = logging.getLogger(__name__) # When used by Flask, Flask will configure this.


def get_drive_service(credentials_path=None):
    """
    Authenticates and returns a Google Drive service object.
    Credentials path should be absolute or resolvable from where app is run.
    """
    # If Flask app context is available, credentials_path could come from app.config
    # For now, direct path or default.
    if credentials_path is None:
        # Construct path relative to this file if run standalone, or expect app to provide full path
        credentials_path = DEFAULT_CREDENTIALS_PATH #This might need adjustment based on execution context

    try:
        creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        service = build('drive', 'v3', credentials=creds)
        logger.info("Successfully authenticated with Google Drive API.")
        return service
    except FileNotFoundError:
        logger.error(f"Credentials file not found at {credentials_path}. Please ensure it's correctly placed.")
        return None
    except Exception as e:
        logger.error(f"An error occurred during Google Drive authentication: {e}", exc_info=True)
        return None

def find_or_create_folder(service, folder_name, parent_folder_id):
    """
    Finds a folder by name within a parent folder. If not found, creates it.
    Returns the folder ID.
    """
    if not service:
        logger.error("Drive service not available for find_or_create_folder.")
        return None

    # Sanitize folder_name for query if it might contain single quotes
    safe_folder_name = folder_name.replace("'", "\\'")
    query = f"mimeType='application/vnd.google-apps.folder' and trashed=false and name='{safe_folder_name}' and '{parent_folder_id}' in parents"

    try:
        response = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        folders = response.get('files', [])
        if folders:
            logger.info(f"Folder '{folder_name}' found with ID: {folders[0].get('id')}")
            return folders[0].get('id') # Folder found
        else:
            logger.info(f"Folder '{folder_name}' not found. Creating new folder...")
            file_metadata = {
                'name': folder_name, # Use original folder_name here, not safe_folder_name
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            folder = service.files().create(body=file_metadata, fields='id').execute()
            logger.info(f"Folder '{folder_name}' created with ID: {folder.get('id')}")
            return folder.get('id')
    except HttpError as error:
        logger.error(f"An HttpError occurred while finding or creating folder '{folder_name}': {error.resp.status} - {error._get_reason()}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while finding or creating folder '{folder_name}': {e}", exc_info=True)
        return None

def upload_photo_to_drive(service, file_path, file_name, folder_id):
    """
    Uploads a photo to the specified Google Drive folder.
    Args:
        service: Authenticated Google Drive service object.
        file_path: Local path to the file to be uploaded.
        file_name: Name of the file as it should appear in Google Drive.
        folder_id: ID of the Google Drive folder to upload into.
    Returns:
        The File ID of the uploaded file, or None if an error occurred.
    """
    if not service:
        logger.error("Drive service not available for upload.")
        return None

    file_metadata = {
        'name': file_name,
        'parents': [folder_id]
    }
    # Dynamically determine mimetype or allow common image types
    import mimetypes
    mimetype, _ = mimetypes.guess_type(file_path)
    if not mimetype or not mimetype.startswith('image/'):
        logger.warning(f"Could not determine image mimetype for {file_name}, defaulting to image/jpeg.")
        mimetype = 'image/jpeg' # Default or raise error

    media = MediaFileUpload(file_path, mimetype=mimetype)

    try:
        # Request additional fields like 'webViewLink' and 'thumbnailLink' if useful immediately
        file_details = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink, thumbnailLink, webContentLink'
        ).execute()
        logger.info(f"File '{file_name}' uploaded successfully. File ID: {file_details.get('id')}, Link: {file_details.get('webViewLink')}")
        return file_details # Return the full response object
    except HttpError as error:
        logger.error(f"An HttpError occurred during upload of '{file_name}': {error.resp.status} - {error._get_reason()}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during upload of '{file_name}': {e}", exc_info=True)
        return None

def list_folders(service, parent_folder_id):
    """Lists subfolders within a given parent folder in Google Drive."""
    if not service:
        logger.error("Drive service not available for listing folders.")
        return []
    try:
        query = f"mimeType='application/vnd.google-apps.folder' and trashed=false and '{parent_folder_id}' in parents"
        results = service.files().list(
            q=query,
            pageSize=100,
            fields="nextPageToken, files(id, name)"
        ).execute()
        folders = results.get('files', [])
        logger.info(f"Found {len(folders)} subfolders in folder ID '{parent_folder_id}'.")
        return folders
    except HttpError as error:
        logger.error(f"An HttpError occurred while listing folders in '{parent_folder_id}': {error.resp.status} - {error._get_reason()}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"An unexpected error occurred while listing folders in '{parent_folder_id}': {e}", exc_info=True)
        return []

def list_photos_in_folder(service, folder_id):
    """Lists photos (images) within a specific Google Drive folder."""
    if not service:
        logger.error("Drive service not available for listing photos.")
        return []
    try:
        query = f"('{folder_id}' in parents) and (mimeType contains 'image/') and trashed=false"
        results = service.files().list(
            q=query,
            pageSize=50,
            fields="nextPageToken, files(id, name, thumbnailLink, webViewLink, createdTime, iconLink, webContentLink)"
        ).execute()
        photos = results.get('files', [])
        logger.info(f"Found {len(photos)} photos in folder ID '{folder_id}'.")
        return photos
    except HttpError as error:
        logger.error(f"An HttpError occurred while listing photos in folder '{folder_id}': {error.resp.status} - {error._get_reason()}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"An unexpected error occurred while listing photos in folder '{folder_id}': {e}", exc_info=True)
        return []

def get_folder_details(service, folder_id, main_club_folder_id_from_config):
    """Gets details for a specific folder, including its name and parents."""
    if not service:
        logger.error("Drive service not available for getting folder details.")
        return None
    if folder_id == main_club_folder_id_from_config:
        logger.info(f"Getting details for main gallery folder: {folder_id}")
        return {'id': main_club_folder_id_from_config, 'name': 'Main Gallery', 'parents': None}
    try:
        file_details = service.files().get(fileId=folder_id, fields="id, name, parents").execute()
        logger.info(f"Fetched details for folder ID '{folder_id}': Name '{file_details.get('name')}'")
        return file_details
    except HttpError as error:
        logger.error(f"An HttpError occurred while fetching details for folder '{folder_id}': {error.resp.status} - {error._get_reason()}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching details for folder '{folder_id}': {e}", exc_info=True)
        return None

if __name__ == '__main__':
    # Setup basic logging for standalone script testing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger.info("gdrive_service.py running in standalone mode for testing.")
    # Example Usage (for testing this module directly)
    # Ensure 'service_account_credentials.json' is in the 'instance' folder relative to this script,
    # or provide the correct path.
    # And ensure MAIN_CLUB_FOLDER_ID is set correctly.

    # To test, you'd need a sample image.
    # Create a dummy image file for testing:
    # e.g., in the same directory as gdrive_service.py, create a file 'test_image.jpg'

    # test_image_path = 'test_image.jpg'
    # if not os.path.exists(test_image_path):
    #     with open(test_image_path, 'w') as f:
    #         f.write("dummy image content") # Not a real image, but Drive will accept it.

    print("Attempting to connect to Google Drive...")
    drive = get_drive_service()

    if drive:
        print("Successfully connected to Google Drive.")

        # Test 1: Upload to main club folder
        # print(f"\nAttempting to upload 'test_image.jpg' to main folder ({MAIN_CLUB_FOLDER_ID})...")
        # uploaded_file = upload_photo_to_drive(drive, test_image_path, 'My Test Photo.jpg')
        # if uploaded_file:
        #     print(f"Uploaded file ID: {uploaded_file.get('id')}")
        # else:
        #     print("Upload failed.")

        # Test 2: Create a subfolder and upload to it
        # subfolder_name = "Test Event Photos"
        # print(f"\nAttempting to find or create subfolder '{subfolder_name}'...")
        # subfolder_id = find_or_create_folder(drive, subfolder_name, MAIN_CLUB_FOLDER_ID)
        # if subfolder_id:
        #     print(f"Using subfolder ID: {subfolder_id}")
        #     print(f"Attempting to upload 'test_image.jpg' to subfolder '{subfolder_name}'...")
        #     uploaded_to_subfolder = upload_photo_to_drive(drive, test_image_path, 'Another Test Photo.jpg', subfolder_id)
        #     if uploaded_to_subfolder:
        #         print(f"Uploaded file ID: {uploaded_to_subfolder.get('id')}")
        #     else:
        #         print("Upload to subfolder failed.")
        # else:
        #     print(f"Could not find or create subfolder '{subfolder_name}'.")

        # print("\nNOTE: To run tests, uncomment the test code above and create a 'test_image.jpg' file.")
    else:
        print("Failed to connect to Google Drive. Check credentials and setup.")
