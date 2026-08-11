
Instructions for: Ubuntu 24.04 and Ardour 9.7-312-g97a96e7c24

sudo apt update

sudo apt install -y \
    build-essential \
    pkg-config \
    python3 \
    gettext \
    intltool \
    itstool \
    ladspa-sdk \
    libarchive-dev \
    libasound2-dev \
    libaubio-dev \
    libboost-dev \
    libcairomm-1.0-dev \
    libcurl4-openssl-dev \
    libcwiid-dev \
    libdbus-1-dev \
    libfftw3-dev \
    libfluidsynth-dev \
    libglibmm-2.4-dev \
    libgtkmm-2.4-dev \
    libhidapi-dev \
    libjack-jackd2-dev \
    liblilv-dev \
    liblo-dev \
    liblrdf0-dev \
    libltc-dev \
    libpangomm-1.4-dev \
    libpulse-dev \
    libqm-dsp-dev \
    libreadline-dev \
    librubberband-dev \
    libsamplerate0-dev \
    libsigc++-2.0-dev \
    libsndfile1-dev \
    libsuil-dev \
    libtag1-dev \
    libusb-1.0-0-dev \
    libwebsockets-dev \
    libxinerama-dev \
    libxrandr-dev \
    lv2-dev \
    vamp-plugin-sdk


cd ~/code/ardour

/usr/bin/python3 ./waf configure \
    --optimize \
    --cxx17 \
    --ptformat \
    --with-backends=jack,alsa,pulseaudio,dummy \
    --libjack=weak

/usr/bin/python3 ./waf -j"$(nproc)"


cd ~/code/ardour/gtk2_ardour
./ardev



sudo dpkg-reconfigure -p high jackd2
