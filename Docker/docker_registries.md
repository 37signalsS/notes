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

**Документация Harbor:**
- [Обзор возможностей](./Docker_registries/Harbor/overview.md)
- [Установка (Docker Compose, Helm)](./Docker_registries/Harbor/installation.md)
- [Работа с реестром](./Docker_registries/Harbor/usage.md)
- [Настройка TLS](./Docker_registries/Harbor/certificates.md)

## Дополнительная информация

**Безопасность:**
- [Безопасность публичных реестров](./Docker_registries/public_registry_security.md) — угрозы, сканирование, подписи
- [Сканирование уязвимостей](./Docker_security/vulnerability_scanning.md) — Trivy, Clair, Dockle

**Версионирование:**
- [Версионирование и тегирование образов](./Docker_registries/image_versioning_and_tagging.md) — стратегии, best practices

**Сравнение реестров:**

| Реестр | Тип | Сканирование | Подпись | Репликация |
| :--- | :--- | :--- | :--- | :--- |
| **Docker Hub** | Public/Private | Базовый (Premium) | — | — |
| **GHCR** | Public/Private | Зависит от интеграции | — | — |
| **Harbor** | Private | Trivy/Clair | Notary/Cosign | ✓ |
| **GitLab Registry** | Private | Зависит от интеграции | — | — |

**Связанные темы:**
- [Команды Docker CLI](./docker_commands.md)
- [Управление артефактами в CI/CD](../CI-CD/artifact_management.md)
