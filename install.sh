#!/bin/bash
set -e

echo "========================================"
echo "ใจดี Chatbot - Installation Script"
echo "========================================"
echo ""

# Enable debug mode if needed
DEBUG=0
if [[ "$1" == "--debug" ]]; then
    DEBUG=1
    set -x  # Enable command tracing
    echo "Debug mode enabled"
fi

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Python is not installed or not in PATH."
    echo "Please install Python 3.9 or higher from https://www.python.org/downloads/"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PYTHON_VERSION" -lt 3 ]; then
    echo "Python version 3 or higher is required. Found version $PYTHON_VERSION."
    exit 1
fi

echo "Using Python version $PYTHON_VERSION.$PYTHON_MINOR"

# Check if we're on a Debian/Ubuntu system
IS_DEBIAN_UBUNTU=0
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [[ "$ID" == "debian" || "$ID" == "ubuntu" || "$ID_LIKE" == *"debian"* ]]; then
        IS_DEBIAN_UBUNTU=1
        echo "Detected Debian/Ubuntu-based system: $PRETTY_NAME"
    fi
fi

# Check if python3-venv is installed (for Debian/Ubuntu)
VENV_PACKAGE_INSTALLED=1
if [ $IS_DEBIAN_UBUNTU -eq 1 ]; then
    if ! dpkg -l | grep -q "python$PYTHON_VERSION\.$PYTHON_MINOR-venv\|python$PYTHON_VERSION-venv\|python3-venv"; then
        VENV_PACKAGE_INSTALLED=0
        echo "The python3-venv package is required but not installed."
        echo "To install it, run: sudo apt install python${PYTHON_VERSION}.${PYTHON_MINOR}-venv"
        echo "If that's not available, try: sudo apt install python${PYTHON_VERSION}-venv"
        echo "Or: sudo apt install python3-venv"
        
        read -p "Would you like to install python3-venv automatically? (y/n): " INSTALL_VENV
        if [[ "$INSTALL_VENV" =~ ^[Yy]$ ]]; then
            echo "Installing python3-venv package..."
            if sudo apt update && sudo apt install -y python${PYTHON_VERSION}.${PYTHON_MINOR}-venv || sudo apt install -y python${PYTHON_VERSION}-venv || sudo apt install -y python3-venv; then
                echo "Successfully installed python3-venv"
                VENV_PACKAGE_INSTALLED=1
            else
                echo "Failed to install python3-venv. Please install it manually and run this script again."
                exit 1
            fi
        else
            echo "Please install python3-venv manually and run this script again."
            exit 1
        fi
    fi
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
    if [ $? -ne 0 ]; then
        echo "Failed to create virtual environment."
        echo "If you're on Ubuntu/Debian, please ensure python3-venv is installed."
        echo "You can install it using: sudo apt install python${PYTHON_VERSION}.${PYTHON_MINOR}-venv"
        exit 1
    fi
fi

# Explicitly check if the activation script exists
if [ ! -f "venv/bin/activate" ]; then
    echo "Virtual environment was created, but activation script wasn't found."
    echo "This might indicate an issue with your Python installation or permissions."
    echo "Try recreating the virtual environment manually:"
    echo "    rm -rf venv"
    echo "    python3 -m venv venv"
    
    # Additional diagnostics
    echo "Checking virtual environment structure:"
    ls -la venv/
    if [ -d "venv/bin" ]; then
        echo "Contents of venv/bin:"
        ls -la venv/bin/
    else
        echo "venv/bin directory doesn't exist!"
    fi
    
    exit 1
fi

# Activate the virtual environment and install dependencies
echo "Activating virtual environment and installing dependencies..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "Failed to activate virtual environment."
    exit 1
fi

# Verify activation
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "Virtual environment activation didn't work as expected."
    exit 1
fi

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
