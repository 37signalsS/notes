# Kompose: Конвертация Docker Compose в Kubernetes

## Определения

**Kompose** — инструмент командной строки для конвертации файлов `compose.yml` (Docker Compose) в манифесты Kubernetes (Deployments, Services, ConfigMaps, PVC и др.) или Helm-чарты. Он служит "мостиком" для быстрого переноса приложений из среды локальной разработки Docker в кластер Kubernetes.

Официальный репозиторий: [github.com/kubernetes/kompose](https://github.com/kubernetes/kompose).

**Актуальная версия:** v1.38.0.

---

## Основные концепции

### Принцип работы

Kompose использует библиотеку `compose-go` (референтная библиотека для парсинга Compose-файлов) для чтения конфигурации и сопоставления директив Compose с объектами Kubernetes. Поддерживается современная **Compose Specification**, что позволяет обрабатывать файлы без указания версии (`version: "3.x"` устарел и не требуется).

Процесс конвертации:
1. Парсинг `compose.yml` через `compose-go`
2. Маппинг сервисов Compose на ресурсы Kubernetes (Deployment, Service, ConfigMap, PVC)
3. Генерация YAML-манифестов с пространством имён по умолчанию (`default`) или указанного через флаг `-n`

### Маппинг Compose -> Kubernetes

| Директива Compose | Ресурс Kubernetes | Примечание |
| :--- | :--- | :--- |
| `image` | `Deployment` / `Pod` | Образ контейнера |
| `ports` | `Service` | По умолчанию `ClusterIP`; тип меняется через метки |
| `volumes` (named) | `PersistentVolumeClaim` | Требует StorageClass в кластере |
| `volumes` (bind) | `ConfigMap` или PVC | Bind-монты конвертируются условно (см. раздел "Ограничения") |
| `environment` | `Deployment` (env) | Переменные окружения как есть |
| `build` | не создаёт ресурс | Требует предварительной сборки образа или флага `--build` |
| `deploy.replicas` | `spec.replicas` | Количество реплик |
| `deploy.resources.limits` | `resources.limits` | Лимиты CPU/RAM |
| `deploy.resources.reservations` | `resources.requests` | Запросы CPU/RAM |
| `depends_on` | `Init Containers` | Только базовый порядок; conditions не поддерживаются |
| `networks` (именованные) | `NetworkPolicy` (частично) | В大多数 случаев игнорируется (в K8s все поды в namespace могут общаться) |
| `network_mode: host` | не конвертируется | Нет прямого аналога в K8s; требует рефакторинга |
| `secrets` | `Secret` | Конвертируются с ограничениями (см. раздел "Секреты") |
| `healthcheck` | не создаёт probes | Требуется ручное добавление liveness/readiness |

### Метки (Labels) Kompose

С помощью специальных меток в `compose.yml` можно управлять процессом генерации и тонкой настройкой ресурсов:

#### Метки сервисов

| Метка | Описание | Пример значения |
| :--- | :--- | :--- |
| `kompose.service.type` | Тип создаваемого сервиса | `nodeport`, `loadbalancer`, `clusterip` |
| `kompose.service.expose` | Создание Ingress (K8s) или Route (OpenShift) | `true` или `domain.com` |
| `kompose.service.expose.ingress-class-name` | Класс Ingress-контроллера | `nginx`, `traefik` |
| `kompose.service.name_override` | Переопределение имени сервиса | `my-custom-name` |
| `kompose.service.healthcheck.liveness.http_get_port` | Порт для liveness-пробы | `8080` |
| `kompose.service.healthcheck.liveness.http_get_path` | Путь для liveness-пробы | `/healthz` |
| `kompose.service.healthcheck.readiness.http_get_port` | Порт для readiness-пробы | `8080` |
| `kompose.service.healthcheck.readiness.http_get_path` | Путь для readiness-пробы | `/ready` |

#### Метки контроллера

| Метка | Описание | Пример значения |
| :--- | :--- | :--- |
| `kompose.controller.type` | Выбор контроллера ресурсов | `deployment`, `daemonset`, `statefulset` |

#### Метки томов

| Метка | Описание | Пример значения |
| :--- | :--- | :--- |
| `kompose.volume.size` | Размер запрашиваемого Persistent Volume | `5Gi` |
| `kompose.volume.storage-class-name` | Имя StorageClass для PVC | `standard`, `fast` |

#### Метки сборки и образов

| Метка | Описание | Пример значения |
| :--- | :--- | :--- |
| `kompose.image-pull-secret` | Добавление секрета для скачивания образа | `reg-cred` |
| `kompose.image-pull-policy` | Политика скачивания образа | `Always`, `IfNotPresent`, `Never` |

#### Метки автомасштабирования

| Метка | Описание | Пример значения |
| :--- | :--- | :--- |
| `kompose.hpa.cpu` | Генерация Horizontal Pod Autoscaler по CPU (%) | `80` |
| `kompose.hpa.memory` | Генерация Horizontal Pod Autoscaler по памяти (%) | `80` |
| `kompose.hpa.replicas.min` | Минимальное количество реплик HPA | `2` |
| `kompose.hpa.replicas.max` | Максимальное количество реплик HPA | `10` |

---

## Практические сценарии

### Установка

#### macOS

```bash
# Homebrew (рекомендуется)
brew install kompose

# MacPorts
sudo port install kompose
```

#### Linux (бинарный файл)

```bash
# x86_64
curl -L https://github.com/kubernetes/kompose/releases/download/v1.38.0/kompose-linux-amd64 -o kompose

# ARM64
curl -L https://github.com/kubernetes/kompose/releases/download/v1.38.0/kompose-linux-arm64 -o kompose

chmod +x kompose
sudo mv ./kompose /usr/local/bin/kompose
```

#### Windows

```powershell
# Chocolatey
choco install kubernetes-kompose

# winget
winget install Kubernetes.kompose
```

#### Go (из main-ветки)

```bash
go install github.com/kubernetes/kompose@latest
```

#### CentOS / RHEL (EPEL)

```bash
sudo yum install epel-release
sudo yum -y install kompose
```

#### Docker (без установки на хост)

```bash
# Сборка образа из исходников
docker build -t kompose https://github.com/kubernetes/kompose.git#main

# Запуск конвертации через контейнер
docker run --rm -it -v $PWD:/opt -w /opt kompose kompose convert
```

### Проверка установки

```bash
kompose version
# → v1.38.0
```

### Базовая конвертация

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
    environment:
      POSTGRES_DB: myapp
      POSTGRES_PASSWORD: secret
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
# → INFO Kubernetes file "db-service.yaml" created
# → INFO Kubernetes file "db-data-persistentvolumeclaim.yaml" created
```

**Результат** — каждый сервис Compose становится Deployment + Service; именованные тома — PersistentVolumeClaim.

### Вывод в директорию

```bash
kompose convert -o k8s/
# Все манифесты будут созданы в папке k8s/
```

### Расширенные возможности

```bash
# Генерация Helm-чарта вместо отдельных YAML
kompose convert --chart

# Генерация манифестов для OpenShift (Route вместо Ingress)
kompose convert --provider openshift

# Сборка образов перед генерацией (нужен локальный Docker)
kompose convert --build local

# Сборка и пуш в реестр
kompose convert --build remote

# Указание пространства имён
kompose convert -n my-namespace

# Использование JMESPath-выражения для фильтрации
kompose convert --jinja ""
```

### Развертывание и удаление

```bash
# Конвертация и немедленный применение к кластеру (аналог kubectl apply)
kompose up

# Удаление ресурсов, созданных через kompose up
kompose down
```

### Полный workflow миграции с Docker Compose на Kubernetes

#### Шаг 1. Подготовка

```bash
# 1. Убедиться, что kubectl настроен и подключён к кластеру
kubectl cluster-info

# 2. Проверить наличие StorageClass (для PVC)
kubectl get storageclass
# → NAME                 PROVISIONER                    RECLAIMPOLICY   VOLUME...
# → standard (default)   k8s.io/minikube-hostpath       Delete         ...

# 3. Конвертировать Compose-файл
kompose convert -o k8s/
```

#### Шаг 2. Пост-конвертационная доработка

После конвертации необходимо вручную доработать манифесты:

**a) Добавить liveness/readiness probes:**

```yaml
# k8s/web-deployment.yaml (добавить в spec.containers)
containers:
  - name: web
    image: nginx:alpine
    ports:
      - containerPort: 80
    livenessProbe:
      httpGet:
        path: /
        port: 80
      initialDelaySeconds: 10
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /
        port: 80
      initialDelaySeconds: 5
      periodSeconds: 5
```

**b) Заменить plain-text секреты на Kubernetes Secrets:**

```bash
# Создать секрет
kubectl create secret generic db-secrets \
  --from-literal=POSTGRES_PASSWORD=secret \
  --from-literal=POSTGRES_DB=myapp \
  --dry-run=client -o yaml > k8s/db-secret.yaml
```

```yaml
# k8s/db-deployment.yaml — заменить env на secretKeyRef
env:
  - name: POSTGRES_PASSWORD
    valueFrom:
      secretKeyRef:
        name: db-secrets
        key: POSTGRES_PASSWORD
  - name: POSTGRES_DB
    valueFrom:
      secretKeyRef:
        name: db-secrets
        key: POSTGRES_DB
```

**c) Установить resource requests/limits:**

```yaml
resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi
```

**d) Настроить replicas:**

```yaml
spec:
  replicas: 2
```

#### Шаг 3. Тестирование

```bash
# Применить манифесты
kubectl apply -f k8s/

# Проверить статус подов
kubectl get pods -w

# Проверить сервисы
kubectl get svc

# Проверить логи
kubectl logs -l io.kompose.service=web

# Проверить ошибки
kubectl describe pod <pod-name>
```

#### Шаг 4. Валидация

```bash
# Проверить, что все поды в Running
kubectl get pods | grep -v Running
# → (пустой вывод = все OK)

# Проверить доступность сервиса
kubectl port-forward svc/web 8080:80
# → открыть http://localhost:8080
```

---

## Дополнительная информация

### Ограничения и особенности

1. **Bind-монты (local paths):** Локальные пути (`./config:/etc/config`) не маппятся напрямую. Kompose может создать PVC, но файлы не копируются. Рекомендуется использовать ConfigMap/Secret для конфигурационных файлов.

2. **Сети (networks):** Именованные сети Compose в большинстве случаев игнорируются, поскольку в Kubernetes все поды в одном namespace могут общаться по умолчанию. `network_mode: host` не конвертируется — требует рефакторинга архитектуры приложения.

3. **depends_on:** Поддерживается только базовый порядок запуска через Init Containers. Сложные условия (ожидание готовности через `condition: service_healthy`) не конвертируются. ДляWaiting-логики используйте `initContainers` с утилитами типа `wait-for-it` или `wget`.

4. **Healthchecks:** Директива `healthcheck` в Compose **не конвертируется** в liveness/readiness probes. Пробы необходимо добавлять вручную после конвертации.

5. **Секреты:** Директива `secrets` в Compose конвертируется в Kubernetes Secrets, но с ограничениями:
   - Файлы секретов должны существовать на диске перед конвертацией
   - Для внешних секретов (Vault, AWS Secrets Manager) используйте CSI-драйверы или External Secrets Operator
   - Environment-переменные с паролями конвертируются как plain-text — заменяйте на `secretKeyRef`

6. **Tomas (PVC):** PVC создаются автоматически, однако для их успешного связывания в кластере должен быть настроен динамический провижининг (StorageClass по умолчанию). Укажите `kompose.volume.storage-class-name` если в кластере несколько StorageClass.

7. **Сборка образов:** `build` в Compose не автоматизирует пуш в реестр. Используйте `--build local` для локальной сборки или `--build remote` для сборки+пуша. В production-сценариях рекомендуется выносить сборку в CI/CD-пайплайн.

8. **Production:** Kompose — отличный инструмент для быстрого старта и прототипирования. Для промышленной эксплуатации рекомендуется использовать результат как основу для GitOps-процессов через [Helm](./Helm/helm_overview.md) или Kustomize, добавляя probes, network policies, RBAC и логирование.

### Типичные ошибки и их решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Error: no StorageClass defined` | В кластере нет StorageClass по умолчанию | Создайте StorageClass или укажите `kompose.volume.storage-class-name` |
| `Pod stuck in Pending` | PVC не может быть provisioned | Проверьте `kubectl get pvc` и наличие подходящего StorageClass |
| `CrashLoopBackOff` | Приложение не может прочитать секреты/конфиги | Проверьте, что Secrets и ConfigMap созданы до подов |
| `ImagePullBackOff` | Образ недоступен в реестре кластера | Убедитесь, что образ в accessible registry; добавьте imagePullSecrets |
| `Bind mount not working` | Локальный путь не скопировался | Используйте ConfigMap/Secret или `emptyDir` вместо bind-монта |

### Команды диагностики

```bash
# Статус всех ресурсов
kubectl get all -n <namespace>

# Детали конкретного пода
kubectl describe pod <pod-name>

# Логи (включая previous если под перезапускался)
kubectl logs <pod-name> --previous

# События кластера (ошибки, предупреждения)
kubectl get events --sort-by='.lastTimestamp'

# Проверка PVC
kubectl get pvc
kubectl describe pvc <pvc-name>
```

### Смотрите также

- [Docker Compose](../../Docker/Docker_compose/docker_compose_file_example.md) — примеры современных файлов Compose.
- [Kubernetes — обзор](../kubernetes_overview.md) — фундаментальные концепции K8s.
- [Helm](./Helm/helm_overview.md) — управление релизами в Kubernetes.
