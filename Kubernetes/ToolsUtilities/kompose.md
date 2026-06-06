# Kompose: Конвертация Docker Compose в Kubernetes

## Определения

**Kompose** — инструмент командной строки для конвертации файлов `docker-compose.yml` в ресурсы Kubernetes (Deployments, Services, ConfigMaps и др.). Упрощает миграцию приложений с Docker Compose на Kubernetes.

Официальный репозиторий: **[github.com/kubernetes/kompose](https://github.com/kubernetes/kompose)**.

## Основные концепции

### Принцип работы

Kompose анализирует сервисы, порты, тома и другие директивы в `docker-compose.yml` и генерирует стандартные манифесты Kubernetes в формате YAML. Это позволяет быстро развернуть простое приложение в Kubernetes без ручного написания манифестов.

### Поддерживаемые директивы Compose

- `image` → `Deployment` с указанием образа
- `ports` → `Service` с настройкой портов
- `volumes` → `PersistentVolumeClaim` или `hostPath`
- `environment` / `env_file` → `ConfigMap` или переменные окружения в `Deployment`
- `depends_on` → не поддерживается напрямую (требуется ручная доработка)
- `networks` → ограниченная поддержка (требуется ручная настройка)

## Практические сценарии

### Конвертация и развертывание

**Установка:**

```bash
# macOS (Homebrew)
brew install kompose

# Linux
curl -L https://github.com/kubernetes/kompose/releases/latest/download/kompose-linux-amd64 \
  -o kompose && chmod +x kompose && sudo mv kompose /usr/local/bin/
```

**Конвертация:**

```yaml
# docker-compose.yml
version: '3.8'
services:
  web:
    image: nginx:latest
    ports:
      - "80:80"
  app:
    image: my-app:latest
    ports:
      - "5000:5000"
```

```bash
# Конвертация в манифесты Kubernetes
kompose convert
```

Будут созданы файлы: `web-deployment.yaml`, `web-service.yaml`, `app-deployment.yaml`, `app-service.yaml`.

**Развертывание:**

```bash
kubectl apply -f .
```

### Конвертация с флагами

```bash
# Генерация с указанием controller type
kompose convert --controller deployment

# Конвертация с chart для Helm
kompose convert --chart

# Вывод в stdout вместо файлов
kompose convert -o -
```

## Дополнительная информация

### Смотрите также

- [Docker Compose](../../Docker/Docker_compose/docker_compose_file_example.md) — примеры файлов Compose.
- [Kubernetes — обзор](../kubernetes_overview.md) — основы Kubernetes.
- [Kustomize](./kustomize/kustomize_overview.md) — альтернативный инструмент управления манифестами.
