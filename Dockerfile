FROM ubuntu:14.04

MAINTAINER InboxApp
RUN apt-get update

RUN apt-get -y install\
    python-software-properties\
    git \
    wget \
    supervisor \
    mysql-client \
    python \
    python-dev \
    python-pip \
    python-setuptools \
    build-essential \
    libmysqlclient-dev \
    gcc \
    g++ \
    libzmq-dev \
    libxml2-dev \
    libxslt-dev \
    lib32z1-dev \
    libffi-dev \
    python-lxml \
    curl \
    tnef && \
    pip install 'setuptools>=5.3'

ADD ./requirements.txt /root/inbox/

ENV INBOX_ROOT /root/inbox

WORKDIR /root/inbox

RUN pip install -r ./requirements.txt && \
    apt-get -y purge build-essential && \
    apt-get -y autoremove && \
    mkdir -p /var/lib/inboxapp && \
    mkdir -p /var/log/inboxapp

ADD . /root/inbox

RUN pip install -e .
# Imporant to leave the configuration file provisioning till last

ADD  ./etc/config-dev.json /etc/inboxapp/config.json

ADD ./etc/secrets-dev.yml /etc/inboxapp/secrets.yml


