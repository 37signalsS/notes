# Эфемерные и автоскейлер раннеры в GitLab CI/CD

**Актуально для:** GitLab Runner 19.4.x (GitLab 19.x)

> **Статус:** Docker Machine executor помечен как deprecated (GitLab 17.5) и будет удалён в GitLab 20.0 (May 2027). Для новых развёртываний используйте Fleeting + Docker Autoscaler (`executor = "docker-autoscaler"`) или Instance executor. Материалы по Docker Machine оставлены только для миграции существующих конфигураций.

> **Примечание:** Полная теория типами раннеров, системным и project-level конфигурацией, сравнением моделей и стратегиями масштабирования описана в **[Управление парком Runner'ов](../Advanced/runner_fleet_management.md)**. Это руководство фокусируется на production-grade практических конфигурациях для self-hosted (on-prem) инфраструктуры.

## Определения

**Эфемерный Runner (Ephemeral Runner)** — исполнитель, который после выполнения одной (или ограниченного числа) задач уничтожается и заменяется свежим. Исключает накопление состояния (side-effects), кэш-атаки и «сноубола» зависимостей между джобами.

**Fleeting** — библиотека управления эфемерной инфраструктурой, разработанная GitLab. Через плагины взаимодействует с API оркестраторов и гипервизоров (libvirt/KVM, Proxmox, VMware vSphere), обеспечивая создание и удаление узлов по требованию.

**Taskscaler** — высокоуровневый планировщик, который распределяет задачи по инстансам Fleeting, учитывая их загрузку и жизненный цикл.

**Docker Autoscaler** — executor, который оборачивает Docker executor и использует Fleeting для динамического создания VM с Docker Engine на борту. GA начиная с GitLab Runner 17.1.

**Instance Executor** — executor, создающий виртуальные машины по требованию через Fleeting. Выполняет задачу напрямую на хосте VM без Docker-in-Docker. GA начиная с GitLab Runner 17.1.

**Runner Manager** — процесс-демон (`gitlab-runner`), который опрашивает GitLab API, получает задания и управляет жизненным циклом runner'ов.

## Архитектура и принципы работы

Современный парк эфемерных раннеров строится на трехуровневой архитектуре (подробности — в **[Управление парком Runner'ов](../Advanced/runner_fleet_management.md)**):

1. **Control Plane:** CI/CD сервер GitLab распределяет задачи и хранит метаданные флота.
2. **Orchestration Layer:** Fleeting + Taskscaler управляет жизненным циклом VM/контейнеров.
3. **Execution Layer:** Runner'ы (VM, контейнеры, bare metal), где выполняется код джобы.

### Жизненный цикл эфемерного runner'а

1. **Provisioning:** Fleeting создаёт вычислительный ресурс (VM или контейнер) через плагин гипервизора.
2. **Registration:** Runner Manager автоматически регистрирует новый инстанс в GitLab с использованием JIT Config (временные токены).
3. **Execution:** Выполнение задачи в изолированной среде.
4. **Deregistration & Termination:** После выполнения (или по истечении `idle_time`) инстанс удаляется из GitLab и уничтожается гипервизором.

### Модели изоляции

| Модель | Executor | Изоляция | Применение |
|:---|:---|:---|:---|
| **Одна джоба — одна VM** | `instance` | Полная (VM на задачу) | High-trust, security-sensitive |
| **Одна джоба — один Docker-контейнер на свежей VM** | `docker-autoscaler` | Высокая (Docker-in-VM) | Стандарт для Docker-based сборок |
| **Одна джоба — один Pod** | `kubernetes` | Высокая (Pod на задачу) | K8s-native окружения |

## Предварительные требования

### Аппаратные и программные требования

- **GitLab Server:** Self-hosted инстанс GitLab 19.x с доступным API
- **GitLab Runner:** 19.4.x, установленный из официального репозитория
- **ОС Runner Manager:** Linux (Ubuntu 22.04+/Debian 12+/RHEL 9+), systemd
- **Виртуализация:** Одна из поддерживаемых платформ:
  - KVM/libvirt (встроен в ядро Linux)
  - Proxmox VE
  - VMware vSphere
  - Bare metal с Docker Engine (для Kubernetes executor)
- **Сеть:** Runner Manager должен иметь доступ к GitLab API (исходящие HTTPS). Входящие соединения не требуются (Pull-модель).
- **NTP:** Синхронизация времени между GitLab Server и Runner Manager — критична для проверки JWT-подписи.
- **sysctl:** `net.ipv4.ip_forward = 1` для Docker bridge networking (если используется docker-autoscaler).

### Безопасность

- Включить `protected` и `locked` флаги для production Runner'ов в GitLab Admin Area
- Настроить Runner Groups с наследованием настроек
- Включить audit logging (Admin Area → Settings → Audit Events)
- Использовать отдельный ServiceAccount для Kubernetes executor'а с минимальными RBAC-правами

## Практические сценарии

### Сценарий 1: Fleeting + docker-autoscaler с libvirt/KVM (on-prem)

Настройка пула эфемерных VM на собственном гипервизоре через community plugin `fleeting-plugin-libvirt`. Каждая джоба получает свежую VM с Docker Engine, которая удаляется после выполнения.

**Установка плагина:**

```bash
# Установка gitlab-runner
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
sudo apt-get install -y gitlab-runner

# Установка fleeting-plugin-libvirt (community plugin)
sudo curl -L "https://gitlab.com/fleetingplugin/fleeting-plugin-libvirt/-/releases/latest/download/fleeting-plugin-libvirt-linux-amd64" \
  -o /usr/local/bin/fleeting-plugin-libvirt
sudo chmod +x /usr/local/bin/fleeting-plugin-libvirt
```

**Регистрация runner'а:**

```bash
sudo gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.corp.local" \
  --token "$RUNNER_REGISTRATION_TOKEN" \
  --executor "docker-autoscaler" \
  --description "docker-autoscaler-libvirt" \
  --tag-list "docker,linux,ephemeral,libvirt" \
  --run-untagged="false" \
  --locked="false"
```

**Конфигурация `/etc/gitlab-runner/config.toml`:**

```toml
concurrent = 8
check_interval = 0

[[runners]]
  name = "docker-autoscaler-libvirt"
  url = "https://gitlab.corp.local"
  token = "<runner-token>"
  executor = "docker-autoscaler"
  shell = "sh"
  [runners.docker]
    image = "docker:27.0"
    privileged = true
    disable_cache = false
    volumes = ["/cache", "/var/run/docker.sock:/var/run/docker.sock"]

  [runners.autoscaler]
    plugin = "fleeting-plugin-libvirt"
    capacity_per_instance = 1
    max_use_count = 1
    max_instances = 20
    delete_instances_on_shutdown = true
    log_internal_ip = true
    log_external_ip = true

    [runners.autoscaler.plugin_config]
      uri = "qemu:///system"
      pool_name = "default"
      pool_path = "/var/lib/libvirt/images"
      base_volume_name = "flatcar_production_qemu_image.img"
      vcpu_count = 2
      memory_mib = 4096
      disk_size_gib = 20
      max_size = 20

    [runners.autoscaler.connector_config]
      os = "linux"
      arch = "amd64"
      protocol = "ssh"
      protocol_port = 22
      username = "core"
      key_path = "/etc/gitlab-runner/libvirt-runner"
      use_static_credentials = true
      timeout = "10m"

    [[runners.autoscaler.policy]]
      idle_count = 3
      idle_time = "20m0s"
      preemptive_mode = true
```

**Проверка:**

```bash
# Проверка работы плагина
sudo gitlab-runner fleeting list
# → отображает установленный плагин и его версию

# Запуск runner'а
sudo systemctl enable --now gitlab-runner

# Проверка статуса
sudo gitlab-runner list
# → runner зарегистрирован и online

# Отправка тестовой задачи — в логах видно создание VM
sudo journalctl -u gitlab-runner -f
```

### Сценарий 2: Instance executor с Fleeting (self-hosted VM)

Настройка executor, который создаёт VM по требованию и выполняет задачу напрямую на хосте (без Docker-in-Docker). Подходит для задач, требующих доступа к оборудованию или специфичного ПО.

**Регистрация:**

```bash
sudo gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.corp.local" \
  --token "$RUNNER_REGISTRATION_TOKEN" \
  --executor "instance" \
  --description "instance-fleet-libvirt" \
  --tag-list "linux,instance,ephemeral" \
  --run-untagged="false" \
  --locked="false"
```

**Конфигурация `/etc/gitlab-runner/config.toml`:**

```toml
[[runners]]
  name = "instance-fleet-libvirt"
  url = "https://gitlab.corp.local"
  token = "<runner-token>"
  executor = "instance"
  shell = "bash"

  [runners.autoscaler]
    plugin = "fleeting-plugin-libvirt"
    capacity_per_instance = 1
    max_use_count = 1
    max_instances = 20
    delete_instances_on_shutdown = true

    [runners.autoscaler.plugin_config]
      uri = "qemu:///system"
      pool_name = "default"
      pool_path = "/var/lib/libvirt/images"
      base_volume_name = "ubuntu-22.04-ci.qcow2"
      vcpu_count = 4
      memory_mib = 8192
      disk_size_gib = 40
      max_size = 20

    [runners.autoscaler.connector_config]
      os = "linux"
      arch = "amd64"
      protocol = "ssh"
      protocol_port = 22
      username = "runner"
      key_path = "/etc/gitlab-runner/libvirt-runner"
      use_static_credentials = true
      timeout = "10m"

    [[runners.autoscaler.policy]]
      idle_count = 2
      idle_time = "20m0s"
      preemptive_mode = true

  [runners.instance]
    [runners.instance.pre_build_script]
      # Опционально: подготовка окружения перед задачей
      "apt-get update && apt-get install -y git build-essential"
```

**Проверка:**

```bash
# Проверка, что instance executor активен
sudo gitlab-runner list
# → executor: instance

# Тестовая задача — runner создаёт VM, выполняет задачу, удаляет VM
sudo journalctl -u gitlab-runner -f
```

### Сценарий 3: Kubernetes Executor (self-hosted)

Настройка runner'ов в self-hosted Kubernetes кластере. По умолчанию Kubernetes executor создаёт новый Pod на каждую задачу, что обеспечивает эфемерность без необходимости внешнего автоскейлера.

**Создание ServiceAccount и RBAC:**

```yaml
# gitlab-runner-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: gitlab-runner
  namespace: gitlab-runner
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: gitlab-runner
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "namespaces"]
    verbs: ["get", "list", "watch", "create", "delete", "update"]
  - apiGroups: [""]
    resources: ["services", "configmaps"]
    verbs: ["get", "list", "watch", "create", "delete", "update"]
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "create", "delete", "update"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch", "create", "delete", "update"]
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "watch", "create", "delete", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: gitlab-runner
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: gitlab-runner
subjects:
  - kind: ServiceAccount
    name: gitlab-runner
    namespace: gitlab-runner
```

```bash
kubectl apply -f gitlab-runner-rbac.yaml
```

**Регистрация runner'а:**

```bash
sudo gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.corp.local" \
  --token "$RUNNER_REGISTRATION_TOKEN" \
  --executor "kubernetes" \
  --description "k8s-ephemeral-runner" \
  --tag-list "k8s,linux,docker" \
  --run-untagged="false" \
  --locked="false"
```

**Конфигурация `/etc/gitlab-runner/config.toml`:**

```toml
[[runners]]
  name = "k8s-ephemeral-runner"
  url = "https://gitlab.corp.local"
  token = "<runner-token>"
  executor = "kubernetes"
  [runners.kubernetes]
    namespace = "gitlab-runner"
    image = "docker:27.0"
    privileged = true
    pull_policy = ["always"]
    cpu_request = "250m"
    cpu_limit = "1000m"
    memory_request = "256Mi"
    memory_limit = "2Gi"
    service_account = "gitlab-runner"
    [runners.kubernetes.pod_security_context]
      run_as_user = 1000
      run_as_group = 1000
      fs_group = 1000
    [runners.kubernetes.volumes]
      [[runners.kubernetes.volumes.host_path]]
        name = "docker"
        mount_path = "/var/run/docker.sock"
        host_path = "/var/run/docker.sock"
      [[runners.kubernetes.volumes.host_path]]
        name = "cache"
        mount_path = "/cache"
        host_path = "/tmp/gitlab-runner-cache"
```

**Проверка:**

```bash
kubectl get ns gitlab-runner
# → Active

# Запуск тестовой задачи — создаётся Pod, выполняется, удаляется
kubectl get pods -n gitlab-runner -w
```

### Сценарий 4: Windows Runner (static, без автоскейлера)

> **Важно:** Fleeting и Docker Autoscaler не поддерживают Windows-инстансы. Для Windows задач используйте статические runner'ы, размещённые на Windows Server или в Windows-сегменте K8s кластера.

**Регистрация Windows Runner (shell executor):**

```powershell
# На Windows Server 2022
gitlab-runner register `
  --url "https://gitlab.corp.local" `
  --token "$RUNNER_REGISTRATION_TOKEN" `
  --executor "shell" `
  --shell "powershell" `
  --description "windows-powershell-runner" `
  --tag-list "windows,powershell,dotnet" `
  --run-untagged="false" `
  --locked="false"

# Установка как Windows Service
gitlab-runner install
gitlab-runner start
```

**Конфигурация `C:\GitLab-Runner\config.toml`:**

```toml
[[runners]]
  name = "windows-powershell-runner"
  url = "https://gitlab.corp.local"
  token = "<runner-token>"
  executor = "shell"
  shell = "pwsh"
  [runners.docker]
    image = "mcr.microsoft.com/dotnet/sdk:8.0"
```

**Проверка:**

```powershell
Get-Service gitlab-runner
# → Status: Running

gitlab-runner list
# → windows-powershell-runner online
```

### Сценарий 5: Docker-in-Docker (DinD) с эфемерными раннерами

Использование DinD service для сборки и публикации образов. Раннер остаётся чистым после каждой задачи.

```yaml
stages:
  - build
  - deploy

build_and_push:
  stage: build
  image: docker:27.0
  services:
    - docker:27.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2376
    DOCKER_TLS_CERTDIR: /certs
    IMAGE_TAG: $CI_COMMIT_SHORT_SHA
  before_script:
    - docker info
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$IMAGE_TAG .
    - docker push $CI_REGISTRY_IMAGE:$IMAGE_TAG
  after_script:
    - docker logout $CI_REGISTRY
  tags:
    - docker
    - ephemeral
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Примечание:** Для DinD в Kubernetes executor требуется `privileged = true` и монтирование `/var/run/docker.sock` или использование DinD service.

### Сценарий 6: Мониторинг пула эфемерных раннеров

Отслеживание состояния runner'ов через GitLab API и Prometheus.

**GitLab API (curl + jq):**

```yaml
stages:
  - monitor

check_runner_pool:
  stage: monitor
  image: curlimages/curl:8.8.0
  script:
    - |
      curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "https://gitlab.corp.local/api/v4/projects/$CI_PROJECT_ID/runners" | \
        jq '.[] | {id, status, online, active: .status == "online"}'
    - |
      curl --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
        "https://gitlab.corp.local/api/v4/projects/$CI_PROJECT_ID/runners/$RUNNER_ID" | \
        jq '{id, status, online, description}'
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      cron: "*/30 * * * *"
```

**Prometheus metrics (встроенный HTTP-сервер runner'а):**

```toml
# В config.toml
[[runners]]
  [runners.metrics]
    server_address = ":9252"
```

```yaml
# scrape-конфиг Prometheus
scrape_configs:
  - job_name: gitlab-runner
    static_configs:
      - targets: ['runner-1.corp.local:9252', 'runner-2.corp.local:9252']
```

```promql
# Активные задачи
sum(gitlab_runner_jobs{state="running"})

# Размер очереди
gitlab_runner_queue_size

# Падения инфраструктурой
rate(gitlab_runner_job_failures_total{reason="runner_system_failure"}[5m])

# Утилизация слотов
sum(gitlab_runner_jobs{state="running"}) / count(gitlab_runner_jobs) * 100
```

## Валидация и проверка

1. **Runner status:** `gitlab-runner list` — runner должен быть `online`
2. **Autoscaling:** Отправьте N параллельных задач (N > `capacity_per_instance`) и убедитесь, что новые VM/Pod'ы создаются
3. **Ephemeral cleanup:** После завершения задач проверьте, что инстансы удаляются:
   - Для libvirt: `virsh list --all`
   - Для K8s: `kubectl get pods -n gitlab-runner`
4. **Metrics:** `curl http://<runner-manager>:9252/metrics` — эндпоинт доступен и возвращает метрики
5. **Security:** Проверьте RBAC (K8s) или SSH-ключи (libvirt) — только минимально необходимые права

## Troubleshooting

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Fleeting plugin not found** | Плагин не установлен или не в PATH | Установите плагин в `/usr/local/bin` и проверьте `gitlab-runner fleeting list` |
| **Runner stuck in `offline`** | Неверный URL, токен или сеть | Проверьте `gitlab-runner verify` и DNS/маршрутизацию до GitLab API |
| **libvirt: connection refused** | `libvirtd` не запущен или нет прав | Проверьте `systemctl status libvirtd` и членство в группе `libvirt` |
| **K8s pod pending** | Нет ресурсов или нет scheduler | Проверьте `kubectl describe pod` и ResourceQuota |
| **High memory usage** | `memory_mib` слишком велик или `max_use_count` не ограничен | Уменьшите `memory_mib` или установите `max_use_count = 1` для строгой эфемерности |
| **DinD connection refused** | Docker daemon не запущен в VM/контейнере | Убедитесь, что `privileged = true` и Docker установлен в golden image |
| **Runner token expired** | Токен истёк | Пересоздайте токен в **Settings > CI/CD > Runners** |
| **Slow VM provisioning** | Недостаточно ресурсов на гипервизоре или сетевые задержки | Проверьте `virsh top`, `htop` на гипервизоре и время отклика SSH |

## Best Practices

**Безопасность:**
- Используйте SSH-ключи вместо паролей для подключения к VM (конфиг `connector_config.key_path`)
- Ограничьте `allowed_images` в `[runners.docker]` для предотвращения запуска неавторизованных образов
- Используйте отдельный ServiceAccount для runner'ов в Kubernetes с минимальными RBAC-правами
- Включите audit logging в GitLab для отслеживания создания/удаления runner'ов
- Никогда не используйте `privileged = true` без необходимости; для DinD — только на изолированных раннерах
- Шифруйте конфигурацию `/etc/gitlab-runner/config.toml` (например, через Ansible Vault или systemd-секреты)

**Производительность:**
- Используйте эфемерные раннеры для CI задач (чистая среда, нет дрейфа)
- Настройте `idle_count = 1-3` для продакшена в зависимости от скорости provisioning
- Установите `capacity_per_instance = 1` и `max_use_count = 1` для максимальной изоляции и безопасности
- Используйте внутренний registry mirror (Harbor, Nexus) для ускорения загрузки образов
- Настройте `preemptive_mode = true` для немедленного запуска задач при наличии idle инстансов
- Используйте `pull_policy = ["if-not-present"]` для внутренних образов и `["always"]` для публичных

**Надёжность:**
- Используйте Protected Tags для production раннеров
- Настройте retry в `.gitlab-ci.yml` (`retry: 2`) для transient failures
- Размещайте Runner Manager на отказоустойчивом хосте (не ephemeral VM)
- Мониторьте метрики `gitlab_runner_*` и настраивайте алерты на падение очереди или рост failures
- Используйте golden image с предустановленным Docker, git и CA-сертификатами для ускорения provisioning

## Очистка

```bash
# Остановка runner manager
sudo systemctl stop gitlab-runner
sudo systemctl disable gitlab-runner

# Удаление registration токена из GitLab (через UI или API)
curl --request DELETE \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "https://gitlab.corp.local/api/v4/projects/$CI_PROJECT_ID/runners/$RUNNER_ID"

# Очистка orphaned VM в libvirt
sudo virsh list --all --name | grep gitlab-runner | while read vm; do
  sudo virsh destroy "$vm"
  sudo virsh undefine "$vm" --remove-all-storage
done

# Очистка кеша Docker
docker system prune -a --volumes --force

# Очистка конфигурации
sudo rm -rf /etc/gitlab-runner
sudo rm -f /usr/local/bin/fleeting-plugin-libvirt
```

## Дополнительная информация

### Смотрите также

- **[Управление парком Runner'ов](../Advanced/runner_fleet_management.md)** — теория, типы раннеров, стратегии масштабирования, модели управления
- **[Windows Runner в Production](../Tutorials/windows_runner_production.md)** — production-grade конфигурация Windows Runner'ов
- **[Runner Registration](../Tutorials/runner_registration.md)** — пошаговая регистрация runner'ов
- **[GitLab Runner Documentation](https://docs.gitlab.com/runner/)** — официальная документация
- **[Fleeting Plugin Libvirt](https://gitlab.com/fleetingplugin/fleeting-plugin-libvirt)** — community plugin для libvirt/KVM
