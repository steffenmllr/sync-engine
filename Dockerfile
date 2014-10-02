FROM ubuntu:14.04

MAINTAINER InboxApp
RUN apt-get update

RUN apt-get -y install \
python-software-properties \
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
tmux \
curl \
tnef 

RUN pip install 'setuptools>=5.3'

ADD ./requirements.txt /root/inbox/

ENV INBOX_ROOT /root/inbox

WORKDIR /root/inbox

RUN pip install -r ./requirements.txt

ADD . /root/inbox

RUN pip install -e .

RUN ./install_inbox_eas.sh

RUN apt-get -y purge build-essential
RUN apt-get -y autoremove

RUN mkdir -p /var/lib/inboxapp
RUN mkdir -p /var/log/inboxapp

# Imporant to leave the configuration file provisioning till last

ADD  ./etc/config-dev.json /etc/inboxapp/config.json

ADD ./etc/secrets-dev.yml /etc/inboxapp/secrets.yml

#TODO: initialize database (don't know when to do this yet)

