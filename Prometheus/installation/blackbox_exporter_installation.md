# Установка Blackbox Exporter

> **Важно**: Указанные версии компонентов могут быть устаревшими. Всегда проверяйте официальные репозитории GitHub для загрузки **последних стабильных версий**.
>
> **Последняя стабильная версия:** `0.28.0` (декабрь 2025)
>
> **Новые возможности v0.28.0:** HTTP/3 (QUIC) prober, gRPC metadata, byte matching в TCP, автоматическая перезагрузка конфига

1. **Загрузка и установка**:

    ```bash
    BLACKBOX_EXPORTER_VERSION="0.28.0"
    cd /tmp
    wget https://github.com/prometheus/blackbox_exporter/releases/download/v${BLACKBOX_EXPORTER_VERSION}/blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
    tar xvfz blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
    mv blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox_exporter /usr/local/bin/
    ```

2. **Настройка каталогов и конфигурации**:

    ```bash
    mkdir /etc/blackbox_exporter
    # Скопируйте файл blackbox.yml из архива или создайте свой
    cp blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox.yml /etc/blackbox_exporter/
    chown -R nobody:nobody /etc/blackbox_exporter
    ```

3. **Создание файла с опциями запуска** (`/etc/sysconfig/blackbox_exporter`):

    ```bash
    cat <<EOF > /etc/sysconfig/blackbox_exporter
    OPTIONS="--config.file=/etc/blackbox_exporter/blackbox.yml"
    EOF
    ```

4. **Создание systemd-сервиса** (`/etc/systemd/system/blackbox_exporter.service`):

    ```bash
    cat <<EOF > /etc/systemd/system/blackbox_exporter.service
    [Unit]
    Description=Prometheus Blackbox Exporter
    Documentation=https://github.com/prometheus/blackbox_exporter
    After=network-online.target

    [Service]
    Restart=always
    User=nobody
    Group=nobody
    EnvironmentFile=/etc/sysconfig/blackbox_exporter
    ExecStart=/usr/local/bin/blackbox_exporter \$OPTIONS
    ExecReload=/bin/kill -HUP \$MAINPID

    [Install]
    WantedBy=multi-user.target
    EOF
    ```

5. **Запуск и проверка**:

    ```bash
    systemctl daemon-reload
    systemctl start blackbox_exporter
    systemctl enable blackbox_exporter
    curl -s -o /dev/null -w "%{http_code}" http://localhost:9115 # Ожидаемый ответ: 200
    ```
