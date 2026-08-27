# Ansible: установка, настройка и первоначальная конфигурация UI для Ansible — Semaphore

## Определения

**Ansible Semaphore** — это современный, легковесный веб-интерфейс с открытым исходным кодом для запуска плейбуков Ansible и управления инфраструктурной автоматизацией. Написан на языке Go, поддерживает базы данных SQLite, MySQL и PostgreSQL. Предоставляет собой альтернативу более тяжеловесным решениям типа **AWX** (Ansible AWX) или коммерческому **AAP** (Ansible Automation Platform).

**Основные отличия от AWX:**
- Написан на Go, а не на Python (более легковесный)
- Поддерживает SQLite (не требует PostgreSQL/MySQL)
- Использует Git-репозитории как источник плейбуков (а не import из UI)
- Задачи выполняются локально или на удаленных исполнителях (Runners)
- Интерфейс более минималистичный и быстрый
- Включает встроенное планирование заданий (cron-расписание)
- Поддерживает несколько типов приложений: Ansible, Terraform/OpenTofu, Shell/Bash, PowerShell, Python

---

## Предварительные требования

### Системные требования

| Компонент | Минимальные требования | Рекомендуемые |
| :--- | :--- | :--- |
| **ОС** | Ubuntu 20.04+, Debian 10+, CentOS 7+ | Ubuntu 22.04+, Debian 12+ |
| **RAM** | 1 ГБ | 2+ ГБ |
| **CPU** | 1 ядро | 2+ ядра |
| **Диск** | 10 ГБ | 20+ ГБ |
| **Python** | 3.8+ | 3.10+ |
| **Ansible** | 2.12+ | 2.17+ (ansible-core 2.18+) |
| **Git** | 2.0+ | Последняя стабильная версия |

### Необходимые компоненты

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y python3 python3-pip python3-venv \
  git curl wget gnupg2 postgresql-client

# CentOS/RHEL
sudo dnf install -y python3 python3-pip git curl wget

# Проверка версий
python3 --version
git --version
ansible --version
```

---

## Установка

### Способ 1: Docker (рекомендуемый)

#### Минимальный вариант (BoltDB — без внешней БД)

```yaml
# docker-compose.yml
---
version: "3.8"

services:
  semaphore:
    image: semaphoreui/semaphore:latest
    container_name: semaphore
    ports:
      - "3000:3000"
    environment:
      SEMAPHORE_DB_DIALECT: bolt
      SEMAPHORE_ADMIN_PASSWORD: "changeme_strong_password"
      SEMAPHORE_ADMIN_NAME: admin
      SEMAPHORE_ADMIN_EMAIL: admin@yourdomain.com
      SEMAPHORE_ADMIN: admin
      SEMAPHORE_ACCESS_KEY_ENCRYPTION: "${SEMAPHORE_ACCESS_KEY_ENCRYPTION}"
    volumes:
      - semaphore-data:/var/lib/semaphore
    restart: unless-stopped

volumes:
  semaphore-data:
```

#### Production вариант (PostgreSQL)

```yaml
# docker-compose.yml
---
version: "3.8"

services:
  postgres:
    image: postgres:16-alpine
    container_name: semaphore-postgres
    environment:
      POSTGRES_DB: semaphore
      POSTGRES_USER: semaphore
      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    restart: unless-stopped

  semaphore:
    image: semaphoreui/semaphore:latest
    container_name: semaphore
    ports:
      - "3000:3000"
    environment:
      SEMAPHORE_DB_DIALECT: postgres
      SEMAPHORE_DB_HOST: postgres
      SEMAPHORE_DB_PORT: 5432
      SEMAPHORE_DB_USER: semaphore
      SEMAPHORE_DB_PASS: "${POSTGRES_PASSWORD}"
      SEMAPHORE_DB_DIALECT: postgres
      SEMAPHORE_ADMIN_PASSWORD: "${SEMAPHORE_ADMIN_PASSWORD}"
      SEMAPHORE_ADMIN_NAME: admin
      SEMAPHORE_ADMIN_EMAIL: admin@yourdomain.com
      SEMAPHORE_ADMIN: admin
      SEMAPHORE_ACCESS_KEY_ENCRYPTION: "${SEMAPHORE_ACCESS_KEY_ENCRYPTION}"
    volumes:
      - semaphore-config:/etc/semaphore
      - semaphore-tmp:/tmp/semaphore
    depends_on:
      - postgres
    restart: unless-stopped

volumes:
  postgres-data:
  semaphore-config:
  semaphore-tmp:
```

#### .env файл для Docker Compose

```bash
# .env
POSTGRES_PASSWORD=your_strong_postgres_password
SEMAPHORE_ADMIN_PASSWORD=your_strong_admin_password
SEMAPHORE_ACCESS_KEY_ENCRYPTION=$(openssl rand -hex 32)
```

#### Генерация ключа шифрования

```bash
# Автоматическая генерация при первом запуске (Docker)
# Или вручную:
SEMAPHORE_ACCESS_KEY_ENCRYPTION=$(openssl rand -hex 32)
echo "SEMAPHORE_ACCESS_KEY_ENCRYPTION=${SEMAPHORE_ACCESS_KEY_ENCRYPTION}"
```

#### Запуск

```bash
# Запуск в фоновом режиме
docker compose up -d

# Просмотр логов
docker compose logs -f semaphore

# Остановка
docker compose down

# Обновление
docker compose pull && docker compose up -d
```

### Способ 2: Docker Compose с Nginx (production)

```yaml
# docker-compose.yml
---
version: "3.8"

services:
  postgres:
    image: postgres:16-alpine
    container_name: semaphore-postgres
    environment:
      POSTGRES_DB: semaphore
      POSTGRES_USER: semaphore
      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD}"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    restart: unless-stopped

  semaphore:
    image: semaphoreui/semaphore:latest
    container_name: semaphore
    environment:
      SEMAPHORE_DB_DIALECT: postgres
      SEMAPHORE_DB_HOST: postgres
      SEMAPHORE_DB_PORT: 5432
      SEMAPHORE_DB_USER: semaphore
      SEMAPHORE_DB_PASS: "${POSTGRES_PASSWORD}"
      SEMAPHORE_ADMIN_PASSWORD: "${SEMAPHORE_ADMIN_PASSWORD}"
      SEMAPHORE_ADMIN_NAME: admin
      SEMAPHORE_ADMIN_EMAIL: admin@yourdomain.com
      SEMAPHORE_ADMIN: admin
      SEMAPHORE_ACCESS_KEY_ENCRYPTION: "${SEMAPHORE_ACCESS_KEY_ENCRYPTION}"
      SEMAPHORE_WEB_ROOT: ""
    volumes:
      - semaphore-config:/etc/semaphore
      - semaphore-tmp:/tmp/semaphore
    depends_on:
      - postgres
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    container_name: semaphore-nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - semaphore
    restart: unless-stopped

volumes:
  postgres-data:
  semaphore-config:
  semaphore-tmp:
```

### Способ 3: Установка из пакета (без Docker)

```bash
# Добавление репозитория (Debian/Ubuntu)
curl -1sLf 'https://dl.cloudsmith.io/public/semaphoreui/semaphore/setup.deb.sh' | sudo -E bash

# Установка
sudo apt install semaphore

# Первичная настройка
sudo semaphore setup

# Запуск как systemd сервис
sudo systemctl enable --now semaphore
```

#### systemd unit (автоматически создается при установке из пакета)

```ini
# /etc/systemd/system/semaphore.service
[Unit]
Description=Semaphore Ansible UI
After=network.target

[Service]
Type=simple
User=semaphore
Group=semaphore
ExecStart=/usr/bin/semaphore server --config /etc/semaphore/config.json
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

#### Ручное создание systemd unit (при установке из бинарника)

```bash
# Создание пользователя
sudo useradd -r -s /bin/false semaphore
sudo mkdir -p /etc/semaphore /var/lib/semaphore
sudo chown semaphore:semaphore /etc/semaphore /var/lib/semaphore

# Скачивание бинарника
SEMAPHORE_VERSION=$(curl -s https://api.github.com/repos/semaphoreui/semaphore/releases/latest | grep tag_name | cut -d'"' -f4 | sed 's/v//')
wget "https://github.com/semaphoreui/semaphore/releases/download/v${SEMAPHORE_VERSION}/semaphore_${SEMAPHORE_VERSION}_linux_amd64.tar.gz"
tar xzf "semaphore_${SEMAPHORE_VERSION}_linux_amd64.tar.gz"
sudo mv semaphore /usr/bin/
sudo chmod +x /usr/bin/semaphore

# Первичная настройка
sudo -u semaphore semaphore setup --config /etc/semaphore/config.json
```

### Способ 4: Kubernetes (Helm)

```bash
# Добавление репозитория Helm
helm repo add semaphore https://semaphoreui.github.io/helm-charts
helm repo update

# Установка
helm install semaphore semaphore/semaphore \
  --namespace semaphore \
  --create-namespace \
  --set postgresql.enabled=true \
  --set admin.password=changeme
```

---

## Настройка

### Интерактивная настройка (CLI)

```bash
# Интерактивный мастер настройки
semaphore setup --config /etc/semaphore/config.json

# Примеры ответов:
# > What DB engine do you want to use? → postgres
# > DB Host? → localhost
# > DB Port? → 5432
# > DB User? → semaphore
# > DB Password? → ****
# > DB Name? → semaphore
# > Playbook path? → /var/lib/semaphore
# > Webroot? → http://yourdomain.com
# > Telegram chat ID? → (Enter to skip)
# > Alerting bot token? → (Enter to skip)

# Или запуск в неинтерактивном режиме:
semaphore setup --config /etc/semaphore/config.json \
  --db-host localhost \
  --db-port 5432 \
  --db-user semaphore \
  --db-pass "password" \
  --db-name semaphore \
  --db-dialect postgres \
  --admin-user admin \
  --admin-password "changeme" \
  --admin-email "admin@yourdomain.com" \
  --web-host "http://yourdomain.com"
```

### Конфигурационный файл

```json
// /etc/semaphore/config.json
{
  "bolt": {
    "host": "",
    "port": 0,
    "database": "semaphore",
    "user": "",
    "password": ""
  },

  "postgres": {
    "host": "localhost",
    "port": 5432,
    "user": "semaphore",
    "password": "your_password",
    "database": "semaphore",
    "options": {}
  },

  "dialect": "postgres",

  "tmp_path": "/tmp/semaphore",
  "tmpirc_path": "/tmp/semaphore",
  "max_parallel_tasks": 10,
  "max_task_duration_sec": 3600,
  "max_tasks_per_template": 100,
  "schedule_timezone": "UTC",

  "git_client": "cmd_git",
  "ssh_config_path": "~/.ssh/config",

  "web_host": "https://semaphore.example.com",
  "interface": "",
  "port": 3000,

  "access_key_encryption": "your_64_byte_hex_key",

  "cookie_hash": "your_cookie_hash_key",
  "cookie_encryption": "your_cookie_encryption_key",

  "email_alert": false,
  "email_host": "smtp.example.com",
  "email_port": 587,
  "email_username": "user@example.com",
  "email_password": "smtp_password",
  "email_sender": "semaphore@example.com",
  "email_secure": true,

  "telegram_alert": false,
  "telegram_chat": "",
  "telegram_token": "",

  "slack_alert": false,
  "slack_url": "",

  "ldap_enable": false,
  "ldap_needtls": false,
  "ldap_binddn": "cn=admin,dc=example,dc=org",
  "ldap_bindpassword": "ldap_password",
  "ldap_server": "ldap.example.com:636",
  "ldap_searchdn": "dc=example,dc=org",
  "ldap_searchfilter": "(&(objectClass=inetOrgPerson)(uid=%s))",

  "oidc_providers": [],

  "mfa": {
    "totp": {
      "enabled": false,
      "allow_recovery": true
    }
  },

  "runner": {
    "enabled": false,
    "token": "",
    "max_parallel_tasks": 4
  }
}
```

### Переменные окружения (Docker)

Все параметры конфигурации доступны через переменные окружения с префиксом `SEMAPHORE_`. Примеры:

```bash
# Базовая конфигурация
SEMAPHORE_DB_DIALECT=postgres
SEMAPHORE_DB_HOST=localhost
SEMAPHORE_DB_PORT=5432
SEMAPHORE_DB_USER=semaphore
SEMAPHORE_DB_PASS=password
SEMAPHORE_DB_NAME=semaphore

# Администратор
SEMAPHORE_ADMIN=admin
SEMAPHORE_ADMIN_PASSWORD=changeme
SEMAPHORE_ADMIN_NAME=admin
SEMAPHORE_ADMIN_EMAIL=admin@yourdomain.com

# Безопасность
SEMAPHORE_ACCESS_KEY_ENCRYPTION=your_64_byte_hex_key

# Сервер
SEMAPHORE_PORT=3000
SEMAPHORE_WEB_ROOT=""
SEMAPHORE_MAX_PARALLEL_TASKS=10

# Git
SEMAPHORE_GIT_CLIENT=cmd_git
```

---

## Настройка обратного прокси (Nginx)

### Nginx с SSL (Let's Encrypt)

```nginx
# /etc/nginx/sites-available/semaphore
upstream semaphore_backend {
    server 127.0.0.1:3000;
}

server {
    listen 80;
    server_name semaphore.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name semaphore.example.com;

    ssl_certificate /etc/letsencrypt/live/semaphore.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/semaphore.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    client_max_body_size 50m;

    location / {
        proxy_pass http://semaphore_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket поддержка
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    # Логи
    access_log /var/log/nginx/semaphore_access.log;
    error_log /var/log/nginx/semaphore_error.log;
}
```

### Установка и настройка Nginx

```bash
# Установка Nginx
sudo apt install nginx

# Включение сайта
sudo ln -s /etc/nginx/sites-available/semaphore /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default

# Проверка конфигурации
sudo nginx -t

# Перезапуск Nginx
sudo systemctl reload nginx

# Установка SSL-сертификата
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d semaphore.example.com
sudo certbot renew --dry-run
```

### Публичный URL (behind reverse proxy)

Если Semaphore работает за обратным прокси и доступен по подпути (например, `https://example.com/semaphore`), установите `web_host`:

```json
{
  "web_host": "https://example.com/semaphore"
}
```

Или через переменную окружения:
```bash
SEMAPHORE_WEB_ROOT=https://example.com/semaphore
```

---

## Работа с плейбуками

### Создание шаблона задания (Task Template)

#### Через Web UI

1. Перейдите в **Task Templates** → **New Template**
2. Выберите тип **Ansible Playbook**
3. Заполните параметры:
   - **Name**: Имя шаблона (например, "Deploy Web Application")
   - **Repository**: Git-репозиторий с плейбуками
   - **Playbook file path**: Путь к файлу плейбука (например, `deploy.yml`)
   - **Inventory**: Инвентарь (группы хостов)
   - **Environment**: Группы переменных
   - **SSH Key**: SSH-ключ для подключения к хостам
   - **Vault passwords**: Пароли Ansible Vault (если используются)
   - **Extra CLI arguments**: Дополнительные аргументы (например, `--tags deploy --limit webservers`)
   - **Verbosity**: Уровень детализации вывода (`-v`, `-vv`, `-vvv`)

#### Типы шаблонов

| Тип | Описание | Использование |
| :--- | :--- | :--- |
| **Task** | Обычный запуск плейбука | Ручной или автоматический запуск |
| **Build** | Создание артефактов | CI/CD, инкрементирование версий |
| **Deploy** | Развёртывание артефактов | Деплой конкретной версии на серверы |

#### Пример: шаблон с тегами и лимитом

```yaml
# Шаблон в UI:
Name: "Deploy Application"
Repository: "infrastructure-playbooks"
Playbook: "deploy.yml"
Inventory: "Production"
Environment: "Production Variables"
SSH Key: "Server SSH Key"
Extra CLI arguments: "--tags deploy --limit webservers -vvv"
Verbosity: 3
```

### Планирование заданий (Schedules)

#### Через Web UI

1. Перейдите в шаблон задания → **Schedules**
2. Добавьте расписание с cron-выражением
3. Укажите название расписания

#### Примеры cron-расписаний

```bash
# Ежедневно в 2:00 ночи
0 2 * * *

# Каждые 6 часов
0 */6 * * *

# По будням в 8:00 утра
0 8 * * 1-5

# Каждые 15 минут (для мониторинга)
*/15 * * * *

# Первый понедельник каждого месяца в 9:00
0 9 * * 1
```

#### Автоматический запуск при коммите в Git

Настройте webhook в GitHub/GitLab для вызова API Semaphore при пуше:

```bash
# Пример curl-запроса для запуска задания
curl -X POST "https://semaphore.example.com/api/project/1/tasks" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"template_id": 1, "debug": false}'
```

### Переменные и Vault

#### Группы переменных (Variable Groups)

1. Перейдите в **Variable Groups** → **New Variable Group**
2. Задайте имя и переменные

```yaml
# Пример переменных
app_version: "2.1.0"
deploy_user: "deploy"
database_host: "db.example.com"
database_port: 5432
environment: "production"

# Vault-переменные (зашифрованные)
vault_db_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  61626364656667686970...
```

#### SSH-ключи (Key Store)

1. Перейдите в **Key Store** → **New Key**
2. Выберите тип:
   - **SSH Key**: Приватный SSH-ключ для подключения к хостам
   - **Password**: Пароль для подключения или Vault
   - **None**: Ключ не используется

```bash
# Генерация SSH-ключа для Semaphore
ssh-keygen -t ed25519 -f ~/.ssh/semaphore_key -N ""

# Копирование публичного ключа на целевые хосты
ssh-copy-id -i ~/.ssh/semaphore_key.pub user@target-host
```

### Инвентарь (Inventory)

#### Статический инвентарь

```yaml
# inventory/production.yml
---
all:
  children:
    webservers:
      hosts:
        web01.example.com:
          ansible_host: 192.168.1.10
        web02.example.com:
          ansible_host: 192.168.1.11
      vars:
        ansible_user: deploy
        ansible_ssh_private_key_file: /path/to/key

    dbservers:
      hosts:
        db01.example.com:
          ansible_host: 192.168.1.20
      vars:
        ansible_user: admin
```

#### Динамический инвентарь

Semaphore поддерживает динамические инвентари через скрипты или плагины Ansible.

### Дополнительные Python-пакеты

Если Ansible-модули требуют дополнительных Python-пакетов:

```bash
# Создание requirements.txt
cat > /path/to/requirements.txt << EOF
boto3>=1.28.0
botocore>=1.31.0
requests>=2.31.0
pywinrm>=0.4.1
EOF
```

```yaml
# В Docker Compose — монтирование requirements.txt
volumes:
  - /path/to/requirements.txt:/etc/semaphore/requirements.txt
```

При запуске контейнера Semaphore автоматически установит пакеты из `requirements.txt`.

---

## Управление через API

### Аутентификация

```bash
# Получение токена через логин/пароль
TOKEN=$(curl -s -X POST "http://localhost:3000/api/auth/login" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"auth": "admin", "password": "your-password"}' | jq -r '.token')

echo $TOKEN
```

### Основные операции

```bash
# Просмотр проектов
curl -s "http://localhost:3000/api/projects" \
  -H "Authorization: Bearer $TOKEN" | jq

# Просмотр шаблонов проекта
curl -s "http://localhost:3000/api/project/1/templates" \
  -H "Authorization: Bearer $TOKEN" | jq

# Запуск задания
curl -X POST "http://localhost:3000/api/project/1/tasks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": 1,
    "debug": false,
    "dry_run": false,
    "playbook": "deploy.yml",
    "environment": "production"
  }'

# Просмотр статуса задания
curl -s "http://localhost:3000/api/project/1/tasks/42" \
  -H "Authorization: Bearer $TOKEN" | jq '{status, start, end}'

# Просмотр лога задания
curl -s "http://localhost:3000/api/project/1/tasks/42/output" \
  -H "Authorization: Bearer $TOKEN"

# Просмотр инвентаря
curl -s "http://localhost:3000/api/project/1/inventory" \
  -H "Authorization: Bearer $TOKEN" | jq

# Просмотр ключей
curl -s "http://localhost:3000/api/project/1/keys" \
  -H "Authorization: Bearer $TOKEN" | jq

# Просмотр переменных
curl -s "http://localhost:3000/api/project/1/environment" \
  -H "Authorization: Bearer $TOKEN" | jq

# Просмотр репозиториев
curl -s "http://localhost:3000/api/project/1/repositories" \
  -H "Authorization: Bearer $TOKEN" | jq

# Запуск задания с лимитом
curl -X POST "http://localhost:3000/api/project/1/tasks" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": 1,
    "limit": "webservers"
  }'
```

### Создание API-токена через Web UI (с версии 2.14)

1. Перейдите в **User Settings** → **API Tokens**
2. Нажмите **Create Token**
3. Укажите имя токена и срок действия

### Удаление API-токена

```bash
curl -X DELETE "http://localhost:3000/api/user/tokens/YOUR_ACCESS_TOKEN" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Удалённые исполнители (Runners)

### Концепция

Runners позволяют выполнять задачи на отдельных серверах, не на сервере Semaphore UI. Это аналогично GitLab Runner или GitHub Actions Runner.

**Преимущества:**
- Повышение безопасности (задачи в изолированных контейнерах/подсетях)
- Распределение нагрузки по нескольким серверам
- Возможность выполнения в Kubernetes или Docker

### Настройка сервера

```json
// Конфигурация Semaphore сервера для работы с runners
{
  "use_remote_runner": true,
  "runner_registration_token": "your_random_registration_token"
}
```

```bash
# Или через переменные окружения
SEMAPHORE_USE_REMOTE_RUNNER=True
SEMAPHORE_RUNNER_REGISTRATION_TOKEN=your_random_registration_token
```

### Настройка runner'а

```bash
# Интерактивная настройка
semaphore runner setup --config /etc/semaphore-runner/config.json

# Регистрация runner'а
semaphore runner register --config /etc/semaphore-runner/config.json

# Или через stdin
echo REGISTRATION_TOKEN | semaphore runner register \
  --stdin-registration-token \
  --config /etc/semaphore-runner/config.json

# Запуск runner'а
semaphore runner start --config /etc/semaphore-runner/config.json

# Остановка runner'а
semaphore runner stop --config /etc/semaphore-runner/config.json

# Удаление runner'а
semaphore runner unregister --config /etc/semaphore-runner/config.json
```

### Конфигурация runner'а

```json
// /etc/semaphore-runner/config.json
{
  "tmp_path": "/tmp/semaphore",
  "web_host": "https://semaphore.example.com",

  "runner": {
    "token": "your_runner_token",
    "name": "production-runner-01",
    "max_parallel_tasks": 4,
    "tags": ["production", "web"],
    "one_off": false,

    "executor": {
      "type": "local"
    }
  }
}
```

### Executor'ы (стратегии выполнения)

| Executor | Описание | Когда использовать |
| :--- | :--- | :--- |
| **local** (по умолчанию) | Выполнение на сервере runner'а | Простые сценарии, малая нагрузка |
| **docker** | Запуск в Docker-контейнере | Изоляция, воспроизводимость |
| **k8s** | Запуск в Kubernetes Pod | Масштабирование, облачные среды |

#### Docker executor

```json
{
  "runner": {
    "executor": {
      "type": "docker",
      "docker": {
        "host": "unix:///var/run/docker.sock",
        "image": "semaphoreui/job:latest",
        "helper_image": "semaphoreui/helper:latest",
        "network": "semaphore_network",
        "pull_policy": "if-not-present",
        "cpu_limit": 2,
        "memory_limit": "2g",
        "cleanup_grace_seconds": 30
      }
    }
  }
}
```

#### Kubernetes executor

```json
{
  "runner": {
    "executor": {
      "type": "k8s",
      "k8s": {
        "namespace": "semaphore",
        "image": "semaphoreui/job:latest",
        "helper_image": "semaphoreui/helper:latest",
        "service_account": "default",
        "poll_interval_seconds": 3,
        "cleanup_grace_seconds": 30
      }
    }
  }
}
```

---

## Уведомления

### Telegram

```json
{
  "telegram_alert": true,
  "telegram_chat": "YOUR_CHAT_ID",
  "telegram_token": "YOUR_BOT_TOKEN"
}
```

```bash
# Настройка через переменные окружения
SEMAPHORE_TELEGRAM_ALERT=true
SEMAPHORE_TELEGRAM_CHAT=YOUR_CHAT_ID
SEMAPHORE_TELEGRAM_TOKEN=YOUR_BOT_TOKEN
```

### Slack

```json
{
  "slack_alert": true,
  "slack_url": "https://hooks.slack.com/services/XXX/YYY/ZZZ"
}
```

### Email

```json
{
  "email_alert": true,
  "email_host": "smtp.example.com",
  "email_port": 587,
  "email_username": "user@example.com",
  "email_password": "smtp_password",
  "email_sender": "semaphore@example.com",
  "email_secure": true
}
```

### Microsoft Teams

```json
{
  "microsoft_teams_alert": true,
  "microsoft_teams_url": "https://outlook.office.com/webhook/XXX"
}
```

### Rocket.Chat

```json
{
  "rocketchat_alert": true,
  "rocketchat_url": "https://chat.example.com/hooks/XXX"
}
```

### Gotify

```json
{
  "gotify_alert": true,
  "gotify_url": "https://gotify.example.com",
  "gotify_token": "YOUR_GOTIFY_TOKEN"
}
```

---

## Безопасность

### Двухфакторная аутентификация (2FA/MFA)

```json
{
  "mfa": {
    "totp": {
      "enabled": true,
      "allow_recovery": true
    },
    "email": {
      "enabled": false
    }
  }
}
```

### LDAP/AD аутентификация

```json
{
  "ldap_enable": true,
  "ldap_needtls": true,
  "ldap_server": "ldap.example.com:636",
  "ldap_binddn": "cn=admin,dc=example,dc=org",
  "ldap_bindpassword": "ldap_password",
  "ldap_searchdn": "dc=example,dc=org",
  "ldap_searchfilter": "(&(objectClass=inetOrgPerson)(uid=%s))",
  "ldap_mappings": {
    "dn": "dn",
    "mail": "mail",
    "uid": "uid",
    "cn": "cn"
  }
}
```

### OpenID Connect (OIDC)

```json
{
  "oidc_providers": [
    {
      "name": "Keycloak",
      "client_id": "semaphore",
      "client_secret": "your_client_secret",
      "issuer_url": "https://keycloak.example.com/realms/master",
      "redirect_url": "https://semaphore.example.com/api/auth/oidc/keycloak/callback",
      "scopes": ["openid", "email", "profile"]
    }
  ]
}
```

### Шифрование ключей доступа

```bash
# Генерация ключа шифрования (64 hex-символа = 32 байта)
ACCESS_KEY=$(openssl rand -hex 32)
echo "SEMAPHORE_ACCESS_KEY_ENCRYPTION=${ACCESS_KEY}"
```

### Защита паролей и секретов

- **Не коммитьте** `config.json` с секретами в Git
- Используйте переменные окружения или Vault для хранения паролей
- Регулярно ротируйте ключи шифрования

---

## Мониторинг и метрики

### Проверка здоровья (Health Check)

```bash
# Эндпоинт для мониторинга
curl -s http://localhost:3000/api/ping
# Ответ: pong
```

### Метрики Prometheus (Pro)

```json
{
  "metrics": {
    "enabled": true,
    "bind": ":9090"
  }
}
```

```bash
# Пример конфигурации Prometheus scrape
scrape_configs:
  - job_name: 'semaphore'
    static_configs:
      - targets: ['semaphore:9090']
```

---

## Сравнение с AWX

| Характеристика | Semaphore | AWX | AAP |
| :--- | :--- | :--- | :--- |
| **Язык** | Go | Python | Python |
| **БД** | SQLite, MySQL, PostgreSQL | PostgreSQL | PostgreSQL |
| **Мин. RAM** | 1 ГБ | 4 ГБ | 8+ ГБ |
| **Установка** | Docker, пакет, бинарник | Docker, K8s | Docker, K8s |
| **Динамический инвентарь** | Нет (через скрипты) | Да | Да |
| **Workflows** | Нет | Да | Да |
| **RBAC** | Базовый (команды) | Расширенный | Полный |
| **REST API** | Да | Да | Да |
| **WebSocket** | Да | Да | Да |
| **Планирование** | Cron | Cron | Cron |
| **Runners** | Да (удалённые) | Да ( Execution Environments) | Automation Mesh |
| **Terraform/OpenTofu** | Да | Нет | Нет |
| **Shell/PowerShell** | Да | Нет | Нет |
| **Стоимость** | Бесплатно | Бесплатно | Платно |

**Когда выбирать Semaphore:**
- Небольшая команда, простые сценарии
- Нет Kubernetes
- Нужна минимальная инфраструктура
- Важна скорость и простота
- Нужна поддержка Terraform/OpenTofu

**Когда выбирать AWX:**
- Нужны Workflows и Dynamic Inventory
- Средний/крупный масштаб
- Есть Kubernetes
- Нужен расширенный RBAC

---

## CI/CD интеграция

### GitHub Actions → Semaphore

```yaml
# .github/workflows/deploy.yml
---
name: Deploy via Semaphore
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Semaphore Task
        run: |
          curl -X POST "${{ secrets.SEMAPHORE_URL }}/api/project/${{ secrets.PROJECT_ID }}/tasks" \
            -H "Authorization: Bearer ${{ secrets.SEMAPHORE_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d '{"template_id": ${{ secrets.TEMPLATE_ID }}}'
```

### GitLab CI → Semaphore

```yaml
# .gitlab-ci.yml
---
deploy:
  stage: deploy
  script:
    - |
      curl -X POST "${SEMAPHORE_URL}/api/project/${PROJECT_ID}/tasks" \
        -H "Authorization: Bearer ${SEMAPHORE_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"template_id\": ${TEMPLATE_ID}}"
  only:
    - main
```

### Автоматический запуск при коммите

Настройте cron-расписание для проверки новых коммитов:

```bash
# cron: каждые 5 минут проверять коммиты
*/5 * * * * /path/to/check-and-trigger.sh

#!/bin/bash
# check-and-trigger.sh
LAST_COMMIT=$(git -C /path/to/repo rev-parse HEAD)
STORED_COMMIT=$(cat /tmp/last_commit)

if [ "$LAST_COMMIT" != "$STORED_COMMIT" ]; then
  curl -X POST "https://semaphore.example.com/api/project/1/tasks" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"template_id": 1}'
  echo "$LAST_COMMIT" > /tmp/last_commit
fi
```

---

## Поиск и устранение неисправностей

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `permission denied` | Нет прав на выполнение плейбука | Проверьте SSH-ключ и права доступа |
| `Vault password not set` | Не указан пароль Vault | Добавьте Vault password в Key Store |
| `Repository not found` | Git-репозиторий недоступен | Проверьте URL, токен доступа, DNS |
| `template not found` | Шаблон не найден или удалён | Проверьте ID шаблона в UI |
| `connection refused` | Semaphore не запущен | `systemctl start semaphore` или `docker compose up -d` |
| `database connection failed` | Проблемы с БД | Проверьте настройки подключения к БД |
| `task timeout` | Задание выполняется слишком долго | Увеличьте `max_task_duration_sec` |
| `runner offline` | Runner не подключен | Проверьте статус runner'а, перезапустите |

### Диагностические команды

```bash
# Проверка статуса Semaphore
sudo systemctl status semaphore

# Просмотр логов
sudo journalctl -u semaphore -f
# Или для Docker:
docker compose logs -f semaphore

# Проверка конфигурации
semaphore config show --config /etc/semaphore/config.json

# Проверка подключения к БД
semaphore db check --config /etc/semaphore/config.json

# Миграция БД (при обновлении)
semaphore db migrate --config /etc/semaphore/config.json

# Проверка API
curl -s http://localhost:3000/api/ping

# Проверка Git-клиента
which git
git --version

# Проверка Ansible
which ansible-playbook
ansible --version

# Проверка Python-пакетов (в контейнере)
docker exec semaphore pip list
```

### Проверка вне Semaphore

Для исключения проблем с окружением:

```bash
# Переключение на пользователя semaphore
sudo su --login semaphore

# Активация venv (если используется)
source /home/semaphore/venv/bin/activate

# Ручной запуск плейбука
ansible-playbook /path/to/playbook.yml -i /path/to/inventory

# Если плейбук работает через CLI — проблема в конфигурации Semaphore
# Если плейбук НЕ работает через CLI — проблема в окружении
```

---

## Лучшие практики

1. **Храните плейбуки в Git** —Semaphore работает с Git-репозиториями; используйте ветвление для environments.
2. **Используйте Variable Groups** — разделяйте переменные для dev/staging/production.
3. **Настройте Vault** — зашифровывайте пароли и секреты через Ansible Vault.
4. **Регулярно обновляйте** — `docker compose pull && docker compose up -d` или `apt update && apt upgrade semaphore`.
5. **Настройте бэкапы** — для PostgreSQL используйте `pg_dump`; для SQLite — копирование файла БД.
6. **Ограничьте параллельность** — `max_parallel_tasks` предотвратит перегрузку сервера.
7. **Настройте уведомления** — Telegram/Slack/email для мониторинга заданий.
8. **Используйте Runners** — для изоляции задач и масштабирования.
9. **Настройте SSL/TLS** — всегда используйте HTTPS в production.
10. **Мониторьте `/api/ping`** — интегрируйте с Prometheus/Grafana/Zabbix.

---

## Дополнительная информация

*   [Официальная документация Semaphore UI](https://docs.semaphoreui.com/)
*   [GitHub: semaphoreui/semaphore](https://github.com/semaphoreui/semaphore)
*   [Swagger API Documentation](https://semaphoreui.com/api-docs)
*   [Postman Collection](https://www.postman.com/semaphoreui)
*   [Discord Community](https://discord.gg/5R6k7hNGcH)
*   [Docker Hub](https://hub.docker.com/r/semaphoreui/semaphore)
*   [Semaphore UI vs AWX](https://docs.semaphoreui.com/faq/semaphore-vs-awx)
*   [Сравнение: AWX vs Semaphore](./awx_ansible.md) — подробное сравнение возможностей
*   [Установка AWX](./awx_installation.md) — если нужен более функциональный вариант
*   [Ansible: Использование ролей](./ansible_roles.md) — работа с ролями через Semaphore
*   [Ansible: Использование плейбуков](./ansible_playbooks.md) — создание плейбуков для запуска
