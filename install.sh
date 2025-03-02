#!/bin/bash
set -e

echo "========================================"
echo "ใจดี Chatbot - Installation Script"
echo "========================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Python is not installed or not in PATH."
    echo "Please install Python 3.9 or higher from https://www.python.org/downloads/"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c "import sys; print(sys.version_info.major)")
if [ "$PYTHON_VERSION" -lt 3 ]; then
    echo "Python version 3 or higher is required. Found version $PYTHON_VERSION."
    exit 1
fi

# Check if Docker is installed (optional)
DOCKER_AVAILABLE=0
if command -v docker &> /dev/null; then
    DOCKER_AVAILABLE=1
    echo "Docker is available. You can use Docker for deployment."
else
    echo "Docker is not available. You can install it from https://www.docker.com/products/docker-desktop"
    echo "Continuing with local installation..."
fi

# Create a virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate the virtual environment and install dependencies
echo "Activating virtual environment and installing dependencies..."
source venv/bin/activate

echo "Installing required packages..."
pip install -r requirements.txt

# Check for .env file and create it if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file with default settings..."
    cat > .env << EOF
# LINE API Credentials
LINE_CHANNEL_ACCESS_TOKEN=your_line_channel_access_token
LINE_CHANNEL_SECRET=your_line_channel_secret

# Deepseek AI Configuration
DEEPSEEK_API_KEY=your_deepseek_api_key

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# MySQL Configuration
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=password
MYSQL_DB=chatbot

# For Docker Compose
MYSQL_ROOT_PASSWORD=password
EOF
    echo "Please edit the .env file with your actual credentials."
fi

echo ""
echo "Installation completed successfully!"
echo ""
echo "Available options:"
echo "1. Run locally with Python"
echo "2. Run with Docker Compose (requires Docker)"
echo "3. Exit"
echo ""

read -p "Choose an option [1-3]: " OPTION

case $OPTION in
    1)
        echo "Starting the chatbot locally..."
        python3 app_deepseek.py
        ;;
    2)
        if [ $DOCKER_AVAILABLE -eq 1 ]; then
            echo "Starting with Docker Compose..."
            docker-compose up -d
        else
            echo "Docker is not available. Cannot start with Docker Compose."
        fi
        ;;
    *)
        echo "Exiting installation."
        ;;
esac

echo ""
echo "Thank you for installing ใจดี Chatbot!"
echo "For more information, visit https://github.com/yourusername/chatbot"
echo ""

# Deactivate the virtual environment
deactivate
