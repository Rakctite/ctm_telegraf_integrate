FROM telegraf:1.38.4

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-psycopg2 \
    && rm -rf /var/lib/apt/lists/*

COPY telegraf.conf /etc/telegraf/telegraf.conf
COPY telegraf_py /telegraf/telegraf_py

RUN find /telegraf/telegraf_py -type d -name __pycache__ -prune -exec rm -rf {} + \
    && chmod 0644 /etc/telegraf/telegraf.conf /telegraf/telegraf_py/*.py

CMD ["telegraf", "--config", "/etc/telegraf/telegraf.conf"]
