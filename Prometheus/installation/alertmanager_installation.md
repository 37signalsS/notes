# Установка Alertmanager

> **Важно**: Указанные версии компонентов могут быть устаревшими. Всегда проверяйте официальные репозитории GitHub для загрузки **последних стабильных версий**.

1. **Создание пользователя**:

    ```bash
    useradd --no-create-home --shell /bin/false alertmanager --comment "User to run Alertmanager"
    ```

2. **Загрузка и установка (пример для версии 0.26.0)**:

    ```bash
    ALERTMANAGER_VERSION="0.26.0" # Проверьте последнюю стабильную версию
    cd /tmp
    wget https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
    tar xvfz alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
    cd alertmanager-${ALERTMANAGER_VERSION}.linux-amd64
    mv alertmanager amtool /usr/local/bin/
    ```

3. **Настройка каталогов и конфигурации**:

    ```bash
    mkdir /etc/alertmanager
    cp alertmanager.yml /etc/alertmanager/alertmanager.yml
    chown alertmanager:alertmanager -R /etc/alertmanager
    mkdir /var/lib/alertmanager/
    chown alertmanager:alertmanager /var/lib/alertmanager/
    ```

4. **Создание файла с опциями запуска** (`/etc/sysconfig/alertmanager`):

    ```bash
    cat <<EOF > /etc/sysconfig/alertmanager
    OPTIONS="--config.file=/etc/alertmanager/alertmanager.yml 
      --storage.path=/var/lib/alertmanager/"
    EOF
    ```

5. **Создание systemd-сервиса** (`/etc/systemd/system/alertmanager.service`):

    ```bash
    cat <<EOF > /etc/systemd/system/alertmanager.service
    [Unit]
    Description=Prometheus Alertmanager
    Documentation=https://prometheus.io/docs/alerting/latest/alertmanager/
    After=network-online.target

    [Service]
    User=alertmanager
    Group=alertmanager
    Restart=always
    EnvironmentFile=/etc/sysconfig/alertmanager
    ExecStart=/usr/local/bin/alertmanager \$OPTIONS
    ExecReload=/bin/kill -HUP \$MAINPID
    [Install]
    WantedBy=multi-user.target
    EOF
    ```

6. **Запуск и проверка**:

    ```bash
    systemctl daemon-reload
    systemctl start alertmanager.service
    systemctl enable alertmanager.service
    curl -s -o /dev/null -w "%{http_code}" http://localhost:9093 # Ожидаемый ответ: 200
    ```
