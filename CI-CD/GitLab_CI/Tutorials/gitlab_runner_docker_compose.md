# Установка GitLab + Runner через Docker Compose

## Определения

**Docker Compose** — инструмент для декларативного описания и управления многоконтейнерными приложениями через единый YAML-файл.

**GitLab Runner** — агент, выполняющий CI/CD-задачи (jobs) из пайплайнов GitLab.

**Container Registry** — встроенный в GitLab реестр Docker-образов для хранения и распространения артефактов сборки.

## Основные концепции

### Единая конфигурация сервисов

Docker Compose позволяет описать GitLab Server и GitLab Runner в одном файле, обеспечивая:

- Совместный запуск и остановку всех компонентов
- Единую сеть для взаимодействия между сервером и Runner
- Централизованное управление ресурсами

### Docker-in-Docker (DinD)

Проброс Docker Socket (`/var/run/docker.sock`) в контейнер Runner позволяет ему запускать контейнеры непосредственно на хост-машине. Это упрощённый подход, подходящий для тестовых и учебных сред.

### Встроенный Container Registry

GitLab предоставляет встроенный Docker Registry для хранения образов, собранных в CI/CD-пайплайнах. Включается через параметр `registry_enabled` в конфигурации.

## Практические сценарии

### Предварительные требования

- Docker и Docker Compose v2+ установлены
- Минимум 4 ядра CPU и 8 ГБ RAM
- Для локального доступа — запись в `/etc/hosts`:

```bash
127.0.0.1 gitlab.devops
```

### Шаг 1: Подготовка директорий

```bash
mkdir -p /srv/gitlab-runner/config
```

### Шаг 2: Создание docker-compose.yml

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

**Ключевые моменты:**

| Параметр | Описание |
| :--- | :--- |
| `registry_enabled` | Включает встроенный Container Registry для хранения Docker-образов |
| `/var/run/docker.sock` | Проброс Docker Socket позволяет Runner'у запускать контейнеры (Docker-in-Docker) |
| `/srv/gitlab-runner/config` | Постоянное хранение `config.toml` — конфигурации зарегистрированных Runner'ов |

### Шаг 3: Запуск сервисов

```bash
docker compose up -d
```

Первый запуск GitLab занимает **5-15 минут**. Проверить готовность можно командой:

```bash
docker logs -f gitlab
```

### Шаг 4: Регистрация Runner

После инициализации GitLab необходимо зарегистрировать Runner:

1. Получите регистрационный токен в UI: **Settings → CI/CD → Runners** (или через API)
2. Зарегистрируйте Runner:

```bash
docker run --rm -it -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  gitlab/gitlab-runner:alpine register
```

Интерактивный запрос:

- GitLab URL: `http://gitlab.devops`
- Registration token: (из UI)
- Executor: `docker`
- Default Docker image: `alpine:latest`

### Шаг 5: Проверка

1. Откройте `http://gitlab.devops` в браузере
2. Логин: `root`, пароль — из `/etc/gitlab/initial_root_password`
3. Убедитесь, что Runner появился в **Settings → CI/CD → Runners** с зеленым индикатором

### Альтернатива: автоматическая регистрация

Для полностью автоматизированного развертывания можно использовать скрипт, который:

1. Запускает Docker Compose
2. Ожидает инициализации GitLab (цикл с проверкой API)
3. Получает регистрационный токен через GitLab API
4. Регистрирует Runner автоматически

Пример логики такого скрипта:

```bash
#!/bin/bash
# 1. Запуск сервисов
docker compose up -d

# 2. Ожидание инициализации GitLab
until curl -s http://gitlab.devops | grep -q "GitLab"; do
  echo "Ожидание инициализации GitLab..."
  sleep 30
done

# 3. Получение токена и регистрация Runner
# (через GitLab API или UI)

echo "Установка завершена"
```

## Дополнительная информация

### Область применения

Данный сценарий предназначен для **тестовых и учебных сред**. Для production используйте раздельное размещение компонентов с фиксированными версиями образов.

### Рекомендуемая версия

Текущая стабильная версия: **GitLab 18.10.3** (апрель 2026). Фиксируйте версию в Docker Compose для предсказуемости обновлений.

### Смежные руководства

- [Установка GitLab CE через Docker](./self_hosted_installation.md) — production-ориентированный сценарий
- [Регистрация GitLab Runner](./runner_registration.md) — альтернативные методы регистрации
