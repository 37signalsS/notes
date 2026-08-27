# NetBox: Развертывание в Docker

Руководство по развертыванию NetBox с использованием Docker Compose. Обзор концепций и архитектуры приведен в файле **[NetBox: Обзор и базовые концепции](./overview.md)**.

## Определения

**Docker Compose** — инструмент для определения и запуска многоконтейнерных Docker-приложений через YAML-файл `compose.yml`. Позволяет описать все сервисы, сети и тома в одном файле.

**netbox-docker** — официальный репозиторий Docker-образов NetBox, содержащий оптимизированные Dockerfile и готовые compose-конфигурации для быстрого развертывания.

**Volume** — механизм Docker для сохранения данных за пределами контейнера. Используется для персистентного хранения PostgreSQL, Redis, медиафайлов и конфигурации.

**Healthcheck** — Docker-механизм для проверки работоспособности контентного процесса. Автоматически перезапускает контейнер при обнаружении сбоя.

**SOCI (Seccomp OCI Filesystem)** — механизм изоляции контейнеров, ограничивающий системные вызовы для повышения безопасности.

## Базовые концепции

### Архитектура Docker-развертывания NetBox

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Host                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │  Nginx   │  │ NetBox   │  │      PostgreSQL      │  │
│  │ (proxy)  │→ │(gunicorn)│→ │       (БД)           │  │
│  └──────────┘  └────┬─────┘  └──────────────────────┘  │
│                     │                                    │
│  ┌──────────┐  ┌────▼─────┐  ┌──────────────────────┐  │
│  │  Redis   │← │ netbox-  │  │     Redis (кэш)      │  │
│  │ (очередь)│  │   rq     │  │                      │  │
│  └──────────┘  └──────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### Преимущества Docker перед Bare Metal

| Критерий | Docker Compose | Bare Metal |
| :--- | :--- | :--- |
| **Установка** | 5 минут | 30-60 минут |
| **Обновление** | `docker compose pull && up -d` | Ручное обновление кода |
| **Откат** | Теги образов | Восстановление из бэкапа |
| **Изоляция** | Полная | Совместное использование ОС |
| **Масштабирование** | Вертикальное | Вертикальное + горизонтальное |
| **Мониторинг** | Стандартный Docker | Настройка вручную |

### Сетевые порты Docker-контейнеров

| Контейнер | Внутренний порт | Назначение |
| :--- | :--- | :--- |
| `nginx` | 80, 443 | HTTP/HTTPS доступ |
| `netbox` | 8000 | WSGI-сервер (Gunicorn) |
| `postgres` | 5432 | PostgreSQL |
| `redis` | 6379 | Redis (очереди + кэш) |
| `redis-cache` | 6379 | Redis (только кэш) |

## Практические сценарии

### 1. Подготовка окружения

Установите Docker и Docker Compose:

```bash
# Установка Docker (Debian/Ubuntu)
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Проверка
docker --version
docker compose version
```

### 2. Быстрое развертывание

```bash
# Клонирование официального репозитория
git clone https://github.com/netbox-community/netbox-docker.git
cd netbox-docker

# Создание .env файла
cp .env.example .env
```

Редактируйте `.env`:

```env
# Основные настройки
NETBOX_HOSTNAME=netbox.example.com
SECRET_KEY=$(openssl rand -hex 32)
SUPERUSER_PASSWORD=admin_password_here
SUPERUSER_API_TOKEN=$(openssl rand -hex 32)

# PostgreSQL
POSTGRES_PASSWORD=strong_postgres_password

# Redis
REDIS_PASSWORD=strong_redis_password

# Временная зона
TIMEZONE=Europe/Moscow
```

Запуск:

```bash
docker compose pull
docker compose up -d
```

**Валидация:** Проверьте статус контейнеров:

```bash
docker compose ps
# NAME          STATUS          PORTS
# nginx         Up (healthy)    0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
# netbox        Up (healthy)    8000/tcp
# postgres      Up (healthy)    5432/tcp
# redis         Up (healthy)    6379/tcp
# redis-cache   Up (healthy)    6372/tcp
```

### 3. Настройка SSL/TLS в Docker

Вариант 1:自负азанный сертификат (тестирование):

```bash
mkdir -p nginx/certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/netbox.key \
  -out nginx/certs/netbox.crt
```

Вариант 2: Let's Encrypt (production):

```bash
# Установка Certbot на хосте
sudo apt install -y certbot

# Остановка Nginx в контейнере
docker compose stop nginx

# Получение сертификата
sudo certbot certonly --standalone -d netbox.example.com

# Копирование сертификатов
sudo cp /etc/letsencrypt/live/netbox.example.com/fullchain.pem nginx/certs/netbox.crt
sudo cp /etc/letsencrypt/live/netbox.example.com/privkey.pem nginx/certs/netbox.key

# Запуск Nginx
docker compose start nginx
```

### 4. Настройка автоматического обновления

```bash
# Скрипт обновления /opt/netbox/scripts/update_netbox_docker.sh
#!/bin/bash
cd /opt/netbox-docker

# Создание бэкапа
docker compose exec postgres pg_dump -U netbox netbox | gzip > /opt/backups/netbox_$(date +%Y%m%d).sql.gz

# Обновление образов
docker compose pull

# Перезапуск с новыми образами
docker compose up -d

# Очистка старых образов
docker image prune -f

echo "$(date): NetBox Docker updated" >> /var/log/netbox-update.log
```

```bash
# Расписание: еженедельно в воскресенье в 4:00
0 4 * * 0 /opt/netbox/scripts/update_netbox_docker.sh
```

### 5. Управление логами

```bash
# Просмотр логов всех контейнеров
docker compose logs -f

# Просмотр логов конкретного сервиса
docker compose logs -f netbox

# Настройка логирования в compose.yml
```

Добавьте в `compose.yml`:

```yaml
services:
  netbox:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  postgres:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### 6. Мониторинг Docker-контейнеров

```bash
# Проверка использования ресурсов
docker stats --no-stream

# Проверка здоровья контейнеров
docker inspect --format='{{.State.Health.Status}}' netbox-docker-netbox-1
# → healthy

# Проверка логов здоровья
docker inspect --format='{{json .State.Health}}' netbox-docker-netbox-1 | jq
```

### 7. Настройка резервного копирования

```bash
#!/bin/bash
# /opt/netbox/scripts/docker_backup.sh

BACKUP_DIR="/opt/backups/netbox-docker"
DATE=$(date +%Y%m%d_%H%M%S)
RETENTION_DAYS=30

mkdir -p $BACKUP_DIR

# Бэкап PostgreSQL
docker compose exec -T postgres pg_dump -U netbox netbox | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# Бэкап медиафайлов
docker compose exec -T netbox tar czf - /opt/netbox/netbox/media/ > $BACKUP_DIR/media_$DATE.tar.gz

# Бэкап конфигурации
tar czf $BACKUP_DIR/config_$DATE.tar.gz \
    .env \
    compose.yml \
    nginx/ \
    configuration.py

# Удаление старых бэкапов
find $BACKUP_DIR -name "*.gz" -mtime +$RETENTION_DAYS -delete

echo "$(date): Docker backup completed" >> /var/log/netbox-backup.log
```

### 8. Настройка networking для production

В `compose.yml`:

```yaml
networks:
  netbox-internal:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16

services:
  postgres:
    networks:
      netbox-internal:
        ipv4_address: 172.20.0.10

  redis:
    networks:
      netbox-internal:
        ipv4_address: 172.20.0.20

  netbox:
    networks:
      netbox-internal:
        ipv4_address: 172.20.0.30

  nginx:
    networks:
      netbox-internal:
        ipv4_address: 172.20.0.40
    ports:
      - "80:80"
      - "443:443"
```

### 9. Персистентные тома для production

```yaml
services:
  postgres:
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    volumes:
      - redis_data:/data

  netbox:
    volumes:
      - ./configuration.py:/opt/netbox/netbox/netbox/configuration.py:ro
      - netbox_static:/opt/netbox/netbox/static
      - netbox_media:/opt/netbox/netbox/media

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  netbox_static:
    driver: local
  netbox_media:
    driver: local
```

### 10. Производительность Docker-окружения

```bash
# Увеличение лимитов Docker Engine
# /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2",
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 65536,
      "Soft": 65536
    }
  }
}
```

## Обслуживание и эксплуатация

### Типовые проблемы и их решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Контейнер перезапускается** | Ошибка в configuration.py | `docker compose logs netbox` — проверьте вывод |
| **Нет доступа к UI** | Nginx не проксирует | Проверьте `docker compose logs nginx` |
| **PostgreSQL: FATAL password** | Неверный пароль в .env | Сверьте `POSTGRES_PASSWORD` в `.env` и `configuration.py` |
| **Redis: NOAUTH** | Неверный пароль Redis | Проверьте `REDIS_PASSWORD` в `.env` |
| **Данные не сохраняются** | Нет volume для postgres | Добавьте `postgres_data` volume в compose.yml |
| **Медленная работа** | Мало ресурсов контейнеру | Увеличьте лимиты CPU/RAM в compose.yml |

### Типовые ошибки Docker

```bash
# Ошибка: "Cannot connect to Docker daemon"
sudo systemctl start docker
sudo usermod -aG docker $USER

# Ошибка: "no space left on device"
docker system prune -a
docker volume prune

# Ошибка: "port is already allocated"
sudo ss -tlnp | grep :80
# Остановите конфликтующий сервис
```

### Масштабирование NetBox Worker

```yaml
# Масштабирование netbox-rq worker
services:
  netbox-rq:
    image: netboxcommunity/netbox:latest
    command: /opt/netbox/venv/bin/python manage.py rqworker high default low
    deploy:
      replicas: 3  # 3 воркера для обработки очередей
```

```bash
# Масштабирование в runtime
docker compose up -d --scale netbox-rq=3
```

## Дополнительная информация

### См. также

- [NetBox: Обзор и базовые концепции](./overview.md)
- [Установка NetBox в Debian (Bare Metal)](./netbox_debian_installation_guide.md)
- [Архитектура NetBox в Enterprise-среде](./netbox-enterprise-automation.md)
- [Мониторинг NetBox (Prometheus/Grafana)](./netbox_monitoring_integration.md)
- [Официальный репозиторий netbox-docker](https://github.com/netbox-community/netbox-docker)
- [Документация Docker Compose](https://docs.docker.com/compose/)
