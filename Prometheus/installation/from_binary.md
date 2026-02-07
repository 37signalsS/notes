# Установка стека Prometheus из бинарных файлов

### Определения

*   **Prometheus Server**: Основной компонент стека, отвечающий за сбор, хранение и обработку метрик в формате временных рядов (TSDB).
*   **Node Exporter**: Экспортер для сбора метрик с аппаратного и программного обеспечения хостовой системы (CPU, RAM, диск, сеть).
*   **Blackbox Exporter**: Экспортер для проверки доступности эндпоинтов по различным протоколам (HTTP, HTTPS, TCP, ICMP, DNS). Работает по принципу "черного ящика".
*   **Alertmanager**: Обрабатывает алерты, отправленные Prometheus. Отвечает за их дедупликацию, группировку и маршрутизацию в различные системы уведомлений (Email, Slack, PagerDuty).
*   **Pushgateway**: Позволяет кратковременным и batch-заданиям, которые не могут быть постоянно доступны для скрейпинга, отправлять свои метрики в Prometheus.

---

### Основные концепции

#### Принцип установки

1.  **Создание пользователя**: Для изоляции процессов и повышения безопасности для каждого компонента создается отдельный системный пользователь без прав на вход в систему. Исключением является `Node Exporter`, которому для сбора некоторых метрик может потребоваться `root`-доступ.
2.  **Загрузка и размещение бинарных файлов**: Архив с последней стабильной версией компонента загружается с официального репозитория на GitHub, распаковывается, а исполняемый файл помещается в директорию `/usr/local/bin/`.
3.  **Создание конфигурации**: Создаются необходимые каталоги (например, `/etc/<component>`, `/var/lib/<component>`) и файлы конфигурации для компонента.
4.  **Настройка `systemd` сервиса**: Для управления процессом (автозапуск, перезапуск) создается unit-файл в `/etc/systemd/system/`. Параметры запуска выносятся в отдельный environment-файл в `/etc/sysconfig/` (для CentOS/RHEL) или интегрируются напрямую в unit-файл.

#### Управление через `systemd`

После создания unit-файла для каждого компонента используются стандартные команды `systemctl`:

*   `systemctl daemon-reload`: Перечитать конфигурацию `systemd`.
*   `systemctl start <service>`: Запустить сервис.
*   `systemctl enable <service>`: Включить автозапуск сервиса при старте системы.
*   `systemctl status <service>`: Проверить статус сервиса.
*   `systemctl stop <service>`: Остановить сервис.
*   `systemctl restart <service>`: Перезапустить сервис.
*   `systemctl reload <service>`: Перезагрузить конфигурацию сервиса без его полной остановки (поддерживается не всеми сервисами).

---

### Практические сценарии

> **Важно**: Указанные версии компонентов могут быть устаревшими. Всегда проверяйте официальные репозитории GitHub для загрузки **последних стабильных версий**.

#### 3.1. Установка Prometheus Server

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
    OPTIONS="--config.file=/etc/prometheus/prometheus.yml \
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

#### 3.2. Установка Node Exporter

1.  **Загрузка и установка (пример для версии 1.6.0)**:
    ```bash
    NODE_EXPORTER_VERSION="1.6.0" # Проверьте последнюю стабильную версию
    cd /tmp
    wget https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
    tar xvfz node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
    mv node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/
    ```

2.  **Создание файла с опциями запуска** (`/etc/sysconfig/node_exporter`):
    > Для сбора всех метрик `node_exporter` рекомендуется запускать от `root`.
    ```bash
    cat <<EOF > /etc/sysconfig/node_exporter
    OPTIONS="--web.listen-address=:9100"
    EOF
    ```

3.  **Создание systemd-сервиса** (`/etc/systemd/system/node_exporter.service`):
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

4.  **Запуск и проверка**:
    ```bash
    systemctl daemon-reload
    systemctl start node_exporter
    systemctl enable node_exporter
    curl -s -o /dev/null -w "%{http_code}" http://localhost:9100/metrics # Ожидаемый ответ: 200
    ```

#### 3.3. Установка Blackbox Exporter

1.  **Загрузка и установка (пример для версии 0.24.0)**:
    ```bash
    BLACKBOX_EXPORTER_VERSION="0.24.0" # Проверьте последнюю стабильную версию
    cd /tmp
    wget https://github.com/prometheus/blackbox_exporter/releases/download/v${BLACKBOX_EXPORTER_VERSION}/blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
    tar xvfz blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
    mv blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox_exporter /usr/local/bin/
    ```

2.  **Настройка каталогов и конфигурации**:
    ```bash
    mkdir /etc/blackbox_exporter
    # Скопируйте файл blackbox.yml из архива или создайте свой
    cp blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox.yml /etc/blackbox_exporter/
    chown -R nobody:nobody /etc/blackbox_exporter
    ```

3.  **Создание файла с опциями запуска** (`/etc/sysconfig/blackbox_exporter`):
    ```bash
    cat <<EOF > /etc/sysconfig/blackbox_exporter
    OPTIONS="--config.file=/etc/blackbox_exporter/blackbox.yml"
    EOF
    ```

4.  **Создание systemd-сервиса** (`/etc/systemd/system/blackbox_exporter.service`):
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
5.  **Запуск и проверка**:
    ```bash
    systemctl daemon-reload
    systemctl start blackbox_exporter
    systemctl enable blackbox_exporter
    curl -s -o /dev/null -w "%{http_code}" http://localhost:9115 # Ожидаемый ответ: 200
    ```

#### 3.4. Установка Alertmanager

1.  **Создание пользователя**:
    ```bash
    useradd --no-create-home --shell /bin/false alertmanager --comment "User to run Alertmanager"
    ```
2.  **Загрузка и установка (пример для версии 0.26.0)**:
    ```bash
    ALERTMANAGER_VERSION="0.26.0" # Проверьте последнюю стабильную версию
    cd /tmp
    wget https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
    tar xvfz alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
    cd alertmanager-${ALERTMANAGER_VERSION}.linux-amd64
    mv alertmanager amtool /usr/local/bin/
    ```

3.  **Настройка каталогов и конфигурации**:
    ```bash
    mkdir /etc/alertmanager
    cp alertmanager.yml /etc/alertmanager/alertmanager.yml
    chown alertmanager:alertmanager -R /etc/alertmanager
    mkdir /var/lib/alertmanager/
    chown alertmanager:alertmanager /var/lib/alertmanager/
    ```

4.  **Создание файла с опциями запуска** (`/etc/sysconfig/alertmanager`):
    ```bash
    cat <<EOF > /etc/sysconfig/alertmanager
    OPTIONS="--config.file=/etc/alertmanager/alertmanager.yml \
      --storage.path=/var/lib/alertmanager/"
    EOF
    ```

5.  **Создание systemd-сервиса** (`/etc/systemd/system/alertmanager.service`):
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

6.  **Запуск и проверка**:
    ```bash
    systemctl daemon-reload
    systemctl start alertmanager.service
    systemctl enable alertmanager.service
    curl -s -o /dev/null -w "%{http_code}" http://localhost:9093 # Ожидаемый ответ: 200
    ```

#### 3.5. Установка Pushgateway

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
    OPTIONS="--web.listen-address=:9091 \
        --web.telemetry-path=/metrics \
        --persistence.file=/var/lib/pushgateway/metrics.store \
        --persistence.interval=5m \
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

---

### Дополнительная информация

#### Проверка конфигурации компонентов

Перед применением изменений в конфигурации Prometheus и Alertmanager всегда проверяйте синтаксис с помощью утилит `promtool` и `amtool`. Это помогает избежать ошибок, которые могут привести к остановке сбора метрик или обработки оповещений.

*   **Prometheus**:
    ```bash
    promtool check config /etc/prometheus/prometheus.yml
    ```
    Подробнее об утилите `promtool` можно прочитать в заметке [`promtool_and_best_practices.md`](../promtool_and_best_practices.md).

*   **Alertmanager**:
    ```bash
    amtool check-config /etc/alertmanager/alertmanager.yml
    ```

#### Рекомендации по безопасности

При развертывании компонентов Prometheus следуйте основным принципам безопасности:

*   **Пользователи**: Запускайте каждый компонент от непривилегированного пользователя. Это снижает потенциальный ущерб в случае эксплуатации уязвимостей.
*   **Сетевые доступы**: Настраивайте файрвол для ограничения доступа к веб-интерфейсам и API компонентов только с доверенных IP-адресов.
*   **TLS**: Для защиты трафика между компонентами и при доступе пользователей используйте TLS-шифрование, например, с помощью обратного прокси-сервера (Nginx, Traefik).
