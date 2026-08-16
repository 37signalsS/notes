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

### Шаг 3: Запуск и первичная инициализация

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
| **Ошибка 502 Whoops** | Puma еще запускается или мало RAM | Подождите 5 мин или увеличьте лимиты в Compose. |
| **PostgreSQL Upgrade Fail** | Несовместимость версий при обновлении | Выполните `gitlab-ctl pg-upgrade` перед обновлением образа. |
| **Git Clone SSH Fail** | Порт 2222 не проброшен | Проверьте секцию `ports` в Compose и настройки Firewall. |
| **Duo Chat не работает** | Нет связи с AI Gateway | Проверьте доступ к `cloud.gitlab.com` и настройки WebSockets в прокси. |

### Смотрите также

- **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — глубокий разбор компонентов.
- **[Регистрация GitLab Runner](./runner_registration.md)** — настройка CI/CD.
- **[GitLab + Runner через Docker Compose](./gitlab_runner_docker_compose.md)** — готовый стек.
