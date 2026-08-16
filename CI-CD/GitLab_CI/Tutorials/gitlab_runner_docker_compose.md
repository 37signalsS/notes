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
| **Runner: resolve host fail** | Контейнер пайплайна не знает о `gitlab.local` | Добавьте `extra_hosts = ["gitlab.local:host-gateway"]` в `config.toml` раннера. |
| **Ошибка 401 при регистрации** | Токен `glrt-` устарел или неверно скопирован | Перевыпустите токен в Admin Area. |
| **Бесконечный статус Starting** | Недостаточно RAM для Valkey/PostgreSQL | Увеличьте лимиты в Compose или RAM на хосте. |
| **Registry: Connection Refused** | Порт 5050 не проброшен или Registry выключен | Проверьте `gitlab_rails['registry_enabled']` в конфиге. |

## Дополнительная информация

### Импорт проектов для тестов

Для быстрой проверки пайплайнов можно импортировать существующие репозитории. Включите эту возможность: **Admin Area > Settings > General > Visibility and access controls > Import sources** (отметьте `Repository by URL`).

### Смотрите также

- **[Установка Self-Hosted GitLab CE](./self_hosted_installation.md)** — подробнее о параметрах Omnibus.
- **[Регистрация GitLab Runner](./runner_registration.md)** — детализация параметров `gitlab-runner register`.
- **[Обзор Runner'ов и Executor'ов](../Advanced/gitlab_ci_runners_executors.md)** — глубокая теория.
- **[Dockerfile: Лучшие практики для Python](../../../Docker/Dockerfile/Docker_best_practices/python.md)** — подготовка образов для CI/CD.
