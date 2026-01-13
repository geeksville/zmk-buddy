

# Just lists available recipes
default:
    just --list

# do static type checking with mypy
lint:
    poetry run black zmk_buddy
    poetry run mypy zmk_buddy
    poetry run pylint --jobs=0 --disable=fixme zmk_buddy

# Test using a custom layout
test-layout:
    # poetry run zmk-buddy -c test/urob/config.yaml -k test/urob/base.yaml -d -z ferris/sweep
    poetry run zmk-buddy -k test/urob/base.yaml -d -z corne

# Just run with my keyboard config
run: 
    zmk-buddy -k test/urob/base.yaml -z corne

# Use pip to install the PyPI released version of keymap-drawer
keymap-use-release:
    @echo "Switching to PyPI release version of keymap-drawer..."
    pip uninstall -y keymap-drawer || true
    pip install "keymap-drawer>=0.22.1"
    @echo "Now using PyPI release version of keymap-drawer"

# Use a local clone of the keymap-drawer git repo instead of the pypi version
# Clones into vendor/keymap-drawer and installs in editable mode
keymap-use-dev:
    @echo "Setting up local dev version of keymap-drawer..."
    mkdir -p vendor
    @if [ ! -d "vendor/keymap-drawer" ]; then \
        echo "Cloning keymap-drawer..."; \
        git clone https://github.com/geeksville/keymap-drawer.git vendor/keymap-drawer; \
    else \
        echo "keymap-drawer already cloned, updating..."; \
        cd vendor/keymap-drawer && git pull; \
    fi
    pip uninstall -y keymap-drawer || true
    pip install -e ./vendor/keymap-drawer
    @echo "Now using local dev version from vendor/keymap-drawer"

# Bump version, commit, tag and push to trigger a PyPI release
# Usage: just bump-version patch|minor|major
bump-version bump_type="patch":
    @echo "Bumping {{bump_type}} version..."
    poetry version {{bump_type}}
    @VERSION=$(poetry version -s) && \
        git add pyproject.toml && \
        git commit -m "Bump version to v$VERSION" && \
        git tag "v$VERSION" && \
        echo "Created tag v$VERSION" && \
        git push && git push --tags && \
        echo "Pushed to origin. GitHub Actions will publish to PyPI."