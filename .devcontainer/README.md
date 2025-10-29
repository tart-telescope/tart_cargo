# TART Cargo Codespace Configuration

This directory contains the GitHub Codespaces / VS Code Dev Container configuration for the TART Cargo project.

## What's Included

The devcontainer provides:
- **Ubuntu base** (Debian Bookworm via Python 3.12 image)
- **Python 3.12** with pip and poetry
- **Apptainer** (container runtime for radio astronomy tools)
- **System dependencies**: squashfuse, fuse2fs, fuse3, gocryptfs
- **VS Code extensions**: Python, Pylance

## Getting Started

### Using GitHub Codespaces

1. Navigate to the repository on GitHub
2. Click the green "Code" button
3. Select "Codespaces" tab
4. Click "Create codespace on [branch]"
5. Wait for the environment to build (first time takes ~5-10 minutes)

### Using VS Code Dev Containers

1. Install Docker Desktop
2. Install the "Dev Containers" extension in VS Code
3. Open the repository folder in VS Code
4. Click "Reopen in Container" when prompted (or use Command Palette: "Dev Containers: Reopen in Container")

## After the Container Starts

The post-create script automatically:
- Installs Apptainer and dependencies
- Sets up Python environment with poetry
- Installs tart_cargo dependencies

You can then use tart-cargo:

```bash
# Activate the poetry environment
poetry shell

# Or run directly
poetry run stimela --help

# Run an example recipe
poetry run stimela run test/example_recipe.yml tart=mu-udm
```

## Verifying Installation

To verify everything is installed correctly:

```bash
# Check Python version
python --version  # Should show Python 3.12.x

# Check Apptainer
apptainer --version  # Should show Apptainer version

# Check poetry
poetry --version
```

## Troubleshooting

If you encounter issues:

1. **Apptainer not found**: The post-create script should install it. Check logs or manually run:
   ```bash
   bash .devcontainer/post-create.sh
   ```

2. **Permission issues**: The container runs with `--privileged` flag to support apptainer operations

3. **Dependencies not installed**: Manually run:
   ```bash
   poetry install
   ```

## Customization

You can customize the environment by editing:
- `devcontainer.json` - Main configuration (extensions, features, settings)
- `post-create.sh` - Installation and setup script
