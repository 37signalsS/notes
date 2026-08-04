# Установка GitLab и Runner через Docker Compose

## Определения

**Docker Compose** — инструмент для описания и запуска многоконтейнерных приложений. Позволяет поднять GitLab и его Runner одной командой с общими сетями и томами.

**GitLab Runner** — агент, выполняющий задачи (jobs). В данной схеме Runner запускается как соседний контейнер (Sidecar).

**Container Registry** — встроенный реестр образов. Для локальной работы требует настройки HTTP-доступа или доверенных сертификатов.

**Docker-in-Docker (DinD)** — метод сборки образов внутри контейнера. В данном руководстве реализуется через проброс Docker Socket (`/var/run/docker.sock`).

## Основные концепции

### Взаимодействие сервисов (Networking)

В Docker Compose контейнеры находятся в одной сети. Это позволяет Runner'у обращаться к GitLab по имени сервиса (`http://gitlab`), а не по внешнему IP. Однако для корректной генерации ссылок в интерфейсе GitLab должен знать свой внешний URL.

### Жизненный цикл и Healthchecks

GitLab Omnibus — тяжелое приложение (запуск 5–10 мин). Использование `healthcheck` в Compose позволяет Runner'у не начинать работу, пока сервер не будет полностью готов.

### Безопасность в Dev-окружении

Проброс `/var/run/docker.sock` дает Runner'у полные права `root` на хост-системе. Это допустимо для локальной разработки, но **категорически запрещено** для публичных инстансов.

## Практические сценарии

### Предварительные требования

- **RAM:** Минимум 8 ГБ (16 ГБ рекомендуется).
- **Диск:** SSD, минимум 40 ГБ свободного места.
- **ОС:** Linux, macOS или Windows (WSL2) с Docker Desktop 4.x+.

### Шаг 1: Настройка локального DNS

Добавьте в `/etc/hosts` (или `C:\Windows\System32\drivers\etc\hosts`):
```text
127.0.0.1 gitlab.local
```

### Шаг 2: Создание конфигурации Docker Compose

Создайте файл `docker-compose.yml`:

```yaml
services:
  gitlab:
    image: 'gitlab/gitlab-ce:18.10.3-ce.0'
    container_name: gitlab
    restart: always
    hostname: 'gitlab.local'
    environment:
      GITLAB_OMNIBUS_CONFIG: |
        external_url 'http://gitlab.local'
        registry_external_url 'http://gitlab.local:5050'
        gitlab_rails['registry_enabled'] = true
        # Оптимизация для малых инстансов (Dev)
        puma['worker_processes'] = 2
        sidekiq['max_concurrency'] = 10
    ports:
      - '80:80'
      - '443:443'
      - '5050:5050'
    volumes:
      - '/srv/gitlab/config:/etc/gitlab'
      - '/srv/gitlab/logs:/var/log/gitlab'
      - '/srv/gitlab/data:/var/opt/gitlab'
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost/-/health"]
      interval: 30s
      timeout: 10s
      retries: 10
    shm_size: '256m'
    deploy:
      resources:
        limits:
          memory: 12G

  gitlab-runner:
    image: 'gitlab/gitlab-runner:alpine'
    container_name: gitlab-runner
    restart: always
    depends_on:
      gitlab:
        condition: service_healthy
    volumes:
      - '/srv/gitlab-runner/config:/etc/gitlab-runner'
      - '/var/run/docker.sock:/var/run/docker.sock'
    # Добавляем алиас для связи с локальным GitLab
    extra_hosts:
      - "gitlab.local:host-gateway"
```

### Шаг 3: Запуск и получение пароля

1. Запустите стек: `docker compose up -d`.
2. Дождитесь статуса `healthy` (проверка: `docker ps`).
3. Извлеките временный пароль `root`:
   ```bash
   docker exec -it gitlab grep 'Password:' /etc/gitlab/initial_root_password
   ```

### Шаг 4: Современная регистрация Runner (GitLab 17.x+)

С выходом GitLab 17.0 старые Registration Tokens (из настроек CI/CD) считаются устаревшими.

1. Зайдите в GitLab под `root`.
2. Перейдите в **Settings > CI/CD > Runners**.
3. Нажмите **New project runner**.
4. Укажите теги (например, `local-docker`) и нажмите **Create runner**.
5. Скопируйте **Authentication Token** (начинается с `glrt-`).
6. Запустите регистрацию:

```bash
docker exec -it gitlab-runner gitlab-runner register \
  --non-interactive \
  --url "http://gitlab.local" \
  --token "glrt-ВАШ_ТОКЕН" \
  --executor "docker" \
  --docker-image "alpine:latest" \
  --docker-volumes "/var/run/docker.sock:/var/run/docker.sock" \
  --docker-network-mode "gitlab_default"
```
*Примечание: `--docker-network-mode` должен соответствовать имени сети, созданной Compose (обычно `директория_default`).*

## Технические нюансы и Тюнинг

### Проблема доступности Registry
Для того чтобы Runner мог пушить образы в локальный Registry по HTTP, в `/etc/gitlab-runner/config.toml` (на хосте) или в параметрах регистрации нужно добавить:
```toml
[[runners]]
  [runners.docker]
    allowed_images = ["*"]
    allowed_services = ["*"]
    # Разрешить незащищенные реестры
    extra_hosts = ["gitlab.local:host-gateway"]
```

### Очистка ресурсов
Локальные сборки быстро забивают диск. Настройте автоматическую очистку в GitLab: **Admin Area > Settings > CI/CD > Container Registry**.

## Решение проблем (Troubleshooting)

- **Runner не видит GitLab:** Убедитесь, что `extra_hosts` прописан в `docker-compose.yml`, иначе Runner внутри контейнера Docker (который он сам запустил) не сможет разрешить имя `gitlab.local`.
- **Ошибка 401 Unauthorized:** Проверьте, не истек ли `glrt-` токен. В новых версиях GitLab токены создаются "до" регистрации.
- **Бесконечный запуск:** Проверьте логи (`docker logs -f gitlab`). Если процесс завис на `ruby_block[wait for redis]`, увеличьте лимит RAM.

## Дополнительная информация

### Смотрите также

- **[Установка Self-Hosted GitLab CE](./self_hosted_installation.md)** — подробнее о параметрах Omnibus.
- **[Регистрация GitLab Runner](./runner_registration.md)** — глубокий разбор типов токенов.
- **[Обзор Runner'ов и Executor'ов](../Advanced/gitlab_ci_runners_executors.md)** — выбор между Docker и Shell.
