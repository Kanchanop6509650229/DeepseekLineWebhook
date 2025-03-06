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

# Check for required packages on Debian/Ubuntu
if [ $IS_DEBIAN_UBUNTU -eq 1 ]; then
    # Check for python3-venv
    VENV_PACKAGE_INSTALLED=0
    if dpkg -l | grep -q "python${PYTHON_VERSION}\.${PYTHON_MINOR}-venv\|python${PYTHON_VERSION}-venv\|python3-venv"; then
        VENV_PACKAGE_INSTALLED=1
        echo "Python virtual environment packages are already installed."
    else
        echo "The python3-venv package is required but not installed."
    fi
    
    # Check for python3-dev (needed for compiling extensions)
    DEV_PACKAGE_INSTALLED=0
    if dpkg -l | grep -q "python${PYTHON_VERSION}\.${PYTHON_MINOR}-dev\|python${PYTHON_VERSION}-dev\|python3-dev"; then
        DEV_PACKAGE_INSTALLED=1
        echo "Python development packages are already installed."
    else
        echo "Python development packages are required but not installed."
    fi
    
    # If either package is missing, offer to install
    if [ $VENV_PACKAGE_INSTALLED -eq 0 ] || [ $DEV_PACKAGE_INSTALLED -eq 0 ]; then
        echo ""
        echo "Missing required packages:"
        [ $VENV_PACKAGE_INSTALLED -eq 0 ] && echo "- python3-venv (for virtual environments)"
        [ $DEV_PACKAGE_INSTALLED -eq 0 ] && echo "- python3-dev (for compiling extensions)"
        echo ""
        
        read -p "Would you like to install these packages automatically? (y/n): " INSTALL_PACKAGES
        if [[ "$INSTALL_PACKAGES" =~ ^[Yy]$ ]]; then
            echo "Installing required Python packages..."
            
            # Build an array of packages to install
            PACKAGES_TO_INSTALL=()
            
            if [ $VENV_PACKAGE_INSTALLED -eq 0 ]; then
                # Try specific version first, then fall back to generic
                if apt-cache search --names-only "python${PYTHON_VERSION}.${PYTHON_MINOR}-venv" | grep -q .; then
                    PACKAGES_TO_INSTALL+=("python${PYTHON_VERSION}.${PYTHON_MINOR}-venv")
                elif apt-cache search --names-only "python${PYTHON_VERSION}-venv" | grep -q .; then
                    PACKAGES_TO_INSTALL+=("python${PYTHON_VERSION}-venv")
                else
                    PACKAGES_TO_INSTALL+=("python3-venv")
                fi
            fi
            
            if [ $DEV_PACKAGE_INSTALLED -eq 0 ]; then
                # Try specific version first, then fall back to generic
                if apt-cache search --names-only "python${PYTHON_VERSION}.${PYTHON_MINOR}-dev" | grep -q .; then
                    PACKAGES_TO_INSTALL+=("python${PYTHON_VERSION}.${PYTHON_MINOR}-dev")
                elif apt-cache search --names-only "python${PYTHON_VERSION}-dev" | grep -q .; then
                    PACKAGES_TO_INSTALL+=("python${PYTHON_VERSION}-dev")
                else
                    PACKAGES_TO_INSTALL+=("python3-dev")
                fi
                
                # On Ubuntu 24.04+, we might also need distutils
                if [[ "$VERSION_ID" == "24.04" || $(echo $VERSION_ID | cut -d. -f1) -ge 24 ]]; then
                    if apt-cache search --names-only "python${PYTHON_VERSION}-distutils" | grep -q .; then
                        PACKAGES_TO_INSTALL+=("python${PYTHON_VERSION}-distutils")
                    elif apt-cache search --names-only "python3-distutils" | grep -q .; then
                        PACKAGES_TO_INSTALL+=("python3-distutils")
                    fi
                fi
            fi
            
            # Install all required packages
            echo "Installing packages: ${PACKAGES_TO_INSTALL[*]}"
            if sudo apt update && sudo apt install -y "${PACKAGES_TO_INSTALL[@]}"; then
                echo "Successfully installed required packages."
                VENV_PACKAGE_INSTALLED=1
                DEV_PACKAGE_INSTALLED=1
            else
                echo "Failed to install some packages. You may need to install them manually:"
                echo "sudo apt install ${PACKAGES_TO_INSTALL[*]}"
                exit 1
            fi
        else
            echo "Please install the required packages manually and run this script again:"
            echo "sudo apt update && sudo apt install python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-dev"
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

# Remove existing venv if it's incomplete
if [ -d "venv" ] && [ ! -f "venv/bin/activate" ]; then
    echo "Found incomplete virtual environment. Removing it to recreate..."
    rm -rf venv
fi

# Create a virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    # Use the --prompt option to ensure it creates a more complete environment
    python3 -m venv venv --prompt "jaidee-env"
    if [ $? -ne 0 ]; then
        echo "Failed to create virtual environment."
        
        # Additional helpful information for troubleshooting
        echo "Checking Python venv capabilities..."
        python3 -m venv --help
        
        if [ $IS_DEBIAN_UBUNTU -eq 1 ]; then
            echo "On Ubuntu/Debian, try installing these packages:"
            echo "sudo apt install python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-dev"
            
            # Additional suggestions for Ubuntu 24.04+
            if [[ "$VERSION_ID" == "24.04" || $(echo $VERSION_ID | cut -d. -f1) -ge 24 ]]; then
                echo "For Ubuntu 24.04 or later, you might also need:"
                echo "sudo apt install python${PYTHON_VERSION}-distutils"
            fi
        fi
        
        exit 1
    fi
fi

# Double-check that the activate script exists
if [ ! -f "venv/bin/activate" ]; then
    echo "Virtual environment was created, but activation script wasn't found."
    echo "This might indicate an issue with your Python installation or permissions."
    
    # Try to fix it by installing the ensurepip module
    echo "Attempting to fix the environment by installing ensurepip..."
    python3 -m ensurepip
    
    # Try recreating the environment with additional options
    echo "Recreating the virtual environment with additional options..."
    rm -rf venv
    python3 -m venv venv --system-site-packages --prompt "jaidee-env"
    
    # Check again
    if [ ! -f "venv/bin/activate" ]; then
        echo "Still couldn't create a complete virtual environment."
        echo "Environment contents:"
        ls -la venv/
        if [ -d "venv/bin" ]; then
            echo "Contents of venv/bin:"
            ls -la venv/bin/
        else
            echo "venv/bin directory doesn't exist!"
        fi
        
        # Last resort: create the activate script manually
        echo "Creating minimal activate script manually..."
        mkdir -p venv/bin
        cat > venv/bin/activate << 'EOF'
# This file must be used with "source bin/activate" *from bash*
# you cannot run it directly

deactivate () {
    unset -f pydoc >/dev/null 2>&1 || true
    
    # reset old environment variables
    # ! [ -z ${VAR+_} ] returns true if VAR is declared at all
    if ! [ -z "${_OLD_VIRTUAL_PATH:+_}" ] ; then
        PATH="$_OLD_VIRTUAL_PATH"
        export PATH
        unset _OLD_VIRTUAL_PATH
    fi
    
    if ! [ -z "${_OLD_VIRTUAL_PYTHONHOME+_}" ] ; then
        PYTHONHOME="$_OLD_VIRTUAL_PYTHONHOME"
        export PYTHONHOME
        unset _OLD_VIRTUAL_PYTHONHOME
    fi
    
    # The hash command must be called to get it to forget past
    # commands. Without forgetting past commands the $PATH changes
    # we made may not be respected
    hash -r 2>/dev/null
    
    if ! [ -z "${_OLD_VIRTUAL_PS1+_}" ] ; then
        PS1="$_OLD_VIRTUAL_PS1"
        export PS1
        unset _OLD_VIRTUAL_PS1
    fi
    
    unset VIRTUAL_ENV
    unset -f deactivate
}

# unset irrelevant variables
deactivate nondestructive

VIRTUAL_ENV="$(cd "$(dirname "$(dirname "${BASH_SOURCE[0]}")")" && pwd)"
export VIRTUAL_ENV

_OLD_VIRTUAL_PATH="$PATH"
PATH="$VIRTUAL_ENV/bin:$PATH"
export PATH

# unset PYTHONHOME if set
if ! [ -z "${PYTHONHOME+_}" ] ; then
    _OLD_VIRTUAL_PYTHONHOME="$PYTHONHOME"
    unset PYTHONHOME
fi

if [ -z "${VIRTUAL_ENV_DISABLE_PROMPT-}" ] ; then
    _OLD_VIRTUAL_PS1="${PS1-}"
    PS1="(jaidee-env) ${PS1-}"
    export PS1
fi

# Make sure to unalias pydoc if it's already there
alias pydoc 2>/dev/null >/dev/null && unalias pydoc || true

pydoc () {
    python -m pydoc "$@"
}

# The hash command must be called to get it to forget past
# commands. Without forgetting past commands the $PATH changes
# we made may not be respected
hash -r 2>/dev/null
EOF
        chmod +x venv/bin/activate
        
        # Check one final time
        if [ ! -f "venv/bin/activate" ]; then
            echo "Manual creation also failed. Please install virtualenv and try again:"
            echo "pip3 install virtualenv"
            echo "Then run: virtualenv venv"
            exit 1
        fi
    fi
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
