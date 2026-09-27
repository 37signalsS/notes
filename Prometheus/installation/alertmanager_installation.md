# Установка Alertmanager

## Определения

**Alertmanager** — центральный компонент экосистемы Prometheus, отвечающий за обработку, агрегацию и доставку оповещений. Основные функции: дедупликация (удаление дублей от HA-пар Prometheus), группировка алертов и маршрутизация уведомлений (Email, Slack, Telegram, Webhook, PagerDuty).

*   **amtool** — официальная CLI-утилита для взаимодействия с API Alertmanager, проверки конфигурации и управления «тишиной» (silences).
*   **Gossip-протокол** — механизм обмена состоянием между узлами кластера для синхронизации данных о доставленных уведомлениях и созданных паузах.
*   **AlertmanagerConfig (CRD)** — ресурс Kubernetes, позволяющий декларативно управлять маршрутизацией и получателями алертов без изменения основного `alertmanager.yml`.

> **Примечание:** Подробное описание архитектуры, конвейера обработки, маршрутизации, inhibition, silencing и параметров конфигурации приведено в документе **[Alertmanager — управление оповещениями](../alertmanager.md)**.

## Предварительные требования

| Компонент | Минимальная версия / Требование | Проверка |
|:---|:---|:---|
| **ОС** | Linux 2.6.32+ (x86_64, arm64) | `uname -r` |
| **Память** | 128 MiB RAM (рекомендуется 256 MiB для production) | `free -h` |
| **Диск** | 100 MiB для бинарных файлов + объем для persistence | `df -h /var/lib/alertmanager` |
| **curl** | Любая версия с поддержкой HTTP POST/PUT | `curl --version` |
| **systemd** | v219+ (для unit-файлов) | `systemctl --version` |
| **Docker/Podman** | 20.10+ (для контейнеризации) | `docker --version` |
| **Helm** | v3.8+ (для Kubernetes) | `helm version` |
| **Kubernetes** | >= 1.28 (для kube-prometheus-stack) | `kubectl version --short` |
| **Prometheus Operator** | >= v0.57.0 (для AlertmanagerConfig CRD) | `kubectl get pods -n monitoring -l app=prometheus-operator` |

## Основные концепции

### Сценарии использования

1.  **Production bare-metal/VM**: Выделенные серверы с требованием максимального контроля над версиями и hardening.
2.  **Контейнеризированные среды**: Docker/Podman для быстрого старта и изоляции.
3.  **Kubernetes / GitOps**: Управление через Helm-чарт `kube-prometheus-stack` с поддержкой AlertmanagerConfig CRD.
4.  **Парк серверов (IaC)**: Автоматизация через Ansible для массового развертывания.
5.  **Изолированные среды (Air-gapped)**: Среды без доступа к интернету, требующие предварительной подготовки артефактов.

### Сравнение методов установки

| Метод | Уровень контроля | Сложность | Когда использовать |
|:---|:---|:---|:---|
| **Бинарные файлы + systemd** | Максимальный | Средняя | Production bare-metal/VM, требование hardening |
| **Docker / Podman** | Высокий | Низкая | Контейнеризированные среды, быстрый старт |
| **APT (Debian/Ubuntu)** | Средний | Низкая | Стандартные серверы Debian/Ubuntu |
| **Helm (Kubernetes)** | Высокий | Средняя | Kubernetes, GitOps, kube-prometheus-stack |
| **Ansible** | Высокий | Средняя | Парк серверов, IaC |

> **Рекомендация:** Для Production bare-metal/VM используйте бинарные файлы — максимальный контроль над версиями и hardening. Для Kubernetes используйте Helm-чарт `kube-prometheus-stack`. Для быстрого старта в контейнерах — Docker/Podman. Подробно: **[Установка Prometheus: обзор](./overview.md)**.

### Безопасность

По умолчанию Alertmanager **не имеет встроенных механизмов защиты**. Любой пользователь с сетевым доступом может изменять или удалять метрики. Для промышленной эксплуатации (Production) необходимо:
*   **Встроенная защита**: Использование флага `--web.config.file` для настройки TLS и Basic Auth.
*   **Внешний прокси**: Развертывание Nginx или Caddy перед Alertmanager для обработки HTTPS и авторизации.
*   **Сетевые политики**: Ограничение доступа к порту `9093` только для доверенных IP (Prometheus, Grafana) и порту `9094` только между репликами кластера.
*   **mTLS для Gossip**: Шифрование межузлового трафика в HA-кластере (Cluster TLS, доступно с v0.24+).

Подробнее о рисках, антипаттернах и рекомендациях: **[Alertmanager — управление оповещениями](../alertmanager.md)**.

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (Linux/systemd)

Рекомендуемый метод для выделенных серверов или виртуальных машин.

**1. Подготовка системного окружения:**
```bash
# Создание изолированного пользователя без прав входа
sudo useradd --no-create-home --shell /bin/false alertmanager

# Создание директорий для конфигурации и данных
sudo mkdir -p /etc/alertmanager /var/lib/alertmanager
sudo chown alertmanager:alertmanager /etc/alertmanager /var/lib/alertmanager
# → Directories created with correct ownership
```

**2. Загрузка и верификация (v0.33.1):**
```bash
VERSION="0.33.1"
cd /tmp

# Загрузка архива и файла контрольных сумм
wget https://github.com/prometheus/alertmanager/releases/download/v${VERSION}/alertmanager-${VERSION}.linux-amd64.tar.gz
wget https://github.com/prometheus/alertmanager/releases/download/v${VERSION}/sha256sums.txt

# Проверка целостности загруженного файла
sha256sum --check --ignore-missing sha256sums.txt
# → alertmanager-0.33.1.linux-amd64.tar.gz: OK
```

**3. Размещение исполняемых файлов:**
```bash
tar xvfz alertmanager-${VERSION}.linux-amd64.tar.gz
sudo mv alertmanager-${VERSION}.linux-amd64/alertmanager /usr/local/bin/
sudo mv alertmanager-${VERSION}.linux-amd64/amtool /usr/local/bin/
sudo chown alertmanager:alertmanager /usr/local/bin/alertmanager /usr/local/bin/amtool
# → alertmanager and amtool installed to /usr/local/bin/
```

**4. Настройка unit-файла systemd (`/etc/systemd/system/alertmanager.service`):**
```ini
[Unit]
Description=Prometheus Alertmanager
Documentation=https://prometheus.io/docs/alerting/latest/alertmanager/
After=network-online.target

[Service]
User=alertmanager
Group=alertmanager
Type=simple
ExecStart=/usr/local/bin/alertmanager \
    --config.file=/etc/alertmanager/alertmanager.yml \
    --storage.path=/var/lib/alertmanager/ \
    --web.listen-address=:9093 \
    --cluster.listen-address=:9094
Restart=always
# Hardening (Безопасность процесса)
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**5. Активация и запуск сервиса:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now alertmanager
# Проверка статуса
systemctl is-active alertmanager
# → active
```

**6. Валидация установки:**
```bash
# Проверка версии
alertmanager --version
# → alertmanager, version 0.33.1 ...

# Проверка доступности эндпоинта
curl -s http://localhost:9093/-/healthy
# → OK

# Проверка кластерного статуса (если HA)
amtool cluster show --alertmanager.url=http://localhost:9093
# → CLUSTERADDR  PEERADDR  STATE ...
```

### Сценарий 2: Запуск в Docker или Podman

Подходит для сред контейнеризации.

**1. Docker (рекомендуется для production):**
```bash
docker run -d \
  --name alertmanager \
  -p 9093:9093 \
  -p 9094:9094 \
  -v alertmanager_data:/alertmanager \
  -v /etc/alertmanager:/etc/alertmanager:ro \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  prom/alertmanager:v0.33.1 \
  --config.file=/etc/alertmanager/alertmanager.yml \
  --storage.path=/alertmanager \
  --web.listen-address=:9093 \
  --cluster.listen-address=:9094
# → Container started with ID ...
```

**2. Docker Compose (для полного стека):**
```yaml
version: "3.8"
services:
  alertmanager:
    image: prom/alertmanager:v0.33.1
    container_name: alertmanager
    ports:
      - "9093:9093"
      - "9094:9094"
    volumes:
      - alertmanager_data:/alertmanager
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
    command:
      - --config.file=/etc/alertmanager/alertmanager.yml
      - --storage.path=/alertmanager
      - --web.listen-address=:9093
      - --cluster.listen-address=:9094
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges
    restart: unless-stopped

volumes:
  alertmanager_data:
```

**3. Podman Quadlet (для systemd-интеграции):**
```ini
# /etc/containers/systemd/alertmanager.container
[Unit]
Description=Prometheus Alertmanager

[Container]
Image=docker.io/prom/alertmanager:v0.33.1
Name=alertmanager
Volume=alertmanager_data:/alertmanager:Z
Exec=--config.file=/etc/alertmanager/alertmanager.yml --storage.path=/alertmanager --web.listen-address=:9093 --cluster.listen-address=:9094
Port=9093:9093
Port=9094:9094
ReadOnly=true
NoNewPrivileges=true
CapDrop=ALL

[Install]
WantedBy=multi-user.target default.target
```

```bash
# Развертывание через systemd
systemctl daemon-reload
systemctl enable --now alertmanager-container.service
```

**4. Валидация:**
```bash
# Docker
docker ps --filter name=alertmanager
# → CONTAINER ID   IMAGE                          COMMAND ...

curl -s http://localhost:9093/-/healthy
# → OK

# Podman
podman ps --filter name=alertmanager
# → CONTAINER ID   IMAGE                          COMMAND ...
```

### Сценарий 3: Установка через APT (Debian/Ubuntu)

Стандартный метод для серверов Debian/Ubuntu с автоматическими обновлениями.

```bash
# Добавление официального репозитория Prometheus
sudo tee /etc/apt/sources.list.d/prometheus.list <<EOF
deb https://packagecloud.io/prometheus-rpm/release/debian/ $(lsb_release -cs) main
EOF

# Импорт GPG-ключа
curl -sL https://packagecloud.io/prometheus-rpm/release/gpgkey | sudo apt-key add -

# Установка
sudo apt update && sudo apt install -y alertmanager amtool

# Проверка статуса
systemctl status alertmanager
# → Active: active (running) ...
```

**Валидация:**
```bash
# Проверка версии
amtool --version
# → amtool, version 0.33.1 ...

# Проверка доступности
curl -s http://localhost:9093/-/healthy
# → OK
```

### Сценарий 4: Установка в Kubernetes через Helm

**В составе kube-prometheus-stack:**
Редактируйте `values.yaml`:
```yaml
alertmanager:
  enabled: true
  alertmanagerSpec:
    replicas: 3
    storage:
      volumeClaimTemplate:
        spec:
          storageClassName: "fast-ssd"
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 10Gi
    alertmanagerConfigSelector:
      matchLabels:
        alertmanagerConfig: "enabled"
  config:
    global:
      resolve_timeout: 5m
      smtp_from: 'alertmanager@example.com'
    route:
      group_by: ['alertname', 'cluster', 'service']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 12h
      receiver: 'default-receiver'
    receivers:
      - name: 'default-receiver'
        email_configs:
          - to: 'ops@example.com'
        slack_configs:
          - channel: '#monitoring-alerts'
        webhook_configs:
          - url: 'http://notification-service:8080/alerts'
```

Полный список параметров Alertmanager в Helm-чарте: **[Конфигурация Alertmanager в kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/alertmanager_config.md)**.

**Standalone установка:**
```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка
helm install alertmanager prometheus-community/prometheus-alertmanager \
  --namespace monitoring --create-namespace \
  --set alertmanager.alertmanagerSpec.replicas=3 \
  --set alertmanager.alertmanagerSpec.storage.volumeClaimTemplate.spec.resources.requests.storage=10Gi \
  --set alertmanager.config.global.smtp_from='alertmanager@example.com'
# → NAME: alertmanager deployed
```

**Валидация и проверка:**
```bash
# Проверка статуса подов
kubectl get pods -n monitoring -l app.kubernetes.io/name=alertmanager
# → NAME                                          READY   STATUS    RESTARTS   AGE
# → alertmanager-prometheus-alertmanager-0       2/2     Running   0          2m

# Проверка Service и Endpoints
kubectl get svc,endpoints -n monitoring -l app.kubernetes.io/name=alertmanager
# → NAME                    ENDPOINTS          AGE
# → alertmanager-prometheus-alertmanager  10.244.0.5:9093    2m

# Проверка доступности из кластера
kubectl run curl-pod --image=curlimages/curl:latest --rm -it --restart=Never -- \
  curl -s http://alertmanager.monitoring.svc:9093/-/healthy
# → OK
```

### Сценарий 5: Автоматизация через Ansible

Для массового развертывания используйте коллекцию `prometheus.prometheus`:

```yaml
- hosts: monitoring
  become: yes
  vars:
    alertmanager_version: "0.33.1"
  roles:
    - role: prometheus.prometheus.alertmanager
```

Переменные для управления:
```yaml
alertmanager_version: "0.33.1"
alertmanager_config_file: "/etc/alertmanager/alertmanager.yml"
alertmanager_storage_path: "/var/lib/alertmanager/"
alertmanager_web_listen_address: ":9093"
```

Роль автоматически создаёт пользователя, настраивает systemd unit с hardening и проверяет целостность загруженных файлов.

### Сценарий 6: Air-gapped установка

Для изолированных сред без доступа к интернету подготовьте все артефакты на машине с выходом в сеть.

**Бинарные файлы:**
```bash
# На машине с интернетом
ALERTMANAGER_VERSION="0.33.1"
mkdir -p alertmanager-offline && cd alertmanager-offline

# Загрузка архива и контрольных сумм
wget https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
wget https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/sha256sums.txt

# Верификация
sha256sum --check --ignore-missing sha256sums.txt
# → alertmanager-0.33.1.linux-amd64.tar.gz: OK

# Перенос на изолированный хост через USB/SCP
scp alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz user@isolated-host:/tmp/
```

**На изолированном хосте:**
```bash
tar xvfz alertmanager-*.linux-amd64.tar.gz
sudo mv alertmanager-*/alertmanager /usr/local/bin/
sudo mv alertmanager-*/amtool /usr/local/bin/
# Продолжите стандартную установку из Сценария 1
```

**Docker/Podman:**
```bash
# На машине с интернетом: сохранение образа
docker pull prom/alertmanager:v0.33.1
docker save prom/alertmanager:v0.33.1 -o alertmanager-v0.33.1.tar

# Перенос и загрузка на изолированном хосте
docker load -i alertmanager-v0.33.1.tar
```

**Helm charts (Kubernetes):**
```bash
# На машине с интернетом: загрузка чарта и зависимостей
helm pull prometheus-community/kube-prometheus-stack --destination ./charts
helm pull prometheus-community/prometheus-alertmanager --destination ./charts

# Перенос на изолированный хост
helm install alertmanager ./charts/prometheus-alertmanager-*.tgz \
  --namespace monitoring --create-namespace
```

## Дополнительная информация

### Валидация установки

После установки выполните проверку работоспособности:

| Метод | Команда проверки | Ожидаемый результат |
|:---|:---|:---|
| **Binary/systemd** | `systemctl is-active alertmanager` | `active` |
| **Docker** | `docker ps --filter name=alertmanager` | `Status: Up ...` |
| **Kubernetes** | `kubectl get pods -n monitoring -l app.kubernetes.io/name=alertmanager` | `2/2 Running` |
| **HTTP API** | `curl -s http://localhost:9093/-/healthy` | `OK` |
| **Config** | `amtool check-config /etc/alertmanager/alertmanager.yml` | `SUCCESS` |
| **Cluster** | `amtool cluster show --alertmanager.url=http://localhost:9093` | Список пиров |

### Управление данными (Резервное копирование и восстановление)

**Резервное копирование:**
```bash
# Экспорт конфигурации
sudo cp /etc/alertmanager/alertmanager.yml /etc/alertmanager/alertmanager.yml.bak

# Экспорт состояния силенсов (silences) и данных
curl -s http://localhost:9093/api/v2/silences > alertmanager-silences-$(date +%Y%m%d).json
curl -s http://localhost:9093/metrics > alertmanager-metrics-$(date +%Y%m%d).txt

# Экспорт файла персистентности
sudo cp /var/lib/alertmanager/*.db /var/lib/alertmanager/alertmanager.db.bak
```

**Восстановление:**
```bash
# Остановка сервиса
sudo systemctl stop alertmanager

# Восстановление конфигурации
sudo cp /etc/alertmanager/alertmanager.yml.bak /etc/alertmanager/alertmanager.yml

# Восстановление данных
sudo cp /var/lib/alertmanager/alertmanager.db.bak /var/lib/alertmanager/

# Запуск
sudo systemctl start alertmanager
```

**Очистка всех данных:**
```bash
# Внимание: удаляет все силенсы!
curl -X PUT http://localhost:9093/-/wipe
```

### Удаление и очистка

**Binary/systemd:**
```bash
sudo systemctl stop alertmanager
sudo systemctl disable --now alertmanager
sudo rm /etc/systemd/system/alertmanager.service
sudo rm /usr/local/bin/alertmanager /usr/local/bin/amtool
sudo rm -rf /etc/alertmanager /var/lib/alertmanager
sudo systemctl daemon-reload
```

**Docker:**
```bash
docker stop alertmanager && docker rm alertmanager
docker volume rm alertmanager_data
```

**APT:**
```bash
sudo apt remove --purge alertmanager amtool
sudo rm /etc/apt/sources.list.d/prometheus.list
```

**Kubernetes (standalone):**
```bash
helm uninstall alertmanager -n monitoring
kubectl delete namespace monitoring
```

### Обновление и откат

#### Бинарные файлы

```bash
# 1. Остановка сервиса
sudo systemctl stop alertmanager

# 2. Загрузка и замена бинарных файлов
ALERTMANAGER_VERSION="0.33.2"
wget https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
tar xvfz alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
sudo mv alertmanager-${ALERTMANAGER_VERSION}/alertmanager /usr/local/bin/

# 3. Валидация конфигурации (критично перед запуском)
amtool check-config /etc/alertmanager/alertmanager.yml

# 4. Запуск
sudo systemctl start alertmanager
```

**Откат:** Верните предыдущие бинарные файлы из резервной копии и перезапустите сервис.

#### APT

```bash
# Обновление
sudo apt update && sudo apt upgrade alertmanager

# Проверка версии
alertmanager --version

# Фиксация версии (предотвращение автоматического обновления)
sudo apt-mark hold alertmanager
```

**Откат:**
```bash
sudo apt-mark unhold alertmanager
sudo apt install alertmanager=0.33.1
```

#### Helm (Kubernetes)

```bash
# 1. Создание резервной копии текущих значений
helm get values monitoring -n monitoring > values-backup.yaml
kubectl get servicemonitor,podmonitor,prometheusrule,alertmanagerconfig \
  -n monitoring -o yaml > backup-custom-resources.yaml

# 2. Применение изменений
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f values-backup.yaml \
  -f values.yaml

# 3. Проверка rollout
kubectl rollout status statefulset/alertmanager-monitoring-kube-prometheus-alertmanager -n monitoring --timeout=5m

# 4. В случае проблем — откат
helm rollback monitoring -n monitoring --timeout=5m
```

> **Важно:** Helm не обновляет CRD автоматически при обновлении чарта. При мажорных обновлениях примените CRD вручную. Подробнее: **[Конфигурация Alertmanager в kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/alertmanager_config.md)**.

### Управление через CLI (amtool)

`amtool` позволяет управлять алертами без использования браузера.

**1. Создание конфигурации (`~/.config/amtool/config.yml`):**
```yaml
alertmanager.url: "http://localhost:9093"
output: extended
```

**2. Практические команды:**
```bash
# Проверка синтаксиса конфигурации
amtool check-config /etc/alertmanager/alertmanager.yml
# → SUCCESS

# Просмотр активных алертов
amtool alert
# → [Alertname] [Severity] [Starts At] ...

# Просмотр дерева маршрутизации
amtool config routes show --config.file=/etc/alertmanager/alertmanager.yml

# Создание тишины (Silence) для подавления алертов
amtool silence add alertname=DiskFull --duration=2h --comment="Planned maintenance"
# → Silence ID: 12345-abcde...

# Просмотр активных тишин
amtool silence
# → ID                                   ...  COMMENT ...
```

### Устранение неисправностей и диагностика

| Симптом | Причина | Решение |
|:---|:---|:---|
| Алерты не доставляются | Ошибка в receiver (неверный URL, токен) | Проверьте `alertmanager_notifications_failed_total` и логи. |
| Дублирующиеся уведомления | Неправильная HA-конфигурация | Проверьте `cluster.listen-address` и открытый порт 9094. |
| Пустые алерты в receivers | Отсутствуют аннотации | Добавьте `summary` и `description` в PrometheusRule. |
| Алерты не группируются | Неправильные `group_by` | Убедитесь, что метки существуют в алертах. |
| Потеря силенсов после рестарта | Отсутствует persistence | Настройте `--storage.path` или PVC в Kubernetes. |
| `Connection refused` на 9093 | Сервис не запущен | `systemctl status alertmanager` / `docker ps` / `kubectl get pods` |
| `401 Unauthorized` от Prometheus | Отсутствует `basicAuth` | Добавьте учетные данные в `alerting.alertmanagers`. |
| AlertmanagerConfig не применяется | Пустой `alertmanagerConfigSelector` | Добавьте `matchLabels` в `values.yaml`. |
| Gossip-кластер не образуется | Порт 9094 заблокирован | Откройте порт 9094 между репликами (NetworkPolicy). |

### Рекомендации SRE по алертингу

1.  **Actionable Alerts:** Каждый алерт должен иметь аннотацию `runbook_url`. Если на алерт нельзя отреагировать действием — это не алерт, а шум.
2.  **Symptom-based Alerting:** Алертите на симптомы (ошибки, задержки), а не на причины.
3.  **NoData — это алерт:** Всегда настраивайте алерты на отсутствие данных (`absent()`) от критических систем.
4.  **Дедупликация и группировка:** Группировка по `cluster` или `service` позволяет видеть масштаб проблемы.
5.  **Мета-мониторинг:** Добавьте алерт на `rate(alertmanager_notifications_failed_total[5m]) > 0`.

### См. также

*   **[Alertmanager — управление оповещениями](../alertmanager.md)** — подробное описание логики маршрутизации, inhibition, receivers.
*   **[Установка Prometheus: обзор](./overview.md)** — сравнение методов развертывания всего стека.
*   **[Конфигурация Alertmanager в kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/alertmanager_config.md)** — Helm values, upgrade/rollback, AlertmanagerConfig CRD.
*   **[HA Setup](./ha_setup.md)** — практическое развертывание кластера Alertmanager из 3 узлов.
*   **[Alert Rules](./alert_rules_quickstart.md)** — типовые alerting rules для продакшена.
