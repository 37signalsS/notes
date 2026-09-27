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

### Шаблон Boilerplates (community-инструмент для генерации Docker Compose)

Помимо официального репозитория `netbox-docker`, существует community-инструмент **Boilerplates** (CLI), который автоматически генерирует готовый к работе стек Docker Compose с предварительно настроенными интеграциями: обратным прокси-сервером **Traefik** для TLS-терминации, внешней базой данных PostgreSQL, RADIUS-аутентификацией и уведомлениями по электронной почте.

**Установка инструмента:**
```bash
# Установка через pip (или brew, npm — зависит от реализации)
pip install boilerplates
```

**Принцип работы:**
Инструмент запрашивает у пользователя параметры (или принимает их через флаги CLI), после чего генерирует полный набор файлов `docker-compose.yml`, `.env`, `configuration.py` и секретов в указанную директорию.

**Неинтерактивный режим и вывод в директорию:**
```bash
boilerplates -n -o /tmp/netbox-demo
```
- `-n` — неинтерактивный режим, использует значения по умолчанию без промптов.
- `-o <path>` — директория для вывода сгенерированных файлов.

**Переопределение переменных через флаги:**
```bash
boilerplates -n -o /tmp/netbox \
  --traffic true \
  --traffic_host netbox.test1.home.cl.de \
  --email true \
  --email_host smtp.example.com \
  --email_port 587 \
  --email_username user@example.com \
  --email_password secure_password \
  --email_use_tls true
```

**Основные переменные шаблона:**

| Переменная | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `TRAEFIK_NETWORK` | Внешняя сеть Docker для Traefik | `traefik-public` |
| `TRAEFIK_HOST` | Поддомен для доступа к NetBox | `netbox` |
| `TRAEFIK_DOMAIN` | Доменная зона (локальная DNS в домашней лаборатории) | `home.cl.te` |
| `TRAEFIK_TLS` | Включение TLS через Traefik | `false` |
| `EMAIL_HOST` | SMTP-сервер для уведомлений | — |
| `EMAIL_PORT` | Порт SMTP (587 для TLS, 465 для SSL) | — |
| `EMAIL_USERNAME` | Логин SMTP | — |
| `EMAIL_PASSWORD` | Пароль SMTP | — |
| `EMAIL_USE_TLS` | Использовать TLS (`true`) или SSL (`false`) | `true` |
| `NETBOX_SECRET_KEY` | Секретный ключ Django (50 символов) | Автогенерация |
| `DB_HOST` | Хост внешней PostgreSQL (если используется внешняя БД) | Встроенный контейнер |
| `RADIUS_HOST` | Хост RADIUS-сервера | — |
| `RADIUS_SECRET` | Секретный ключ RADIUS | — |

**Сгенерированная структура стека:**
```yaml
services:
  netbox:
    image: netboxcommunity/netbox:latest
    depends_on:
      - postgres
      - redis
      - redis-cache
    env_file: .env
    volumes:
      - netbox_static:/opt/netbox/netbox/static
      - netbox_media:/opt/netbox/netbox/media
      - ./configuration.py:/opt/netbox/netbox/configuration.py:ro

  netbox-rq:
    image: netboxcommunity/netbox:latest
    command: /opt/netbox/venv/bin/python manage.py rqworker high default low

  radius:
    image: freeradius/freeradius-server:latest
    # Контейнер RADIUS для аутентификации

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}

  redis-cache:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
  redis_data:
  netbox_static:
  netbox_media:
```

**Сетевые метки Traefik:**
```yaml
services:
  nginx:
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.netbox.rule=Host(`${TRAEFIK_HOST}.${TRAEFIK_DOMAIN}`)"
      - "traefik.http.routers.netbox.entrypoints=websecure"
      - "traefik.http.routers.netbox.tls.certresolver=myresolver"
    networks:
      - traefik-public
      - netbox-internal
```

**Инициализация и ожидание готовности:**

При первом запуске NetBox инициализирует базу данных, что занимает несколько минут. В этот момент рабочие процессы (netbox-rq) и веб-сервер могут завершаться с ошибкой до готовности PostgreSQL.

```bash
# Мониторинг прогресса инициализации
docker compose logs -f netbox

# Ожидание успешной инициализации
# Искомое сообщение в логах:
# "Конфигурация блока замка успешно загружена" (или аналог на английском)
# После этого все контейнеры перейдут в состояние healthy
```

**Варианты доступа к веб-интерфейсу:**

| Сценарий | Способ доступа | Примечание |
| :--- | :--- | :--- |
| **TLS включен** | `https://netbox.<домен>` через Traefik | Рекомендуется для production |
| **TLS отключен** | `http://<хост>:8000` напрямую | Только для тестирования, небезопасно |

При использовании TLS обратный прокси (Traefik) берет на себя SSL-терминацию, и порт 8000 не暴露вается наружу.

**Проверка работы уведомлений по email:**

```bash
# Вход в интерактивную оболочку контейнера NetBox
docker compose exec netbox /bin/bash

# Запуск скрипта проверки email
python manage.py shell -c "
from django.core.mail import send_mail
send_mail(
    'NetBox Email Test',
    'Тестовое уведомление',
    'netbox@example.com',
    ['ваш@email.com'],
    fail_silently=False,
)
"
# → 1 (отправлено) или ошибка SMTP
```

**Безопасность — стандартный API-токен администратора:**

При первом входе в NetBox (`admin` / `admin`) система отображает предупреждение о стандартном API-токене администратора (`1234567890abcdef...`), который широко известен и крайне небезопасен.

**Обязательные действия после первого входа:**
1. **Сменить пароль** администратора: `Admin → Users → admin → Change password`.
2. **Удалить стандартный API-токен**: `Admin → Users → Tokens → токен "admin" → Delete`.
3. **Создать новый токен** с ограничениями: `write_enabled` по необходимости, `allowed_ips`, `expires`.

**Внешняя база данных PostgreSQL:**

Если используется внешняя PostgreSQL, переопределите переменные в `.env`:
```env
DB_HOST=postgres.external.example.com
DB_PORT=5432
DB_NAME=netbox
DB_USER=netbox
DB_PASSWORD=strong_password
```
В этом случае стек Docker Compose пропустит контейнер PostgreSQL и подключится к внешнему серверу.

### См. также

- [NetBox: Обзор и базовые концепции](./overview.md)
- [Установка NetBox в Debian (Bare Metal)](./netbox_debian_installation_guide.md)
- [Архитектура NetBox в Enterprise-среде](./netbox-enterprise-automation.md)
- [Мониторинг NetBox (Prometheus/Grafana)](./netbox_monitoring_integration.md)
- [Официальный репозиторий netbox-docker](https://github.com/netbox-community/netbox-docker)
- [Документация Docker Compose](https://docs.docker.com/compose/)
