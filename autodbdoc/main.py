import os
from dotenv import load_dotenv
from autodbdoc.db_reader import OracleDBReader
from autodbdoc.doc_generator import DocGenerator
import sys
import shutil
import argparse

def get_terminal_width():
    """Get the width of the terminal."""
    return shutil.get_terminal_size().columns

def progress_callback(message, progress, total):
    """Display progress in CLI mode."""
    # Calculate percentage
    percentage = int((progress / total) * 100)
    
    # Get terminal width and adjust bar length
    terminal_width = get_terminal_width()
    bar_length = min(50, terminal_width - 40)  # Leave space for percentage and message
    
    # Create progress bar
    filled_length = int(bar_length * progress / total)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    
    # Truncate message if too long
    max_message_length = terminal_width - bar_length - 15  # Account for bar and percentage
    if len(message) > max_message_length:
        message = message[:max_message_length-3] + '...'
    
    # Clear the current line
    sys.stdout.write('\r' + ' ' * terminal_width + '\r')
    
    # Print progress bar and message
    sys.stdout.write(f'[{bar}] {percentage:3d}% | {message}')
    sys.stdout.flush()
    
    # If progress is 100%, print newline
    if progress >= total:
        print()

def list_tables(db_reader):
    """List all available tables."""
    tables = db_reader.get_tables()
    print("\nAvailable tables:")
    for i, table in enumerate(tables, 1):
        print(f"{i}. {table}")
    return tables

def select_tables(tables):
    """Let user select tables to document."""
    print("\nEnter table numbers to document (comma-separated) or 'all' for all tables:")
    selection = input().strip().lower()
    
    if selection == 'all':
        return None
    
    try:
        indices = [int(x.strip()) - 1 for x in selection.split(',')]
        selected_tables = [tables[i] for i in indices]
        return selected_tables
    except (ValueError, IndexError):
        print("Invalid selection. Please enter valid table numbers or 'all'.")
        return select_tables(tables)

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Generate database documentation')
    parser.add_argument('--list', action='store_true', help='List available tables and exit')
    parser.add_argument('--tables', nargs='+', help='Specific tables to document')
    args = parser.parse_args()
    
    # Load environment variables
    load_dotenv()
    
    # Get connection parameters from environment variables
    connection_params = {
        'username': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD'),
        'host': os.getenv('DB_HOST'),
        'port': int(os.getenv('DB_PORT', '1521')),
        'service_name': os.getenv('DB_SERVICE')
    }
    
    # Validate required environment variables
    required_vars = ['DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_SERVICE']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please check your .env file and ensure all required variables are set.")
        return
    
    # Initialize database reader with connection parameters
    db_reader = OracleDBReader(connection_params)
    
    try:
        # Get list of tables
        tables = db_reader.get_tables()
        
        # Handle --list option
        if args.list:
            list_tables(db_reader)
            return
        
        # Handle --tables option
        selected_tables = args.tables if args.tables else None
        
        # If no tables specified, let user select
        if not selected_tables:
            tables = list_tables(db_reader)
            selected_tables = select_tables(tables)
        
        # Initialize document generator with progress callback
        doc_generator = DocGenerator(db_reader, progress_callback=progress_callback)
        
        # Generate documentation
        service_name = os.getenv('DB_SERVICE', 'Oracle Database')
        output_dir = "generated_docs"
        os.makedirs(output_dir, exist_ok=True)
        
        filename = doc_generator.generate_documentation(service_name, output_dir, selected_tables)
        print(f"\nDocumentation has been generated successfully: {filename}")
        
    except Exception as e:
        print(f"An error occurred: {str(e)}")
    finally:
        # Close database connection
        db_reader.close()

if __name__ == "__main__":
    main() 