from flask import Flask, render_template, jsonify, send_from_directory
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import folium
import gpxpy
import os
import json
from datetime import datetime


from dotenv import load_dotenv
load_dotenv()


# Initialize Flask app
app = Flask(__name__)

# Define paths relative to src/app.py
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Root directory
GPX_FOLDER = os.path.join(BASE_DIR, 'gpx_files')  # Path to gpx_files
STATIC_MAPS_FOLDER = os.path.join(BASE_DIR, 'static', 'maps')  # Path to static/maps
TEMPLATES_FOLDER = os.path.join(BASE_DIR, 'templates')  # Path to templates

# Set the template and static folders for Flask
app.template_folder = TEMPLATES_FOLDER
app.static_folder = os.path.join(BASE_DIR, 'static')

class GPXMapGenerator:
    def __init__(self):
        self.SCOPES = ['https://spreadsheets.google.com/feeds',
                      'https://www.googleapis.com/auth/drive']
        self.credentials = self.get_credentials_from_env()

    def get_credentials_from_env(self):
        """Get credentials from the environment variable"""
        credentials_json = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
        if not credentials_json:
            raise ValueError("GOOGLE_SHEETS_CREDENTIALS environment variable not set")
        credentials_info = json.loads(credentials_json)
        return ServiceAccountCredentials.from_json_keyfile_dict(credentials_info, self.SCOPES)

    def setup_sheets_connection(self):
        """Set up Google Sheets connection using service account"""
        client = gspread.authorize(self.credentials)
        return client

    def get_spreadsheet_data(self, sheet_url):
        """Get data from Google Sheets"""
        client = self.setup_sheets_connection()
        sheet = client.open_by_url(sheet_url).sheet1
        data = sheet.get_all_records()
        return pd.DataFrame(data)

    def compute_gpx_distance(self, file_path):
        """Compute total distance from a GPX file"""
        total_distance = 0.0
        try:
            with open(file_path, "r") as gpx_file:
                gpx = gpxpy.parse(gpx_file)
                for track in gpx.tracks:
                    for segment in track.segments:
                        total_distance += segment.length_2d()
        except FileNotFoundError:
            print(f"File not found: {file_path}")
        return total_distance / 1000  # Convert to km

    def create_map(self, df, gpx_folder=GPX_FOLDER):
        """Create a Folium map with GPX tracks"""
        m = folium.Map(location=[40.7831, -73.9712], 
                      zoom_start=12, 
                      tiles="CartoDB positron")
        
        total_walked_distance = 0.0
        route_color = "blue"
        
        for _, row in df.iterrows():
            route_id = f'route{row["GPX file ID"]}'
            date = row["Date (walk)"]
            comment = row.get("Comments", "")
            
            file_path = os.path.join(gpx_folder, f"{route_id}.gpx")
            walked_distance = self.compute_gpx_distance(file_path)
            total_walked_distance += walked_distance
            
            try:
                with open(file_path, "r") as gpx_file:
                    gpx = gpxpy.parse(gpx_file)
                    for track in gpx.tracks:
                        for segment in track.segments:
                            points = [(point.latitude, point.longitude) 
                                    for point in segment.points]
                            folium.PolyLine(
                                points,
                                color=route_color,
                                weight=4,
                                opacity=0.9,
                                tooltip=f"{date}: {comment} ({walked_distance:.2f} km)"
                            ).add_to(m)
            except FileNotFoundError:
                print(f"File not found: {file_path}")
                
        return m, total_walked_distance

def generate_map():
    sheet_url = os.getenv('SHEET_URL')  # Read from environment variable
    if not sheet_url:
        return {'success': False, 'error': 'SHEET_URL environment variable not set'}
    
    generator = GPXMapGenerator()
    
    try:
        df = generator.get_spreadsheet_data(sheet_url)
        m, total_walked_distance = generator.create_map(df)
        
        # Save map
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        map_filename = f'gpx_map_{timestamp}.html'
        map_path = os.path.join(STATIC_MAPS_FOLDER, map_filename)
        m.save(map_path)
        
        # Keep only the latest 5 maps
        cleanup_old_maps()
        
        return {
            'success': True,
            'map_file': map_filename,
            'total_distance': round(total_walked_distance, 2),
            'timestamp': datetime.now().strftime("%Y-%m-%d")
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

def cleanup_old_maps(keep_latest=5):
    """Keep only the latest n maps"""
    if os.path.exists(STATIC_MAPS_FOLDER):
        files = sorted([f for f in os.listdir(STATIC_MAPS_FOLDER) if f.endswith('.html')],
                      key=lambda x: os.path.getctime(os.path.join(STATIC_MAPS_FOLDER, x)),
                      reverse=True)
        for old_file in files[keep_latest:]:
            os.remove(os.path.join(STATIC_MAPS_FOLDER, old_file))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/update_map')
def update_map():
    return jsonify(generate_map())

@app.route('/static/maps/<path:filename>')
def serve_map(filename):
    return send_from_directory(STATIC_MAPS_FOLDER, filename)

if __name__ == '__main__':
    # Create static/maps directory if it doesn't exist
    os.makedirs(STATIC_MAPS_FOLDER, exist_ok=True)
    app.run(debug=True, port=5001)