import os
from autodbdoc.db_reader import OracleDBReader
from autodbdoc.doc_generator import DocGenerator

def main():
    # Initialize database reader
    db_reader = OracleDBReader()
    
    try:
        # Get list of tables
        tables = db_reader.get_tables()
        print(f"Found {len(tables)} tables in the database")
        
        # Initialize document generator
        doc_generator = DocGenerator()
        
        # Create title page
        doc_generator.create_title_page(os.getenv('DB_SERVICE', 'Oracle Database'))
        
        # Process each table
        for table_name in tables:
            print(f"Processing table: {table_name}")
            
            # Get table metadata
            table_description = db_reader.get_table_description(table_name)
            columns = db_reader.get_table_columns(table_name)
            constraints = db_reader.get_table_constraints(table_name)
            
            # Add table documentation to the document
            doc_generator.add_table_documentation(table_name, table_description, columns, constraints)
        
        # Save the document
        output_file = f"database_documentation_{os.getenv('DB_SERVICE', 'oracle')}.docx"
        doc_generator.save(output_file)
        print(f"\nDocumentation has been generated successfully: {output_file}")
        
    except Exception as e:
        print(f"An error occurred: {str(e)}")
    finally:
        # Close database connection
        db_reader.close()

if __name__ == "__main__":
    main() 