# Установка Self-Hosted GitLab CE с помощью Docker
## Определения

**GitLab CE (Community Edition)** — бесплатная и открытая версия платформы GitLab для самостоятельного размещения (self-hosted), включающая полный цикл DevSecOps: от управления исходным кодом до мониторинга и интеграции с AI.

**Self-Hosted** — модель деплоя, при которой ПО устанавливается на собственной инфраструктуре (On-premise или Private Cloud), обеспечивая полный суверенитет над данными, исходным кодом и пайплайнами.

**GitLab Omnibus** — монолитный программный пакет, объединяющий все компоненты GitLab (Nginx, PostgreSQL, Valkey/Redis, Puma, Sidekiq, Gitaly). Docker-образ GitLab является официальным способом запуска этого пакета в изолированной среде.

**Valkey** — высокопроизводительное хранилище структур данных in-memory (форк Redis), используемое в GitLab 19.x как основной механизм кэширования и брокер сообщений для Sidekiq.

**GitLab Duo (Self-Managed)** — набор функций на базе искусственного интеллекта (Code Suggestions, Security Review), доступный для self-hosted инстансов через интеграцию с AI Gateway.

## Основные концепции

### Архитектура и выбор среды

Хотя исторически Omnibus на VM считался "золотым стандартом", в 2026 году Docker-инсталляция на базе Ubuntu 24.04 LTS является предпочтительной из-за простоты обновлений и изоляции зависимостей (особенно критично для PostgreSQL 17).

- **Дисковая подсистема:** GitLab 19.x крайне чувствителен к задержкам I/O из-за интенсивной работы Gitaly (хранилище git-репозиториев). Использование SSD/NVMe и драйвера `overlay2` является обязательным требованием для Production.
- **Управление памятью:** GitLab — ресурсоемкое Java/Ruby/Go приложение. В 19.x базовое потребление выросло из-за метрик и AI-интеграций. Ограничение CPU и RAM через Docker Cgroups предотвращает OOM-kill хоста.
- **Shared Memory (`shm_size`):** Для стабильной работы веб-сервера Puma и системы метрик требуется минимум 1GB общей памяти. Стандартные 64MB в Docker приведут к частым ошибкам 502/504.

### Ключевые компоненты и зависимости

- **PostgreSQL 17:** Минимально поддерживаемая версия БД в GitLab 19.0+. При миграции со старых инстансов (17.x/18.x) требуется предварительное обновление схемы данных.
- **Смена Redis на Valkey:** В версии 19.x GitLab официально перешел на поддержку Valkey 7.2+. Это обеспечивает лучшую производительность при многопоточной нагрузке Sidekiq.
- **External URL:** Параметр `external_url` в `gitlab.rb` определяет не только адрес в браузере, но и внутреннюю логику формирования ссылок в API, уведомлениях и Git-адресах.

## Практические сценарии

### Предварительные требования

**Аппаратные ресурсы (Production для 20+ пользователей):**
- **CPU:** 8 vCPUs (минимально 4 для тестов).
- **RAM:** 16 ГБ (8 ГБ — абсолютный минимум, требующий настройки swap).
- **Storage:** 100 ГБ+ на SSD/NVMe (зависит от объема репозиториев и артефактов).

**Системные зависимости:**
- Docker Engine 27.0+ / Docker Compose v2.20+.
- Хост-ОС: Ubuntu 24.04 LTS или аналогичная с ядром 6.8+.

**Сетевые требования:**
- DNS `A`-запись (например, `gitlab.example.com`).
- Открытые порты: `80`, `443` (Web/API/Registry) и `2222` (SSH, если 22 занят хостом).
- Разрешенный исходящий HTTPS доступ к `cloud.gitlab.com` для работы GitLab Duo.

### Шаг 1: Подготовка инфраструктуры

Создайте структуру директорий. Рекомендуется использовать переменную окружения `$GITLAB_HOME` для унификации путей.

```bash
# Определяем путь в текущей сессии (или добавьте в ~/.bashrc)
export GITLAB_HOME=$HOME/gitlab

mkdir -p $GITLAB_HOME/{config,logs,data}
chmod -R 755 $GITLAB_HOME
```

### Шаг 2: Создание конфигурации Docker Compose

Создайте файл `$GITLAB_HOME/docker-compose.yml`. В этой версии мы используем Valkey и оптимизированные настройки для GitLab 19.x.

```yaml
services:
  gitlab:
    image: 'gitlab/gitlab-ce:19.2.2-ce.0'
    container_name: gitlab
    restart: always
    hostname: 'gitlab.example.com'
    environment:
      GITLAB_OMNIBUS_CONFIG: |
        external_url 'https://gitlab.example.com'
        # Настройка кэша: переход на Valkey
        redis['backend'] = 'valkey'
        # SSH на нестандартном порту
        gitlab_rails['gitlab_shell_ssh_port'] = 2222
        # Интеграция с AI Gateway (GitLab Duo)
        gitlab_rails['ai_gateway_url'] = 'https://cloud.gitlab.com'
        # Оптимизация для PostgreSQL 17
        postgresql['shared_buffers'] = "1GB"
    ports:
      - '80:80'
      - '443:443'
      - '2222:22'
    volumes:
      - '$GITLAB_HOME/config:/etc/gitlab'
      - '$GITLAB_HOME/logs:/var/log/gitlab'
      - '$GITLAB_HOME/data:/var/opt/gitlab'
    shm_size: '1gb'
    deploy:
      resources:
        limits:
          memory: 16G
        reservations:
          memory: 8G
```

### Шаг 3: Настройка SSL/TLS (Let's Encrypt или собственный сертификат)

**Вариант A: Let's Encrypt (рекомендуется для публичных серверов)**

Для автоматического получения сертификата через Let's Encrypt домен должен быть доступен из интернета на порту 80.

```ruby
# В GITLAB_OMNIBUS_CONFIG:
external_url 'https://gitlab.example.com'

# Let's Encrypt автоматически получит сертификат
letsencrypt['enable'] = true
letsencrypt['contact_emails'] = ['admin@example.com']
letsencrypt['auto_renew'] = true
letsencrypt['auto_renew_hour'] = 3
letsencrypt['auto_renew_minute'] = 30
```

**Вариант B: Собственный сертификат (самоподписанный или от внутреннего CA)**

```bash
# Генерация самоподписанного сертификата (для тестов)
mkdir -p $GITLAB_HOME/config/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout $GITLAB_HOME/config/ssl/gitlab.key \
  -out $GITLAB_HOME/config/ssl/gitlab.crt \
  -subj "/CN=gitlab.example.com"
chmod 600 $GITLAB_HOME/config/ssl/gitlab.key
```

```ruby
# В GITLAB_OMNIBUS_CONFIG:
external_url 'https://gitlab.example.com'
nginx['ssl_certificate'] = "/etc/gitlab/ssl/gitlab.crt"
nginx['ssl_certificate_key'] = "/etc/gitlab/ssl/gitlab.key"
nginx['ssl_protocols'] = "TLSv1.2 TLSv1.3"
nginx['ssl_ciphers'] = "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384"
nginx['ssl_prefer_server_ciphers'] = "on"
```

### Шаг 4: Настройка сетевой безопасности (Firewall)

Настройте файрвол на хосте для ограничения доступа к GitLab:

```bash
# Ubuntu/Debian (UFW)
sudo ufw allow 80/tcp    # HTTP (для Let's Encrypt и редиректа)
sudo ufw allow 443/tcp   # HTTPS
sudo ufw allow 2222/tcp  # SSH (Git SSH через нестандартный порт)
sudo ufw enable
sudo ufw status verbose
# → Status: active
# → To                         Action      From
# → 80/tcp                     ALLOW       Anywhere
# → 443/tcp                    ALLOW       Anywhere
# → 2222/tcp                   ALLOW       Anywhere
```

```bash
# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --permanent --add-port=443/tcp
sudo firewall-cmd --permanent --add-port=2222/tcp
sudo firewall-cmd --reload
```

**Важно:** Если GitLab находится за обратным прокси (Nginx/Traefik), открывайте порты только на прокси, а не на хост GitLab.

### Шаг 5: Запуск и первичная инициализация

1. **Запуск контейнера:**
   ```bash
   cd $GITLAB_HOME && docker compose up -d
   ```
2. **Мониторинг логов:** Инициализация базы данных и запуск AI-сервисов в 19.x может занять до 20 минут.
   ```bash
   docker logs -f gitlab
   # Ожидайте строки: "gitlab Reconfigured!"
   ```
3. **Получение пароля `root`:**
   ```bash
   docker exec gitlab grep 'Password:' /etc/gitlab/initial_root_password
   ```
   *Внимание: Пароль автоматически удалится через 24 часа. Смените его немедленно в профиле администратора.*

### Шаг 4: Валидация установки

После входа проверьте статус компонентов:
1. **Здоровье сервисов:** `docker exec gitlab gitlab-ctl status`. Все сервисы (включая `valkey` и `postgresql`) должны быть `run`.
2. **Проверка конфигурации:** `docker exec gitlab gitlab-rake gitlab:check`.
3. **AI-функционал:** Перейдите в `Admin Area -> Settings -> General -> AI-powered features` и проверьте статус подключения к GitLab Duo.

## Техническое обслуживание и Безопасность

### Резервное копирование и Восстановление

**Критическое правило:** Бэкап GitLab состоит из двух частей:
1. **Архив данных:** Создается через `gitlab-backup`.
2. **Секреты:** Файлы `/etc/gitlab/gitlab-secrets.json` и `/etc/gitlab/gitlab.rb`. Без них восстановить БД невозможно.

**Создание бэкапа:**
```bash
docker exec gitlab gitlab-backup create
```
Архив появится в `$GITLAB_HOME/data/backups/`.

**Восстановление (Recovery):**
1. Остановите сервисы записи: `docker exec gitlab gitlab-ctl stop puma sidekiq`.
2. Запустите восстановление: `docker exec gitlab gitlab-backup restore BACKUP=<TIMESTAMP>`.
3. Скопируйте старые `gitlab-secrets.json` и `gitlab.rb` в `$GITLAB_HOME/config/`.
4. Перезапустите контейнер: `docker restart gitlab`.

### Безопасность (Hardening)

1. **Реестр контейнеров:** Если планируете использовать встроенный Registry, обязательно настройте TLS и отдельный порт.
2. **MFA:** Активируйте 2FA для всех пользователей. В 19.x доступна поддержка беспарольного входа (WebAuthn/Passkeys).
3. **Обновления:** GitLab выпускает Security patches каждый месяц. Для обновления просто измените тег образа в `docker-compose.yml` и выполните `docker compose pull && docker compose up -d`.

## Управление пользователями и группами

### Создание пользователей

```bash
# Через Rails console
docker exec -it gitlab gitlab-rails console

# Создание пользователя
user = User.new(
  name: 'John Doe',
  username: 'jdoe',
  email: 'jdoe@example.com',
  password: 'secure_password123',
  password_confirmation: 'secure_password123',
  projects_limit: 10,
  can_create_group: true
)
user.save!
```

```bash
# Через API (рекомендуется для автоматизации)
curl --request POST "https://gitlab.example.com/api/v4/users" \
  --header "PRIVATE-TOKEN: <your_admin_token>" \
  --header "Content-Type: application/json" \
  --data '{
    "name": "John Doe",
    "username": "jdoe",
    "email": "jdoe@example.com",
    "password": "secure_password123",
    "skip_confirmation": true
  }'
```

### Управление группами и проектами

```bash
# Создание группы
curl --request POST "https://gitlab.example.com/api/v4/groups" \
  --header "PRIVATE-TOKEN: <your_admin_token>" \
  --header "Content-Type: application/json" \
  --data '{
    "name": "DevOps Team",
    "path": "devops-team",
    "visibility": "internal"
  }'

# Добавление пользователя в группу с ролью
curl --request POST "https://gitlab.example.com/api/v4/groups/<group_id>/members" \
  --header "PRIVATE-TOKEN: <your_admin_token>" \
  --header "Content-Type: application/json" \
  --data '{
    "user_id": <user_id>,
    "access_level": 30
  }'
# → access_level: 30 = Developer, 40 = Maintainer, 50 = Owner
```

### Роли и разрешения

| Роль | Уровень доступа | Описание |
| :--- | :--- | :--- |
| **Guest** | 10 | Просмотр issues, комментарии к MR |
| **Reporter** | 20 | Клонирование, просмотр кода |
| **Developer** | 30 | Push в ветки, создание MR, управление Issues |
| **Maintainer** | 40 | Управление проектом, настройки CI/CD, деплой |
| **Owner** | 50 | Полный контроль, удаление проекта, настройки группы |

## Аутентификация через LDAP/Active Directory

Для интеграции с корпоративной.directory:

```ruby
# В GITLAB_OMNIBUS_CONFIG:
gitlab_rails['ldap_enabled'] = true
gitlab_rails['ldap_servers'] = {
  'main' => {
    'label' => 'Corporate LDAP',
    'host' => 'ldap.example.com',
    'port' => 636,
    'uid' => 'sAMAccountName',
    'encryption' => 'simple_ssl',
    'bind_dn' => 'CN=GitLab Service,OU=Service Accounts,DC=example,DC=com',
    'password' => 'ldapservicepassword',
    'active_directory' => true,
    'base' => 'DC=example,DC=com',
    'verify_certificates' => true,
    'allow_username_or_email_login' => true,
    'block_auto_created_users' => false,
    'base_filter' => '(objectClass=user)(memberOf=CN=GitLab Users,OU=Groups,DC=example,DC=com)',
    'timeout' => 10,
    'turn_on_sync' => true
  }
}
```

**Синхронизация групп:**

```ruby
# Маппинг LDAP-групп на роли GitLab
gitlab_rails['ldap_group_sync_cron'] = '0 2 * * *'  # Ежедневно в 2:00
gitlab_rails['ldap_group_sync_worker_cron'] = '0 2 * * *'
```

## Автоматизация резервного копирования

### Настройка cron для автоматических бэкапов

```bash
# Создание скрипта бэкапа
cat > $GITLAB_HOME/backup.sh << 'EOF'
#!/bin/bash
set -e

BACKUP_DIR="$GITLAB_HOME/data/backups"
LOG_FILE="$GITLAB_HOME/logs/backup.log"
RETENTION_DAYS=30

echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting backup..." >> "$LOG_FILE"

# Создание бэкапа
docker exec gitlab gitlab-backup create CRON=1

# Копирование секретов
cp $GITLAB_HOME/config/gitlab-secrets.json "$BACKUP_DIR/secrets_$(date +%Y%m%d).json"
cp $GITLAB_HOME/config/gitlab.rb "$BACKUP_DIR/config_$(date +%Y%m%d).rb"

# Очистка старых бэкапов
find "$BACKUP_DIR" -name "*.tar" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "secrets_*.json" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "config_*.rb" -mtime +$RETENTION_DAYS -delete

echo "$(date '+%Y-%m-%d %H:%M:%S') - Backup completed." >> "$LOG_FILE"
EOF

chmod +x $GITLAB_HOME/backup.sh
```

```bash
# Добавление в crontab
echo "0 2 * * * $GITLAB_HOME/backup.sh" | crontab -
# → Бэкап каждый день в 2:00

# Проверка crontab
crontab -l
# → 0 2 * * * /home/user/gitlab/backup.sh
```

### Offsite копирование (rsync/scp)

```bash
# Копирование бэкапов на удаленный сервер
cat > $GITLAB_HOME/offsite_backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="$GITLAB_HOME/data/backups"
REMOTE_USER="backup"
REMOTE_HOST="backup.example.com"
REMOTE_PATH="/data/gitlab-backups"

rsync -avz --progress "$BACKUP_DIR/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH/"
EOF

chmod +x $GITLAB_HOME/offsite_backup.sh
```

## Мониторинг здоровья инстанса

### Проверка статуса всех сервисов

```bash
# Проверка всех сервисов
docker exec gitlab gitlab-ctl status
# → run: gitaly: (pid 1234) 120s; run: log: (pid 1230) 120s
# → run: logrotate: (pid 1238) 120s; run: nginx: (pid 1236) 120s
# → run: postgresql: (pid 1242) 120s; run: prometheus: (pid 1240) 120s
# → run: puma: (pid 1246) 120s; run: redis: (pid 1244) 120s
# → run: sidekiq: (pid 1248) 120s; run: valkey: (pid 1250) 120s

# Проверка HTTP健康check
curl -s https://gitlab.example.com/-/health
# → {"healthy":true}
```

### Настройка Prometheus метрик

```ruby
# В GITLAB_OMNIBUS_CONFIG:
prometheus_monitoring['enable'] = true
prometheus_monitoring['listen_address'] = '0.0.0.0:9090'
prometheus_monitoring['scrape_interval'] = 15

# Экспорт метрик для внешнего Prometheus
gitlab_rails['prometheus_method'] = 'push'
gitlab_rails['prometheus_push_gateway'] = 'http://prometheus.example.com:9091'
```

### Ключевые метрики для мониторинга

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `gitlab_uptime` | Время работы инстанса | < 99.9% |
| `gitlab_build_total` | Количество пайплайнов | Задержка > 10 мин |
| `gitlab_ruby_process_cpu_seconds` | Нагрузка CPU | > 80% на 5 мин |
| `gitlab_ruby_process_resident_memory_bytes` | Потребление RAM | > 80% от лимита |
| `gitlab_database_connection_pool` | Пулы соединений с БД | Все заняты |
| `gitlab_gitaly_disk_space` | Остаток диска в Gitaly | < 20% |

## Процесс обновления GitLab

### Перед обновлением

1. **Создайте бэкап:** `docker exec gitlab gitlab-backup create`
2. **Проверьте CHANGELOG:** Находите свою текущую версию и целевую
3. **Определите путь обновления:** GitLab поддерживает обновление только на одну major-версию за раз (например, 18.x → 19.x, но не 17.x → 19.x)

### Пошаговое обновление

```bash
# 1. Остановите сервисы записи (если обновление критично)
docker exec gitlab gitlab-ctl stop puma sidekiq

# 2. Создайте бэкап
docker exec gitlab gitlab-backup create

# 3. Обновите образ в docker-compose.yml
# Измените тег: gitlab/gitlab-ce:19.2.2-ce.0 → gitlab/gitlab-ce:19.3.0-ce.0

# 4. Скачайте новый образ
docker compose pull gitlab

# 5. Запустите обновление
docker compose up -d

# 6. Мониторьте логи
docker logs -f gitlab
# Ожидайте: "gitlab Reconfigured!" и "gitlab-ctl status" показывает все сервисы run

# 7. Проверьте версию
docker exec gitlab gitlab-rake gitlab:check
# → Строка: "GitLab version: 19.3.0"
```

### Откат при проблемах

```bash
# 1. Остановите новый контейнер
docker compose down

# 2. Восстановите старый образ (измените тег обратно)
# gitlab/gitlab-ce:19.2.2-ce.0

# 3. Восстановите бэкап
docker compose up -d
docker exec gitlab gitlab-ctl stop puma sidekiq
docker exec gitlab gitlab-backup restore BACKUP=<TIMESTAMP>
cp $GITLAB_HOME/config/backup/gitlab-secrets.json $GITLAB_HOME/config/
cp $GITLAB_HOME/config/backup/gitlab.rb $GITLAB_HOME/config/
docker restart gitlab
```

## Настройка Container Registry

Для использования встроенного Docker Registry:

```ruby
# В GITLAB_OMNIBUS_CONFIG:
registry_external_url 'https://registry.gitlab.example.com'

# Настройка хранения
gitlab_rails['registry_enabled'] = true
registry['storage'] = {
  's3' => {
    'enabled' => false
  },
  'filesystem' => {
    'rootdirectory' => '/var/opt/gitlab/gitlab/shared/registry'
  }
}

# Ограничение размера образа
registry['max_blob_size'] = '100 MB'
registry['max_manifest_size'] = '10 MB'
```

```bash
# Проверка работы Registry
curl -s https://gitlab.example.com/v2/_catalog
# → {"repositories":[]}

# Вход в Registry
docker login registry.gitlab.example.com
# Username: jdoe
# Password: <personal_access_token_with_read_registry_scope>
```

## Дополнительная информация

### Работа за внешним Reverse Proxy (Nginx/Traefik)

Если SSL терминируется на внешнем балансировщике, GitLab должен знать об этом для корректного формирования заголовков. В `docker-compose.yml` (секция `GITLAB_OMNIBUS_CONFIG`):

```ruby
external_url 'https://gitlab.example.com'
nginx['listen_port'] = 80
nginx['listen_https'] = false
nginx['proxy_set_headers'] = {
  "X-Forwarded-Proto" => "https",
  "X-Forwarded-Ssl" => "on"
}
```

### Оптимизация для малых ресурсов (Low RAM)

Если доступно только 8 ГБ RAM, отключите мониторинг и ограничьте воркеры:

```ruby
prometheus_monitoring['enable'] = false
alertmanager['enable'] = false
puma['worker_processes'] = 2
sidekiq['max_concurrency'] = 5
gitaly['configuration'] = {
  storage: [{ name: 'default', path: '/var/opt/gitlab/git-data/repositories' }],
  concurrency: [{ rpc: "/gitaly.SmartHTTPService/PostReceivePack", max_per_repo: 3 }]
}
```

### Типичные ошибки и их решение (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Ошибка 502 Whoops** | Puma еще запускается или мало RAM | Подождите 5 мин или увеличьте лимиты в Compose. Проверьте: `docker exec gitlab gitlab-ctl status` |
| **PostgreSQL Upgrade Fail** | Несовместимость версий при обновлении | Выполните `gitlab-ctl pg-upgrade` перед обновлением образа. **Внимание:** pg-upgrade требует дополнительного места на диске (2x размер БД). |
| **Git Clone SSH Fail** | Порт 2222 не проброшен | Проверьте секцию `ports` в Compose и настройки Firewall: `sudo ufw status` |
| **Duo Chat не работает** | Нет связи с AI Gateway | Проверьте доступ к `cloud.gitlab.com` и настройки WebSockets в прокси |
| **Registry: "unauthorized"** | Не настроен TLS или неверный порт | Убедитесь, что `registry_external_url` совпадает с DNS-записью и портом в Compose |
| **LDAP: "Connection refused"** | Неверный хост/порт или сертификат | Проверьте `ldapsearch -H ldaps://ldap.example.com -b DC=example,DC=com` |
| **CI/CD jobs stuck in pending** | Runner не зарегистрирован или offline | Проверьте: `docker exec gitlab-runner gitlab-runner status` |
| **Sidekiq queue overflow** | Много задач, мало воркеров | Увеличьте `sidekiq['max_concurrency']` или добавьте RAM |
| **Out of memory (OOM)** | GitLab превыси лимит RAM | Увеличьте `deploy.resources.limits.memory` в Compose. Для 19.x рекомендуется 16GB+ |
| **Disk space warning** | Заполнен `/var/opt/gitlab` | Очистите старые бэкапы: `find $GITLAB_HOME/data/backups -name "*.tar" -mtime +30 -delete` |
| **SSL certificate expired** | Let's Encrypt не обновился | Проверьте: `docker exec gitlab gitlab-ctl renew-le-certs` |
| **Webhook delivery failed** | GitLab не может достучаться до внешнего URL | Проверьте сеть из контейнера: `docker exec gitlab curl -I https://target.com` |

### Смотрите также

- **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — глубокий разбор компонентов и их взаимодействия.
- **[Регистрация GitLab Runner](./runner_registration.md)** — настройка CI/CD после установки GitLab.
- **[GitLab + Runner через Docker Compose](./gitlab_runner_docker_compose.md)** — готовый стек для быстрого старта.
