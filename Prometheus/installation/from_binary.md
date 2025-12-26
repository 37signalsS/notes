# Установка стека Prometheus из бинарных файлов

## 1. Определения

- **Prometheus Server**: Основной компонент, отвечающий за сбор, хранение и обработку метрик в формате временных рядов (TSDB).
- **Node Exporter**: Экспортер для сбора метрик с аппаратного и программного обеспечения хостовой системы (CPU, RAM, диск, сеть).
- **Blackbox Exporter**: Экспортер для проверки доступности эндпоинтов по различным протоколам (HTTP, HTTPS, TCP, ICMP, DNS). Работает по принципу "черного ящика".
- **Alertmanager**: Обрабатывает алерты, отправленные Prometheus. Отвечает за их дедупликацию, группировку, и маршрутизацию в различные системы уведомлений (Email, Slack, PagerDuty).
- **Pushgateway**: Позволяет кратковременным и batch-заданиям, которые не могут быть постоянно доступны для скрейпинга, отправлять свои метрики в Prometheus.

## 2. Основные концепции

### 2.1. Принцип установки

1.  **Создание пользователя**: Для изоляции процессов и повышения безопасности для каждого компонента (кроме Node Exporter, которому нужен root-доступ) создается отдельный системный пользователь без прав на вход в систему.
2.  **Загрузка и размещение бинарных файлов**: Архив с последней стабильной версией загружается с официального репозитория на GitHub, распаковывается, и исполняемый файл помещается в `/usr/local/bin/`.
3.  **Создание конфигурации**: Создаются необходимые каталоги (`/etc/<component>`, `/var/lib/<component>`) и файлы конфигурации.
4.  **Настройка `systemd` сервиса**: Для управления процессом (автозапуск, перезапуск) создается unit-файл в `/usr/lib/systemd/system/`. Параметры запуска выносятся в отдельный environment-файл в `/etc/sysconfig/`.

### 2.2. Управление через `systemd`

После создания unit-файла для каждого компонента используются стандартные команды `systemctl`:
- `systemctl daemon-reload`: Перечитать конфигурацию `systemd`.
- `systemctl start <service>`: Запустить сервис.
- `systemctl enable <service>`: Включить автозапуск сервиса при старте системы.
- `systemctl status <service>`: Проверить статус сервиса.

---

## 3. Практические сценарии: Установка компонентов

### 3.1. Установка Prometheus Server

**Версия**: 3.8.1

1.  **Создание пользователя**:
    ```bash
    useradd prometheus --comment "Prometheus server user" --shell /bin/false
    ```

2.  **Загрузка и установка**:
    ```bash
    PROMETHEUS_VERSION="3.8.1"
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

5.  **Создание systemd-сервиса** (`/usr/lib/systemd/system/prometheus.service`):
    ```bash
    cat <<EOF > /usr/lib/systemd/system/prometheus.service
    [Unit]
    Description=Prometheus Server
    Documentation=https://github.com/prometheus/prometheus
    After=network-online.target

    [Service]
    Restart=always
    User=prometheus
    Group=prometheus
    EnvironmentFile=/etc/sysconfig/prometheus
    ExecStart=/usr/local/bin/prometheus $OPTIONS
    ExecReload=/bin/kill -HUP $MAINPID
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

### 3.2. Установка Node Exporter

**Версия**: 1.10.2

1.  **Загрузка и установка**:
    ```bash
    NODE_EXPORTER_VERSION="1.10.2"
    cd /tmp
    wget https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
    tar xvfz node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
    mv node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/
    ```

2.  **Создание файла с опциями запуска** (`/etc/sysconfig/node_exporter`):
    > Для сбора всех метрик `node_exporter` запускается от `root`.
    ```bash
    cat <<EOF > /etc/sysconfig/node_exporter
    OPTIONS=""
    EOF
    ```

3.  **Создание systemd-сервиса** (`/usr/lib/systemd/system/node_exporter.service`):
    ```bash
    cat <<EOF > /usr/lib/systemd/system/node_exporter.service
    [Unit]
    Description=Prometheus Node exporter for machine metrics
    Documentation=https://github.com/prometheus/node_exporter
    After=network-online.target

    [Service]
    Restart=always
    User=root
    EnvironmentFile=/etc/sysconfig/node_exporter
    ExecStart=/usr/local/bin/node_exporter $OPTIONS
    ExecReload=/bin/kill -HUP $MAINPID
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

### 3.3. Установка Blackbox Exporter

**Версия**: 0.28.0

1.  **Загрузка и установка**:
    ```bash
    BLACKBOX_EXPORTER_VERSION="0.28.0"
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

4.  **Создание systemd-сервиса** (`/usr/lib/systemd/system/blackbox_exporter.service`):
    ```bash
    cat <<EOF > /usr/lib/systemd/system/blackbox_exporter.service
    [Unit]
    Description=Prometheus Blackbox Exporter
    Documentation=https://github.com/prometheus/blackbox_exporter
    After=network-online.target

    [Service]
    Restart=always
    User=nobody
    Group=nobody
    EnvironmentFile=/etc/sysconfig/blackbox_exporter
    ExecStart=/usr/local/bin/blackbox_exporter $OPTIONS
    ExecReload=/bin/kill -HUP $MAINPID

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

### 3.4. Установка Alertmanager

**Версия**: 0.30.0

1.  **Создание пользователя**:
    ```bash
    useradd --comment "User to run Alertmanager" --shell /bin/false alertmanager
    ```
2.  **Загрузка и установка**:
    ```bash
    ALERTMANAGER_VERSION="0.30.0"
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

5.  **Создание systemd-сервиса** (`/usr/lib/systemd/system/alertmanager.service`):
    ```bash
    cat <<EOF > /usr/lib/systemd/system/alertmanager.service
    [Unit]
    Description=Prometheus Alertmanager
    Documentation=https://prometheus.io/docs/alerting/latest/alertmanager/
    After=network-online.target

    [Service]
    User=alertmanager
    Group=alertmanager
    Restart=always
    EnvironmentFile=/etc/sysconfig/alertmanager
    ExecStart=/usr/local/bin/alertmanager $OPTIONS
    ExecReload=/bin/kill -HUP $MAINPID
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

### 3.5. Установка Pushgateway

**Версия**: 1.11.2

1.  **Создание пользователя**:
    ```bash
    useradd pushgateway --comment "Pushgateway server user" --shell /bin/false
    ```

2.  **Загрузка и установка**:
    ```bash
    PUSHGATEWAY_VERSION="1.11.2"
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
4. **Создание каталога для хранения метрик**:
   ```bash
   mkdir /var/lib/pushgateway
   chown pushgateway:pushgateway /var/lib/pushgateway
   ```

5.  **Создание systemd-сервиса** (`/usr/lib/systemd/system/pushgateway.service`):
    ```bash
    cat <<EOF > /usr/lib/systemd/system/pushgateway.service
    [Unit]
    Description=Prometheus Pushgateway
    Documentation=https://github.com/prometheus/pushgateway
    After=network-online.target

    [Service]
    User=pushgateway
    Group=pushgateway
    EnvironmentFile=/etc/sysconfig/pushgateway
    Restart=always
    ExecStart=/usr/local/bin/pushgateway $OPTIONS
    ExecReload=/bin/kill -HUP $MAINPID
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

## 4. Продвинутые детали

### 4.1. Проверка конфигурации

Перед применением изменений в конфигурации Prometheus всегда проверяйте её синтаксис с помощью утилиты `promtool`, которая устанавливается вместе с сервером. Это помогает избежать ошибок, которые могут привести к остановке сбора метрик.

```bash
promtool check config /etc/prometheus/prometheus.yml
```
Для Alertmanager также существует утилита `amtool` для проверки конфигурации и управления состоянием.

```bash
amtool check-config /etc/alertmanager/alertmanager.yml
```
Подробнее об утилите `promtool` можно прочитать в заметке [`promtool_and_best_practices.md`](./promtool_and_best_practices.md).

### 4.2. Безопасность

- **Пользователи**: Запуск от непривилегированных пользователей снижает потенциальный ущерб в случае эксплуатации уязвимостей.
- **Сетевые доступы**: Настраивайте файрвол для ограничения доступа к веб-интерфейсам и API компонентов только с доверенных IP-адресов.
- **TLS**: Для защиты трафика между компонентами и при доступе пользователей используйте TLS-шифрование, например, с помощью обратного прокси-сервера (Nginx, Traefik).

```