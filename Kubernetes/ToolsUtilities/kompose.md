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

С помощью специальных меток в `compose.yml` можно управлять процессом генерации и тонкой настройкой ресурсов:

| Метка | Описание | Пример значения |
| :--- | :--- | :--- |
| `kompose.service.type` | Тип создаваемого сервиса | `nodeport`, `loadbalancer`, `clusterip` |
| `kompose.service.expose` | Создание Ingress (K8s) или Route (OpenShift) | `true` или `domain.com` |
| `kompose.controller.type` | Выбор контроллера ресурсов | `deployment`, `daemonset`, `statefulset` |
| `kompose.volume.size` | Размер запрашиваемого Persistent Volume | `5Gi` |
| `kompose.service.name_override` | Переопределение имени сервиса | `my-custom-name` |
| `kompose.hpa.cpu` | Генерация Horizontal Pod Autoscaler по CPU (%) | `80` |
| `kompose.image-pull-secret` | Добавление секрета для скачивания образа | `reg-cred` |

## Практические сценарии

### Установка

Версия v1.38.0:

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
# → v1.38.0
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

### Развертывание в один клик

Инструмент может не только генерировать файлы, но и сразу применять их к текущему контексту кластера:

```bash
# Конвертация и немедленный запуск (kubectl apply)
kompose up

# Удаление ресурсов, созданных через kompose up
kompose down
```

## Дополнительная информация

### Ограничения и особенности

1.  **Неполное соответствие:** Сложные настройки сетей (`macvlan`, `host`), `cgroup_parent` и специфичные параметры ядра (sysctls) игнорируются.
2.  **Зависимости (depends_on):** Поддерживается только базовый порядок запуска. Сложные условия (например, ожидание готовности базы через `healthcheck`) требуют ручного внедрения `InitContainers`.
3.  **Секреты:** Директива `secrets` в Compose конвертируется в Kubernetes Secrets, но требует предварительного создания файлов на диске или использования меток для внешних секретов.
4.  **Статичность и Production:** Kompose — отличный инструмент для быстрого старта, но для промышленной эксплуатации рекомендуется использовать результат как основу для GitOps-процессов через Helm или Kustomize.
5.  **Тома:** PVC создаются автоматически, однако для их успешного связывания в кластере должен быть настроен динамический провижининг (StorageClass по умолчанию).

### Смотрите также

- [Docker Compose](../../Docker/Docker_compose/docker_compose_file_example.md) — примеры современных файлов Compose.
- [Kubernetes — обзор](../kubernetes_overview.md) — фундаментальные концепции K8s.
- [Helm](./helm/helm_overview.md) — управление релизами в Kubernetes.
