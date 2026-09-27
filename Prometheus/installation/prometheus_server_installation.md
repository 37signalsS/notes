# Установка Prometheus Server

## Определения

**Prometheus Server** — центральный компонент системы мониторинга, отвечающий за сбор (scraping) метрик, их хранение во встроенной базе данных временных рядов (TSDB), выполнение запросов на языке PromQL, а также обработку правил записи и оповещения (alerting).

> **См. также:** **[Архитектура Prometheus](../overview.md)**, **[Внутреннее устройство TSDB](../concepts/tsdb.md)**, **[Конфигурация](../configuration.md)**.

## Предварительные требования

### Аппаратные требования

| Сценарий | CPU | RAM | Диск | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **Тестирование / Dev** | 2 ядра | 4 ГБ | 20 ГБ (SSD) | До 50 000 активных рядов |
| **Production (малый)** | 4 ядра | 8 ГБ | 100 ГБ (SSD) | До 500 000 рядов |
| **Production (средний)** | 8 ядер | 16 ГБ | 500 ГБ (NVMe) | До 1 000 000 рядов |
| **High Load / Шардирование** | 16+ ядер | 32–64 ГБ | 1 ТБ+ (NVMe) | >1 000 000 рядов, требуется sharding |

### Программные требования

| Компонент | Версия / Требование |
| :--- | :--- |
| **ОС** | Linux (RHEL/CentOS/Debian/Ubuntu/Rocky/Alma), macOS (только для dev), Windows (только для dev/WSL2) |
| **Systemd** | Рекомендуется для управления жизненным циклом на Linux |
| **Go runtime** | Не требуется (Prometheus поставляется статическим бинарником) |
| **Пorts** | 9090 (HTTP API / Web UI), 9093 (Alertmanager, если на том же хосте) |
| **Права** | Отдельный пользователь `prometheus` (nologin), права на `/etc/prometheus` и `/var/lib/prometheus` |

## Основные концепции

### Жизненный цикл сбора данных (Scrape Lifecycle)

1. **Discovery**: Prometheus находит таргеты через статические конфигурации, DNS, Kubernetes API, Consul и другие сервисы-дискавери.
2. **Scrape**: Указанные эндпоинты опрашиваются с интервалом `scrape_interval`. Полученные метрики добавляются временными метками.
3. **WAL**: Сэмплы записываются в Write-Ahead Log на диск для гарантии сохранности при сбоях.
4. **Head Block**: Активные данные помещаются в оперативную память для быстрого доступа и запросов.
5. **Compaction**: Каждые 2 часа Head Block закрывается и записывается на диск как постоянный блок. Фоновый процесс объединяет старые блоки.

### Сервис-дискавери (Service Discovery)

Prometheus поддерживает множество механизмов обнаружения таргетов:
*   **Статические (`static_configs`)** — фиксированный список `host:port`.
*   **DNS (`dns_sd_configs`)** — динамическое обнаружение через DNS-записи (SRV, A, AAAA).
*   **Kubernetes (`kubernetes_sd_configs`)** — автоматическое обнаружение Pod, Service, Endpoints, Node, Ingress.
*   **Consul / Nomad** — интеграция с HashiCorp-экосистемой.
*   **Файловая (`file_sd_configs`)** — чтение таргетов из JSON/YAML-файлов, полезно для динамических сред.

### Сравнение методов установки

| Метод | Уровень контроля | Сложность | Когда использовать | Ссылка |
| :--- | :--- | :--- | :--- | :--- |
| **Бинарные файлы + systemd** | Максимальный | Средняя | Production bare-metal/VM, требование hardening | Сценарий 1 |
| **APT (Debian/Ubuntu)** | Средний | Низкая | Стандартные серверы Debian/Ubuntu, автоматические обновления | Сценарий 2 |
| **YUM/DNF (RHEL/Rocky)** | Средний | Низкая | Enterprise Linux, соответствие политикам | Сценарий 3 |
| **Docker / Podman** | Высокий | Низкая | Контейнеризированные среды, быстрый старт | Сценарий 4 |
| **Kubernetes / Helm** | Высокий | Средняя | K8s-кластеры, GitOps | Сценарий 5 |
| **Ansible (IaC)** | Высокий | Средняя | Парк серверов, повторяемые конфигурации | Сценарий 6 |

> **Рекомендация:** Для production bare-metal/VM используйте бинарные файлы. Для Debian/Ubuntu — APT. Для Kubernetes — Helm. Подробное сравнение: **[Установка Prometheus: обзор](../installation/overview.md)**.

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (Linux/systemd)

Этот метод обеспечивает максимальный контроль над производительностью и рекомендуется для Production-сред.

**1. Подготовка системы:**
Создайте системного пользователя без домашней директории и прав входа, а также необходимые каталоги.
```bash
# Создание пользователя
sudo useradd --no-create-home --shell /bin/false prometheus

# Создание директорий для конфигурации и данных TSDB
sudo mkdir -p /etc/prometheus /var/lib/prometheus
```

**2. Загрузка и верификация (v3.13.2):**
```bash
PROMETHEUS_VERSION="3.13.2"
cd /tmp

# Загрузка архива и файла контрольных сумм
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/sha256sums.txt

# Проверка целостности загруженного файла
sha256sum --check --ignore-missing sha256sums.txt
# → prometheus-3.13.2.linux-amd64.tar.gz: OK
```

**3. Размещение исполняемых и конфигурационных файлов:**
```bash
tar xvfz prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
cd prometheus-${PROMETHEUS_VERSION}.linux-amd64

# Перемещение бинарных файлов в стандартный путь выполнения
sudo mv prometheus promtool /usr/local/bin/

# Копирование консольных библиотек и шаблонов (необходимы для Web UI)
sudo cp -r consoles console_libraries /etc/prometheus/
sudo cp prometheus.yml /etc/prometheus/

# Установка прав владения (рекурсивно для директории данных)
sudo chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
sudo chown prometheus:prometheus /usr/local/bin/prometheus /usr/local/bin/promtool
# → Files placed and permissions updated
```

**4. Настройка systemd-сервиса с элементами Hardening:**
Создайте `/etc/systemd/system/prometheus.service`:
```ini
[Unit]
Description=Prometheus Server
Documentation=https://prometheus.io/docs/introduction/overview/
After=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/var/lib/prometheus/ \
    --storage.tsdb.retention.time=15d \
    --storage.tsdb.wal-compression \
    --web.enable-lifecycle \
    --web.enable-otlp-receiver \
    --web.listen-address=:9090

# Ограничение прав процесса
Restart=always
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**5. Запуск:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prometheus
# Проверка статуса
systemctl is-active prometheus
# → active
```

### Сценарий 2: Установка через APT (Debian/Ubuntu)

Установка через стандартные репозитории Debian/Ubuntu или PPA. Пакеты автоматически создают пользователя, systemd unit и конфигурационные файлы.

```bash
# 1. Обновление локального индекса пакетов
sudo apt update

# 2. Установка сервера и базового экспортера
sudo apt install -y prometheus prometheus-node-exporter
# → [OK] Installed prometheus, prometheus-node-exporter

# 3. Проверка автоматического запуска сервисов
sudo systemctl is-active prometheus
# → active

# 4. Проверка версии
prometheus --version
# → prometheus, version 3.13.2 ...
```

**Фиксация версии (pinning) для предотвращения автоматического обновления:**
```bash
sudo apt-mark hold prometheus prometheus-node-exporter
# → prometheus set on hold.
# → prometheus-node-exporter set on hold.
```

Подробно: **[Установка Prometheus через APT](../installation/with_apt.md)**.

### Сценарий 3: Установка через YUM/DNF (RHEL/CentOS/Rocky/Alma)

Enterprise Linux-дистрибутивы используют репозиторий `packagecloud.io/prometheus-rpm`.

**1. Добавление репозитория (RHEL 9+/Rocky 9+):**
```bash
sudo tee /etc/yum.repos.d/prometheus.repo <<EOF
[prometheus]
name=Prometheus
baseurl=https://packagecloud.io/prometheus-rpm/release/el/9/\$basearch
enabled=1
gpgcheck=1
gpgkey=https://packagecloud.io/prometheus-rpm/release/gpgkey
EOF
```

**2. Установка и запуск:**
```bash
sudo dnf install -y prometheus node_exporter
sudo systemctl enable --now prometheus node_exporter

# Проверка
systemctl status prometheus
# → active (running)
prometheus --version
# → prometheus, version 3.13.2
```

**3. Проверка целей скрапинга:**
```bash
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets'
```

**4. Валидация конфигурации:**
```bash
promtool check config /etc/prometheus/prometheus.yml
# → SUCCESS
```

**Изолированные среды (Air-gapped):**
```bash
# На машине с интернетом: скачивание RPM и зависимостей
dnf download --resolve prometheus node_exporter --alldeps

# Перенос файлов через USB/SCP на изолированный хост
# Установка из локального каталога
sudo dnf install -y ./prometheus-*.rpm ./node_exporter-*.rpm
```

### Сценарий 4: Установка через Docker / Podman

Используйте официальный образ. Рекомендуется использовать конкретные теги версий вместо `latest`.

```bash
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml:ro \
  -v prometheus_data:/prometheus \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  prom/prometheus:v3.13.2 \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.wal-compression \
  --web.enable-lifecycle
# → Container started with ID ...
```

**Air-gapped (Docker):**
```bash
# На машине с интернетом: сохраните образ
docker pull prom/prometheus:v3.13.2
docker save -o prometheus-v3.13.2.tar prom/prometheus:v3.13.2

# Перенос архива на изолированный хост
docker load -i prometheus-v3.13.2.tar

# Запуск из загруженного образа
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml:ro \
  -v prometheus_data:/prometheus \
  prom/prometheus:v3.13.2 \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.wal-compression \
  --web.enable-lifecycle
```

### Сценарий 5: Установка через Helm (Kubernetes)

В Kubernetes-кластерах стандартом является использование Helm-чарта `kube-prometheus-stack`, который автоматизирует управление всем стеком через оператора Prometheus.

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus.community.github.io/helm-charts
helm repo update

# Просмотр доступных версий
helm search repo prometheus-community/kube-prometheus-stack --versions

# Установка
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f values.yaml
```

**Проверка установки:**
```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus
# → monitoring-kube-prometheus-prometheus-0   2/2     Running   0          2m

kubectl get servicemonitor,podmonitor,prometheusrule,alertmanagerconfig -n monitoring
# → servicemonitor ... listed
```

Подробно: **[Установка Prometheus в Kubernetes через Helm](../installation/with_helm_chart.md)**.

**Air-gapped (Helm):**
```bash
# На машине с интернетом: загрузка чарта
helm pull prometheus-community/kube-prometheus-stack --destination ./charts

# Перенос архива на изолированный кластер
helm install monitoring ./charts/kube-prometheus-stack-*.tgz \
  --namespace monitoring --create-namespace \
  -f values.yaml
```

### Сценарий 6: Установка через Ansible (IaC)

Для массового развертывания на парке серверов используйте коллекцию `prometheus.prometheus`:

```yaml
---
- name: Развертывание Prometheus Server
  hosts: monitoring
  become: yes
  vars:
    prometheus_version: "3.13.2"
    prometheus_storage_tsdb_path: "/var/lib/prometheus"
    prometheus_config_file: "/etc/prometheus/prometheus.yml"

  tasks:
    - name: Создание системного пользователя
      ansible.builtin.user:
        name: prometheus
        shell: /bin/false
        create_home: no
        state: present

    - name: Создание директорий
      ansible.builtin.file:
        path: "{{ item }}"
        state: directory
        owner: prometheus
        group: prometheus
        mode: '0755'
      loop:
        - /etc/prometheus
        - /var/lib/prometheus

    - name: Загрузка и распаковка Prometheus
      ansible.builtin.unarchive:
        src: https://github.com/prometheus/prometheus/releases/download/v{{ prometheus_version }}/prometheus-{{ prometheus_version }}.linux-amd64.tar.gz
        dest: /tmp/
        remote_src: yes

    - name: Размещение бинарных файлов
      ansible.builtin.copy:
        src: "{{ item }}"
        dest: /usr/local/bin/
        mode: '0755'
        owner: root
        group: root
      loop:
        - /tmp/prometheus-{{ prometheus_version }}.linux-amd64/prometheus
        - /tmp/prometheus-{{ prometheus_version }}.linux-amd64/promtool

    - name: Размещение конфигурации
      ansible.builtin.copy:
        src: prometheus.yml
        dest: "{{ prometheus_config_file }}"
        owner: prometheus
        group: prometheus
        mode: '0644'

    - name: Настройка systemd unit
      ansible.builtin.copy:
        dest: /etc/systemd/system/prometheus.service
        content: |
          [Unit]
          Description=Prometheus Server
          After=network-online.target

          [Service]
          User=prometheus
          Group=prometheus
          Type=simple
          ExecStart=/usr/local/bin/prometheus \
              --config.file={{ prometheus_config_file }} \
              --storage.tsdb.path={{ prometheus_storage_tsdb_path }} \
              --storage.tsdb.retention.time=15d \
              --storage.tsdb.wal-compression \
              --web.enable-lifecycle \
              --web.enable-otlp-receiver \
              --web.listen-address=:9090
          Restart=always
          NoNewPrivileges=true
          ProtectSystem=full
          ProtectHome=true
          PrivateTmp=true

          [Install]
          WantedBy=multi-user.target
        mode: '0644'

    - name: Запуск и включение Prometheus
      ansible.builtin.systemd:
        name: prometheus
        state: started
        enabled: yes
        daemon_reload: yes
```

### Сценарий 7: Настройка правил записи (Recording Rules)

Recording Rules предварительно вычисляют сложные PromQL-выражения, снижая нагрузку на сервер при построении дашбордов и алертов.

**1. Создание файла правил:**
```yaml
# /etc/prometheus/recording_rules.yml
groups:
  - name: node.recording
    interval: 30s
    rules:
      # Утилизация CPU в процентах
      - record: node:cpu_utilization:ratio
        expr: |
          100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)

      # Доступная память в процентах
      - record: node:memory_utilization:ratio
        expr: |
          1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)
```

**2. Подключение в `prometheus.yml`:**
```yaml
rule_files:
  - 'recording_rules.yml'
  - 'alerting_rules.yml'
```

**3. Валидация и применение:**
```bash
# Проверка синтаксиса
promtool check rules /etc/prometheus/recording_rules.yml
# → SUCCESS: 2 rules found

# Горячая перезагрузка конфигурации
curl -X POST http://localhost:9090/-/reload
```

Подробнее: **[Правила в Prometheus: Recording и Alerting](../rules.md)**.

### Сценарий 8: Интеграция с Alertmanager

Alertmanager обрабатывает алерты от Prometheus: дедупликация, группировка, маршрутизация и отправка уведомлений.

**1. Установка Alertmanager:**
```bash
# Бинарная установка
wget https://github.com/prometheus/alertmanager/releases/download/v0.33.1/alertmanager-0.33.1.linux-amd64.tar.gz
tar xvfz alertmanager-0.33.1.linux-amd64.tar.gz
sudo mv alertmanager amtool /usr/local/bin/
sudo mkdir -p /etc/alertmanager
```

**2. Настройка `alertmanager.yml`:**
```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'slack-notifications'

receivers:
  - name: 'slack-notifications'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'
        channel: '#alerts'
```

**3. Подключение в `prometheus.yml`:**
```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ['localhost:9093']

rule_files:
  - 'alerting_rules.yml'
```

**4. Запуск Alertmanager:**
```bash
sudo systemctl enable --now alertmanager
```

Подробно: **[Установка Alertmanager](../installation/alertmanager_installation.md)**.

### Сценарий 9: Настройка безопасности (Native Basic Auth & TLS)

Использование встроенных механизмов защиты без внешнего прокси.

**1. Создание файла `web-config.yml`:**
```yaml
basic_auth_users:
  admin: "$2y$12$hN3qMZZP4zWlYhX.Q.W.Ze9rYgWJ9g2U1c2G5rX1b.x.x.x.x.x.x" # bcrypt hash

tls_server_config:
  cert_file: /etc/prometheus/certs/server.crt
  key_file: /etc/prometheus/certs/server.key
```

**2. Запуск:** Добавьте флаг `--web.config.file=/etc/prometheus/web-config.yml` в `ExecStart` или команду запуска контейнера.

**3. Валидация:**
```bash
# Без авторизации — должно быть 401
curl -k https://localhost:9090/api/v1/status/flags
# → 401 Unauthorized

# С Basic Auth — успешный ответ
curl -k -u admin:password https://localhost:9090/api/v1/status/flags | jq .
# → {"status":"success","data":[...]}
```

Подробнее: **[Безопасность Prometheus](../security.md)**.

## Валидация установки

### Матрица проверок по методам

| Метод | Команда проверки | Ожидаемый результат |
| :--- | :--- | :--- |
| **Бинарные файлы** | `systemctl is-active prometheus` | `active` |
| | `promtool check config /etc/prometheus/prometheus.yml` | `SUCCESS` |
| | `curl -s http://localhost:9090/-/ready` | `Prometheus Server is Ready.` |
| **APT** | `systemctl is-active prometheus` | `active` |
| | `apt-cache policy prometheus` | Отображает установленную версию |
| | `curl -s http://localhost:9090/api/v1/status/flags` | JSON с флагами |
| **YUM/DNF** | `systemctl is-active prometheus` | `active` |
| | `rpm -q prometheus` | Версия пакета |
| | `curl -s http://localhost:9090/api/v1/targets` | JSON с таргетами |
| **Docker** | `docker ps --filter name=prometheus` | `Up` |
| | `docker logs prometheus` | `Server is Ready` |
| | `curl -s http://localhost:9090/-/ready` | `Prometheus Server is Ready.` |
| **Helm** | `kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus` | `Running` |
| | `kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus -c prometheus` | `Server is Ready` |
| | `kubectl port-forward -n monitoring svc/monetheus-kube-prometheus-prometheus 9090:9090` | Доступ к UI |

## Резервное копирование и восстановление

### Резервное копирование

**Вариант 1: Онлайн-снэпшот через HTTP API (без остановки)**
```bash
# Создание снэпшота
curl -X POST http://localhost:9090/api/v1/admin/tsdb/snapshot

# Результат:
# {"data":{"name":"20230916T153745Z-<hash>"}}

# Снэпшот создаётся в каталоге <storage.tsdb.path>/snapshots/
```

**Вариант 2: Файловый бэкап (офлайн, требует остановки)**
```bash
# 1. Остановка Prometheus
systemctl stop prometheus

# 2. Архивирование данных
tar -czf /backup/prometheus-tsdb-$(date +%Y%m%d).tar.gz -C /var/lib/prometheus .

# 3. Запуск Prometheus
systemctl start prometheus
```

### Восстановление

```bash
# 1. Остановка Prometheus
systemctl stop prometheus

# 2. Восстановление данных
tar -xzf /backup/prometheus-tsdb-20230916.tar.gz -C /var/lib/prometheus

# 3. Запуск Prometheus
systemctl start prometheus
```

> **Важно:** WAL содержит данные, ещё не записанные в блоки. Для полного восстановления нужны и блоки, и WAL. При восстановлении из снэпшота Prometheus начнёт восстанавливать Head-блок из WAL автоматически.

Подробнее: **[Внутреннее устройство TSDB](../concepts/tsdb.md)**.

## Обновление и откат

### Бинарные файлы

```bash
# 1. Остановка сервиса
sudo systemctl stop prometheus

# 2. Загрузка и замена бинарных файлов
PROMETHEUS_VERSION="3.13.3"
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
tar xvfz prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
sudo mv prometheus promtool /usr/local/bin/

# 3. Валидация конфигурации (критично перед запуском)
promtool check config /etc/prometheus/prometheus.yml

# 4. Запуск
sudo systemctl start prometheus
```

**Откат:** Верните предыдущие бинарные файлы из резервной копии и перезапустите сервис.

### APT

```bash
# Обновление
sudo apt update && sudo apt upgrade prometheus

# Проверка версии
prometheus --version

# Фиксация версии (предотвращение автоматического обновления)
sudo apt-mark hold prometheus
```

**Откат:**
```bash
sudo apt-mark unhold prometheus
sudo apt install prometheus=3.13.2
```

### Helm

```bash
# Обновление релиза
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring -f values.yaml

# Откат к предыдущей ревизии
helm rollback monitoring -n monitoring

# Просмотр истории
helm history monitoring -n monitoring
```

### Docker

```bash
# Обновление образа
docker stop prometheus && docker rm prometheus
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml:ro \
  -v prometheus_data:/prometheus \
  prom/prometheus:v3.13.3 \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.wal-compression \
  --web.enable-lifecycle

# Или через Compose
docker compose up -d --force-recreate prometheus
```

## Очистка и удаление

### Бинарные файлы

```bash
# Остановка и отключение сервиса
sudo systemctl stop prometheus
sudo systemctl disable prometheus

# Удаление unit-файла
sudo rm /etc/systemd/system/prometheus.service
sudo systemctl daemon-reload

# Удаление бинарных файлов
sudo rm /usr/local/bin/prometheus /usr/local/bin/promtool

# Удаление конфигурации и данных (ВНИМАНИЕ: необратимо)
sudo rm -rf /etc/prometheus /var/lib/prometheus

# Удаление пользователя
sudo userdel prometheus
```

### APT

```bash
# Остановка и отключение сервиса
sudo systemctl stop prometheus
sudo systemctl disable prometheus

# Удаление пакетов
sudo apt remove --purge prometheus prometheus-node-exporter

# Удаление конфигурации и данных
sudo rm -rf /etc/prometheus /var/lib/prometheus

# Удаление пользователя (если не используется другими сервисами)
sudo userdel prometheus
```

### Docker

```bash
# Остановка и удаление контейнера
docker stop prometheus && docker rm prometheus

# Удаление тома с данными (ВНИМАНИЕ: необратимо)
docker volume rm prometheus_data
```

### Helm (Kubernetes)

```bash
# Удаление релиза
helm uninstall monitoring -n monitoring

# Удаление PVC (если не требуется сохранять данные)
kubectl delete pvc -n monitoring -l app.kubernetes.io/instance=monitoring

# Удаление namespace (опционально)
kubectl delete namespace monitoring
```

## Использование promtool (Диагностика)

Инструмент `promtool` необходим для обслуживания и проверки системы:

*   **Валидация конфига**: `promtool check config /etc/prometheus/prometheus.yml` (# → SUCCESS).
*   **Анализ TSDB**: `promtool tsdb analyze /var/lib/prometheus/` (позволяет выявить метрики с наибольшей кардинальностью).
*   **Проверка правил**: `promtool check rules /etc/prometheus/alert_rules.yml`.

## Мониторинг самого сервера

Критически важно собирать метрики самого Prometheus для контроля здоровья TSDB.

```yaml
scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
```

**Ключевые метрики для алертинга:**
*   `prometheus_tsdb_head_series`: Количество активных временных рядов в памяти.
*   `prometheus_tsdb_storage_blocks_bytes`: Общий объем хранилища на диске.
*   `rate(prometheus_tsdb_head_samples_appended_total[5m])`: Скорость записи новых данных.
*   `prometheus_tsdb_wal_size_bytes`: Размер WAL на диске.
*   `time() - max(prometheus_tsdb_commit_timestamp_seconds)`: Задержка сброса Head Block.

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Повреждение WAL** | `panic: runtime error: index out of range` на старте | Проверьте целостность сегментов. В крайнем случае удалите `wal/` (потеря 2 ч данных). |
| **Таймауты скрейпинга** | `up == 0` | Увеличьте `scrape_timeout` в конфигурации. |
| **Переполнение памяти** | Взрывной рост кардинальности | Используйте TSDB Status в Web UI для идентификации проблемных лейблов. |
| **Медленная запись** | WAL на медленном диске (HDD) | Переместите WAL на NVMe SSD. |
| **Высокое потребление RAM** | >1M рядов в Head Block | Проверьте `metric_relabel_configs`, включите Native Histograms, увеличьте `limits.memory`. |
| **Диск заполняется** | Слишком быстрый рост WAL или retention | Уменьшите `retention.time`, проверьте remote_write endpoint. |
| **Алерты не отправляются** | Неверная конфигурация Alertmanager | Проверьте блок `alerting` в `prometheus.yml` и доступность Alertmanager. |

## Рекомендации SRE

1.  **Принцип минимальных привилегий:** Запуск через `user: prometheus`. В systemd используйте `NoNewPrivileges=true`, `ProtectSystem=full`, `ProtectHome=true`, `PrivateTmp=true`.
2.  **Ограничение слушаемого интерфейса:** Используйте `--web.listen-address=127.0.0.1:9090` и reverse proxy (Nginx/Caddy) для внешнего доступа.
3.  **Сетевая сегментация:** Разрешите inbound на порт 9090 только из доверенных подсетей (Grafana, jump-hosts, Prometheus-серверы).
4.  **Ограничение ресурсов PromQL:** Добавьте флаги `--query.max-concurrency=20`, `--query.max-samples=50000000`, `--query.timeout=2m`.
5.  **Мониторинг самого Prometheus:** Собирайте метрики `prometheus_tsdb_head_series`, `prometheus_tsdb_storage_blocks_bytes`, `prometheus_tsdb_wal_size_bytes`.
6.  **GOMEMLIMIT:** В контейнеризированных средах установите `GOMEMLIMIT` на 10–20% ниже `limits.memory`.
7.  **Ротация секретов:** Планируйте регулярную ротацию сертификатов (каждые 90 дней) и паролей.
8.  **Валидация перед обновлением:** Всегда выполняйте `promtool check config` и `promtool check rules` перед применением изменений.

## См. также

*   **[Конфигурация prometheus.yml](../configuration.md)**
*   **[Безопасность Prometheus](../security.md)**
*   **[Масштабирование и Remote Write](../scaling/overview.md)**
*   **[Внутреннее устройство TSDB](../concepts/tsdb.md)**
*   **[Правила: Recording и Alerting](../rules.md)**
*   **[HA Setup](./ha_setup.md)** — практическое развертывание HA Prometheus + Alertmanager.
*   **[Nginx Reverse Proxy](./nginx_reverse_proxy.md)** — TLS, Basic Auth, rate limiting перед Prometheus.
*   **[Capacity Planning](./capacity_planning.md)** — формулы расчёта ресурсов.
*   **[Alert Rules](./alert_rules_quickstart.md)** — практические примеры alerting rules.
