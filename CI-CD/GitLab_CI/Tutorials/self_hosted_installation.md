# Установка Self-Hosted GitLab CE с помощью Docker
## Определения

**GitLab CE (Community Edition)** — бесплатная и открытая версия платформы GitLab для самостоятельного размещения (self-hosted).

**Self-Hosted** — модель деплоя, при которой программное обеспечение устанавливается и обслуживается на собственной инфраструктуре организации, обеспечивая полный контроль над данными.

**GitLab Omnibus** — программный пакет, объединяющий Nginx, PostgreSQL, Redis, Puma и Sidekiq. Docker-образ GitLab является контейнеризированной версией этого пакета.

## Основные концепции

### Docker для Production: Нюансы и Тюнинг

Хотя Omnibus-пакет на VM считается "золотым стандартом", Docker-инсталляция при правильной настройке подходит для большинства задач.

- **Производительность:** Для исключения задержек I/O используйте SSD/NVMe и драйвер `overlay2`.
- **Изоляция:** GitLab — ресурсоемкое приложение. Всегда ограничивайте CPU и RAM для контейнера, чтобы избежать OOM (Out of Memory) на хосте.
- **Отладка:** Все основные утилиты (`gitlab-ctl`, `gitlab-rails`, `gitlab-rake`) доступны внутри контейнера через `docker exec`.

### Критичные параметры конфигурации (`gitlab.rb`)

- **`external_url`:** Определяет протокол (HTTP/HTTPS) и домен. При указании `https` GitLab попытается автоматически настроить Let's Encrypt.
- **`shm_size`:** Docker-контейнеру GitLab требуется минимум 256MB общей памяти (shared memory), иначе сервис Puma будет работать нестабильно.

## Практические сценарии

### Предварительные требования

**Сервер:**
- Минимум 4 ядра CPU и 8 ГБ RAM (рекомендуется 16 ГБ для комфортной работы).
- Docker Engine 24.0+ и Docker Compose v2+.
- Свободное место: от 50 ГБ (SSD).

**Сеть:**
- DNS `A`-запись для домена (например, `gitlab.example.com`).
- Открытые порты: `80`, `443` и `22` (или альтернативный порт для SSH).

### Шаг 1: Подготовка инфраструктуры

1. **Директории:** Создайте структуру директорий для сохранения данных между перезапусками контейнера:

```bash
sudo mkdir -p /srv/gitlab/{config,logs,data}
sudo chmod -R 755 /srv/gitlab/
```

2. **Локальный DNS (для тестирования):** Если вы разворачиваете GitLab локально без реального домена, добавьте запись в `/etc/hosts`, чтобы браузер и другие сервисы могли обращаться к нему по имени:

```text
# /etc/hosts
127.0.0.1 gitlab.local
```
*Примечание: В `docker-compose.yml` используйте `hostname: gitlab.local` и соответствующий `external_url`.*

### Шаг 2: Выбор метода запуска

#### Вариант А: Docker Compose

Создайте `/srv/gitlab/docker-compose.yml`:

```yaml
services:
  gitlab:
    image: 'gitlab/gitlab-ce:18.10.3-ce.0'
    container_name: gitlab
    restart: always
    hostname: 'gitlab.example.com'
    environment:
      GITLAB_OMNIBUS_CONFIG: |
        external_url 'https://gitlab.example.com'
        # Настройка SSH, если 22 порт занят на хосте
        gitlab_rails['gitlab_shell_ssh_port'] = 2222
    ports:
      - '80:80'
      - '443:443'
      - '2222:22'
    volumes:
      - '/srv/gitlab/config:/etc/gitlab'
      - '/srv/gitlab/logs:/var/log/gitlab'
      - '/srv/gitlab/data:/var/opt/gitlab'
    shm_size: '256m'
    deploy:
      resources:
        limits:
          memory: 12G
```

Запуск: `cd /srv/gitlab && sudo docker compose up -d`

#### Вариант Б: Docker Run (Для тестов)

```bash
sudo docker run --detach \
  --hostname gitlab.example.com \
  --publish 443:443 --publish 80:80 --publish 2222:22 \
  --name gitlab \
  --restart always \
  --volume /srv/gitlab/config:/etc/gitlab \
  --volume /srv/gitlab/logs:/var/log/gitlab \
  --volume /srv/gitlab/data:/var/opt/gitlab \
  --shm-size 256m \
  gitlab/gitlab-ce:18.10.3-ce.0
```

### Шаг 3: Первоначальная настройка

1. **Ожидание:** Инициализация занимает до 15 минут. Следите через `docker logs -f gitlab`.
2. **Пароль администратора:**
   ```bash
   sudo docker exec gitlab cat /etc/gitlab/initial_root_password
   ```
   *Пароль удаляется через 24 часа. Смените его сразу после входа.*

## Техническое обслуживание и Безопасность

### Резервное копирование (Backup & Restore)

**Ручное создание бэкапа:**
Утилита `gitlab-backup` создает архив со всеми репозиториями и базой данных.
```bash
# Создание архива
sudo docker exec gitlab gitlab-backup create
# → Создан файл в /var/opt/gitlab/backups/123456789_2026_04_13_18.10.3_gitlab_backup.tar
```

**Восстановление из бэкапа:**
1. Поместите файл в `/srv/gitlab/data/backups/`.
2. Остановите сервисы, работающие с БД:
   ```bash
   sudo docker exec gitlab gitlab-ctl stop puma
   sudo docker exec gitlab gitlab-ctl stop sidekiq
   ```
3. Запустите восстановление:
   ```bash
   sudo docker exec gitlab gitlab-backup restore BACKUP=123456789_2026_04_13_18.10.3
   ```
4. Перезапустите и проверьте: `sudo docker exec gitlab gitlab-ctl restart`.

**Облачные бэкапы (S3):**
Для автоматической выгрузки бэкапов в S3 добавьте в `gitlab.rb`:
```ruby
gitlab_rails['backup_upload_connection'] = {
  'provider' => 'AWS',
  'region' => 'us-east-1',
  'aws_access_key_id' => 'KEY',
  'aws_secret_access_key' => 'SECRET',
  'endpoint' => 'https://s3.example.com'
}
gitlab_rails['backup_upload_remote_directory'] = 'my-gitlab-backups'
```

### Безопасность (Hardening)

1. **Отключение регистрации:** `Admin Area -> Settings -> General -> Sign-up restrictions`.
2. **MFA:** Принудительно включите 2FA для администраторов.
3. **SSH:** Если используется нестандартный порт (2222), обновите `external_url` или `gitlab_shell_ssh_port`, чтобы ссылки `git clone` были корректными.

## Дополнительная информация (Белые пятна)

### Работа за внешним Reverse Proxy (Nginx/Traefik)

Если SSL терминируется на внешнем прокси, GitLab не должен пытаться выпустить сертификат. В `gitlab.rb`:
```ruby
external_url 'https://gitlab.example.com'
nginx['listen_port'] = 80
nginx['listen_https'] = false
nginx['proxy_set_headers'] = {
  "X-Forwarded-Proto" => "https",
  "X-Forwarded-Ssl" => "on"
}
```

### Оптимизация памяти (Small Instance)

Если у вас всего 8 ГБ RAM, уменьшите количество воркеров:
```ruby
puma['worker_processes'] = 2
sidekiq['max_concurrency'] = 10
prometheus_monitoring['enable'] = false # Отключение для экономии ~500MB
```

### Смотрите также

- **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — глубокий разбор компонентов.
- **[Регистрация GitLab Runner](./runner_registration.md)** — настройка CI/CD.
- **[GitLab + Runner через Docker Compose](./gitlab_runner_docker_compose.md)** — готовый стек.
