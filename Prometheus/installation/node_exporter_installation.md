# Установка Node Exporter

## Определения

**Node Exporter** — официальный агент экосистемы Prometheus для сбора метрик аппаратного обеспечения и параметров ядра операционных систем семейства Linux/Unix.

*   **Порт по умолчанию**: `9100`.
*   **Метод сбора**: Pull-модель (Prometheus опрашивает экспортер).
*   **Collectors (Коллекторы)**: Модули внутри экспортера, отвечающие за сбор конкретных типов данных (CPU, Mem, Disk и т.д.).
*   **Актуальная версия**: `v1.12.1`.
*   **Архитектуры**: amd64, arm64, armv7, ppc64le, s390x.

> **Детальное описание метрик, алертов и параметров фильтрации находится в документе **[Node Exporter — Полное руководство](../Exporters/node_exporter.md)**.

## Предварительные требования

### Аппаратные требования

| Компонент | CPU Request | Memory Request | CPU Limit | Memory Limit |
| :--- | :--- | :--- | :--- | :--- |
| **Node Exporter** | 25m | 32Mi | 150m | 128Mi |

### Программные требования

*   **ОС**: Linux (Debian 12+, Ubuntu 22.04+, RHEL 9+, Rocky Linux 9+), BSD или macOS. Для Linux требуется systemd или cron.
*   **Архитектура**: amd64, arm64, armv7, ppc64le, s390x.
*   **Права доступа**:
    *   Для доступа к метрикам ядра (`diskstats`, `hwmon`, `edac`) рекомендуется запуск от `root`.
    *   При запуске от непривилегированного пользователя добавьте его в группы `disk`, `hwmon`, `adm`.
*   **Файловые системы**: Метрики файловых систем собираются из `/proc/mounts` и `/proc/self/mountinfo`. Для корректной работы в контейнерах требуется монтирование `/proc` и `/sys` хоста.
*   **Сеть**: Порт `9100` должен быть доступен для Prometheus-сервера.
*   **Ресурсы**: Рекомендуемые лимиты — не более 150m CPU и 128Mi RAM на инстанс. При включении тяжелых коллекторов (`zfs`, `nfs`, `nfsd`) может потребоваться увеличение до 300m CPU.

## Основные концепции

### Принцип работы

Node Exporter запускается как фоновый процесс (демон) и читает данные напрямую из виртуальных файловых систем ядра (`/proc` и `/sys`). Он не требует установки дополнительных библиотек или изменения кода приложений.

### Источники данных: procfs и sysfs

Node Exporter не является активным агентом, который опрашивает ядро через системные вызовы. Вместо этого он читает и парсит данные из виртуальных файловых систем Linux, которые ядро обновляет автоматически. Это обеспечивает высокую производительность и минимальный оверхед:

*   **`/proc`**: Статистика запущенных процессов, памяти (`meminfo`), планировщика CPU (`stat`) и аппаратных прерываний (`interrupts`).
*   **`/sys`**: Данные об аппаратных устройствах (диски, сетевые карты), драйверах, `cgroups` и термодатчиках.

### Поддержка cgroup v2

В современных дистрибутивах Linux (Debian 12+, Ubuntu 22.04+, RHEL 9+) Node Exporter полноценно поддерживает **cgroup v2**. Метрики собираются через интерфейсы `/sys/fs/cgroup`. Это критично для корректного мониторинга ресурсов в контейнеризированных средах и системах с `systemd`.

### Управление коллекторами

По умолчанию большинство коллекторов включено. Для оптимизации нагрузки на систему и уменьшения объема хранимых данных (cardinality) их можно фильтровать при запуске:

*   **Включение:** `--collector.<name>`
*   **Отключение:** `--no-collector.<name>`
*   **Фильтрация в Prometheus:** Можно запрашивать только часть метрик через параметр `collect[]` в URL (например, `http://localhost:9100/metrics?collect[]=cpu&collect[]=meminfo`).

### Textfile Collector

Встроенный модуль `node_exporter`, читающий файлы формата `.prom` из локальной директории. Позволяет экспортировать кастомные метрики из bash-скриптов, cron-задач и сторонних утилит без написания отдельного экспортера. Подробнее: **[Textfile Collector](../Exporters/extensibility/textfile_collector.md)**.

### Мониторинг Windows

Для ОС семейства Windows Node Exporter не предназначен. Используйте **[Windows Exporter](https://github.com/prometheus-community/windows_exporter)** или **Grafana Alloy**, которые собирают метрики WMI/Performance Counters.

## Сравнение методов установки

Выбор метода зависит от операционной системы, требований к контролю версий, инфраструктурного контекста и уровня автоматизации.

| Метод | Когда использовать | Уровень контроля | Автоматизация | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **Бинарные файлы** | Production bare-metal/VM, требование точной версии | Максимальный | systemd unit, Ansible | Рекомендуется для production |
| **APT (Debian/Ubuntu)** | Стандартные серверы Debian/Ubuntu, автоматические обновления | Средний | systemd (автоматически) | Удобно для парка Debian-серверов |
| **YUM/DNF (RHEL/CentOS/Rocky)** | Enterprise Linux, соответствие политикам hardening | Средний | systemd (автоматически) | Удобно для enterprise-сред |
| **Docker / Podman** | Изолированные среды, микросервисы, быстрый старт | Высокий | docker-compose, systemd | Требует монтирования системных директорий |
| **Helm (Kubernetes)** | Kubernetes, GitOps | Высокий | Helm, ArgoCD, Flux | Стандарт де-факто для K8s |
| **Ansible** | Парк серверов (IaC), повторяемые конфигурации | Высокий | Полная автоматизация | Рекомендуется для >5 хостов |
| **Air-gapped** | Закрытый контур без интернета | Высокий | Пакетные артефакты | Требует предварительной подготовки |

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (Linux/systemd)

Рекомендуемый метод для обеспечения максимальной производительности и доступа к системным ресурсам.

**1. Загрузка и установка (v1.12.1):**
```bash
VERSION="1.12.1"
wget https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/node_exporter-${VERSION}.linux-amd64.tar.gz
tar xvfz node_exporter-${VERSION}.linux-amd64.tar.gz
sudo mv node_exporter-${VERSION}.linux-amd64/node_exporter /usr/local/bin/
# → node_exporter installed to /usr/local/bin/
```

**1.1 Верификация архива (рекомендуется):**
```bash
wget https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/sha256sums.txt
sha256sum -c sha256sums.txt --ignore-missing
# → node_exporter-1.12.1.linux-amd64.tar.gz: OK
```

**2. Настройка systemd-юнита (`/etc/systemd/system/node_exporter.service`):**
```ini
[Unit]
Description=Prometheus Node Exporter
Documentation=https://github.com/prometheus/node_exporter
After=network.target

[Service]
User=root
ExecStart=/usr/local/bin/node_exporter \
    --web.listen-address=:9100 \
    --collector.textfile.directory=/var/lib/node_exporter/textfile_metrics
Restart=always

# Hardening (Безопасность)
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```
*Примечание: Использование `User=root` необходимо для доступа к некоторым метрикам ядра (например, `diskstats`, `hwmon`).*

**3. Запуск:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
# Проверка статуса
systemctl is-active node_exporter
# → active
```

### Сценарий 2: Развертывание в Docker / Podman

Используется для мониторинга хоста из изолированного контейнера. Требует монтирования системных директорий.

**Docker Compose:**
```yaml
services:
  node-exporter:
    image: prom/node-exporter:v1.12.1
    container_name: node_exporter
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
    network_mode: host
    pid: host
    restart: unless-stopped
```

**Podman Quadlet (systemd-интеграция):**
```ini
# /etc/containers/systemd/node-exporter.container
[Unit]
Description=Node Exporter

[Container]
Image=docker.io/prom/node-exporter:v1.12.1
Volume=/proc:/host/proc:ro
Volume=/sys:/host/sys:ro
Volume=/:/rootfs:ro
Network=host
Pid=host
Exec=--path.procfs=/host/proc --path.sysfs=/host/sys --path.rootfs=/rootfs

[Install]
WantedBy=multi-user.target
```

### Сценарий 3: Установка через APT (Debian/Ubuntu)

Установка из официального репозитория Prometheus.

```bash
# 1. Добавление репозитория
sudo apt update && sudo apt install -y apt-transport-https curl
curl -sL https://prometheus.io/download/apt/prometheus.gpg | sudo apt-key add -
echo "deb https://prometheus.io/download/apt/ main main" | sudo tee /etc/apt/sources.list.d/prometheus.list

# 2. Установка
sudo apt update && sudo apt install -y prometheus-node-exporter

# 3. Проверка
systemctl status prometheus-node-exporter
# → active (running)
```

### Сценарий 4: Установка в Kubernetes

#### Вариант A: DaemonSet (ручной)

Развертывание на каждую ноду кластера через DaemonSet.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
  labels:
    app: node-exporter
spec:
  selector:
    matchLabels:
      app: node-exporter
  template:
    metadata:
      labels:
        app: node-exporter
    spec:
      hostNetwork: true
      hostPID: true
      containers:
        - name: node-exporter
          image: prom/node-exporter:v1.12.1
          args:
            - '--path.procfs=/host/proc'
            - '--path.sysfs=/host/sys'
            - '--path.rootfs=/rootfs'
          ports:
            - containerPort: 9100
              hostPort: 9100
          volumeMounts:
            - name: proc
              mountPath: /host/proc
              readOnly: true
            - name: sys
              mountPath: /host/sys
              readOnly: true
            - name: rootfs
              mountPath: /rootfs
              readOnly: true
      volumes:
        - name: proc
          hostPath:
            path: /proc
        - name: sys
          hostPath:
            path: /sys
        - name: rootfs
          hostPath:
            path: /
```

#### Вариант B: kube-prometheus-stack (Helm)

Рекомендуемый способ для Kubernetes. Node Exporter развертывается как DaemonSet через Helm-чарт.

```bash
# 1. Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/kube-prometheus-stack
helm repo update

# 2. Установка
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  --set nodeExporter.enabled=true

# 3. Проверка
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus-node-exporter
```

### Сценарий 5: Автоматизация через Ansible

Рекомендуемый способ для массового развертывания через коллекцию `prometheus.prometheus`.

```yaml
- hosts: all
  become: yes
  roles:
    - role: prometheus.prometheus.node_exporter
      vars:
        node_exporter_version: "1.12.1"
        node_exporter_enabled_collectors:
          - systemd
          - textfile
        node_exporter_textfile_dir: "/var/lib/node_exporter/textfile_metrics"
```

### Сценарий 6: Air-gapped установка

Установка в закрытом контуре без доступа к интернету.

**Бинарный метод:**
```bash
# 1. На машине с интернетом
VERSION="1.12.1"
wget https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/node_exporter-${VERSION}.linux-amd64.tar.gz
wget https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/sha256sums.txt
sha256sum -c sha256sums.txt --ignore-missing

# 2. Перенос на целевой хост (USB/SCP)
scp node_exporter-${VERSION}.linux-amd64.tar.gz target:/tmp/

# 3. Установка на целевом хосте
tar xvfz node_exporter-${VERSION}.linux-amd64.tar.gz
sudo mv node_exporter-${VERSION}.linux-amd64/node_exporter /usr/local/bin/
```

**Docker/Podman:**
```bash
# На машине с интернетом
docker pull prom/node-exporter:v1.12.1
docker save -o node-exporter.tar prom/node-exporter:v1.12.1

# Перенос и загрузка на целевом хосте
scp node-exporter.tar target:/tmp/
docker load -i /tmp/node-exporter.tar
```

**Helm:**
```bash
# На машине с интернетом
helm pull prometheus-community/kube-prometheus-stack --version 88.1.0
helm pull prometheus-community/prometheus-node-exporter --version 7.0.0

# Перенос chart-ов в закрытый контур
scp kube-prometheus-stack-*.tgz target:/tmp/
scp prometheus-node-exporter-*.tgz target:/tmp/
```

### Сценарий 7: Настройка безопасности (Basic Auth / TLS)

Защита эндпоинта от несанкционированного доступа без использования Nginx.

**1. Создание файла `web-config.yml`:**
```yaml
basic_auth_users:
    admin: "$2y$12$..." # bcrypt hash

tls_server_config:
    cert_file: /etc/node_exporter/tls.crt
    key_file: /etc/node_exporter/tls.key
```

**2. Запуск с флагом:**
Добавьте `--web.config.file=/etc/node_exporter/web-config.yml` в параметры запуска сервиса.

## Валидация установки

### Бинарный / systemd

```bash
# Проверка работы сервиса
systemctl is-active node_exporter
# → active

# Проверка порта
ss -tlnp | grep 9100
# → LISTEN 0 4096 *:9100 *:* users:(("node_exporter",pid=1234,fd=3))

# Проверка метрик
curl -s http://localhost:9100/metrics | head -n 20
# → # HELP node_cpu_seconds_total ...
# → # TYPE node_cpu_seconds_total counter
```

### Docker / Podman

```bash
# Проверка статуса контейнера
docker ps | grep node_exporter
# → node_exporter   prom/node-exporter:v1.12.1   ...

# Проверка метрик
curl -s http://localhost:9100/metrics | head -n 20
```

### Kubernetes

```bash
# Проверка DaemonSet/Deployment
kubectl get pods -n monitoring -l app=node-exporter
# → node-exporter-abc12   1/1   Running   0   30s   10.244.0.5   worker1

# Проверка сервиса
kubectl get svc -n monitoring node-exporter
# → NAME            TYPE        CLUSTER-IP      PORT(S)    AGE
# → node-exporter   ClusterIP   10.96.100.50    9100/TCP   5m

# Проверка метрик через port-forward
kubectl port-forward -n monitoring svc/node-exporter 9100:9100 &
curl -s http://localhost:9100/metrics | head -n 20
```

### Ansible

```bash
# Проверка через Ansible
ansible all -m systemd -a "name=node_exporter state=started"
```

## Резервное копирование и восстановление

### Бинарный / systemd

```bash
# Резервное копирование
sudo cp /usr/local/bin/node_exporter /backup/node_exporter-$(date +%F).bin
sudo cp /etc/systemd/system/node_exporter.service /backup/
sudo cp /etc/default/node_exporter /backup/ 2>/dev/null || true

# Восстановление
sudo cp /backup/node_exporter-2026-09-17.bin /usr/local/bin/node_exporter
sudo systemctl restart node_exporter
```

### Docker / Podman

```bash
# Резервное копирование конфигурации
docker inspect node_exporter > /backup/node_exporter-config.json

# Восстановление
docker stop node_exporter && docker rm node_exporter
docker run -d --name node_exporter ... (используя сохраненную конфигурацию)
```

### Kubernetes

```bash
# Резервное копирование values
helm get values monitoring -n monitoring > /backup/kps-values.yaml

# Восстановление
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring -f /backup/kps-values.yaml
```

## Обновление и откат

### Бинарный метод

```bash
# 1. Остановка сервиса
sudo systemctl stop node_exporter

# 2. Загрузка новой версии
VERSION="1.13.0"
wget https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/node_exporter-${VERSION}.linux-amd64.tar.gz
tar xvfz node_exporter-${VERSION}.linux-amd64.tar.gz
sudo mv node_exporter-${VERSION}.linux-amd64/node_exporter /usr/local/bin/

# 3. Запуск
sudo systemctl start node_exporter

# Откат (если нужно)
sudo cp /backup/node_exporter-2026-09-17.bin /usr/local/bin/node_exporter
sudo systemctl restart node_exporter
```

### APT

```bash
sudo apt update && sudo apt upgrade -y prometheus-node-exporter
# Откат
sudo apt install prometheus-node-exporter=1.12.1-0
```

### Helm

```bash
# Обновление
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  -n monitoring --set nodeExporter.image.tag=v1.13.0

# Откат
helm rollback monitoring 1 -n monitoring
```

## Очистка и удаление

### Бинарный / systemd

```bash
sudo systemctl stop node_exporter
sudo systemctl disable --now node_exporter
sudo rm /etc/systemd/system/node_exporter.service
sudo rm /usr/local/bin/node_exporter
sudo rm -rf /var/lib/node_exporter
sudo systemctl daemon-reload
```

### Docker / Podman

```bash
docker stop node_exporter && docker rm node_exporter
docker rmi prom/node-exporter:v1.12.1
```

### Kubernetes

```bash
# Удаление DaemonSet (ручной)
kubectl delete daemonset node-exporter -n monitoring

# Удаление через Helm
helm uninstall monitoring -n monitoring
```

### Ansible

```yaml
# Удаление через Ansible
- hosts: all
  become: yes
  roles:
    - role: prometheus.prometheus.node_exporter
      vars:
        node_exporter_state: absent
```

## Расширенный Textfile Collector

### Конфигурация

```ini
# /etc/systemd/system/node_exporter.service (добавить флаг)
ExecStart=/usr/local/bin/node_exporter \
    --web.listen-address=:9100 \
    --collector.textfile.directory=/var/lib/node_exporter/textfile_metrics
```

### Практические примеры метрик

#### Disk I/O (psync)

```bash
#!/bin/bash
# /usr/local/bin/psync-metrics.sh
OUTFILE="/var/lib/node_exporter/textfile_metrics/psync.prom"

PSYNC=$(cat /proc/sys/fs/pid_max 2>/dev/null || echo 0)
echo "# HELP psync_pid_max Maximum number of processes" > $OUTFILE
echo "# TYPE psync_pid_max gauge" >> $OUTFILE
echo "psync_pid_max $PSYNC" >> $OUTFILE
```

#### CPU Temperature (если доступен thermal_zone)

```bash
#!/bin/bash
# /usr/local/bin/temp-metrics.sh
OUTFILE="/var/lib/node_exporter/textfile_metrics/temp.prom"

TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)
echo "# HELP node_custom_temperature_celsius CPU temperature" > $OUTFILE
echo "# TYPE node_custom_temperature_celsius gauge" >> $OUTFILE
echo "node_custom_temperature_celsius $(echo $TEMP/1000 | bc -l)" >> $OUTFILE
```

#### Дисковое пространство (кастомный скрипт)

```bash
#!/bin/bash
# /usr/local/bin/disk-metrics.sh
OUTFILE="/var/lib/node_exporter/textfile_metrics/disk.prom"

df -h / | tail -1 | awk '{print "node_custom_disk_usage_percent{device=\"" $1 "\"} " $5}' | tr -d '%' > $OUTFILE
```

### Systemd timer вместо cron

```ini
# /etc/systemd/system/psync-metrics.timer
[Unit]
Description=Run psync metrics every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

## Диагностика типичных проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Ошибка `Permission denied` | Недостаточно прав у пользователя | Запустите от `root` или добавьте пользователя в группы `disk`, `hwmon`. |
| Метрики файловой системы пустые | Контейнер без `rootfs` | Проверьте монтирование `/` и флаг `--path.rootfs`. |
| Высокая нагрузка на CPU | Слишком много коллекторов | Отключите тяжелые коллекторы (например, `nfs`, `zfs`, если не нужны). |
| Отсутствие метрик diskstats | Ядро не экспортирует /proc/diskstats | Проверьте версию ядра и наличие модулей. |
| Пустые метрики textfile collector | Неверные права на директорию | `chown -R node_exporter:node_exporter /var/lib/node_exporter/textfile_metrics` |
| Метрики обновляются редко | Недостаточный scrape interval | Увеличьте частоту опроса в Prometheus. |
| Ошибка TLS handshake | Неверный сертификат | Проверьте срок действия и права на ключ. |

## Рекомендации SRE

1. **Запуск от root**: Для доступа к метрикам ядра (`diskstats`, `hwmon`, `edac`) используйте `User=root` в systemd-юните.
2. **Ограничение коллекторов**: Включите только необходимые коллекторы для уменьшения cardinality и нагрузки на TSDB.
3. **Textfile Collector**: Используйте для кастомных метрик, которые не покрываются стандартными коллекторами (RAID, базы данных, бэкапы).
4. **Hardening**: Примените директивы `NoNewPrivileges`, `ProtectSystem`, `ProtectHome`, `PrivateTmp` для systemd-юнита.
5. **Scrape interval**: Используйте `scrape_interval: 30s` или больше для production-сред.
6. **Мониторинг доступности**: Настройте алерт на `up{job="node-exporter"} == 0` для быстрого обнаружения падения экспортера.
7. **Версионирование**: Используйте фиксированные версии в Docker/Kubernetes/Ansible для повторяемости развертываний.
8. **Верификация**: Проверяйте sha256sum скачанных архивов перед установкой.

## См. также

*   **[Node Exporter — Полное руководство](../Exporters/node_exporter.md)** — глубокое описание всех коллекторов, метрик и алертов.
*   **[Установка Prometheus: обзор](./overview.md)** — сравнение методов установки компонентов.
*   **[Textfile Collector](../Exporters/extensibility/textfile_collector.md)** — механизм сбора кастомных метрик.
*   **[Конфигурация экспортеров в kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/exporters_config.md)** — Helm-параметры Node Exporter.
*   **[Обогащение метрик Node Exporter](../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/node_exporter_enrichment.md)** — relabeling и PodMonitor.
*   **[Методология поиска неисправностей](../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md)**
*   **[Capacity Planning](./capacity_planning.md)** — формулы расчёта ресурсов Prometheus..
