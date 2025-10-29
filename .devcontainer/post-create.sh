#!/bin/bash
set -e

echo "================================================"
echo "Setting up TART Cargo Development Environment"
echo "================================================"

# Update package list
echo "Updating package list..."
sudo apt-get update

# Install dependencies for apptainer
echo "Installing apptainer dependencies..."
sudo apt-get install -y \
    squashfuse \
    fuse2fs \
    fuse3 \
    libfuse-dev \
    uidmap \
    wget \
    cryptsetup

# Install gocryptfs if available (might not be in all repos)
echo "Installing gocryptfs..."
sudo apt-get install -y gocryptfs || echo "gocryptfs not available in repos, skipping..."

# Determine architecture
ARCH=$(dpkg --print-architecture)
echo "Detected architecture: $ARCH"

# Download and install apptainer
echo "Installing Apptainer..."
APPTAINER_VERSION="1.3.4"

if [ "$ARCH" = "amd64" ]; then
    APPTAINER_DEB="apptainer_${APPTAINER_VERSION}_amd64.deb"
elif [ "$ARCH" = "arm64" ]; then
    APPTAINER_DEB="apptainer_${APPTAINER_VERSION}_arm64.deb"
else
    echo "Unsupported architecture: $ARCH"
    exit 1
fi

wget -q "https://github.com/apptainer/apptainer/releases/download/v${APPTAINER_VERSION}/${APPTAINER_DEB}" -O /tmp/apptainer.deb
sudo apt-get install -y /tmp/apptainer.deb
rm /tmp/apptainer.deb

# Verify apptainer installation
echo "Verifying Apptainer installation..."
apptainer --version

# Upgrade pip
echo "Upgrading pip..."
python -m pip install --upgrade pip

# Install poetry for package management (used by this project)
echo "Installing poetry..."
python -m pip install poetry

# Install the project dependencies
echo "Installing tart_cargo dependencies..."
if [ -f "pyproject.toml" ]; then
    poetry install
else
    echo "Warning: pyproject.toml not found"
fi

echo "================================================"
echo "Setup complete! You can now use tart-cargo."
echo "================================================"
echo ""
echo "To get started:"
echo "  1. Activate the poetry environment: poetry shell"
echo "  2. Run a recipe: poetry run stimela run test/example_recipe.yml tart=mu-udm"
echo ""
