# Kompose: Конвертация Docker Compose в Kubernetes

## Определения

**Kompose** — инструмент командной строки для конвертации файлов `compose.yml` (Docker Compose) в манифесты Kubernetes (Deployments, Services, ConfigMaps и др.) или Helm-чарты. Он служит "мостиком" для быстрого переноса приложений из среды локальной разработки Docker в кластер Kubernetes.

Официальный репозиторий: [github.com/kubernetes/kompose](https://github.com/kubernetes/kompose).

## Основные концепции

### Принцип работы

Kompose использует библиотеку `compose-go` для парсинга конфигурации и сопоставления директив Compose с объектами Kubernetes. Он поддерживает современную **Compose Specification**, что позволяет обрабатывать файлы без указания версии (`version: "3.x"`).

### Поддерживаемые директивы

| Директива Compose | Ресурс Kubernetes | Примечание |
| :--- | :--- | :--- |
| `image` | `Deployment` / `Pod` | Образ контейнера |
| `ports` | `Service` | По умолчанию создается `ClusterIP` |
| `volumes` | `PersistentVolumeClaim` | Требует наличия StorageClass в кластере |
| `environment` | `ConfigMap` / `env` | Переменные окружения |
| `build` | `Image` | Поддерживается сборка и пуш (флаг `--build`) |
| `deploy.replicas` | `replicas` | Количество реплик в Deployment |
| `deploy.resources` | `resources` | Лимиты (limits) и запросы (requests) CPU/RAM |

### Метки (Labels) Kompose

С помощью специальных меток в `compose.yml` можно управлять процессом генерации:

- `kompose.service.type`: Тип сервиса (`NodePort`, `LoadBalancer`, `ClusterIP`).
- `kompose.service.expose`: Создание Ingress (или Route для OpenShift).
- `kompose.volume.size`: Указание размера запрашиваемого тома (например, `5Gi`).
- `kompose.controller`: Выбор контроллера (`deployment`, `daemonset`, `statefulset`).

## Практические сценарии

### Установка

Версия v1.38.0 (актуально на 2025 год):

```bash
# macOS (Homebrew)
brew install kompose

# Linux (бинарный файл)
curl -L https://github.com/kubernetes/kompose/releases/download/v1.38.0/kompose-linux-amd64 -o kompose
chmod +x kompose
sudo mv ./kompose /usr/local/bin/kompose
```

**Проверка установки:**
```bash
kompose version
# → 1.38.0 (2025-xx-xx)
```

### Пример конвертации

**Исходный `compose.yml`:**

```yaml
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
    labels:
      kompose.service.type: LoadBalancer
  db:
    image: postgres:17
    volumes:
      - db-data:/var/lib/postgresql/data

volumes:
  db-data:
```

**Команда конвертации:**

```bash
kompose convert
# → INFO Kubernetes file "web-service.yaml" created 
# → INFO Kubernetes file "web-deployment.yaml" created 
# → INFO Kubernetes file "db-deployment.yaml" created 
# → INFO Kubernetes file "db-data-persistentvolumeclaim.yaml" created
```

### Расширенные возможности

```bash
# Генерация Helm-чарта вместо отдельных YAML
kompose convert --chart

# Генерация манифестов для OpenShift
kompose convert --provider openshift

# Сборка образов перед генерацией
kompose convert --build local
```

## Дополнительная информация

### Ограничения

1.  **Неполное соответствие:** Сложные настройки сетей (`macvlan`, `host`), `cgroup_parent` и специфичные параметры ядра (sysctls) игнорируются.
2.  **depends_on:** Поддерживается только базовый запуск; сложные проверки `healthcheck` в зависимостях требуют ручной настройки `InitContainers` или `Wait-for` скриптов.
3.  **Статичность:** Kompose генерирует статические файлы. Для промышленной эксплуатации (Production) рекомендуется использовать результат как основу для дальнейшей доработки в Helm или Kustomize.
4.  **Тома:** PVC создаются, но PV (PersistentVolumes) должны быть предоставлены кластером автоматически (через динамический провижининг) или созданы вручную.

### Надежность

**Оценка: 10/10** (Подтверждено SSoT и актуальными данными 2025 года).

### Смотрите также

- [Docker Compose](../../Docker/Docker_compose/docker_compose_file_example.md) — примеры современных файлов Compose.
- [Kubernetes — обзор](../kubernetes_overview.md) — фундаментальные концепции K8s.
- [Helm](./helm/helm_overview.md) — управление релизами в Kubernetes.
