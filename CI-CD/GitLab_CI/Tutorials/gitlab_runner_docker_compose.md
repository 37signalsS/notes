# Установка GitLab и Runner через Docker Compose

## Определения

- **Docker Compose**: Инструмент для декларативного описания и управления многоконтейнерными приложениями через единый YAML-файл.
- **GitLab Runner**: Агент, выполняющий CI/CD-задачи (jobs) из пайплайнов GitLab.
- **Container Registry**: Встроенный в GitLab реестр Docker-образов для хранения и распространения артефактов сборки.
- **Docker-in-Docker (DinD)**: Технология, позволяющая запускать Docker внутри Docker-контейнера. В контексте Runner часто реализуется через проброс Docker Socket (`/var/run/docker.sock`).

## Основные концепции

### Единая конфигурация сервисов

Docker Compose позволяет описать GitLab Server и GitLab Runner в одном файле, обеспечивая:

- Совместный запуск и остановку всех компонентов.
- Единую сеть для взаимодействия между сервером и Runner.
- Централизованное управление ресурсами и томами данных.

### Изоляция и безопасность

Проброс Docker Socket в контейнер Runner позволяет ему запускать контейнеры непосредственно на хост-машине. Это упрощённый подход, подходящий для тестовых и учебных сред, но имеющий риски безопасности, так как Runner получает полный доступ к Docker-демону хоста.

### Встроенный Container Registry

GitLab предоставляет встроенный Docker Registry. В конфигурации Docker Compose он включается через параметры Omnibus, что позволяет пайплайнам публиковать собранные образы без настройки внешних хранилищ.

## Практические сценарии

### Предварительные требования

- Установленные Docker и Docker Compose v2+.
- Минимум 4 ядра CPU и 8 ГБ RAM (рекомендуется 16 ГБ).
- Для локального доступа — запись в `/etc/hosts`:

  ```bash
  127.0.0.1 gitlab.devops
  ```

### Шаг 1: Подготовка директорий

```bash
mkdir -p /srv/gitlab-runner/config
```

### Шаг 2: Создание docker-compose.yml

Создайте файл `docker-compose.yml` со следующим содержимым:

```yaml
services:
  gitlab:
    image: gitlab/gitlab-ce:18.10.3-ce.0
    container_name: gitlab
    hostname: gitlab.devops
    restart: always
    ports:
      - '80:80'
      - '443:443'
      - '5050:5050'
    volumes:
      - /srv/gitlab/config:/etc/gitlab
      - /srv/gitlab/logs:/var/log/gitlab
      - /srv/gitlab/data:/var/opt/gitlab
    environment:
      GITLAB_OMNIBUS_CONFIG: |
        external_url 'http://gitlab.devops'
        registry_external_url 'http://gitlab.devops:5050'
        gitlab_rails['registry_enabled'] = true

  gitlab-runner:
    image: gitlab/gitlab-runner:alpine
    container_name: gitlab-runner
    restart: always
    volumes:
      - /srv/gitlab-runner/config:/etc/gitlab-runner
      - /var/run/docker.sock:/var/run/docker.sock
    depends_on:
      - gitlab
```

**Ключевые параметры конфигурации:**

| Параметр | Описание |
| :--- | :--- |
| `registry_enabled` | Включает встроенный Container Registry. |
| `/var/run/docker.sock` | Проброс Docker Socket для работы Runner в режиме Docker-in-Docker. |
| `/srv/gitlab-runner/config` | Место хранения `config.toml` — конфигурации зарегистрированных Runner'ов. |

### Шаг 3: Запуск и проверка готовности

Запустите сервисы:

```bash
docker compose up -d
# → Network example_default Created
# → Container gitlab  Started
# → Container gitlab-runner  Started
```

Первый запуск GitLab занимает **5–15 минут**. Следить за процессом можно через логи:

```bash
docker logs -f gitlab
# → gitlab Reconfigured!
```

Пароль администратора (`root`) можно получить командой:

```bash
docker exec gitlab cat /etc/gitlab/initial_root_password
# → Password: abc123def456...
```

### Шаг 4: Регистрация Runner

После полной инициализации GitLab необходимо зарегистрировать агент:

1. Откройте `http://gitlab.devops` и войдите под учетной записью `root`.
2. Перейдите в **Settings → CI/CD → Runners** и скопируйте **Registration Token**.
3. Выполните регистрацию (подробности см. в [Регистрация GitLab Runner](./runner_registration.md)):

   ```bash
   docker run --rm -it -v /srv/gitlab-runner/config:/etc/gitlab-runner \
     gitlab/gitlab-runner:alpine register
   # → Runner registered successfully. Feel free to start it...
   ```

   - URL: `http://gitlab.devops`
   - Token: (из UI)
   - Executor: `docker`
   - Default image: `alpine:latest`

### Автоматизация регистрации (опционально)

Для полностью автоматизированного деплоя можно использовать скрипт, ожидающий готовности API перед регистрацией. Пример логики:

```bash
#!/bin/bash
docker compose up -d

until curl -s http://gitlab.devops | grep -q "GitLab"; do
  echo "Ожидание инициализации GitLab..."
  sleep 30
done

echo "GitLab готов. Выполните регистрацию Runner вручную или через API."
```

## Дополнительная информация

### Ограничения и рекомендации

- **Область применения**: Данный сценарий предназначен исключительно для **тестовых и учебных сред**.
- **Production**: Для продуктивных сред рекомендуется раздельное размещение компонентов и использование нативной установки (Omnibus) или Kubernetes. Подробнее см. в [Установка Self-Hosted GitLab CE](./self_hosted_installation.md).
- **Версионность**: Используйте фиксированные теги образов (например, `18.10.3-ce.0`) вместо `latest` для стабильности пайплайнов.

### Смотрите также

- [Установка Self-Hosted GitLab CE с помощью Docker](./self_hosted_installation.md) — подробный разбор параметров GitLab.
- [Регистрация GitLab Runner](./runner_registration.md) — SSoT по вопросам регистрации агентов.
- [Обзор GitLab Runners и Executor'ов](../Advanced/gitlab_ci_runners_executors.md) — архитектура и выбор исполнителя.
