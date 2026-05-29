# Docker Registry: Хранение и распространение образов

## Определения

**Docker Registry** — сервис для хранения и распространения Docker-образов. Централизованное хранилище для скачивания (pull) и загрузки (push) образов.

**Ключевые понятия:**

| Понятие | Описание |
| :--- | :--- |
| **Реестр (Registry)** | Хранилище образов (Docker Hub, Harbor, GHCR, GitLab Registry) |
| **Репозиторий** | Коллекция образов с одним именем, разными тегами (`ubuntu`) |
| **Тег (Tag)** | Метка версии образа внутри репозитория (`ubuntu:22.04`) |
| **Частный реестр** | Реестр с ограниченным доступом (on-premise, VPN) |

**Типы реестров:**

- **Публичные:** Docker Hub (бесплатно с ограничениями)
- **Частные:** Harbor, GitLab Registry, Nexus, GHCR (GitHub Container Registry)

Реестры контейнеров — частный случай [репозиториев артефактов](../CI-CD/artifact_management.md).

## Основные концепции

### Разделение сред (Dev / Prod)

Лучшей практикой безопасности является использование **разных реестров для разных сред** (например, отдельный реестр для Development/Testing и отдельный для Pre-Prod/Production).

- **Разделение нагрузок:** В Dev-реестре разработчики создают множество образов, которые сканируются на уязвимости по запросу. В Prod-реестре образы хранятся дольше и сканируются регулярно (так как появляются новые уязвимости).
- **Безопасность (Supply Chain):** Образы попадают в Prod-реестр только после прохождения полного CI/CD пайплайна, сканирования и **криптографической подписи**. Доступ на push в Prod-реестр должен быть только у автоматизированных пайплайнов (ручной push запрещен). Это также исключает возможность использования единого реестра как скрытого канала передачи данных между изолированными контурами.

### Рабочий процесс

```
1. docker login → аутентификация
2. docker tag → присвоение имени реестра
3. docker push → отправка в реестр
4. docker pull → получение из реестра
```

### Аутентификация

```bash
# Вход в реестр
docker login my-registry.example.com

# Выход
docker logout my-registry.example.com
```

Токен сохраняется в `~/.docker/config.json`.

### Тегирование

```bash
# Формат: <реестр>/<проект>/<образ>:<тег>
docker tag my-app:latest registry.example.com/my-project/my-app:1.0.0
```

### Отправка и получение

```bash
# Push (отправляются только новые слои)
docker push registry.example.com/my-project/my-app:1.0.0

# Pull (по умолчанию Docker Hub)
docker pull registry.example.com/my-project/my-app:1.0.0
docker pull ubuntu:22.04  # эквивалент docker.io/library/ubuntu:22.04
```

Подробнее: [Команды Docker CLI](./docker_commands.md)

## Практические сценарии

### Сценарий 1: GitHub Container Registry (GHCR)

**GHCR** — OCI-совместимый реестр с интеграцией в GitHub. Аутентификация через Personal Access Tokens.

**Настройка:**

```bash
# 1. Создать токен: Profile → Settings → Developer settings → Personal access tokens
# Scope: write:packages (push), read:packages (pull)

# 2. Аутентификация
docker login ghcr.io -u <username> -p <token>

# 3. Тегирование и публикация
docker tag my-app:latest ghcr.io/<username>/<repo>:v1.0.0
docker push ghcr.io/<username>/<repo>:v1.0.0

# 4. Kubernetes Secret для imagePullSecrets
kubectl create secret docker-registry registry-secret \
  --docker-server=ghcr.io \
  --docker-username=<username> \
  --docker-password=<token> \
  -n <namespace>
```

**Использование в werf:** [Werf: Автоматизация сборки и развёртывания](../CI-CD/Tools/werf_overview.md)

### Сценарий 2: Harbor (корпоративный реестр)

**Harbor** — open-source реестр с расширенными возможностями для enterprise:

- Сканирование уязвимостей (Trivy/Clair)
- Подпись образов (Notary/Cosign)
- Репликация между инстансами
- Робот-аккаунты для CI/CD

**Базовое использование:**

```bash
# Аутентификация
docker login harbor.example.com

# Тегирование
docker tag my-app:latest harbor.example.com/library/my-app:v1

# Push/Pull
docker push harbor.example.com/library/my-app:v1
docker pull harbor.example.com/library/my-app:v1
```

**Документация Harbor:** подробное описание см. в [обзоре Harbor](./Docker_registries/Harbor/overview.md), [установке](./Docker_registries/Harbor/installation.md), [настройке TLS](./Docker_registries/Harbor/certificates.md) и [работе с реестром](./Docker_registries/Harbor/usage.md).

### Docker Hub — реестр по умолчанию

**Docker Hub** (hub.docker.com) — официальный публичный реестр, который Docker использует по умолчанию при отсутствии явного указания другого registry.

**Ключевые особенности:**

- При выполнении `docker pull nginx` образ загружается из Docker Hub (`docker.io/library/nginx:latest`)
- Содержит каталог **официальных образов** (Docker Official Images) — образы, прошедшие проверку качества и безопасности (Ubuntu, Node, MySQL, Nginx, PostgreSQL и др.)
- Официальные образы отмечены бейджем «Official Image» и имеют высокий рейтинг (звёзды) и количество загрузок
- Поддерживает публичные и приватные репозитории (бесплатно — 1 приватный)
- Авторизация через `docker login` или OAuth (GitHub)

**Полный путь к образу:**

```bash
# Короткая запись (по умолчанию Docker Hub)
docker pull ubuntu:22.04

# Полный путь (docker.io — адрес Docker Hub, library — пространство официальных образов)
docker pull docker.io/library/ubuntu:22.04

# Образ пользователя/организации
docker pull evsq/getting-started-todo-app:latest
```

> **Рекомендация:** в production используйте частные реестры (Harbor, GHCR, GitLab Registry). Публичные образы из Docker Hub следует проверять: смотреть рейтинг, количество загрузок, дату последнего обновления.

**Авторизация для push:**

```bash
# Вход в Docker Hub
docker login

# После входа можно отправлять образы в свой репозиторий
docker tag my-app:latest evsq/my-app:v1
docker push evsq/my-app:v1
```

При сборке образа с целью последующей отправки в реестр необходимо указывать имя пользователя в теге. Без этого Docker не сможет определить целевой реестр.

## Дополнительная информация

**Сравнение реестров:**

| Реестр | Тип | Сканирование | Подпись | Репликация |
| :--- | :--- | :--- | :--- | :--- |
| **Docker Hub** | Public/Private | Базовый (Premium) | — | — |
| **GHCR** | Public/Private | Зависит от интеграции | — | — |
| **Harbor** | Private | Trivy/Clair | Notary/Cosign | ✓ |
| **GitLab Registry** | Private | Зависит от интеграции | — | — |

**См. также:**

- [Безопасность публичных реестров](./Docker_registries/public_registry_security.md)
- [Версионирование и тегирование образов](./Docker_registries/image_versioning_and_tagging.md)
- [Команды Docker CLI](./docker_commands.md)
