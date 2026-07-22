# Конфигурация Docker Compose для стека мониторинга

## Определения

**Docker Compose для мониторинга** — декларативное определение полного стека наблюдения (Prometheus + Grafana + Alertmanager + Node Exporter + cAdvisor) в едином `docker-compose.yml`. Позволяет запускать, останавливать и обновлять весь стек одной командой.

> **См. также:** [Обзор Docker Stack](./overview.md), [Docker Compose basics](../../../Docker/Docker_compose/docker_compose_file_example.md).

## Основные концепции

### Архитектура стека

| Сервис | Образ | Порт | Назначение |
|---|---|---|---|
| **Prometheus** | `prom/prometheus` | 9090 | Сбор и хранение метрик |
| **Grafana** | `grafana/grafana` | 3000 | Визуализация и дашборды |
| **Alertmanager** | `prom/alertmanager` | 9093 | Обработка и маршрутизация алертов |
| **Node Exporter** | `prom/node-exporter` | 9100 | Метрики хоста (CPU, RAM, disk, network) |
| **cAdvisor** | `ghcr.io/google/cadvisor` | 8080 | Метрики контейнеров Docker |

### Сетевая модель

Все сервисы объединены в единую bridge-сеть `monitoring-net`. Внутри сети DNS-разрешение работает по именам сервисов — `prometheus`, `alertmanager`, `grafana` и т.д. Это позволяет конфигурационным файлам ссылаться на другие сервисы по имени (например, `alertmanager:9093` в `prometheus.yml`).

### Персистентность

| Том | Хранит |
|---|---|
| `prometheus_data` | TSDB Prometheus (временные ряды) |
| `grafana_data` | Дашборды, data sources, пользователи Grafana |

### Bind mounts для конфигурации

| Путь на хосте | Путь в контейнере | Содержимое |
|---|---|---|
| `./prometheus/` | `/etc/prometheus/` | `prometheus.yml`, `rules.yml` |
| `./alertmanager/` | `/config/` | `config.yml` Alertmanager |

> Конфигурационные файлы Prometheus и Alertmanager описаны в отдельных заметках: [Prometheus config](./prometheus_config.md), [Alertmanager config](./docker_compose_alertmanager_config.md).

### Актуальные версии образов

| Компонент | Образ | Версия |
|---|---|---|
| **Prometheus** | `prom/prometheus` | v3.13.1 |
| **Grafana** | `grafana/grafana` | v13.1.1 |
| **Alertmanager** | `prom/alertmanager` | v0.33.1 |
| **Node Exporter** | `prom/node-exporter` | v1.12.1 |
| **cAdvisor** | `ghcr.io/google/cadvisor` | v0.60.5 |

> **Важно:** Проверяйте [Docker Hub](https://hub.docker.com/u/prom) для получения последних версий.

## Практические сценарии

### Полный `docker-compose.yml`

```yaml
services:
  prometheus:
    image: prom/prometheus:v3.13.1
    container_name: prometheus
    volumes:
      - ./prometheus:/etc/prometheus
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=15d'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
    ports:
      - "9090:9090"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - monitoring-net

  alertmanager:
    image: prom/alertmanager:v0.33.1
    container_name: alertmanager
    volumes:
      - ./alertmanager:/config
    command:
      - '--config.file=/config/config.yml'
      - '--storage.path=/alertmanager'
      - '--data.retention=120h'
    ports:
      - "9093:9093"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:9093/-/healthy"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - monitoring-net

  node-exporter:
    image: prom/node-exporter:v1.12.1
    container_name: node-exporter
    pid: host
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
    restart: unless-stopped
    networks:
      - monitoring-net

  cadvisor:
    image: ghcr.io/google/cadvisor:v0.60.5
    container_name: cadvisor
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:rw
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
    ports:
      - "8080:8080"
    restart: unless-stopped
    networks:
      - monitoring-net

  grafana:
    image: grafana/grafana:13.1.1
    container_name: grafana
    user: "472:472"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-admin}
      - GF_SERVER_ROOT_URL=http://localhost:3000
    ports:
      - "3000:3000"
    restart: unless-stopped
    depends_on:
      prometheus:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "wget -q --spider http://localhost:3000/api/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - monitoring-net

volumes:
  prometheus_data:
  grafana_data:

networks:
  monitoring-net:
    driver: bridge
```

### Описание ключевых параметров

#### Prometheus

| Параметр | Значение | Описание |
|---|---|---|
| `--storage.tsdb.retention.time=15d` | 15 дней | Срок хранения метрик. Увеличить при наличии дискового пространства |
| `healthcheck` | `wget /-/healthy` | Проверка доступности для `depends_on` других сервисов |

#### Alertmanager

| Параметр | Значение | Описание |
|---|---|---|
| `--data.retention=120h` | 5 дней | Хранение silences и данных кластера |
| `--storage.path=/alertmanager` | Внутренний путь | Персистентный volume через bind mount |

#### Node Exporter

| Параметр | Значение | Описание |
|---|---|---|
| `pid: host` | Host PID namespace | Видит процессы хоста для корректного сбора метрик |
| `/proc:/host/proc:ro` | Read-only | Доступ к метрикам процессов хоста |
| `--collector.filesystem.mount-points-exclude` | Regex | Исключение виртуальных ФС из метрик disk |

#### cAdvisor

| Параметр | Значение | Описание |
|---|---|---|
| `/var/run:/var/run:rw` | Read-write | Доступ к Docker socket для получения метрик контейнеров |
| `/var/lib/docker/:/var/lib/docker:ro` | Read-only | Чтение метрик хранения контейнеров |

#### Grafana

| Параметр | Значение | Описание |
|---|---|---|
| `user: "472:472"` | UID:GID grafana | Запуск от непривилегированного пользователя (security best practice) |
| `depends_on: prometheus.service_healthy` | Health check dependency | Grafana ждёт готовности Prometheus перед запуском |
| `GF_SECURITY_ADMIN_PASSWORD` | `${GRAFANA_ADMIN_PASSWORD:-admin}` | Пароль из env или `admin` по умолчанию |

### Рекомендации по безопасности

| Мера | Реализация |
|---|---|
| **Непривилегированный пользователь** | Grafana: `user: "472:472"` |
| **Переменные окружения для секретов** | `${GRAFANA_ADMIN_PASSWORD}` через `.env`-файл |
| **Health checks** | Все критичные сервисы проверяют доступность через `wget` |
| **Read-only mounts** | `/proc`, `/sys`, `/var/lib/docker` — только чтение |
| **Ограничение ресурсов** | Добавить `deploy.resources.limits` для каждого сервиса |

### Ограничение ресурсов (production)

```yaml
  prometheus:
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 4G
        reservations:
          cpus: '0.5'
          memory: 1G

  grafana:
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
```

> **Подробнее:** [Resource management in Docker Compose](../../../Docker/Docker_compose/docker_compose_file_example.md).

## Дополнительная информация

### Связанные темы

* [Обзор Docker Stack](./overview.md) — структура проекта, быстрый старт, проверка компонентов
* [Конфигурация Prometheus](./prometheus_config.md) — `prometheus.yml`, rules, scrape-цели
* [Конфигурация Alertmanager](./docker_compose_alertmanager_config.md) — маршрутизация алертов
* [Настройка Grafana с provisioning](../../../Grafana/Installation/docker_compose_setup.md) — автоматический datasource, security checklist
* [Мониторинг Docker](../../../Docker/Docker_metrics/docker_prometheus_integration.md) — метрики контейнеров

### Устранение неполадок

| Проблема | Причина | Решение |
|---|---|---|
| **Prometheus не видит Alertmanager** | Сервисы в разных сетях | Проверьте `networks` — все сервисы должны быть в `monitoring-net` |
| **Grafana не запускается** | Права на volume | `chmod -R 472:472` для bind mounts Grafana |
| **Node Exporter не собирает метрики disk** | Неправильный `--path.rootfs` | Убедитесь, что `- /:/rootfs:ro` присутствует в volumes |
| **cAdvisor не видит контейнеры** | Нет доступа к Docker socket | Проверьте `/var/run:/var/run:rw` в volumes |
| **Высокое потребление RAM Prometheus** | Большой retention или высокая кардинальность | Уменьшите `--storage.tsdb.retention.time`, проверьте метрики через `topk(10, count by(__name__)({}))` |

**Полезные команды:**

```bash
# Запуск всего стека
docker compose up -d

# Логи конкретного сервиса
docker compose logs -f prometheus

# Статус контейнеров
docker compose ps

# Перезапуск одного сервиса
docker compose restart alertmanager

# Полная пересборка
docker compose down && docker compose up -d

# Проверка health endpoint
curl http://localhost:9090/-/healthy
curl http://localhost:9093/-/healthy
curl http://localhost:3000/api/health
```
