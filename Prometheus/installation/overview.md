# Установка Prometheus: обзор

## Определения

**Установка Prometheus** — процесс развертывания и настройки компонентов экосистемы мониторинга. Полная архитектура системы описана в документе **[Обзор Prometheus](../overview.md)**.

Экосистема включает следующие ключевые компоненты:

*   **Prometheus Server**: центральный узел для сбора, хранения и обработки метрик в формате временных рядов (TSDB). Подробно: **[Установка Prometheus Server](./prometheus_server_installation.md)**.
*   **Node Exporter**: агент для сбора метрик хостовой операционной системы (CPU, RAM, диск, сеть). Подробно: **[Установка Node Exporter](./node_exporter_installation.md)**.
*   **Blackbox Exporter**: компонент для проверки доступности эндпоинтов по протоколам HTTP, HTTPS, TCP, ICMP и DNS. Подробно: **[Blackbox Exporter: установка](../Exporters/blackbox/blackbox_exporter_installation_and_setup.md)**.
*   **Alertmanager**: обработка оповещений — дедупликация, группировка и маршрутизация уведомлений. Подробно: **[Установка Alertmanager](./alertmanager_installation.md)**.
*   **Pushgateway**: шлюз для приема метрик от кратковременных или пакетных (batch) заданий. Подробно: **[Установка Pushgateway](./pushgateway_installation.md)**.

## Основные концепции

### Матрица выбора метода установки

Выбор метода зависит от операционной системы, требований к контролю версий, инфраструктурного контекста и уровня автоматизации.

| Метод | Когда использовать | Уровень контроля | Автоматизация | Подробное руководство |
| :--- | :--- | :--- | :--- | :--- |
| **Бинарные файлы** | Production bare-metal/VM, требование точной версии | Максимальный | systemd unit, Ansible | **[Установка Prometheus Server](./prometheus_server_installation.md)** |
| **APT (Debian/Ubuntu)** | Стандартные серверы Debian/Ubuntu, автоматические обновления | Средний | systemd (автоматически) | **[Установка через APT](./with_apt.md)** |
| **YUM/DNF (RHEL/CentOS/Rocky)** | Enterprise Linux, соответствие политикам hardening | Средний | systemd (автоматически) | См. раздел [Установка через YUM/DNF](#установка-через-yumdnf-rhelcentosrockyalma) |
| **Homebrew (macOS)** | Локальная разработка, тестирование, CI macOS | Высокий | launchd / brew services | См. раздел ниже |
| **Docker / Podman** | Изолированные среды, микросервисы, быстрый старт | Высокий | docker-compose, systemd | **[Обзор Docker Stack](./docker_stack/overview.md)** |
| **Ansible** | Парк серверов (IaC), повторяемые конфигурации | Высокий | Полная автоматизация | См. раздел ниже |
| **Helm / Operator** | Kubernetes, GitOps, облачные среды | Высокий | Helm, ArgoCD, Flux | **[Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md)** |
| **Windows MSI** | Мониторинг инфраструктуры на базе Windows | Средний | Chocolatey, Scoop, systemd (WSL2) | См. раздел ниже |

> **Рекомендация:** Для production bare-metal/VM используйте бинарные файлы — это обеспечивает максимальный контроль над версиями, флагами запуска и hardening. Для серверов Debian/Ubuntu APT даёт автоматическую интеграцию с systemd и ротацией логов. В Kubernetes используйте Helm-чарт `kube-prometheus-stack` как стандарт де-факто.

### Способы установки

#### Бинарные файлы

Ручная загрузка исполняемых файлов с GitHub Releases с последующей настройкой systemd. Метод обеспечивает максимальный контроль над параметрами запуска и hardening.

**Плюсы:** Точная версия, полный контроль над флагами CLI, прозрачность.
**Минусы:** Ручное обновление, отсутствие автоматических зависимостей.

Минимальные шаги:
1. Создание системного пользователя `prometheus` без оболочки (`nologin`).
2. Загрузка и верификация архивов через `sha256sum`.
3. Размещение бинарных файлов в `/usr/local/bin/`, конфигурации в `/etc/prometheus/`, данных TSDB в `/var/lib/prometheus/`.
4. Настройка systemd-юнита с директив hardening (`NoNewPrivileges`, `ProtectSystem`, `ProtectHome`).

Полное пошаговое руководство: **[Установка Prometheus Server](./prometheus_server_installation.md)**.

#### Пакеты APT/YUM

Установка через стандартные репозитории дистрибутива или официальный PPA (Ubuntu). Пакеты автоматически создают пользователя, systemd unit и конфигурационные файлы.

**APT (Debian/Ubuntu):**
```bash
sudo apt update && sudo apt install -y prometheus prometheus-node-exporter
systemctl status prometheus
# → active (running)
```

Подробно: **[Установка через APT](./with_apt.md)**.

**YUM/DNF (RHEL/CentOS/Rocky/Alma):**
```bash
# Добавление официального репозитория Prometheus
sudo tee /etc/yum.repos.d/prometheus.repo <<EOF
[prometheus]
name=Prometheus
baseurl=https://packagecloud.io/prometheus-rpm/release/el/9/\$basearch
enabled=1
gpgcheck=1
gpgkey=https://packagecloud.io/prometheus-rpm/release/gpgkey
EOF

# Установка
sudo dnf install -y prometheus node_exporter
sudo systemctl enable --now prometheus node_exporter
```

> **Примечание:** Для RHEL/CentOS 7 используйте `yum` вместо `dnf`. Для RHEL 8+ и производных — `dnf`. В изолированных сетях скачайте RPM-пакеты и зависимости вручную на машине с интернетом, затем перенесите через защищённый канал.

#### Homebrew (macOS)

Установка через менеджер пакетов macOS. Подходит только для разработки и тестирования — macOS не предназначен для production эксплуатации Prometheus.

```bash
brew install prometheus
brew services start prometheus
prometheus --version
# → prometheus, version 3.13.2 ...
```

**Ограничения macOS:**
*   Отсутствие systemd — управление через `launchd` (brew services) или ручной запуск.
*   Нет встроенной защиты от OOMKiller — настройте `GOMEMLIMIT` вручную.
*   Путь к данным по умолчанию: `/usr/local/var/prometheus` (Intel) или `/opt/homebrew/var/prometheus` (Apple Silicon).

Для продакшен-мониторинга серверов macOS используйте Node Exporter в Docker или виртуальную машину с Linux.

#### Docker / Podman

Запуск в контейнерах. Для полного стека (Prometheus + Grafana + Alertmanager + Node Exporter) используйте Docker Compose.

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
```

Полный стек с persistence, сетевой изоляцией и healthchecks: **[Обзор Docker Stack](./docker_stack/overview.md)**.

#### Ansible

Автоматизация развертывания через коллекцию `prometheus.prometheus`. Подходит для управления парком серверов (bare-metal/VM).

```yaml
- hosts: monitoring
  become: yes
  roles:
    - prometheus.prometheus.prometheus
    - prometheus.prometheus.node_exporter
    - prometheus.prometheus.alertmanager
    - prometheus.prometheus.pushgateway
```

Переменные для управления версиями и путями:
```yaml
prometheus_version: "3.13.2"
prometheus_storage_tsdb_path: "/var/lib/prometheus/"
prometheus_config_file: "/etc/prometheus/prometheus.yml"
```

Роль автоматически создаёт пользователя, настраивает systemd unit с hardening и проверяет целостность загруженных файлов.

#### Helm / Kubernetes

В Kubernetes-кластерах стандартом является использование Helm-чарта `kube-prometheus-stack`, который автоматизирует управление всем стеком через оператора Prometheus.

Подробные инструкции и сценарии: **[Установка через Helm (kube-prometheus-stack)](../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/online_installation.md)**.

> **См. также:** **[Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**.

#### Режим агента (Agent Mode)

Prometheus v3.x поддерживает режим Agent, при котором данные сразу отправляются по Remote Write без локальной TSDB.

```bash
prometheus --agent \
  --config.file=/etc/prometheus/agent.yml \
  --web.enable-remote-write-receiver
```

**Ключевые отличия Agent Mode от Server Mode:**
*   Отсутствует блок `rule_files` — правила не вычисляются локально.
*   Отсутствует веб-интерфейс для запросов (нет TSDB).
*   Обязателен блок `remote_write` в конфигурации.
*   Потребление RAM/CPU на 30–50% ниже за счёт отсутствия TSDB и правил.
*   Подходит для edge-кластеров, филиалов и контейнеризированных сборщиков.

Подробнее: **[Конфигурация Prometheus](../configuration.md#режим-агента-agent-mode)**.

### Принцип установки (бинарные файлы)

1.  **Создание пользователя**: Для изоляции процессов создается системный пользователь (например, `prometheus`) без оболочки (`nologin`) и домашней директории.
2.  **Размещение бинарных файлов**: Исполняемые файлы помещаются в `/usr/local/bin/` для обеспечения глобального доступа.
3.  **Конфигурация и хранилище**:
    *   Конфигурационные файлы: `/etc/prometheus/`
    *   Данные TSDB (база данных): `/var/lib/prometheus/`
4.  **Настройка systemd**: Создание unit-файла в `/etc/systemd/system/` для управления жизненным циклом сервиса.
5.  **Hardening (Усиление безопасности)**: При использовании systemd рекомендуется ограничивать права процесса:
    *   `NoNewPrivileges=true`
    *   `ProtectSystem=full`
    *   `ProtectHome=true`
    *   `PrivateTmp=true`

### Модели развертывания

| Модель | Описание | Сценарий |
| :--- | :--- | :--- |
| **Standalone** | Одиночный инстанс Prometheus Server | Небольшие инфраструктуры, разработка |
| **HA (High Availability)** | Два или более инстанса, независимо опрашивающих одни цели, с дедупликацией в Alertmanager | Production, требование отказоустойчивости |
| **Agent Mode + Remote Write** | Легковесные сборщики без локального хранения, отправка данных в центральное хранилище | Edge-кластеры, филиалы, масштабируемые архитектуры |
| **Federation** | Иерархия: вышестоящий Prometheus опрашивает нижестоящие | Агрегация из нескольких дата-центров без облачных хранилищ |

## Практические сценарии

### Быстрый старт (Debian/Ubuntu)

Минимальная настройка для локального тестирования:

```bash
# Установка сервера и базового экспортера
sudo apt update && sudo apt install -y prometheus prometheus-node-exporter

# Проверка статуса сервиса
systemctl status prometheus
# → Active: active (running) ...

# Проверка доступности
curl -I http://localhost:9090/graph    # Web UI Prometheus
curl -I http://localhost:9100/metrics  # Метрики Node Exporter
```

> **Подробное руководство:** [Установка через APT](./with_apt.md).

### Установка через YUM/DNF (RHEL/CentOS/Rocky/Alma)

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

### Установка на macOS (Homebrew)

Подходит для быстрой настройки среды разработки:

```bash
# Установка Prometheus и Node Exporter
brew install prometheus prometheus-node-exporter

# Запуск сервиса (автоматически создаёт launchd plist)
brew services start prometheus
brew services start node_exporter

# Проверка версии
prometheus --version
# → prometheus, version 3.13.2 ...

# Проверка доступности
curl -I http://localhost:9090/graph
# → HTTP/1.1 200 OK
```

**Пути и окружение:**
*   Конфигурация: `/usr/local/etc/prometheus/prometheus.yml` (Intel) или `/opt/homebrew/etc/prometheus/prometheus.yml` (Apple Silicon).
*   Данные: `/usr/local/var/prometheus/` (Intel) или `/opt/homebrew/var/prometheus/` (Apple Silicon).
*   Логи: `brew services tail prometheus`.

**Ограничения:**
*   Нет systemd — используйте `brew services` или `launchctl`.
*   Для production не рекомендуется — используйте виртуальную машину с Linux или Docker.

### Запуск через Docker или Podman

Универсальный способ для изолированного запуска. Для production-стека с persistence, сетевой изоляцией и healthchecks используйте Docker Compose.

Полное руководство: **[Обзор Docker Stack](./docker_stack/overview.md)**.

Минимальный пример:
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

# Проверка логов
docker logs prometheus
```

### Автоматизация через Ansible (полный стек)

Для массового развертывания всего стека используйте коллекцию `prometheus.prometheus`:

```yaml
- name: Развертывание полного стека мониторинга
  hosts: monitoring
  become: yes
  vars:
    prometheus_version: "3.13.2"
    alertmanager_version: "0.33.1"
    node_exporter_version: "1.12.1"
    pushgateway_version: "1.11.3"
  roles:
    - role: prometheus.prometheus.prometheus
      vars:
        prometheus_storage_tsdb_path: "/var/lib/prometheus"
        prometheus_config_file: "/etc/prometheus/prometheus.yml"
    - role: prometheus.prometheus.node_exporter
    - role: prometheus.prometheus.alertmanager
    - role: prometheus.prometheus.pushgateway
```

**Преимущества Ansible:**
*   Идемпотентность — повторный запуск не ломает рабочую конфигурацию.
*   Управление версиями — фиксация конкретных релизов.
*   Интеграция с Vault для секретов (пароли, TLS-ключи).
*   Единый плейбук для всей инфраструктуры.

### Развертывание в Kubernetes

В Kubernetes-кластерах стандартом является использование Helm-чарта `kube-prometheus-stack`, который автоматизирует управление всем стеком через оператора.

Подробные инструкции и сценарии: **[Установка через Helm (kube-prometheus-stack)](../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/online_installation.md)**.

> **См. также:** **[Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md)**.

### Установка на Windows

Для мониторинга Windows-хостов обычно используется `windows_exporter`. Сам сервер Prometheus может быть запущен как сервис:
1.  **Бинарный файл**: Скачивание `.exe` с официального сайта.
2.  **Chocolatey**: `choco install prometheus`.
3.  **Scoop**: `scoop install prometheus`.

Для production используйте WSL2 с systemd или отдельную Linux-ВМ.

### Обновление и откат

#### Бинарные файлы

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

#### APT

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

#### Docker

```bash
# Обновление образа
docker stop prometheus && docker rm prometheus
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml:ro \
  -v prometheus_data:/prometheus \
  prom/prometheus:v3.13.3 \
  ...

# Или через Compose
docker compose up -d --force-recreate prometheus
```

### Закрытый контур (Air-gapped) — бинарные файлы и APT

Для сред без доступа к интернету подготовьте все артефакты на машине с выходом в сеть.

**Бинарные файлы:**
```bash
# На машине с интернетом
PROMETHEUS_VERSION="3.13.2"
mkdir -p prometheus-offline && cd prometheus-offline
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/sha256sums.txt
wget https://github.com/prometheus/node_exporter/releases/download/v1.12.1/node_exporter-1.12.1.linux-amd64.tar.gz
wget https://github.com/prometheus/alertmanager/releases/download/v0.33.1/alertmanager-0.33.1.linux-amd64.tar.gz
wget https://github.com/prometheus/pushgateway/releases/download/v1.11.3/pushgateway-1.11.3.linux-amd64.tar.gz

# Верификация
sha256sum --check --ignore-missing sha256sums.txt

# Перенос на изолированный хост через USB/SCP
```

**APT (Debian/Ubuntu):**
```bash
# На машине с интернетом
aptly repository create prometheus-local
aptly package import prometheus-local prometheus_*.deb
aptly snapshot create prometheus-snapshot from repo prometheus-local
aptly publish snapshot prometheus-snapshot

# Экспорт репозитория на USB/NFS
# На изолированном хосте: добавление локального репозитория
sudo tee /etc/apt/sources.list.d/prometheus-local.list <<EOF
deb [trusted=yes] file:/mnt/prometheus-local prometheus-local main
EOF
sudo apt update && sudo apt install -y prometheus
```

### Проверка конфигурации

Всегда проверяйте синтаксис файлов конфигурации перед перезапуском:

*   **Prometheus**: `promtool check config /etc/prometheus/prometheus.yml`
*   **Alertmanager**: `amtool check-config /etc/alertmanager/alertmanager.yml`

Подробнее: **[promtool и лучшие практики](../promtool_and_best_practices.md)**.

### Безопасность после установки (Post-install Hardening)

После базовой установки выполните следующие действия:

1.  **Валидация unit-файла:** Убедитесь, что systemd-юнит содержит hardening-директивы (`NoNewPrivileges`, `ProtectSystem`, `ProtectHome`, `PrivateTmp`).
2.  **Ограничение слушаемого интерфейса:** Используйте `--web.listen-address=127.0.0.1:9090` и reverse proxy (Nginx/Caddy) для внешнего доступа.
3.  **Настройка TLS и Basic Auth:** Создайте `web-config.yml` с TLS-сертификатами и bcrypt-хешами паролей. Никогда не используйте Basic Auth без TLS.
4.  **Ограничение ресурсов PromQL:** Добавьте флаги `--query.max-concurrency=20`, `--query.max-samples=50000000`, `--query.timeout=2m`.
5.  **Сетевая сегментация:** Разрешите inbound на порт 9090 только из доверенных подсетей (Grafana, jump-hosts, Prometheus-серверы).
6.  **GOMEMLIMIT:** В контейнеризированных средах установите `GOMEMLIMIT` на 10–20% ниже `limits.memory`.
7.  **Ротация секретов:** Планируйте регулярную ротацию сертификатов (каждые 90 дней) и паролей.

Полное руководство: **[Безопасность Prometheus](../security.md)**.

### Установка на Windows

Для мониторинга Windows-хостов обычно используется `windows_exporter`, но сам сервер Prometheus также может быть запущен как сервис:
1.  **Бинарный файл**: Скачивание `.exe` с официального сайта.
2.  **Chocolatey**: `choco install prometheus`.
3.  **Scoop**: `scoop install prometheus`.

Для production используйте WSL2 с systemd или отдельную Linux-ВМ.

### См. также
*   **[Конфигурация prometheus.yml](../configuration.md)**
*   **[Безопасность Prometheus](../security.md)**
*   **[Масштабирование и Remote Write](../scaling/overview.md)**
*   **[HA Setup: практическое развертывание](./ha_setup.md)** — два Prometheus + кластер Alertmanager.
*   **[Nginx Reverse Proxy](./nginx_reverse_proxy.md)** — TLS termination, Basic Auth, rate limiting.
*   **[Capacity Planning](./capacity_planning.md)** — формулы расчёта CPU/RAM/Disk.
*   **[Alert Rules: практические примеры](./alert_rules_quickstart.md)** — типовые алерты для продакшена.
