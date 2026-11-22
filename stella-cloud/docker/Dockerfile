# Stella agent sandbox: one container per account, started by Stella Cloud.
# agy itself is mounted read-only from the host (/usr/local/bin/agy) or installed into the account's home.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
RUN apt-get update -q \
 && apt-get install -y -q --no-install-recommends ca-certificates curl wget git openssh-client \
      python3 python3-pip python3-venv nodejs npm zip unzip xz-utils less nano jq procps tzdata \
 && rm -rf /var/lib/apt/lists/*
# a writable workspace for any uid (the container runs as the account's own uid, never root)
RUN mkdir -p /home/agent && chmod 777 /home/agent
WORKDIR /home/agent
CMD ["sleep", "infinity"]
