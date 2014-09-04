# Build as:
#   docker build -t inbox .
FROM debian:7.6
MAINTAINER Inbox Team <admin@inboxapp.com>

# Build-time proxy configuration
# TODO: proxy auto-discovery (IPv6 anycast on eth0? -- See also 'squid-deb-proxy-client' package)
# TODO: proxy for wget
COPY docker/01proxy /etc/apt/apt.conf.d/
COPY docker/pip.conf /.pip/pip.conf
RUN mkdir -p /root/.pip && ln -s /.pip/pip.conf /root/.pip/pip.conf

RUN echo "debconf debconf/frontend select Noninteractive" | debconf-set-selections

RUN apt-get -qy update
RUN apt-get -qy upgrade

RUN apt-get -qy install \
   build-essential \
   curl \
   g++ \
   gcc \
   git \
   lib32z1-dev \
   libffi-dev \
   libmysqlclient-dev \
   libxml2-dev \
   libxslt-dev \
   libyaml-dev \
   libzmq-dev \
   mysql-client \
   pkg-config \
   python \
   python-dev \
   python-lxml \
   python-numpy \
   python-pip \
   python-setuptools \
   python-virtualenv \
   stow \
   supervisor \
   tmux \
   tnef \
   wget

# No need to clean up packages; the 'debian' image has an apt config that does
# this already.
#RUN apt-get -qy clean

# /usr/local/stow is no longer auto-created by the 'stow' package
RUN mkdir -p /usr/local/stow

# We'll put downloaded packages into /tmp/pkg
WORKDIR /tmp/pkg

# Download and verify some more files that we'll use below.
RUN wget https://www.python.org/ftp/python/3.4.1/Python-3.4.1.tar.xz
RUN echo 'c595a163104399041fcbe1c5c04db4c1da94f917b82ce89e8944c8edff7aedc4 *Python-3.4.1.tar.xz' | sha256sum -c

RUN wget https://pypi.python.org/packages/source/s/setuptools/setuptools-5.7.tar.gz
RUN echo 'a8bbdb2d67532c5b5cef5ba09553cea45d767378e42c7003347e53ebbe70f482 *setuptools-5.7.tar.gz' | sha256sum -c

RUN wget https://pypi.python.org/packages/source/p/pip/pip-1.5.6.tar.gz
RUN echo 'b1a4ae66baf21b7eb05a5e4f37c50c2706fa28ea1f8780ce8efe14dcd9f1726c *pip-1.5.6.tar.gz' | sha256sum -c

RUN wget http://download.libsodium.org/libsodium/releases/libsodium-0.7.0.tar.gz
RUN echo '4ccaffd1a15be67786e28a61b602492a97eb5bcb83455ed53c02fa038b8e9168 *libsodium-0.7.0.tar.gz' | sha256sum -c

RUN wget http://09cce49df173f6f6e61f-fd6930021b51685920a6fa76529ee321.r45.cf2.rackcdn.com/PyML-0.7.9.tar.gz
RUN echo '4bdab262e5a6a95d371ea8c905e815c4d5da806a6c207cf3eb69776daf23e02c *PyML-0.7.9.tar.gz' | sha256sum -c

RUN wget -O talon.tar.gz https://github.com/mailgun/talon/archive/v1.0.2-4-g1789ccf.tar.gz
RUN echo 'ea41ebe0ac3cf3fd0571c32d9186c3de570f0e67ec3fc19b582a817bc733a365 *talon.tar.gz' | sha256sum -c

# We'll build things from /tmp/bld
WORKDIR /tmp/bld

# Build and install Python 3.4
# (We'll do this until jessie comes out, when we'll be able to switch to real packages.)
RUN tar -x -f /tmp/pkg/Python-3.4.1.tar.xz
RUN mkdir pythonbuild /usr/local/stow/Python-3.4.1
RUN cd pythonbuild && \
    ../Python-3.4.1/configure \
        --prefix=/usr/local/stow/Python-3.4.1 \
        --enable-ipv6 \
        --enable-loadable-sqlite-extensions \
        --with-dbmliborder=bdb:gdbm \
        --with-computed-gotos \
        --without-ensurepip \
        --with-system-expat \
        --with-system-libmpdec \
        --with-system-ffi \
        --with-fpectl
RUN cd pythonbuild && make -j8
#RUN cd pythonbuild && make test
RUN cd pythonbuild && make install
RUN cd /usr/local/stow && stow Python-3.4.1
RUN find /tmp/bld/ -mindepth 1 -delete

# Install libsodium (for PyNaCl)
RUN mkdir /usr/local/stow/libsodium-0.7.0
RUN tar -xf /tmp/pkg/libsodium-0.7.0.tar.gz
RUN cd libsodium-0.7.0 && ./configure --prefix=/usr/local/stow/libsodium-0.7.0 --quiet
RUN cd libsodium-0.7.0 && make -j8
RUN cd libsodium-0.7.0 && make install
RUN cd /usr/local/stow && stow libsodium-0.7.0
RUN pkg-config --exact-version=0.7.0 libsodium  # sanity check
RUN find /tmp/bld/ -mindepth 1 -delete

# Upgrade setuptools and pip (Python 2.7)
RUN easy_install /tmp/pkg/setuptools-5.7.tar.gz
RUN easy_install /tmp/pkg/pip-1.5.6.tar.gz
RUN find /tmp/bld/ -mindepth 1 -delete

## Install some Python packages separately, to avoid having to wait for them to
## build again later.  Put slow, infrequently-changed builds earlier to
## minimize amount of time people will need to spend rebuilding packages that
## haven't changed.

# PyNaCl
RUN pip install pynacl==0.2.3

# PyML 0.7.9, which is needed by talon.
# NB: talon's setup.py doesn't actually check the version, so watch out for
# updates. :-/
RUN pip install /tmp/pkg/PyML-0.7.9.tar.gz
RUN pip install regex==0.1.20110315
RUN pip install lxml==2.3.3
RUN pip install lxml==3.3.5
RUN pip install /tmp/pkg/talon.tar.gz
RUN pip install gevent==1.0.1

# And install the requirements
COPY requirements.txt /tmp/bld/
RUN pip install -r requirements.txt
RUN find /tmp/bld/ -mindepth 1 -delete

# TODO: Rename this
WORKDIR /vagrant

## NB: Don't copy stuff we don't need to run the app, or incremental builds will
## become less effective.
COPY alembic.ini                /vagrant/alembic.ini
COPY bin/                       /vagrant/bin/
COPY etc/                       /vagrant/etc/
COPY inbox/                     /vagrant/inbox/
COPY migrations/                /vagrant/migrations/
COPY requirements.txt           /vagrant/requirements.txt
COPY runtests                   /vagrant/runtests
COPY setup.py                   /vagrant/setup.py
COPY tests/                     /vagrant/tests/
#COPY arclib/                    /vagrant/arclib/

RUN pip install -r requirements.txt -e .

## Finished installing.  Now clean up and prepare startup scripts.

# Clean up build tools
RUN apt-get -y purge build-essential && apt-get -y autoremove

# Remove build-time proxy configuration
RUN rm /etc/apt/apt.conf.d/01proxy /root/.pip/pip.conf /.pip/pip.conf

# Empty /tmp/ and other cached junk
RUN find /tmp/ -mindepth 1 -delete
RUN find /root/.pip /.pip -delete

# Persistent data will go here.
VOLUME ['/etc/inboxapp',
        '/var/log/inboxapp',
        '/var/lib/inboxapp']

# XXX: This variable should probably be removed?
# TODO: What else can go here?
ENV INBOX_ENV dev

COPY docker/default-cmd         /vagrant/docker/default-cmd
COPY setup.sh                   /vagrant/setup.sh
CMD ['/vagrant/docker/default-cmd']

EXPOSE 5000
