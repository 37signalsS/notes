# Руководство по настройке экспортеров: node-exporter и cAdvisor

Этот документ описывает, как настроить `node-exporter` для сбора метрик хост-машины и `cAdvisor` для сбора метрик Docker-контейнеров, а также как добавить их в качестве целей для сбора в Prometheus.

Экспортеры обычно запускаются на тех машинах, которые вы хотите мониторить.

## Структура проекта для экспортеров

На хосте, который вы планируете мониторить, создайте следующую структуру:

```
host-monitoring/
├── docker-compose.yml
└── .env
```

## 1. Настройка Node Exporter

`node-exporter` собирает метрики оборудования и операционной системы.

### Конфигурация Docker Compose

```yaml
# host-monitoring/docker-compose.yml

services:
  node-exporter:
    image: prom/node-exporter
    container_name: ${PROJECT_NAME}-node-exporter
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "9100:9100"
    restart: always
```

*   **`volumes`**: `node-exporter` требует доступа к файловым системам `/proc`, `/sys` и корневой (`/`) хоста для сбора метрик. Они монтируются в режиме "только чтение" (`ro`).
*   **`command`**: Указывает экспортеру, где искать файловые системы хоста внутри контейнера, а также исключает из мониторинга ненужные точки монтирования.
*   **`ports`**: Публикует стандартный порт `node-exporter` `9100`.

### Файл переменных окружения

```ini
# host-monitoring/.env
PROJECT_NAME=host_exporters
```

## 2. Настройка cAdvisor

`cAdvisor` (Container Advisor) собирает метрики о запущенных Docker-контейнерах.

### Конфигурация Docker Compose

Добавьте сервис `cadvisor` в тот же `docker-compose.yml`:

```yaml
# host-monitoring/docker-compose.yml

services:
  node-exporter:
    # ... (конфигурация node-exporter)

  cadvisor:
    image: gcr.io/cadvisor/cadvisor
    container_name: ${PROJECT_NAME}-cadvisor
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:rw
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    ports:
      - "8080:8080" # Может конфликтовать с другими приложениями, можно изменить на 8000:8080
    restart: always
```

*   **`image`**: Используется образ от Google.
*   **`volumes`**: `cAdvisor` также требует доступа к различным системным каталогам и Docker-сокету для сбора информации о контейнерах.
*   **`ports`**: Стандартный порт `cAdvisor` — `8080`. Если он занят, его можно изменить (например, на `8000:8080`).

## 3. Запуск экспортеров

На хосте, который вы хотите мониторить, выполните:

```bash
docker-compose up -d
```

Проверьте, что оба контейнера успешно запустились: `docker ps`.

## 4. Добавление экспортеров в конфигурацию Prometheus

Теперь необходимо настроить ваш основной сервер Prometheus, чтобы он начал собирать метрики с этих новых экспортеров.

Откройте `prometheus.yml` на вашем сервере мониторинга и добавьте два новых `job` в секцию `scrape_configs`.

```yaml
# monitoring/prometheus/prometheus.yml

# ... (global и job 'prometheus')

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'host-metrics'
    static_configs:
      - targets: ['<IP_АДРЕС_ХОСТА_С_ЭКСПОРТЕРАМИ>:9100']

  - job_name: 'docker-metrics'
    static_configs:
      - targets: ['<IP_АДРЕС_ХОСТА_С_ЭКСПОРТЕРАМИ>:8080']
```

*   Замените `<IP_АДРЕС_ХОСТА_С_ЭКСПОРТЕРАМИ>` на реальный IP-адрес машины, где вы запустили `node-exporter` и `cAdvisor`.
*   `host-metrics` будет собирать метрики с `node-exporter` по порту `9100`.
*   `docker-metrics` будет собирать метрики с `cAdvisor` по порту `8080` (или другому, если вы его изменили).

## 5. Перезапуск Prometheus и проверка

Перезапустите Prometheus, чтобы он применил новую конфигурацию:

```bash
# На сервере мониторинга
docker-compose restart prometheus
```

Откройте веб-интерфейс Prometheus (`http://localhost:9090`) и перейдите в раздел **Status -> Targets**. Вы должны увидеть три цели: `prometheus`, `host-metrics` и `docker-metrics`. Через несколько секунд их статус должен измениться на `UP`.

Теперь Prometheus собирает метрики с вашего хоста и всех запущенных на нем Docker-контейнеров. Эти метрики готовы для визуализации в Grafana.

---
**Связанные темы:**
*   [[exporters.md]]
*   [[docker_compose_setup.md]]
*   [[../Grafana/grafana_dashboards.md]]
