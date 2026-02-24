# Установка Node Exporter

> **Важно**: Указанные версии компонентов могут быть устаревшими. Всегда проверяйте официальные репозитории GitHub для загрузки **последних стабильных версий**.

1. **Загрузка и установка (пример для версии 1.6.0)**:

    ```bash
    NODE_EXPORTER_VERSION="1.6.0" # Проверьте последнюю стабильную версию
    cd /tmp
    wget https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
    tar xvfz node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
    mv node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/
    ```

2. **Создание файла с опциями запуска** (`/etc/sysconfig/node_exporter`):
    > Для сбора всех метрик `node_exporter` рекомендуется запускать от `root`.

    ```bash
    cat <<EOF > /etc/sysconfig/node_exporter
    OPTIONS="--web.listen-address=:9100"
    EOF
    ```

3. **Создание systemd-сервиса** (`/etc/systemd/system/node_exporter.service`):

    ```bash
    cat <<EOF > /etc/systemd/system/node_exporter.service
    [Unit]
    Description=Prometheus Node exporter for machine metrics
    Documentation=https://github.com/prometheus/node_exporter
    After=network-online.target

    [Service]
    Restart=always
    User=root
    EnvironmentFile=/etc/sysconfig/node_exporter
    ExecStart=/usr/local/bin/node_exporter \$OPTIONS
    ExecReload=/bin/kill -HUP \$MAINPID
    TimeoutStopSec=20s
    SendSIGKILL=no

    [Install]
    WantedBy=multi-user.target
    EOF
    ```

4. **Запуск и проверка**:

    ```bash
    systemctl daemon-reload
    systemctl start node_exporter
    systemctl enable node_exporter
    curl -s -o /dev/null -w "%{http_code}" http://localhost:9100/metrics # Ожидаемый ответ: 200
    ```
