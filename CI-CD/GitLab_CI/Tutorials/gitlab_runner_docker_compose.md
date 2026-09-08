# Развертывание стека GitLab и Runner через Docker Compose

Практическое руководство по созданию локальной среды разработки (Dev-инфраструктуры), объединяющей GitLab CE и GitLab Runner в единый стек с использованием Docker Compose.

---

## Определения

**Docker Compose** — инструмент для декларативного описания и управления многоконтейнерными приложениями. В контексте GitLab позволяет поднять сервер и агентов исполнения одной командой в изолированной сети.

**GitLab Runner** — агент, отвечающий за выполнение задач (jobs) пайплайна. В данной схеме запускается как «побочный» контейнер (Sidecar), тесно связанный с основным инстансом.

**Container Registry** — встроенное в GitLab хранилище Docker-образов. Для локальной работы по протоколу HTTP требует специфической настройки доверия со стороны Runner'а.

**Docker-in-Docker (DinD)** — технология, позволяющая собирать и запускать Docker-образы внутри контейнера. В этом руководстве реализуется через **Bind Mount** системного сокета Docker (`/var/run/docker.sock`).

**Valkey** — высокопроизводительное in-memory хранилище (форк Redis), используемое в GitLab 19.x для управления очередями задач и кэширования.

## Основные концепции

### Сетевое взаимодействие (Networking)

В среде Docker Compose контейнеры GitLab и Runner помещаются в общую пользовательскую сеть (bridge). Это дает два преимущества:
1.  **Service Discovery:** Runner обращается к GitLab по имени сервиса (`http://gitlab`), что упрощает конфигурацию.
2.  **Изоляция:** Трафик между компонентами не выходит за пределы виртуальной сети Docker, если это не требуется.

*Важно:* Для того чтобы ссылки в интерфейсе GitLab (например, для Git Clone) были корректными, необходимо явно указывать `external_url`, соответствующий домену на хост-машине.

### Оркестрация запуска и Healthchecks

GitLab Omnibus является «тяжелым» приложением и проходит длительный этап инициализации (от 5 до 15 минут). Использование директивы `healthcheck` в Docker Compose критично: она позволяет Runner'у дождаться полной готовности API GitLab перед попыткой регистрации или выполнения задач, предотвращая каскадные ошибки запуска.

### Безопасность и риски Docker Socket

Проброс `/var/run/docker.sock` внутрь контейнера Runner'а дает ему права суперпользователя на хост-системе. 
*   **Dev-окружение:** Допустимо для локальных тестов и сборки образов.
*   **Production:** Категорически запрещено. Используйте изолированные виртуальные машины или технологию Kaniko для сборки без привилегий.

## Практические сценарии

### Предварительные требования

**Аппаратные ресурсы:**
- **RAM:** 16 ГБ (минимум 12 ГБ при отключении мониторинга).
- **CPU:** 4 ядра и более.
- **Диск:** SSD, минимум 50 ГБ свободного места.

**Программное обеспечение:**
- Docker Engine 27.0+ и Docker Compose v2.20+.
- Настроенный локальный DNS или отредактированный файл `/etc/hosts`.

### Шаг 1: Подготовка окружения и DNS

Для корректной работы Registry и SSH добавьте запись в `/etc/hosts` (или `C:\Windows\System32\drivers\etc\hosts` для Windows):
```text
127.0.0.1 gitlab.local
```

### Шаг 2: Конфигурация Docker Compose

Создайте файл `docker-compose.yml` в рабочей директории. Данная конфигурация оптимизирована для GitLab 19.x и включает использование Valkey.

```yaml
services:
  gitlab:
    image: 'gitlab/gitlab-ce:19.2.2-ce.0'
    container_name: gitlab
    restart: always
    hostname: 'gitlab.local'
    environment:
      GITLAB_OMNIBUS_CONFIG: |
        external_url 'http://gitlab.local'
        registry_external_url 'http://gitlab.local:5050'
        gitlab_rails['registry_enabled'] = true
        # Переход на Valkey (вместо Redis) в 19.x
        redis['backend'] = 'valkey'
        # Оптимизация ресурсов для локальной среды
        puma['worker_processes'] = 2
        sidekiq['max_concurrency'] = 8
        prometheus_monitoring['enable'] = false
        postgresql['shared_buffers'] = "512MB"
    ports:
      - '80:80'
      - '443:443'
      - '5050:5050'
      - '2222:22'
    volumes:
      - './config:/etc/gitlab'
      - './logs:/var/log/gitlab'
      - './data:/var/opt/gitlab'
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost/-/health"]
      interval: 30s
      timeout: 10s
      retries: 20
    shm_size: '1gb'
    deploy:
      resources:
        limits:
          memory: 14G

  gitlab-runner:
    image: 'gitlab/gitlab-runner:alpine'
    container_name: gitlab-runner
    restart: always
    depends_on:
      gitlab:
        condition: service_healthy
    volumes:
      - './runner-config:/etc/gitlab-runner'
      - '/var/run/docker.sock:/var/run/docker.sock'
    extra_hosts:
      - "gitlab.local:host-gateway"
```

### Шаг 3: Запуск и Валидация

1.  **Запуск стека:**
    ```bash
    docker compose up -d
    ```
2.  **Мониторинг здоровья:** Дождитесь, пока `docker ps` покажет статус `(healthy)` для контейнера `gitlab`.
3.  **Первичный пароль:**
    ```bash
    docker exec -it gitlab grep 'Password:' /etc/gitlab/initial_root_password
    ```
4.  **Проверка доступа:** Откройте `http://gitlab.local` в браузере. Если страница загружается, сервер готов к работе.

### Шаг 4: Регистрация Runner (Современный метод 17.x+)

В новых версиях GitLab регистрация происходит через **Authentication Tokens**.

1.  В GitLab перейдите в **Admin Area > CI/CD > Runners**.
2.  Нажмите **New instance runner**, укажите тег `local-docker` и создайте его.
3.  Скопируйте полученный токен (`glrt-xxxx`).
4.  Выполните регистрацию внутри контейнера:

```bash
docker exec -it gitlab-runner gitlab-runner register \
  --non-interactive \
  --url "http://gitlab.local" \
  --token "ВАШ_ТОКЕН" \
  --executor "docker" \
  --docker-image "python:3.13-slim" \
  --docker-volumes "/var/run/docker.sock:/var/run/docker.sock" \
  --docker-network-mode "gitlab-runner-default"
```
*Примечание:* Имя сети можно узнать через `docker network ls`. Обычно это `название-папки_default`.

## Технические нюансы и Тюнинг

### Доступ к локальному Registry по HTTP

Runner по умолчанию требует HTTPS для взаимодействия с реестрами. Чтобы разрешить работу с `gitlab.local:5050` по HTTP, отредактируйте `runner-config/config.toml` на хосте:

```toml
[[runners]]
  [runners.docker]
    # Разрешаем проброс локального домена в запускаемые пайплайном контейнеры
    extra_hosts = ["gitlab.local:host-gateway"]
    # Для сборки образов через Docker-in-Docker
    privileged = true 
```

### Автоматическая очистка диска

Локальные сборки быстро потребляют дисковое пространство. Рекомендуется периодически выполнять очистку на хосте:
```bash
docker system prune -f
```

## Решение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Runner: resolve host fail** | Контейнер пайплайна не знает о `gitlab.local` | Добавьте `extra_hosts = ["gitlab.local:host-gateway"]` в `config.toml` раннера и в секцию `services` контейнера пайплайна. |
| **Ошибка 401 при регистрации** | Токен `glrt-` устарел или неверно скопирован | Перевыпустите токен в Admin Area > CI/CD > Runners. Убедитесь, что используете `--token`, а не `--registration-token`. |
| **Бесконечный статус Starting** | Недостаточно RAM для Valkey/PostgreSQL | Увеличьте лимиты в Compose (`deploy.resources.limits.memory`) или RAM на хосте. Минимум 12 ГБ. |
| **Registry: Connection Refused** | Порт 5050 не проброшен или Registry выключен | Проверьте `gitlab_rails['registry_enabled']` в конфиге и наличие `5050:5050` в секции `ports`. |
| **Runner: Cannot connect to Docker daemon** | `/var/run/docker.sock` не проброшен или Docker не запущен на хосте | Убедитесь, что Docker Engine работает: `systemctl status docker`. Проверьте volume: `ls -la /var/run/docker.sock`. |
| **Healthcheck не проходит** | GitLab не успевает запуститься за отведённое время | Увеличьте `retries` до 30 или `interval` до 60s. Проверьте логи: `docker logs gitlab 2>&1 | tail -50`. |
| **OOM: Exit code 137** | Контейнер GitLab превышает лимит памяти | Увеличьте `shm_size` до `2gb` и `deploy.resources.limits.memory` до `16G`. Отключите Sidekiq или Puma workers. |
| **Сетевой конфликт между контейнерами** | Docker Compose создал несколько bridge-сетей | Выполните `docker network ls` и убедитесь, что все сервисы в одной сети. Имя сети: `название-папки_default`. |
| **Git Clone не работает из пайплайна** | `external_url` не соответствует домену доступа | Проверьте, что URL в GitLab-проекте совпадает с `external_url` в конфиге. Для SSH используйте порт 2222. |
| **Runner не берёт задачи из очереди** | Runner не авторизован или теги не совпадают | Проверьте статус: `docker exec -it gitlab-runner gitlab-runner list`. Убедитесь, что теги задачи совпадают с тегами Runner'а. |
| **Disk space exhausted** | Локальные образы и кэш заполнили диск | Выполните `docker system prune -af` на хосте. Настройте cron-задачу для автоматической очистки. |
| **Container屡次 перезапускается** | CrashLoopBackOff из-за ошибки в конфиге | Проверьте логи: `docker logs gitlab --tail 100`. Частая причина — невалидный `GITLAB_OMNIBUS_CONFIG`. |

## Лучшие практики (Best Practices)

**Безопасность:**
- В production-окружениях **никогда** не пробрасывайте Docker Socket. Используйте изолированные VM или Kaniko для сборки образов без привилегий.
- Для локальной среды: Runner в контейнере работает с `privileged = true` — это безопасно только на изолированной Dev-машине.
- Все敏感ные переменные (токены, SSH-ключи) добавляйте через CI/CD Variables с флагами `masked` и `protected`.
- Регулярно обновляйте версии образов: `gitlab/gitlab-ce:19.x` и `gitlab/gitlab-runner:alpine`.

**Производительность:**
- Отключите Prometheus Monitoring (`prometheus_monitoring['enable': false]`) в Dev-окружении — экономит ~1 ГБ RAM.
- Настройте `puma['worker_processes']` и `sidekiq['max_concurrency']` под объём RAM хоста.
- Используйте SSD для хранения данных GitLab — HDD значительно замедляет PostgreSQL и Valkey.
- Настройте `cache` в CI/CD-задачах для ускорения повторных сборок.

**Надёжность:**
- Всегда используйте `depends_on` с `condition: service_healthy` для зависимостей от GitLab.
- Используйте `restart: always` для всех сервисов — это восстанавливает работу после перезагрузки хоста.
- Пинайте версии образов: `19.2.2-ce.0` вместо `latest` — это гарантирует воспроизводимость.
- Настройте `healthcheck` с достаточным количеством `retries` (минимум 20) для тяжёлых контейнеров.

**Данные и хранение:**
- Монтируйте volume для `/etc/gitlab` — это сохраняет конфигурацию при пересоздании контейнера.
- Не храните данные в Anonymous Volumes — они удаляются при `docker compose down -v`.
- Используйте именованные volume для PostgreSQL и Valkey при необходимости персистентности.

## Очистка и откат (Cleanup)

**Полная остановка стека:**
```bash
# Остановка и удаление контейнеров (данные сохраняются)
docker compose down

# Остановка + удаление volumes (ПОЛНАЯ очистка данных)
docker compose down -v

# Остановка + удаление образов + volumes
docker compose down -v --rmi all
```

**Очистка Container Registry на хосте:**
```bash
# Удаление неиспользуемых образов Docker
docker system prune -af

# Очистка логов GitLab (осторожно!)
sudo truncate -s 0 /var/log/gitlab/*/*.log
```

**Откат к предыдущей версии GitLab:**
```bash
# 1. Остановите стек
docker compose down

# 2. Измените версию образа в docker-compose.yml
# gitlab/gitlab-ce:19.2.1-ce.0  (вместо 19.2.2)

# 3. Запустите заново (Docker восстановит данные из volume)
docker compose up -d
```

**Бэкап перед обновлением:**
```bash
# Бэкап конфигурации
cp -r ./config ./config.bak.$(date +%Y%m%d)

# Бэкап данных GitLab (chown может потребоваться)
docker exec -it gitlab gitlab-backup create
docker cp gitlab:/var/opt/gitlab/backups/ ./backups/
```

## Граничные случаи (Edge Cases)

**Обновление GitLab в Docker Compose:**
- При обновлении версии образа GitLab **обязательно** создайте бэкап — major/minor версии могут требовать миграции БД.
- Не пропускайте версии: обновляйтесь последовательно (19.1 → 19.2 → 19.3).
- Процесс миграции занимает от 5 до 30 минут в зависимости от объёма данных.

**Одновременная работа нескольких Runner'ов:**
- Если нужно запустить несколько Runner'ов, используйте разные имена сервисов (`gitlab-runner-1`, `gitlab-runner-2`) и разные порты для `runner-config`.
- Каждый Runner должен иметь уникальный токен регистрации.

**Масштабирование на несколько хостов:**
- Docker Compose — не оркестратор. Для кластера из нескольких хостов используйте Docker Swarm или Kubernetes.
- Для single-host окружения Docker Compose подходит оптимально.

**Проброс SSH для деплоя:**
- Для использования SSH-деплоя из пайплайна пробросьте порт 2222: `2222:22` и настройте SSH-ключ в CI/CD Variables.

**Работа с macOS (Docker Desktop):**
- Docker Desktop для macOS не поддерживает `--privileged` и проброс Docker Socket напрямую. Используйте `colima` или `lima` как альтернативу.

## Мониторинг и логирование

**Просмотр логов:**
```bash
# Логи GitLab (все компоненты)
docker logs gitlab --tail 100 -f

# Логи Runner'а
docker logs gitlab-runner --tail 50 -f

# Логи конкретного компонента GitLab
docker exec -it gitlab tail -f /var/log/gitlab/unicorn/unicorn_stderr.log
docker exec -it gitlab tail -f /var/log/gitlab/sidekiq/sidekiq.log
```

**Проверка состояния компонентов:**
```bash
# Статус всех сервисов GitLab
docker exec -it gitlab gitlab-ctl status

# Статус PostgreSQL
docker exec -it gitlab gitlab-ctl status postgresql

# Статус Redis/Valkey
docker exec -it gitlab gitlab-ctl status valkey
```

**Просмотр метрик (если Prometheus включен):**
```bash
# Доступ к Prometheus UI (только если prometheus_monitoring['enable': true])
# http://gitlab.local:9090
```

## Дополнительная информация

### Импорт проектов для тестов

Для быстрой проверки пайплайнов можно импортировать существующие репозитории. Включите эту возможность: **Admin Area > Settings > General > Visibility and access controls > Import sources** (отметьте `Repository by URL`).

### Смотрите также

- **[Установка Self-Hosted GitLab CE](./self_hosted_installation.md)** — подробнее о параметрах Omnibus и SSL/TLS.
- **[Регистрация GitLab Runner](./runner_registration.md)** — детализация параметров `gitlab-runner register` и 10 сценариев.
- **[Обзор Runner'ов и Executor'ов](../Advanced/gitlab_ci_runners_executors.md)** — архитектура, типы Executor'ов и оптимизация config.toml.
