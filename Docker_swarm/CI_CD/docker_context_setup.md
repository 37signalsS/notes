# Docker Context для CI/CD с Docker Swarm

## Определения

- **Docker Context** — механизм Docker для управления несколькими удаленными окружениями через профили подключения. Каждый контекст содержит информацию о хосте, сертификатах и параметрах подключения.
- **Docker Endpoint** — точка подключения к Docker Engine (локальный сокет или удаленный TCP-хост с TLS).
- **Context Switching** — процесс переключения между контекстами для управления разными кластерами без изменения переменных окружения.

## Базовые концепции

### Зачем нужен Docker Context в CI/CD

При работе с несколькими окружениями (development, staging, production) Docker Context позволяет:

- **Быстрое переключение:** Одна команда для смены целевого кластера
- **Изоляция окружений:** Отдельные сертификаты и настройки для каждого контекста
- **Упрощение пайплайнов:** Не нужно управлять `DOCKER_HOST`, `DOCKER_TLS_VERIFY`, `DOCKER_CERT_PATH` вручную
- **Безопасность:** Сертификаты хранятся в защищенных переменных GitLab CI

### Архитектура подключения

```
[GitLab Runner] → [Docker Context] → [mTLS:2376] → [Swarm Manager]
       ↓
  (ca.pem, cert.pem, key.pem)
```

**Компоненты контекста:**

- `host` — TCP-адрес Docker Daemon (`tcp://manager.example.com:2376`)
- `ca` — путь к корневому сертификату
- `cert` — путь к клиентскому сертификату
- `key` — путь к клиентскому ключу

### Требования

- Настроенный mTLS на Docker Daemon (см. **[swarm_setup.md](./swarm_setup.md)**)
- Клиентские сертификаты (`ca.pem`, `cert.pem`, `key.pem`)
- Доступ к порту 2376 с машины GitLab Runner

## Практические сценарии

### Сценарий 1: Локальная настройка контекста

**Шаг 1: Подготовка сертификатов**

Скопируйте клиентские сертификаты с менеджера Swarm на локальную машину:

- `ca.pem` — корневой сертификат
- `cert.pem` — клиентский сертификат
- `key.pem` — клиентский ключ

**Шаг 2: Создание контекста**

```bash
docker context create prod-swarm \
  --docker "host=tcp://prod.example.com:2376,ca=/path/to/ca.pem,cert=/path/to/cert.pem,key=/path/to/key.pem"
```

**Шаг 3: Переключение на контекст**

```bash
docker context use prod-swarm
```

**Шаг 4: Проверка подключения**

```bash
docker node ls
docker service ls
```

**Шаг 5: Возврат к локальному окружению**

```bash
docker context use default
```

### Сценарий 2: Использование в GitLab CI

В пайплайне GitLab CI контекст создается динамически через переменные окружения.

**Настройка переменных в GitLab (**Settings → CI/CD → Variables**):**

| Переменная | Тип | Описание |
|---|---|---|
| `DOCKER_HOST` | Variable | `tcp://manager.example.com:2376` |
| `CA_PEM` | File | Содержимое `ca.pem` |
| `CERT_PEM` | File | Содержимое `cert.pem` |
| `KEY_PEM` | File | Содержимое `key.pem` |

**Пример `.gitlab-ci.yml`:**

```yaml
deploy:
  stage: deploy
  image: docker:24
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    - docker context create swarm \
      --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm
  script:
    - docker node ls
    - docker stack deploy -c docker-compose.yml myapp
```

**Использование Environment Scope:**

Для развертывания на разные кластеры используйте **[Environment Scope](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**:

1. Создайте переменные `DOCKER_HOST`, `CA_PEM`, `CERT_PEM`, `KEY_PEM` дважды:
   - Один раз со скоупом `production` (для prod-кластера)
   - Второй раз со скоупом `development` (для dev-кластера)

2. GitLab автоматически подставит правильные значения в зависимости от окружения.

### Сценарий 3: Управление несколькими контекстами

**Просмотр доступных контекстов:**

```bash
docker context ls
```

**Вывод:**

```
NAME          DESCRIPTION                               DOCKER ENDPOINT
default       Current DOCKER_HOST based configuration   unix:///var/run/docker.sock
prod-swarm    Production Swarm Cluster                  tcp://prod.example.com:2376
dev-swarm     Development Swarm Cluster                 tcp://dev.example.com:2376
```

**Переключение между окружениями:**

```bash
# Production
docker context use prod-swarm
docker service ls

# Development
docker context use dev-swarm
docker service ls
```

**Удаление контекста:**

```bash
docker context rm dev-swarm
```

### Сценарий 4: Отладка и диагностика

**Проверка текущего контекста:**

```bash
docker context show
```

**Инспекция контекста:**

```bash
docker context inspect prod-swarm
```

**Проверка подключения:**

```bash
# Переключение на контекст
docker context use prod-swarm

# Проверка списка узлов
docker node ls

# Проверка сервисов
docker service ls

# Проверка журналов
docker service logs myapp
```

**Диагностика проблем:**

```bash
# Проверка журналов Docker на менеджере
sudo journalctl -u docker -f

# Проверка доступности порта
telnet manager.example.com 2376

# Проверка сертификатов
openssl x509 -in ~/.docker/ca.pem -text -noout
```

## Дополнительная информация

### Безопасность

**Рекомендации для продакшена:**

- **Хранение секретов:** Используйте GitLab CI Variables типа File для сертификатов
- **Маскирование:** Включите опцию "Masked" для чувствительных переменных
- **Environment Scope:** Разделяйте доступ к разным окружениям через скоупы
- **Ротация ключей:** Регулярно обновляйте клиентские сертификаты

**Аудит безопасности:**

```bash
# Проверка прав на файлы сертификатов
ls -la ~/.docker/*.pem

# Проверка активных контекстов
docker context ls

# Проверка текущего подключения
docker info | grep "Docker Root Dir"
```

### Распространенные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| `context not found` | Контекст не создан | Выполнить `docker context create` |
| `Cannot connect to the Docker daemon` | Неправильный DOCKER_HOST | Проверить адрес и порт |
| `certificate has expired` | Истек срок сертификата | Перегенерировать сертификаты |
| `permission denied` | Неправильные права на ключи | `chmod 600 ~/.docker/*.pem` |

### Связанные документы

- **Настройка кластера (mTLS)** — **[swarm_setup.md](./swarm_setup.md)**
- **Управление через CLI** — **[../swarm_management_cli.md](../swarm_management_cli.md)**
- **Переменные GitLab CI** — **[../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**
- **Развертывание инфраструктуры** — **[infra_deployment.md](./infra_deployment.md)**
- **Развертывание приложения** — **[app_deployment.md](./app_deployment.md)**
