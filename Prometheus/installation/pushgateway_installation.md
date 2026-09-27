# Установка Pushgateway

## Определения

**Pushgateway** — промежуточный сервис-посредник в экосистеме Prometheus, предназначенный для сбора метрик от кратковременных (ephemeral) или пакетных (batch) задач. Он служит буфером, позволяя задачам отправлять свои метрики («push»), которые затем Prometheus собирает по стандартной pull-модели.

*   **Порт по умолчанию**: `9091`.
*   **Режим работы**: Пассивное хранилище метрик в оперативной памяти с опциональным сбросом на диск для обеспечения персистентности.
*   **Актуальная версия**: `v1.11.3` (на момент написания).

> **Примечание:** Подробное описание архитектуры, принципов работы, Grouping Key, нативных гистограмм, UTF-8 имён меток, HTTP API управления и антипаттернов приведено в документе **[Pushgateway: общая информация](../pushgateway.md)**.

## Предварительные требования

| Компонент | Минимальная версия / Требование | Проверка |
|:---|:---|:---|
| **ОС** | Linux 2.6.32+ (x86_64, arm64) | `uname -r` |
| **Память** | 128 MiB RAM (рекомендуется 256 MiB) | `free -h` |
| **Диск** | 100 MiB для бинарных файлов + объем для persistence | `df -h /var/lib/pushgateway` |
| **curl** | Любая версия с поддержкой HTTP POST/PUT | `curl --version` |
| **systemd** | v219+ (для unit-файлов) | `systemctl --version` |
| **Docker/Podman** | 20.10+ (для контейнеризации) | `docker --version` |
| **Helm** | v3.8+ (для Kubernetes) | `helm version` |

## Основные концепции

### Сценарии использования

1.  **Краткоживущие задачи**: Процесс завершается быстрее, чем стандартный интервал сбора Prometheus (scrape interval).
2.  **Сетевая изоляция**: Задача находится за NAT или Firewall и не может принимать входящие TCP-соединения от сервера мониторинга.
3.  **Скрипты автоматизации**: Сбор результатов выполнения cron-задач или CI/CD пайплайнов.

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

По умолчанию Pushgateway **не имеет встроенных механизмов защиты**. Любой пользователь с сетевым доступом может изменять или удалить метрики. Для промышленной эксплуатации (Production) необходимо:
*   **Встроенная защита**: Использование флага `--web.config.file` для настройки TLS и Basic Auth.
*   **Внешний прокси**: Развертывание Nginx или Angie перед Pushgateway для обработки HTTPS и авторизации.
*   **Сетевые политики**: Ограничение доступа к порту `9091` только для доверенных IP (отправителей метрик и сервера Prometheus).

Подробнее о рисках, антипаттернах и рекомендациях: **[Pushgateway: общая информация](../pushgateway.md)**.

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (Linux/systemd)

Рекомендуемый метод для выделенных серверов или виртуальных машин.

**1. Подготовка системного окружения:**
```bash
# Создание изолированного пользователя без прав входа
sudo useradd --no-create-home --shell /bin/false pushgateway

# Создание директории для хранения данных
sudo mkdir -p /var/lib/pushgateway
sudo chown pushgateway:pushgateway /var/lib/pushgateway
# → Directory created and permissions set
```

**2. Загрузка и верификация (v1.11.3):**
```bash
PUSHGATEWAY_VERSION="1.11.3"
cd /tmp

# Загрузка архива и файла контрольных сумм
wget https://github.com/prometheus/pushgateway/releases/download/v${PUSHGATEWAY_VERSION}/pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64.tar.gz
wget https://github.com/prometheus/pushgateway/releases/download/v${PUSHGATEWAY_VERSION}/sha256sums.txt

# Проверка целостности загруженного файла
sha256sum --check --ignore-missing sha256sums.txt
# → pushgateway-1.11.3.linux-amd64.tar.gz: OK
```

**3. Размещение исполняемых файлов:**
```bash
tar xvfz pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64.tar.gz
sudo mv pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64/pushgateway /usr/local/bin/
sudo chown pushgateway:pushgateway /usr/local/bin/pushgateway
# → pushgateway binary moved to /usr/local/bin/
```

**4. Настройка unit-файла systemd (`/etc/systemd/system/pushgateway.service`):**
```ini
[Unit]
Description=Prometheus Pushgateway
Documentation=https://github.com/prometheus/pushgateway
After=network-online.target

[Service]
User=pushgateway
Group=pushgateway
Type=simple
ExecStart=/usr/local/bin/pushgateway \
    --persistence.file=/var/lib/pushgateway/metrics.store \
    --persistence.interval=5m \
    --push.enable-utf8-names \
    --web.listen-address=:9091
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
sudo systemctl enable --now pushgateway
# Проверка статуса
systemctl is-active pushgateway
# → active
```

**6. Валидация установки:**
```bash
# Проверка версии
pushgateway --version
# → pushgateway, version 1.11.3 ...

# Проверка доступности эндпоинта
curl -s http://localhost:9091/metrics | head -n 5
# → # HELP pushgateway_build_info Build information

# Проверка systemd-юнита
systemctl status pushgateway
# → Active: active (running) ...
```

### Сценарий 2: Запуск в Docker или Podman

Подходит для сред контейнеризации.

**1. Docker (рекомендуется для production):**
```bash
docker run -d \
  --name pushgateway \
  -p 9091:9091 \
  -v pushgateway_data:/data \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  prom/pushgateway:v1.11.3 \
  --persistence.file=/data/metrics.store \
  --push.enable-utf8-names
# → Container started with ID ...
```

**2. Docker Compose (для полного стека):**
```yaml
version: "3.8"
services:
  pushgateway:
    image: prom/pushgateway:v1.11.3
    container_name: pushgateway
    ports:
      - "9091:9091"
    volumes:
      - pushgateway_data:/data
    command:
      - --persistence.file=/data/metrics.store
      - --persistence.interval=5m
      - --push.enable-utf8-names
    read_only: true
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges
    restart: unless-stopped

volumes:
  pushgateway_data:
```

**3. Podman Quadlet (для systemd-интеграции):**
```ini
# /etc/containers/systemd/pushgateway.container
[Unit]
Description=Prometheus Pushgateway

[Container]
Image=docker.io/prom/pushgateway:v1.11.3
Name=pushgateway
Volume=pushgateway_data:/data:Z
Exec=--persistence.file=/data/metrics.store --persistence.interval=5m --push.enable-utf8-names
Port=9091:9091
ReadOnly=true
NoNewPrivileges=true
CapDrop=ALL

[Install]
WantedBy=multi-user.target default.target
```

```bash
# Развертывание через systemd
systemctl daemon-reload
systemctl enable --now pushgateway-container.service
```

**4. Валидация:**
```bash
# Docker
docker ps --filter name=pushgateway
# → CONTAINER ID   IMAGE                          COMMAND ...

curl -s http://localhost:9091/metrics | head -n 3
# → # HELP pushgateway_build_info Build information

# Podman
podman ps --filter name=pushgateway
# → CONTAINER ID   IMAGE                          COMMAND ...
```

### Сценарий 3: Установка в Kubernetes через Helm

**В составе kube-prometheus-stack:**
Редактируйте `values.yaml`:
```yaml
pushgateway:
  enabled: true
  ingress:
    enabled: true
    hosts:
      - pushgateway.cluster.local
  persistentVolume:
    enabled: true
    size: 2Gi
```

Полный список параметров Push Gateway в Helm-чарте: **[Конфигурация прочих компонентов kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/other_components_config.md)**.

**Standalone установка:**
```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка
helm install pushgateway prometheus-community/prometheus-pushgateway \
  --namespace monitoring --create-namespace \
  --set pushgateway.persistence.enabled=true \
  --set pushgateway.persistence.size=2Gi
# → NAME: pushgateway deployed
```

**Валидация и проверка:**
```bash
# Проверка статуса подов
kubectl get pods -n monitoring -l app=pushgateway
# → NAME                          READY   STATUS    RESTARTS   AGE
# → pushgateway-xxxxxx            1/1     Running   0          2m

# Проверка Service и Endpoints
kubectl get svc,endpoints -n monitoring -l app=pushgateway
# → NAME                    ENDPOINTS          AGE
# → pushgateway             10.244.0.5:9091    2m

# Проверка доступности из кластера
kubectl run curl-pod --image=curlimages/curl:latest --rm -it --restart=Never -- \
  curl -s http://pushgateway.monitoring.svc:9091/metrics | head -n 3
# → # HELP pushgateway_build_info Build information
```

### Сценарий 4: Настройка Native TLS и Basic Auth

Использование встроенных механизмов защиты без внешнего прокси.

**1. Генерация bcrypt-хеша пароля:**
```bash
# Установка htpasswd (apache2-utils)
sudo apt install -y apache2-utils

# Генерация хеша для пользователя admin
htpasswd -nB admin
# → New password: ...
# → Re-type new password: ...
# → admin:$2y$12$LQvPHiM/N.S.B.bcrypt.hash.here
```

**2. Создание web-config.yml:**
```yaml
tls_server_config:
  cert_file: /etc/pushgateway/certs/server.crt
  key_file: /etc/pushgateway/certs/server.key

basic_auth_users:
  admin: "$2y$12$LQvPHiM/N.S.B.bcrypt.hash.here"
```

**3. Добавьте флаг `--web.config.file=/etc/pushgateway/web-config.yml` в параметры запуска.**

**4. Валидация:**
```bash
# Проверка с Basic Auth
curl -u admin:password https://localhost:9091/metrics
# → # HELP pushgateway_build_info Build information

# Проверка без авторизации (должен вернуть 401)
curl -s -o /dev/null -w "%{http_code}" https://localhost:9091/metrics
# → 401
```

### Сценарий 5: Air-gapped установка

Для изолированных сред без доступа к интернету подготовьте все артефакты на машине с выходом в сеть.

**Бинарные файлы:**
```bash
# На машине с интернетом
PUSHGATEWAY_VERSION="1.11.3"
mkdir -p pushgateway-offline && cd pushgateway-offline

# Загрузка архива и контрольных сумм
wget https://github.com/prometheus/pushgateway/releases/download/v${PUSHGATEWAY_VERSION}/pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64.tar.gz
wget https://github.com/prometheus/pushgateway/releases/download/v${PUSHGATEWAY_VERSION}/sha256sums.txt

# Верификация
sha256sum --check --ignore-missing sha256sums.txt
# → pushgateway-1.11.3.linux-amd64.tar.gz: OK

# Перенос на изолированный хост через USB/SCP
scp pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64.tar.gz user@isolated-host:/tmp/
```

**На изолированном хосте:**
```bash
tar xvfz pushgateway-*.linux-amd64.tar.gz
sudo mv pushgateway-*/pushgateway /usr/local/bin/
# Продолжите стандартную установку из Сценария 1
```

**Docker/Podman:**
```bash
# На машине с интернетом: сохранение образа
docker pull prom/pushgateway:v1.11.3
docker save prom/pushgateway:v1.11.3 -o pushgateway-v1.11.3.tar

# Перенос и загрузка на изолированном хосте
docker load -i pushgateway-v1.11.3.tar
```

## Дополнительная информация

### Валидация установки

После установки выполните проверку работоспособности:

| Метод | Команда проверки | Ожидаемый результат |
|:---|:---|:---|
| **Binary/systemd** | `systemctl is-active pushgateway` | `active` |
| **Docker** | `docker ps --filter name=pushgateway` | `Status: Up ...` |
| **Kubernetes** | `kubectl get pods -n monitoring -l app=pushgateway` | `1/1 Running` |
| **HTTP API** | `curl -s http://localhost:9091/metrics` | `# HELP pushgateway_build_info` |

### Управление данными (Резервное копирование и восстановление)

**Резервное копирование:**
```bash
# Экспорт метрик (все группы)
curl -s http://localhost:9091/metrics > pushgateway-backup-$(date +%Y%m%d).txt

# Экспорт файла персистентности
sudo cp /var/lib/pushgateway/metrics.store /var/lib/pushgateway/metrics.store.bak
```

**Восстановление:**
```bash
# Остановка сервиса
sudo systemctl stop pushgateway

# Восстановление файла
sudo cp /var/lib/pushgateway/metrics.store.bak /var/lib/pushgateway/metrics.store

# Запуск
sudo systemctl start pushgateway
```

**Очистка всех данных:**
```bash
# Внимание: удаляет все метрики!
curl -X PUT http://localhost:9091/-/wipe
```

### Удаление и очистка

**Binary/systemd:**
```bash
sudo systemctl stop pushgateway
sudo systemctl disable --now pushgateway
sudo rm /etc/systemd/system/pushgateway.service
sudo rm /usr/local/bin/pushgateway
sudo rm -rf /var/lib/pushgateway
sudo systemctl daemon-reload
```

**Docker:**
```bash
docker stop pushgateway && docker rm pushgateway
docker volume rm pushgateway_data
```

**Kubernetes (standalone):**
```bash
helm uninstall pushgateway -n monitoring
kubectl delete namespace monitoring
```

### Важные параметры сбора (Scrape Config)

Для корректного сбора данных в `prometheus.yml` **обязательно** используйте параметр `honor_labels: true`. Без него Prometheus заменит исходные метки задач своими собственными (например, установит `job="pushgateway"` для всех метрик), что сделает невозможной их идентификацию.

Подробное объяснение механизма и ограничений: **[Pushgateway: общая информация](../pushgateway.md)**.

```yaml
scrape_configs:
  - job_name: 'pushgateway'
    honor_labels: true
    static_configs:
      - targets: ['pushgateway-host:9091']
```

### Устранение неисправностей и диагностика

| Симптом | Причина | Решение |
|:---|:---|:---|
| Метки `job` затираются | `honor_labels: false` | Проверьте конфиг Prometheus. |
| Ошибка 400 при отправке | Недопустимые имена меток | Используйте флаг `--push.enable-utf8-names`. |
| Данные исчезают после рестарта | Нет флага `--persistence.file` | Укажите путь к файлу хранения в параметрах запуска. |
| Память переполнена | Накопление старых метрик | Реализуйте удаление метрик через `DELETE` запрос после завершения задачи. |
| `Connection refused` на 9091 | Сервис не запущен | `systemctl status pushgateway` / `docker ps` / `kubectl get pods` |
| `ImagePullBackOff` (K8s) | Образ не найден в реестре | Проверьте `imagePullSecrets` и доступность Harbor/Registry |
| Метрики дублируются | Неправильный Grouping Key | Убедитесь, что `job` и дополнительные метки уникальны для каждой задачи |

### См. также

*   **[Pushgateway: руководство по использованию](../pushgateway.md)** — принципы работы, API и ограничения.
*   **[Установка Prometheus: обзор](./overview.md)** — сравнение методов развертывания экосистемы.
*   **[Безопасность Prometheus](../security.md)** — общие принципы защиты инфраструктуры.
*   **[Установка через APT](./with_apt.md)** — установка `prometheus-pushgateway` через пакетный менеджер.
*   **[Nginx Reverse Proxy](./nginx_reverse_proxy.md)** — TLS termination и rate limiting перед Pushgateway.
