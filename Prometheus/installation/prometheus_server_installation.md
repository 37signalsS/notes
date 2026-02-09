# Установка Prometheus Server

> **Важно**: Указанные версии компонентов могут быть устаревшими. Всегда проверяйте официальные репозитории GitHub для загрузки **последних стабильных версий**.

1.  **Создание пользователя**:
    ```bash
    useradd --no-create-home --shell /bin/false prometheus --comment "Prometheus server user"
    ```

2.  **Загрузка и установка (пример для версии 2.45.0)**:
    ```bash
    PROMETHEUS_VERSION="2.45.0" # Проверьте последнюю стабильную версию
    cd /tmp
    wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
    tar xvfz prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
    cd prometheus-${PROMETHEUS_VERSION}.linux-amd64
    mv prometheus promtool /usr/local/bin/
    ```

3.  **Настройка каталогов и конфигурации**:
    ```bash
    mkdir /etc/prometheus
    cp prometheus.yml /etc/prometheus/
    chown -R prometheus:prometheus /etc/prometheus
    mkdir /var/lib/prometheus
    chown prometheus:prometheus /var/lib/prometheus
    ```

4.  **Создание файла с опциями запуска** (`/etc/sysconfig/prometheus`):
    ```bash
    cat <<EOF > /etc/sysconfig/prometheus
    OPTIONS="--config.file=/etc/prometheus/prometheus.yml 
    --storage.tsdb.path=/var/lib/prometheus/"
    EOF
    ```

5.  **Создание systemd-сервиса** (`/etc/systemd/system/prometheus.service`):
    ```bash
    cat <<EOF > /etc/systemd/system/prometheus.service
    [Unit]
    Description=Prometheus Server
    Documentation=https://github.com/prometheus/prometheus
    After=network-online.target

    [Service]
    Restart=always
    User=prometheus
    Group=prometheus
    EnvironmentFile=/etc/sysconfig/prometheus
    ExecStart=/usr/local/bin/prometheus \$OPTIONS
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
    systemctl start prometheus
    systemctl enable prometheus
    curl -s -o /dev/null -w "%{http_code}" http://localhost:9090/graph # Ожидаемый ответ: 200
    ```
