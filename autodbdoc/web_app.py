from flask import Flask, render_template, request, send_file, flash, redirect, url_for, jsonify
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, IntegerField, SubmitField, RadioField, TextAreaField
from wtforms.validators import DataRequired, NumberRange, Optional
import os
import logging
from datetime import datetime
from autodbdoc.db_reader import OracleDBReader
from autodbdoc.doc_generator import DocGenerator
from flask_apscheduler import APScheduler
import uuid
import sqlite3
import json
import time
from apscheduler.schedulers.background import BackgroundScheduler
from .logger_config import logger
import threading

def setup_logging():
    """Configure logging for the application."""
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/autodbdoc.log'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

# Initialize logger
logger = setup_logging()

def init_db():
    """Initialize the SQLite database."""
    db_path = 'jobs.db'
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # Create jobs table with additional user and request info
    c.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            message TEXT,
            current INTEGER DEFAULT 0,
            total INTEGER DEFAULT 0,
            filename TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_ip TEXT,
            user_agent TEXT,
            connection_type TEXT,
            host TEXT,
            port INTEGER,
            service_name TEXT,
            username TEXT,
            request_data TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db():
    """Get a database connection."""
    conn = sqlite3.connect('jobs.db', timeout=30)  # Add timeout to handle concurrent access
    conn.row_factory = sqlite3.Row
    return conn

def update_job_status(job_id, status, message=None, current=None, total=None, filename=None):
    """Update the status of a job in the database."""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            conn = get_db()
            c = conn.cursor()
            
            updates = ['status = ?', 'updated_at = CURRENT_TIMESTAMP']
            params = [status]
            
            if message is not None:
                updates.append('message = ?')
                params.append(message)
            if current is not None:
                updates.append('current = ?')
                params.append(current)
            if total is not None:
                updates.append('total = ?')
                params.append(total)
            if filename is not None:
                updates.append('filename = ?')
                params.append(filename)
            
            params.append(job_id)
            
            query = f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?"
            c.execute(query, params)
            conn.commit()
            conn.close()
            return
        except sqlite3.OperationalError as e:
            retry_count += 1
            if retry_count == max_retries:
                logger.error("Failed to update job status after %d retries: %s", max_retries, str(e))
                raise
            logger.warning("Database locked, retrying (%d/%d)...", retry_count, max_retries)
            time.sleep(0.1)  # Wait before retrying

def get_job_status(job_id):
    """Get the status of a job from the database."""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute('SELECT * FROM jobs WHERE job_id = ?', (job_id,))
            job = c.fetchone()
            conn.close()
            
            if job:
                return dict(job)
            return None
        except sqlite3.OperationalError as e:
            retry_count += 1
            if retry_count == max_retries:
                logger.error("Failed to get job status after %d retries: %s", max_retries, str(e))
                raise
            logger.warning("Database locked, retrying (%d/%d)...", retry_count, max_retries)
            time.sleep(0.1)  # Wait before retrying

def create_job(job_id, request_info, connection_params):
    """Create a new job entry in the database."""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            conn = get_db()
            c = conn.cursor()
            
            # Check if job already exists
            c.execute('SELECT job_id FROM jobs WHERE job_id = ?', (job_id,))
            if c.fetchone():
                logger.warning("Job %s already exists, skipping creation", job_id)
                conn.close()
                return
            
            # Prepare request data for storage
            request_data = {
                'connection_type': connection_params.get('connection_type'),
                'host': connection_params.get('host'),
                'port': connection_params.get('port'),
                'service_name': connection_params.get('service_name'),
                'username': connection_params.get('username')
            }
            
            c.execute('''
                INSERT INTO jobs (
                    job_id, status, message, current, total,
                    user_ip, user_agent, connection_type, host,
                    port, service_name, username, request_data
                ) VALUES (
                    ?, 'running', 'Initializing...', 0, 0,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
            ''', (
                job_id,
                request_info.get('ip'),
                request_info.get('user_agent'),
                connection_params.get('connection_type'),
                connection_params.get('host'),
                connection_params.get('port'),
                connection_params.get('service_name'),
                connection_params.get('username'),
                json.dumps(request_data)
            ))
            
            conn.commit()
            conn.close()
            return
        except sqlite3.OperationalError as e:
            retry_count += 1
            if retry_count == max_retries:
                logger.error("Failed to create job after %d retries: %s", max_retries, str(e))
                raise
            logger.warning("Database locked, retrying (%d/%d)...", retry_count, max_retries)
            time.sleep(0.1)  # Wait before retrying

def get_request_info(request):
    """Extract relevant information from the request."""
    return {
        'ip': request.remote_addr,
        'user_agent': request.headers.get('User-Agent'),
        'referrer': request.headers.get('Referer'),
        'accept_language': request.headers.get('Accept-Language'),
        'accept_encoding': request.headers.get('Accept-Encoding')
    }

def cleanup_old_files():
    """Remove files older than 10 minutes from the generated_docs directory."""
    current_time = time.time()
    for filename in os.listdir(app.config['UPLOAD_FOLDER']):
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file_creation_time = os.path.getctime(filepath)
        age_in_minutes = (current_time - file_creation_time) / 60
        
        if age_in_minutes > 10:
            try:
                os.remove(filepath)
                logger.info(f"Removed old file: {filename}")
            except Exception as e:
                logger.error(f"Error removing file {filename}: {str(e)}")

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF protection
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'generated_docs')
app.config['SCHEDULER_API_ENABLED'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 1800  # 30 minutes
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching for downloads
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Store active jobs
active_jobs = {}

# Initialize the database
init_db()

# Add CORS headers to all responses
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# Handle OPTIONS requests
@app.route('/', methods=['OPTIONS'])
def handle_options():
    return '', 204

class DatabaseForm(FlaskForm):
    connection_type = RadioField(
        'Connection Type',
        choices=[
            ('basic', 'Basic Connection'),
            ('tns', 'TNS Names'),
            ('connection_string', 'Connection String')
        ],
        default='basic',
        validators=[DataRequired()]
    )
    
    # Basic connection fields
    host = StringField('Host', validators=[Optional()])
    port = IntegerField('Port', validators=[Optional(), NumberRange(min=1, max=65535)], default=1521)
    service_name = StringField('Service Name', validators=[Optional()])
    username = StringField('Username', validators=[Optional()])
    password = PasswordField('Password', validators=[Optional()])
    
    # TNS names fields
    tns_config = TextAreaField('TNS Names Configuration', validators=[Optional()])
    
    # Connection string field
    connection_string = TextAreaField('Connection String', validators=[Optional()])
    
    submit = SubmitField('Generate Documentation')

    def validate(self, extra_validators=None):
        if not super().validate():
            return False
            
        # Validate based on connection type
        if self.connection_type.data == 'basic':
            if not self.host.data or not self.service_name.data:
                self.host.errors.append('Host and Service Name are required for basic connection')
                self.service_name.errors.append('Host and Service Name are required for basic connection')
                return False
            if not self.username.data or not self.password.data:
                self.username.errors.append('Username and Password are required for basic connection')
                self.password.errors.append('Username and Password are required for basic connection')
                return False
        elif self.connection_type.data == 'tns':
            if not self.tns_config.data:
                self.tns_config.errors.append('TNS configuration is required')
                return False
            if not self.username.data or not self.password.data:
                self.username.errors.append('Username and Password are required for TNS connection')
                self.password.errors.append('Username and Password are required for TNS connection')
                return False
        elif self.connection_type.data == 'connection_string':
            if not self.connection_string.data:
                self.connection_string.errors.append('Connection string is required')
                return False
                
        return True

def parse_connection_string(connection_string):
    """Parse Oracle connection string into basic connection parameters."""
    try:
        # Remove any whitespace
        connection_string = connection_string.strip()
        
        # Split into user/pass and connection details
        if '@' not in connection_string:
            raise ValueError("Invalid connection string format. Expected format: username/password@host:port/service_name")
            
        credentials, connection = connection_string.split('@')
        if '/' not in credentials:
            raise ValueError("Invalid credentials format. Expected format: username/password")
            
        username, password = credentials.split('/')
        
        # Parse connection details
        if ':' not in connection:
            raise ValueError("Invalid connection format. Expected format: host:port/service_name")
            
        host_port, service_name = connection.split('/')
        if ':' not in host_port:
            raise ValueError("Invalid host:port format")
            
        host, port = host_port.split(':')
        port = int(port)
        
        return {
            'username': username,
            'password': password,
            'host': host,
            'port': port,
            'service_name': service_name
        }
    except Exception as e:
        logger.error("Error parsing connection string: %s", str(e))
        raise ValueError(f"Invalid connection string format: {str(e)}")

def parse_tns_config(tns_config):
    """Parse TNS configuration string to extract connection details."""
    try:
        # Split the configuration into lines and clean them
        lines = [line.strip() for line in tns_config.split('\n') if line.strip()]
        
        # Find the TNS name (first line ending with =)
        tns_name = None
        for line in lines:
            if line.endswith('='):
                tns_name = line.strip('= ').strip()
                break
        
        if not tns_name:
            raise ValueError("No TNS name found in configuration")
        
        logger.info(f"Found TNS name: {tns_name}")
        return {
            'tns_name': tns_name,
            'tns_config': tns_config
        }
    except Exception as e:
        logger.error(f"Error parsing TNS configuration: {str(e)}")
        raise

def generate_documentation(job_id, connection_params, selected_tables=None):
    """Generate documentation for the database in a background thread."""
    try:
        # Initialize database reader
        db_reader = OracleDBReader(connection_params)
        
        # Update job status
        update_job_status(
            job_id=job_id,
            status='running',
            message='Connected to database',
            current=5,
            total=100
        )
        
        # Create output directory if it doesn't exist
        output_dir = app.config['UPLOAD_FOLDER']
        os.makedirs(output_dir, exist_ok=True)
        
        # Define progress callback
        def progress_callback(message, current, total):
            update_job_status(
                job_id=job_id,
                status='running',
                message=message,
                current=current,
                total=total
            )
        
        # Initialize document generator
        doc_generator = DocGenerator(db_reader, progress_callback=progress_callback)
        
        # Generate documentation
        service_name = connection_params.get('service_name', 'Oracle Database')
        
        # Generate the documentation with selected tables
        filename = doc_generator.generate_documentation(service_name, output_dir, selected_tables)
        
        # Update job status
        update_job_status(
            job_id=job_id,
            status='completed',
            message='Documentation generated successfully',
            current=100,
            total=100,
            filename=filename
        )
        
        # Clean up old files
        cleanup_old_files()
        
    except Exception as e:
        logger.error(f"Error generating documentation: {str(e)}")
        update_job_status(
            job_id=job_id,
            status='error',
            message=f"Error: {str(e)}",
            current=0,
            total=100
        )

@app.route('/', methods=['GET', 'POST'])
def index():
    """Render the home page and handle form submission."""
    form = DatabaseForm()
    
    if request.method == 'POST':
        # Check if it's a form submission
        if form.validate_on_submit():
            try:
                request_info = get_request_info(request)
                
                # Parse connection parameters based on connection type
                connection_params = {}
                if form.connection_type.data == 'basic':
                    connection_params = {
                        'username': form.username.data,
                        'password': form.password.data,
                        'host': form.host.data,
                        'port': form.port.data,
                        'service_name': form.service_name.data
                    }
                elif form.connection_type.data == 'tns':
                    connection_params = parse_tns_config(form.tns_config.data)
                    connection_params['username'] = form.username.data
                    connection_params['password'] = form.password.data
                elif form.connection_type.data == 'connection_string':
                    connection_params = parse_connection_string(form.connection_string.data)
                
                # Validate connection parameters
                if not connection_params:
                    flash('Invalid connection parameters', 'danger')
                    return render_template('index.html', form=form)
                
                # Create a new job
                job_id = str(uuid.uuid4())
                create_job(job_id, request_info, connection_params)
                
                # Return success with job ID for table selection step
                return jsonify({
                    'status': 'success',
                    'message': 'Connection established',
                    'job_id': job_id,
                    'connection_params': connection_params
                })
                
            except Exception as e:
                logger.error(f"Error processing form: {str(e)}")
                return jsonify({
                    'status': 'error',
                    'message': f"Error: {str(e)}"
                })
        else:
            # Return validation errors as JSON
            return jsonify({
                'status': 'error',
                'message': 'Form validation failed',
                'errors': form.errors
            })
        
        # If we got here, something went wrong
        return jsonify({
            'status': 'error',
            'message': 'An unexpected error occurred'
        })
    
    # GET request - render the form
    return render_template('index.html', form=form)

@app.route('/progress/<job_id>')
def get_progress(job_id):
    """Get progress for a specific job."""
    job_status = get_job_status(job_id)
    if not job_status:
        return jsonify({'status': 'error', 'message': 'Job not found'}), 404
    return jsonify(job_status)

@app.route('/download/<filename>')
def download_file(filename):
    try:
        logger.info(f"Downloading file: {filename}")
        return send_file(
            os.path.join(app.config['UPLOAD_FOLDER'], filename),
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 404

@app.route('/tables', methods=['POST'])
def get_tables():
    """Get the list of tables for the given connection parameters."""
    connection_params = request.json.get('connection_params')
    
    if not connection_params:
        return jsonify({'status': 'error', 'message': 'Missing connection parameters'})
    
    try:
        # Initialize database reader
        db_reader = OracleDBReader(connection_params)
        
        # Get list of tables
        tables = db_reader.get_tables()
        
        # Close the connection
        db_reader.close()
        
        return jsonify({
            'status': 'success',
            'tables': tables
        })
    except Exception as e:
        logger.error(f"Error getting tables: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"Failed to get tables: {str(e)}"
        })

@app.route('/generate', methods=['POST'])
def start_generation():
    """Start the documentation generation process with selected tables."""
    data = request.json
    job_id = data.get('job_id')
    connection_params = data.get('connection_params')
    selected_tables = data.get('selected_tables')
    
    if not job_id or not connection_params:
        return jsonify({
            'status': 'error',
            'message': 'Missing job_id or connection_params'
        })
    
    try:
        # Get job details
        conn = get_db()
        job = conn.execute(
            'SELECT * FROM jobs WHERE job_id = ?', (job_id,)
        ).fetchone()
        conn.close()
        
        if not job:
            return jsonify({
                'status': 'error',
                'message': 'Invalid job ID'
            })
        
        # Update job status
        update_job_status(
            job_id=job_id,
            status='starting',
            message='Starting documentation generation...',
            current=0,
            total=100
        )
        
        # Start generation in a background thread
        thread = threading.Thread(
            target=generate_documentation,
            args=(job_id, connection_params, selected_tables)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'success',
            'message': 'Documentation generation started',
            'job_id': job_id
        })
        
    except Exception as e:
        logger.error(f"Error starting generation: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"Error: {str(e)}"
        })

if __name__ == '__main__':
    logger.info("Starting Flask application")
    app.run(debug=True, host='0.0.0.0', port=8080) 