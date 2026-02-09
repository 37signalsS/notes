# Установка Pushgateway

> **Важно**: Указанные версии компонентов могут быть устаревшими. Всегда проверяйте официальные репозитории GitHub для загрузки **последних стабильных версий**.

1.  **Создание пользователя**:
    ```bash
    useradd --no-create-home --shell /bin/false pushgateway --comment "Pushgateway server user"
    ```

2.  **Загрузка и установка (пример для версии 1.7.0)**:
    ```bash
    PUSHGATEWAY_VERSION="1.7.0" # Проверьте последнюю стабильную версию
    cd /tmp
    wget https://github.com/prometheus/pushgateway/releases/download/v${PUSHGATEWAY_VERSION}/pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64.tar.gz
    tar xvfz pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64.tar.gz
    cd pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64
    mv pushgateway /usr/local/bin/
    ```

3.  **Создание файла с опциями запуска** (`/etc/sysconfig/pushgateway`):
    ```bash
    cat <<EOF > /etc/sysconfig/pushgateway
    OPTIONS="--web.listen-address=:9091 
        --web.telemetry-path=/metrics 
        --persistence.file=/var/lib/pushgateway/metrics.store 
        --persistence.interval=5m 
        --log.level=info"
    EOF
    ```
4.  **Создание каталога для хранения метрик**:
    ```bash
    mkdir -p /var/lib/pushgateway
    chown pushgateway:pushgateway /var/lib/pushgateway
    ```

5.  **Создание systemd-сервиса** (`/etc/systemd/system/pushgateway.service`):
    ```bash
    cat <<EOF > /etc/systemd/system/pushgateway.service
    [Unit]
    Description=Prometheus Pushgateway
    Documentation=https://github.com/prometheus/pushgateway
    After=network-online.target

    [Service]
    User=pushgateway
    Group=pushgateway
    EnvironmentFile=/etc/sysconfig/pushgateway
    Restart=always
    ExecStart=/usr/local/bin/pushgateway \$OPTIONS
    ExecReload=/bin/kill -HUP \$MAINPID
    TimeoutStopSec=20s
    SendSIGKILL=no

    [Install]
    WantedBy=multi-user.target
    EOF
    ```

6.  **Запуск и проверка**:
    ```bash
    systemctl daemon-reload
    systemctl start pushgateway
    systemctl enable pushgateway
    curl -s -o /dev/null -w "%{http_code}" http://localhost:9091/-/healthy # Ожидаемый ответ: 200
    ```
