# AutoDBDoc

A Python tool that automatically generates Word documents containing Oracle database table documentation.

## Features

- Connects to Oracle database and extracts table metadata
- Generates detailed documentation for each table including:
  - Column information (name, data type, length, nullable, default value)
  - Table constraints
- Creates a well-formatted Word document with proper styling
- Web interface for easy database connection and document generation

## Prerequisites

- Python 3.8 or higher
- Oracle Client libraries installed on your system
- Poetry for dependency management

## Installation

1. Clone this repository
2. Install dependencies using Poetry:
   ```bash
   poetry install
   ```

## Usage

### Web Interface (Recommended)

1. Start the web server:
   ```bash
   poetry run python -m autodbdoc.web_app
   ```

2. Open your web browser and navigate to:
   ```
   http://localhost:5000
   ```

3. Enter your database connection details:
   - Host
   - Port (default: 1521)
   - Service Name
   - Username
   - Password

4. Click "Generate Documentation" to create and download the Word document

### Command Line Interface

Alternatively, you can use the command line interface:

1. Copy the `.env.example` file to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit the `.env` file with your Oracle database connection details:
   ```
   DB_USER=your_username
   DB_PASSWORD=your_password
   DB_HOST=your_host
   DB_PORT=1521
   DB_SERVICE=your_service_name
   ```

3. Run the script:
   ```bash
   poetry run python -m autodbdoc.main
   ```

## Output

The generated Word document will include:
- A title page with database name and generation date
- Detailed documentation for each table including:
  - Column information in a formatted table
  - Table constraints
  - Proper formatting and styling for better readability 