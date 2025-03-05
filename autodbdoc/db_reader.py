import cx_Oracle
from typing import List, Dict, Any
import os
from dotenv import load_dotenv
import platform
import sys
import subprocess
from .logger_config import logger
import re

def check_oracle_client():
    """Check if Oracle Client is properly installed and accessible."""
    instantclient_path = os.path.expanduser('~/oracle/instantclient')
    required_files = [
        'libclntsh.dylib',
        'libnnz.dylib',
        'libclntshcore.dylib',
        'libons.dylib'
    ]
    
    # Check if instantclient directory exists
    if not os.path.exists(instantclient_path):
        logger.error(f"Oracle Instant Client directory not found at: {instantclient_path}")
        return False
    
    return True

def init_oracle_client():
    """Initialize Oracle Client with appropriate library path."""
    if platform.system() == 'Darwin':  # macOS
        instantclient_path = os.path.expanduser('~/oracle/instantclient')
        
        if not check_oracle_client():
            logger.error("\nPlease install Oracle Instant Client:")
            logger.error("1. Download Oracle Instant Client for macOS ARM64 from:")
            logger.error("   https://www.oracle.com/database/technologies/instant-client/downloads.html")
            logger.error("2. Extract the downloaded zip file")
            logger.error("3. Move the contents to ~/oracle/instantclient")
            logger.error("\nAfter installation, try running the script again.")
            sys.exit(1)
        
        try:
            cx_Oracle.init_oracle_client(lib_dir=instantclient_path)
            logger.info(f"Successfully initialized Oracle Client from: {instantclient_path}")
            return True
        except cx_Oracle.DatabaseError as e:
            logger.error(f"Failed to initialize Oracle Client: {str(e)}")
            sys.exit(1)
    return True

# Initialize Oracle Client
init_oracle_client()

class OracleDBReader:
    def __init__(self, connection_params=None):
        """
        Initialize the database reader with connection parameters.
        
        Args:
            connection_params (dict): Dictionary containing connection parameters:
                For basic connection:
                    - username: Database username
                    - password: Database password
                    - host: Database host
                    - port: Database port
                    - service_name: Database service name
                For TNS connection:
                    - username: Database username
                    - password: Database password
                    - tns_config: Complete TNS configuration string
        """
        self.connection = None
        self.connection_params = connection_params
        self.connect()

    def connect(self):
        """Establish connection to Oracle database using provided parameters."""
        try:
            if not self.connection_params:
                raise ValueError("Connection parameters are required")
            
            # Check if using TNS configuration
            if 'tns_config' in self.connection_params:
                # Parse TNS configuration to extract connection details
                tns_lines = self.connection_params['tns_config'].strip().split('\n')
                host = None
                port = None
                service_name = None

                # Function to extract host, port, and service_name
                def extract_tns_details(tns_string):
                    # Remove extra whitespace and newlines for easier parsing
                    tns_string = ' '.join(tns_string.split())

                    # Regular expressions to match the desired fields
                    host_match = re.search(r'HOST\s*=\s*([^)]+)', tns_string)
                    port_match = re.search(r'PORT\s*=\s*(\d+)', tns_string)
                    service_match = re.search(r'SERVICE_NAME\s*=\s*([^)]+)', tns_string)

                    # Extract values if matches are found
                    host = host_match.group(1) if host_match else None
                    port = port_match.group(1) if port_match else None
                    service_name = service_match.group(1) if service_match else None

                    return host, port, service_name
                
                # Extract connection details from TNS configuration
                host, port, service_name = extract_tns_details(self.connection_params['tns_config'])
                
                logger.info(f"Host: {host}, Port: {port}, Service Name: {service_name}")
                if not all([host, port, service_name]):
                    raise ValueError("Missing required TNS parameters (HOST, PORT, or SERVICE_NAME)")
                
                # Create DSN using extracted parameters
                dsn = cx_Oracle.makedsn(
                    host=host,
                    port=port,
                    service_name=service_name
                )
                
                # Connect using the DSN
                self.connection = cx_Oracle.connect(
                    user=self.connection_params['username'],
                    password=self.connection_params['password'],
                    dsn=dsn
                )
                logger.info("Successfully connected to database using TNS configuration")
            else:
                # Create DSN using basic connection parameters
                dsn = cx_Oracle.makedsn(
                    host=self.connection_params['host'],
                    port=self.connection_params['port'],
                    service_name=self.connection_params['service_name']
                )
                
                # Connect using the DSN
                self.connection = cx_Oracle.connect(
                    user=self.connection_params['username'],
                    password=self.connection_params['password'],
                    dsn=dsn
                )
                logger.info("Successfully connected to database using basic configuration")
        except cx_Oracle.Error as error:
            logger.error(f"Error connecting to Oracle database: {error}")
            raise

    def get_table_description(self, table_name: str) -> str:
        """Get table description from user_tab_comments."""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT comments 
            FROM user_tab_comments 
            WHERE table_name = :1
        """, [table_name])
        result = cursor.fetchone()
        return result[0] if result and result[0] else ""

    def get_column_comments(self, table_name: str) -> Dict[str, str]:
        """Get column comments from user_col_comments."""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT column_name, comments 
            FROM user_col_comments 
            WHERE table_name = :1
        """, [table_name])
        
        comments = {}
        for row in cursor.fetchall():
            comments[row[0]] = row[1] if row[1] else ""
        return comments

    def get_tables(self) -> List[str]:
        """Get list of all tables in the database."""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT table_name 
            FROM user_tables 
            ORDER BY table_name
        """)
        return [row[0] for row in cursor.fetchall()]

    def get_table_columns(self, table_name: str) -> List[Dict[str, Any]]:
        """Get column information for a specific table."""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT 
                c.column_name,
                c.data_type,
                c.data_length,
                c.nullable,
                c.data_default,
                c.column_id,
                cc.comments
            FROM user_tab_columns c
            LEFT JOIN user_col_comments cc ON c.table_name = cc.table_name 
                AND c.column_name = cc.column_name
            WHERE c.table_name = :1
            ORDER BY c.column_id
        """, [table_name])
        
        columns = []
        for row in cursor.fetchall():
            columns.append({
                'name': row[0],
                'data_type': row[1],
                'length': row[2],
                'nullable': row[3],
                'default': row[4],
                'position': row[5],
                'description': row[6] if row[6] else ""
            })
        return columns

    def get_table_constraints(self, table_name: str) -> List[Dict[str, Any]]:
        """Get constraint information for a specific table."""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT 
                c.constraint_name,
                c.constraint_type,
                c.search_condition,
                cc.column_name,
                cc.position
            FROM user_constraints c
            LEFT JOIN user_cons_columns cc ON c.constraint_name = cc.constraint_name
            WHERE c.table_name = :1
            ORDER BY c.constraint_name, cc.position
        """, [table_name])
        
        constraints = []
        pk_columns = {}  # Dictionary to store primary key columns by constraint name
        
        for row in cursor.fetchall():
            constraint_name, constraint_type, search_condition, column_name, position = row
            
            # Skip NOT NULL constraints as they're redundant with the nullable column information
            if constraint_type == 'C' and search_condition and 'IS NOT NULL' in search_condition:
                continue
            
            # Handle primary key constraints
            if constraint_type == 'P':
                if constraint_name not in pk_columns:
                    pk_columns[constraint_name] = []
                pk_columns[constraint_name].append(column_name)
                continue
            
            # Handle other constraints
            constraints.append({
                'name': constraint_name,
                'type': constraint_type,
                'condition': search_condition,
                'column': column_name
            })
        
        # Add primary key constraints with all columns
        for pk_name, columns in pk_columns.items():
            constraints.append({
                'name': pk_name,
                'type': 'P',
                'columns': columns
            })
        
        return constraints

    def close(self):
        """Close the database connection."""
        if self.connection:
            self.connection.close() 