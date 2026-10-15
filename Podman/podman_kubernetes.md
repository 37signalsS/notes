# Podman и Kubernetes

## Определения

**Podman kube play** — команда Podman для запуска подов из Kubernetes YAML-манифестов. Позволяет тестировать K8s-конфигурации локально без самого Kubernetes.

**Podman kube generate** — команда Podman для генерации Kubernetes YAML-манифестов из запущенных подов/контейнеров. Упрощает миграцию от Podman к Kubernetes.

**CRI-O** — легковесный runtime для Kubernetes, совместимый с Podman. Использует те же OCI-образы и хранилище.

**Quadlet** — система генерации systemd-юнитов из Podman-контейнеров. Интегрируется с systemd для управления контейнерами как сервисами.

**Podman socket** — API-сервер Podman, совместимый с Docker API. Позволяет использовать Podman как замену Docker daemon.

---

## Теоретический блок

### Podman vs Kubernetes: соотношение

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes (production)                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                  Pod (K8s API object)                │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐         │    │
│  │  │Container │  │Container │  │  Init    │         │    │
│  │  │    1     │  │    2     │  │Container │         │    │
│  │  └──────────┘  └──────────┘  └──────────┘         │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  Podman (local/dev)                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                  Pod (Podman concept)                │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐         │    │
│  │  │Container │  │Container │  │  Infra   │         │    │
│  │  │    1     │  │    2     │  │Container │         │    │
│  │  └──────────┘  └──────────┘  └──────────┘         │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Когда использовать Podman vs Kubernetes

| Сценарий | Инструмент |
|---|---|
| Локальная разработка | Podman |
| Тестирование K8s манифестов | Podman kube play |
| CI/CD сборка и тестирование | Podman |
| Production deployment | Kubernetes |
| Single-node production | Podman + systemd (Quadlet) |
| Multi-node cluster | Kubernetes |

---

## Практический блок

### 1. Podman kube play — запуск K8s манифестов

#### Базовый пример

```yaml
# nginx-pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx-pod
  labels:
    app: nginx
spec:
  containers:
    - name: nginx
      image: nginx:alpine
      ports:
        - containerPort: 80
      resources:
        requests:
          memory: "64Mi"
          cpu: "250m"
        limits:
          memory: "128Mi"
          cpu: "500m"
```

```bash
# Запуск пода
podman kube play nginx-pod.yaml

# Повторный запуск с заменой существующих ресурсов (--replace)
podman kube play nginx-pod.yaml --replace

# Проверка
podman ps
podman pod ps

# Остановка и удаление
podman kube down nginx-pod.yaml
```

#### Многоконтейнерный под

```yaml
# app-pod.yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-pod
spec:
  containers:
    - name: app
      image: my-app:latest
      ports:
        - containerPort: 8080
      env:
        - name: DATABASE_URL
          value: "postgresql://postgres:password@localhost:5432/mydb"
    - name: postgres
      image: postgres:15-alpine
      ports:
        - containerPort: 5432
      env:
        - name: POSTGRES_PASSWORD
          value: "password"
        - name: POSTGRES_DB
          value: "mydb"
      volumeMounts:
        - name: pgdata
          mountPath: /var/lib/postgresql/data
  volumes:
    - name: pgdata
      persistentVolumeClaim:
        claimName: pgdata-pvc
```

```bash
# Запуск
podman kube play app-pod.yaml

# Проверка логов
podman logs app-pod-app
podman logs app-pod-postgres

# Подключение к контейнеру
podman exec -it app-pod-app sh
```

### 2. Podman kube generate — генерация K8s манифестов

```bash
# Создание пода
podman pod create --name my-pod -p 8080:80
podman run --pod my-pod -d nginx:alpine

# Генерация YAML
podman kube generate my-pod > my-pod.yaml

# Просмотр сгенерированного манифеста
cat my-pod.yaml

# Генерация в STDOUT
podman kube generate my-pod
```

### 3. Генерация из запущенных контейнеров

```bash
# Запуск контейнера
podman run -d --name my-app -p 8080:8080 my-app:latest

# Генерация K8s YAML
podman kube generate my-app > my-app-deployment.yaml

# Редактирование для Kubernetes
# (добавить replicas, strategy, и т.д.)
```

### 4. Quadlet — systemd интеграция

#### Создание контейнерного файла

```ini
# /etc/containers/systemd/my-app.container
[Unit]
Description=My Application
After=network-online.target

[Container]
Image=my-app:latest
PublishPort=8080:8080
Volume=my-app-data.volume:/app/data:rw
Network=my-app.network
AutoUpdate=registry

[Service]
Restart=always
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target default.target
```

#### Создание тома

```ini
# /etc/containers/systemd/my-app-data.volume
[Volume]
VolumeName=my-app-data
Label=com.example.type=app-data
```

#### Создание сети

```ini
# /etc/containers/systemd/my-app.network
[Network]
NetworkName=my-app
Subnet=10.89.0.0/24
Gateway=10.89.0.1
```

#### Управление через systemd

```bash
# Перезагрузить systemd
sudo systemctl daemon-reload

# Запустить
sudo systemctl start my-app

# Проверить статус
sudo systemctl status my-app

# Остановить
sudo systemctl stop my-app

# Автозапуск
sudo systemctl enable my-app

# Логи
journalctl -u my-app -f
```

### 5. Podman socket — Docker API совместимость

```bash
# Запуск Podman socket (rootless)
podman machine ssh -- systemctl --user enable --now podman.socket

# Проверка
ls -la /run/user/$(id -u)/podman/podman.sock

# Использование через Docker CLI
DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock docker ps

# Настройка永久ного подключения
export DOCKER_HOST=unix:///run/user/$(id -u)/podman/podman.sock
```

#### Запуск через systemd (на Linux)

```ini
# ~/.config/systemd/user/podman.socket
[Unit]
Description=Podman API Socket
After=podman.service

[Socket]
ListenStream=%t/podman/podman.sock
SocketMode=0660

[Install]
WantedBy=sockets.target
```

```bash
systemctl --user enable --now podman.socket
```

### 6. Тестирование K8s манифестов

#### Сценарий: Тест перед деплоем

```bash
# 1. Сгенерировать манифест из Podman
podman kube generate my-pod > test-pod.yaml

# 2. Добавить K8s-специфичные поля
# (replicas, strategy, readinessProbe, и т.д.)

# 3. Протестировать локально
podman kube play test-pod.yaml

# 4. Проверить работу
curl http://localhost:8080/health

# 5. Остановить
podman kube down test-pod.yaml

# 6. Деплой в Kubernetes
kubectl apply -f test-pod.yaml
```

### 7. Миграция Podman → Kubernetes

```bash
# 1. Создать Podman под
podman pod create --name my-app -p 8080:80
podman run --pod my-app -d my-app:latest
podman run --pod my-app -d sidecar:latest

# 2. Сгенерировать K8s YAML
podman kube generate my-app > my-app-k8s.yaml

# 3. Адаптировать для Kubernetes
# - Добавить Deployment
# - Добавить Service
# - Добавить ConfigMap/Secrets
# - Настроить probes

# 4. Проверить
kubectl apply -f my-app-k8s.yaml
kubectl get pods
kubectl logs -f deployment/my-app
```

### 8. CI/CD с Podman и Kubernetes

```yaml
# .gitlab-ci.yml
stages:
  - build
  - test
  - deploy

build:
  stage: build
  script:
    - podman build -t myapp:${CI_COMMIT_SHA} .

test_local:
  stage: test
  script:
    - podman kube play test-pod.yaml
    - curl -f http://localhost:8080/health
    - podman kube down test-pod.yaml

deploy:
  stage: deploy
  only:
    - main
  script:
    - kubectl set image deployment/myapp myapp=myapp:${CI_COMMIT_SHA}
```

---

## Дополнительная информация

### Сравнение Podman Pod vs Kubernetes Pod

| Аспект | Podman Pod | Kubernetes Pod |
|---|---|---|
| Infra container | Да (automatically) | Нет |
| Networking | Podman network | CNI/CSI |
| Storage | Volumes, bind mounts | PV/PVC, CSI |
| Lifecycle | Start/stop | readiness/liveness probes |
| Scaling | Manual | HPA, replicas |
| Orchestration | Single host | Multi-node cluster |

### Quadlet vs Docker Compose

| Аспект | Quadlet | Docker Compose |
|---|---|---|
| Systemd интеграция | Нативная | Через wrapper |
| Автозапуск | `systemctl enable` | `restart: always` |
| Обновление | `podman auto-update` | Manual/pull |
| Зависимости | systemd deps | depends_on |
| Логирование | journald | drivers |

Подробное сравнение Quadlet и Podlet, примеры конфигураций и сценарии миграции см. в [Quadlet и Podlet](./podman-quadlet-vs-podlet.md).

### Типичные проблемы

| Проблема | Причина | Решение |
|---|---|---|
| `podman kube play` не работает | Несовместимые K8s поля | Убрать unsupported поля |
| Нет networking между контейнерами | Podman vs K8s networking | Проверить `podman pod inspect` |
| Quadlet не стартует | Ошибка в unit файле | `systemctl status`, `journalctl -u` |
| Socket не работает | Не запущен | `systemctl --user enable podman.socket` |

### Ссылки

- **[Podman Pods](./podman_pods.md)** — концепция подов в Podman
- **[Podman dependencies](./podman-dependencies.md)** — зависимости контейнеров
- **[Podman auto-update](./podman_auto_update.md)** — автоматическое обновление
- **[Podman compose](./podman-compose.md)** — Docker Compose совместимость
- **[Kubernetes overview](../../Kubernetes/kubernetes_overview.md)** — обзор Kubernetes
- **[Kubernetes Pods](../../Kubernetes/Base/Pod/)** — Pod в Kubernetes

# force reindex test
