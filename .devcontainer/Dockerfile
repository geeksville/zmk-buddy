# Run inside a recent debian based image with python3, pip3, git and sudo installed
# This is the same as the debian version but used to test against full ubuntu
FROM mcr.microsoft.com/devcontainers/base:noble

# We use 'user' as the name to match what the zhephyr-build image already created
ARG USERNAME=vscode

## Setup a user with sudo support
USER root

# Add core python packages
# apt-get install -y libgl1 libxkbcommon-x11-0 libdbus-1-3 libegl1 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libfontconfig1 libxcb-xfixes0 is needed for Qt6
RUN apt-get update && apt-get -y install --no-install-recommends \
        python3 python3-pip python3-venv python-is-python3 python3-tk sudo git flatpak python3-dev \
        libgl1 libxkbcommon-x11-0 libdbus-1-3 libegl1 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libfontconfig1 libxcb-xfixes0 build-essential curl


# Create a non-root user if one doesn't exist, and give it sudo rights
RUN if ! id -u ${USERNAME} > /dev/null 2>&1; then \
        groupadd --gid 1000 ${USERNAME} && \
        useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash ${USERNAME} && \
        echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME}-nopasswd; \
        fi

USER ${USERNAME}

# Some containers might not have a .local directory at all, don't fail in that case
RUN mkdir -p /home/${USERNAME}/.local/bin

# Add the local bin directory to the PATH. For pipx and flatpacks
ENV PATH="/home/${USERNAME}/.local/bin:$HOME/.local/share/flatpak/exports/bin/:${PATH}"

# pipx
RUN pip install --user --no-cache-dir --break-system-packages pipx 

# install poetry for the user 
RUN pipx install --pip-args=--no-cache-dir poetry

# Install Siril flat pack (for testing)
# Note: this must be done here, if done in Dockerfile it doesn't work - this env var is a nasty hack to allow
# flatpak inside of Dockerfile.
# https://github.com/flatpak/flatpak/issues/5076
#ENV FLATPAK_SYSTEM_HELPER_ON_SESSION=foo
#RUN flatpak --user remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
#RUN flatpak install --user -y flathub org.siril.Siril
# Let siril see /tmp
#RUN flatpak --user override --filesystem=/tmp org.siril.Siril

# Install Atuin
RUN curl --proto '=https' --tlsv1.2 -sSf https://setup.atuin.sh | sh

USER root

# needed for vhs to make movies

# alas chromium-browser requires snap which is a whole other kettle of fish
# RUN apt-get install -y --no-install-recommends chromium-browser chromium-codecs-ffmpeg

# instead we install chrome - you might need to run the GUI once before using it from VHS
#RUN cd /tmp && \
#        wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb && \
#        apt install -y ./google-chrome-stable_current_amd64.deb

# We need the docker CLI for build ghcr.io containers
# needed because i'm using old docker commands above - someday move this docker install to top and the update can leave
#RUN apt-get update
#RUN apt-get -y install --no-install-recommends docker.io

# Make container smaller.  Do this last, so that if we change the container it is fast to use existing apts
RUN rm -rf /var/lib/apt/lists/*