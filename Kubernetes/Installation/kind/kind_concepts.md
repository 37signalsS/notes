# kind — определения и концепции

## Определения

**kind (Kubernetes IN Docker)** — инструмент для запуска локальных кластеров Kubernetes, где каждый узел кластера разворачивается как Docker-контейнер. Предназначен для тестирования Kubernetes, локальной разработки и CI/CD (Continuous Integration / Continuous Deployment).

**kindest/node** — официальный Docker-образ узла kind. Представляет собой полноценную среду, содержащую `systemd`, `containerd`, `kubelet` и другие компоненты Kubernetes, необходимые для работы узла.

**Узел kind** — изолированный Docker-контейнер, выполняющий роль control-plane или worker-узла кластера Kubernetes.

**kindnet** — легковесный CNI (Container Network Interface) плагин по умолчанию, встроенный в kind. Обеспечивает базовую маршрутизацию Pod-to-Pod внутри кластера.

**local-path-provisioner** — встроенный StorageClass (`standard`) в kind, который динамически создает директории внутри файловой системы узла-контейнера для PersistentVolumeClaim (PVC). Используется по умолчанию для хранения данных.

---

## История и развитие kind

kind был создан как инструмент для тестирования самого Kubernetes, но быстро стал стандартом для локальной разработки и CI/CD.

| Версия kind | Год | Ключевые изменения |
| :--- | :--- | :--- |
| **v0.1.0** | 2019 | Первый публичный релиз. Поддержка однонодовых кластеров. |
| **v0.5.0** | 2019 | Добавлена поддержка multi-node кластеров и HA-конфигураций. |
| **v0.10.0** | 2021 | Улучшена производительность загрузки образов. Поддержка Podman. |
| **v0.20.0** | 2023 | Переход с HAProxy на Envoy для балансировщика в HA-кластерах. |
| **v0.25.0** | 2024 | Улучшенная поддержка rootless Docker и Podman. |
| **v0.32.0** | 2025 | Актуальная стабильная версия. Полная поддержка Kubernetes 1.37. |

**Текущий статус (август 2026):**
- kind активно поддерживается SIG-группой Kubernetes (Special Interest Group).
- Рекомендуемая версия: **v0.32.0** или выше.
- Поддержка N-2 версий Kubernetes (от 1.34 до 1.37).

---

## Основные концепции

### Архитектура kind и внутреннее устройство узла

Вопреки популярному заблуждению, kind не использует Docker-in-Docker в чистом виде для запуска пользовательских контейнеров (Pods). С версии Kubernetes 1.24 (после удаления DockerShim) kind использует `containerd` в качестве среды выполнения внутри узлов.

Архитектура узла (контейнера `kindest/node`):
1.  **Init-система:** Внутри Docker-контейнера узла запускается `systemd` как процесс с PID 1.
2.  **Container Runtime:** `systemd` управляет демоном `containerd`, который отвечает за запуск пользовательских подов.
3.  **Kubelet:** Управляется через `systemd` и взаимодействует с `containerd` через протокол CRI (Container Runtime Interface).
4.  **Изоляция сетей:** Каждый кластер создает собственную bridge-сеть на уровне Docker-хоста (обычно с именем `kind`). Взаимодействие между узлами происходит внутри этой сети.
5.  **Хранилище (Storage):** Используется встроенный `local-path-provisioner` (StorageClass `standard`), который динамически создает директории внутри файловой системы узла-контейнера для PVC.

| Компонент | Описание |
| :--- | :--- |
| **Узел как контейнер** | Каждая нода — Docker-контейнер с полным стеком Kubernetes. |
| **Среда выполнения** | Хост использует Docker/Podman, внутри узла работает `containerd`. |
| **Изоляция** | Использование выделенной Docker-сети для каждого кластера. |

### Балансировка нагрузки в HA-кластерах

При создании кластеров с несколькими control-plane узлами (High Availability), kind автоматически развертывает дополнительный контейнер-балансировщик.
-   **Envoy:** В актуальных версиях kind (начиная с v0.32.0+) в качестве балансировщика используется Envoy (ранее использовался HAProxy).
-   **Назначение:** Балансировщик принимает запросы от `kubectl` и распределяет их между API-серверами всех control-plane узлов, обеспечивая единую точку входа (Endpoint).

### Сетевое взаимодействие и доступ к сервисам

-   **Port Mapping (Проброс портов):** Поскольку узлы находятся в изолированной Docker-сети, прямой доступ к портам NodePort или Ingress-контроллеру с хоста невозможен без предварительной настройки `extraPortMappings` в YAML-конфигурации.
-   **Тип LoadBalancer:** В локальной среде Service типа `LoadBalancer` остается в состоянии `Pending`. Для тестирования этого функционала необходимо использовать **MetalLB** или **cloud-provider-kind**.
-   **DNS:** Используется CoreDNS внутри кластера; узлы наследуют настройки DNS от Docker-демона хоста.

### Загрузка образов (Image Sideloading)

Концепция `kind load docker-image` позволяет избежать необходимости пушить образы в реестр перед использованием в кластере.
-   **Механизм:** Образ копируется напрямую из Docker-хранилища хоста в Container Runtime (`containerd`) каждого узла.
-   **Преимущества:** Ускорение цикла разработки и возможность работы в оффлайн-режиме.

### Поддержка альтернативных Provider (Podman, Rootless)

kind поддерживает работу не только поверх классического Docker-демона:
-   **Rootless Docker:** Запуск узлов в пространстве обычного пользователя для повышения безопасности.
-   **Podman:** Использование Podman вместо Docker (включается через `KIND_EXPERIMENTAL_PROVIDER=podman`). Позволяет запускать кластеры в daemonless-окружениях.

### Изоляция и безопасность

kind обеспечивает изоляцию кластеров на нескольких уровнях:

| Уровень | Механизм изоляции |
| :--- | :--- |
| **Сеть** | Каждый кластер получает уникальную bridge-сеть Docker. Узлы разных кластеров не видят друг друга. |
| **Файловая система** | Узлы работают в изолированных контейнерах с собственным rootfs. Данные не пересекаются между узлами. |
| **Процессы** | Каждый узел — отдельный контейнер с PID-пространством, изолированным от хоста и других узлов. |
| **Ресурсы** | CPU, RAM и I/O ограничены параметрами контейнера (настраиваются через Docker/Podman). |

**Особенности безопасности:**
-   Узлы kind запускаются от имени текущего пользователя (без root-привилегий).
-   В rootless-режиме Docker/Podman дополнительная изоляция обеспечивается user namespaces.
-   kind не требует включения privileged-режима для узлов (в отличие от некоторых других решений).
-   Рекомендуется использовать rootless-режим для разработки, чтобы минимизировать риски.

**Ограничения безопасности:**
-   kind предназначен только для тестирования и разработки, не для production-нагрузок.
-   Узлы не имеют изоляции на уровне VM (в отличие от minikube). Все узлы одного кластера разделяют ресурсы хоста.
-   При монтировании томов через `extraMounts` необходимо соблюдать осторожность с путями (особенно `/var/run/docker.sock`).

### Преимущества и ограничения

| Преимущества | Ограничения |
| :--- | :--- |
| **Скорость:** Быстрое создание кластеров (от десятков секунд). | **Не для Production:** Только для тестирования и разработки. |
| **Топология:** Поддержка сложных multi-node и HA кластеров. | **Производительность I/O:** Ограничения из-за вложенности файловых систем. |
| **CI/CD:** Идеален для интеграционных тестов (GitHub Actions, GitLab CI). | **Зависимости:** Требует установленного Docker или Podman. |
| **Декларативность:** Конфигурация через YAML-файлы. | **Сеть:** Доступ извне требует ручного проброса портов. |

### Производительность и ограничения

kind работает на базе контейнеров, что накладывает специфические ограничения по сравнению с bare-metal или VM-кластерами:

| Параметр | Ограничение | Причина | Рекомендация |
| :--- | :--- | :--- | :--- |
| **I/O производительность** | Замедление дисковых операций в 2-5 раз | Вложенность файловых систем (overlayfs) и дополнительные уровни абстракции. | Используйте `emptyDir` для временных данных; избегайте частых записей на диск. |
| **CPU** | Ограничение вычислительных ресурсов | Узлы разделяют CPU хоста. Контейнеры не имеют приоритета над процессами хоста. | Устанавливайте `resources.requests` и `resources.limits` для подов. |
| **RAM** | Ограничение оперативной памяти | Физическая память разделяется между всеми узлами и процессами хоста. | Контролируйте потребление через `resources.limits`; используйте swap при необходимости. |
| **Сеть** | Задержка (latency) выше, чем в bare-metal | Дополнительные уровни NAT и bridge-сети Docker. | Для сетевых тестов учитывайте overhead; не используйте kind для бенчмарков сети. |
| **Масштаб** | Максимум 100 узлов (практический лимит) | Ограничения ресурсов хоста и производительности Docker. | Для крупных нагрузок используйте kubeadm на VM или bare-metal. |

**Сравнение производительности:**

| Сценарий | kind | minikube (VM) | kubeadm (bare-metal) |
| :--- | :--- | :--- | :--- |
| Время запуска кластера | 30-60 секунд | 2-5 минут | 10-30 минут |
| IOPS (random read/write) | 50-70% от хоста | 80-90% от хоста | 100% от хоста |
| Сетевая задержка (Pod-to-Pod) | 0.1-0.5 мс | 0.05-0.2 мс | 0.01-0.05 мс |
| Потребление RAM на узел | 500 MB - 1 GB | 1-2 GB | 2-4 GB |

### Сравнение с локальными аналогами

| Инструмент | Назначение | Отличие от kind |
| :--- | :--- | :--- |
| **[minikube](../minikube/minikube_concepts.md)** | Локальная разработка | Запускает VM (по умолчанию), имеет множество аддонов, ориентирован на однонодовые кластеры. |
| **k3d** | Разработка / IoT | Запускает k3s (облегченный дистрибутив) в контейнерах. Меньше ресурсов, но менее "ванильный" K8s. |
| **[talosctl](../local_cluster_with_talosctl.md)** | Локальная разработка | Использует Talos Linux. Безопаснее, максимально приближен к современным production-практикам. |

### Мониторинг и метрики

kind не предоставляет встроенные средства мониторинга, но поддерживает стандартные инструменты Kubernetes:

| Инструмент | Назначение | Установка в kind |
| :--- | :--- | :--- |
| **metrics-server** | Сбор метрик CPU/RAM для подов и узлов (HPA, `kubectl top`) | `kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml` |
| **Prometheus** | Сбор и хранение метрик, алертинг | Через Helm-чарт `kube-prometheus-stack` или `prometheus-community` |
| **Grafana** | Визуализация метрик | Входит в состав `kube-prometheus-stack` |
| **Loki** | Сбор логов | Через Helm-чарт `grafana/loki-stack` |

**Экспорт метрик из узла:**

```bash
# Метрики kubelet (port 10250)
kubectl get --raw /metrics | head -20

# Метрики API-сервера
kubectl get --raw /metrics | grep apiserver_request
```

**Сбор логов кластера:**

```bash
# Экспорт логов всех узлов и компонентов
kind export logs ./kind-logs --name my-cluster

# Структура экспортированных логов:
# ./kind-logs/
# ├── kind-control-plane/
# │   ├── containers/
# │   ├── pods/
# │   └── systemd/
# └── kind-worker/
```

**Пример метрик Prometheus для kind:**

```yaml
# Минимальный ServiceMonitor для сбора метрик kubelet
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: kubelet-monitor
  namespace: monitoring
spec:
  selector:
    matchLabels:
      k8s-app: kubelet
  endpoints:
  - port: http-metrics
    path: /metrics
    interval: 30s
```

---

## Практические сценарии

### Поддерживаемые версии Kubernetes

kind следует политике поддержки N-2. Состояние на август 2026 года:

| Версия Kubernetes | Статус | EOL (End of Life) |
| :--- | :--- | :--- |
| **1.37** | **Новый релиз** (Август 2026) | Октябрь 2027 |
| **1.36** | Активная поддержка | Июнь 2027 |
| **1.35** | Активная поддержка | Февраль 2027 |
| **1.34** | Режим обслуживания (Maintenance) | Октябрь 2026 |
| **1.33** | **EOL** (Устарела) | Июнь 2026 |

**Использование конкретной версии:**

```yaml
# Фиксация версии Kubernetes 1.37
nodes:
- role: control-plane
  image: kindest/node:v1.37.0
```

### Ключевые переменные окружения

| Переменная | Описание |
| :--- | :--- |
| `KIND_EXPERIMENTAL_PROVIDER` | Переопределение среды выполнения (например, `podman`). |
| `KIND_EXPERIMENTAL_DOCKER_NETWORK` | Пользовательское имя Docker-сети для кластера. |
| `KIND_NODE_IMAGE` | Образ узла по умолчанию для всех кластеров. |

### Решение проблем (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Узел не переходит в Ready** | kubelet не может подключиться к API-серверу или containerd не запущен. | Проверьте логи kubelet: `docker exec <node> journalctl -u kubelet -f`. Убедитесь, что containerd работает: `docker exec <node> crictl ps`. |
| **Pod в Pending** | Недостаточно ресурсов (CPU/RAM) на узле или нет подходящего StorageClass. | Проверьте `kubectl describe pod <pod>` и `kubectl top nodes`. Убедитесь, что StorageClass существует: `kubectl get sc`. |
| **Сетевые проблемы (Pod-to-Pod)** | CNI-плагин (kindnet) не работает или конфликтует с другими плагинами. | Проверьте логи kindnet: `docker exec <node> cat /var/log/kindnetd.log`. Убедитесь, что Pod CIDR совпадает с конфигурацией кластера. |
| **Ошибка `bind: address already in use`** | Порт на хосте занят другим процессом. | Используйте другой порт в `extraPortMappings` или остановите конфликтующий сервис: `lsof -i :<port>`. |
| **Узел не запускается (timeout)** | Недостаточно ресурсов хоста (RAM/CPU) или утилизация Docker Desktop превысила лимиты. | Увеличьте выделенные ресурсы Docker Desktop (Settings → Resources). Проверьте `docker stats` для мониторинга потребления. |
| **Pod с CrashLoopBackOff** | Приложение падает при запуске (ошибка конфигурации, недоступные зависимости). | Проверьте логи контейнера: `kubectl logs <pod> --previous`. Убедитесь, что образ доступен: `crictl images` внутри узла. |
| **Нет доступа к NodePort/Ingress** | Порты не проброшены на хост (не настроены `extraPortMappings`). | Добавьте `extraPortMappings` в конфигурацию kind и пересоздайте кластер. |
| **`kubectl` не может подключиться** | kubeconfig не экспортирован или контекст неправильный. | Выполните `kind export kubeconfig --name <cluster>` и проверьте контекст: `kubectl config current-context`. |

**Диагностические команды:**

```bash
# Проверка состояния узлов
kubectl get nodes -o wide

# Проверка системных подов
kubectl get pods -n kube-system

# Описание узла (для детальной диагностики)
kubectl describe node <node-name>

# Проверка событий кластера
kubectl get events --sort-by='.lastTimestamp'

# Подключение к узлу для низкоуровневой диагностики
docker exec -it <node-name> bash

# Проверка containerd внутри узла
crictl ps
crictl pods
crictl images
```

### Лучшие практики

| Категория | Рекомендация |
| :--- | :--- |
| **Именование кластеров** | Используйте осмысленные имена (`dev`, `staging`, `test-app`) вместо дефолтного `kind`. Это упрощает управление несколькими кластерами. |
| **Версии Kubernetes** | Фиксируйте версию Kubernetes через `image: kindest/node:v1.XX.X` в конфигурации. Избегайте использования latest-образов в CI/CD. |
| **Ресурсы** | Устанавливайте `resources.requests` и `resources.limits` для всех подов. Это предотвращает исчерпание ресурсов узла. |
| **Конфигурация** | Храните конфигурацию kind в YAML-файлах (не в CLI-аргументах). Это обеспечивает воспроизводимость и версионирование. |
| **Проброс портов** | Настройте `extraPortMappings` только для необходимых портов. Избегайте проброса всех портов (30000-32767) для безопасности. |
| **Загрузка образов** | Используйте `kind load docker-image` вместо пуша в реестр для локальной разработки. Для CI/CD используйте локальный реестр kind. |
| **Хранилище** | Для данных, требующих персистентности, используйте `PersistentVolumeClaim` с StorageClass `standard` (по умолчанию). |
| **CI/CD** | Для интеграционных тестов создавайте изолированные кластеры в каждом пайплайне и удаляйте их после завершения. |
| **Безопасность** | Используйте rootless Docker/Podman для разработки. Избегайте монтирования Docker socket в узлы. |
| **Мониторинг** | Устанавливайте metrics-server для HPA и `kubectl top`. Добавляйте Prometheus для длительного хранения метрик. |
| **Очистка** | Регулярно удаляйте неиспользуемые кластеры: `kind delete clusters $(kind get clusters)`. |

**Примеры осмысленных имен кластеров:**

```bash
# Для разных проектов
kind create cluster --name myapp-dev
kind create cluster --name myapp-staging

# Для разных команд/окружений
kind create cluster --name team-backend
kind create cluster --name team-frontend

# Для тестирования разных версий K8s
kind create cluster --name k8s-136 --image kindest/node:v1.36.0
kind create cluster --name k8s-137 --image kindest/node:v1.37.0
```

### Интеграция с инструментами

kind широко используется в связке с другими инструментами DevOps-экосистемы:

| Инструмент | Интеграция с kind | Назначение |
| :--- | :--- | :--- |
| **Helm** | Установка чартов в кластер kind через `helm install` | Пакетное управление приложениями и инфраструктурой |
| **Kustomize** | Применение манифестов через `kubectl apply -k` | Трансформация и патчинг YAML-манифестов |
| **Skaffold** | Автоматическая сборка, загрузка и деплой в kind | Локальная разработка с hot-reload |
| **Tilt** | Интеграция с kind для быстрого цикла разработки | Визуализация логов и статуса деплоя |
| **GitHub Actions** | Официальный экшен `helm/kind-action@v1` | CI/CD пайплайны с интеграционными тестами |
| **GitLab CI** | Запуск kind как сервис в CI-окружении | Тестирование в изолированных кластерах |
| **Telepresence** | Проксирование сервисов из kind на локальную машину | Локальная разработка с доступом к сервисам кластера |

**Пример интеграции с Helm:**

```bash
# 1. Создание кластера
kind create cluster --name dev

# 2. Установка Prometheus через Helm
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace

# 3. Проверка установленных релизов
helm list --all-namespaces
```

**Пример интеграции с Skaffold:**

```yaml
# skaffold.yaml
apiVersion: skaffold/v4beta6
kind: Config
metadata:
  name: myapp
build:
  artifacts:
  - image: myapp
    context: .
    docker:
      dockerfile: Dockerfile
deploy:
  kubectl:
    manifests:
    - k8s/*.yaml
portForward:
- resourceType: deployment
  resourceName: myapp
  port: 8080
  localPort: 8080
```

**Пример GitHub Actions workflow:**

```yaml
name: CI with kind
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Create kind cluster
      uses: helm/kind-action@v1
      with:
        cluster_name: ci-cluster
        version: v0.32.0
        node_image: kindest/node:v1.37.0
    - name: Run tests
      run: |
        kubectl get nodes
        helm install myapp ./chart --wait
        kubectl test
```

### Масштабирование и ограничения ресурсов

kind предназначен для локальной разработки и тестирования, но имеет ограничения по масштабу:

| Параметр | Рекомендуемый лимит | Абсолютный максимум | Примечание |
| :--- | :--- | :--- | :--- |
| **Узлы (nodes)** | 5-10 | 50-100 | Зависит от ресурсов хоста. Каждый узел потребляет 500 MB - 1 GB RAM. |
| **Поды на узел** | 30-50 | 110 | Лимит Kubernetes по умолчанию (maxPods). Может быть увеличен через kubeadm. |
| **Всего подов** | 150-500 | 1000+ | Зависит от кластера и ресурсов хоста. |
| **Сервисы** | 20-50 | 100+ | Каждый сервис создает правила iptables/IPVS на узлах. |
| **ReplicaSet/Deployment** | 10-20 | 50+ | Большое количество контроллеров нагружает API-сервер. |

**Рекомендации по ресурсам хоста:**

| Конфигурация kind | Минимум RAM | Рекомендуемый RAM | CPU |
| :--- | :--- | :--- | :--- |
| 1 control-plane + 1 worker | 4 GB | 8 GB | 2+ cores |
| 3 control-plane + 3 workers (HA) | 8 GB | 16 GB | 4+ cores |
| 5+ узлов (сложные тесты) | 16 GB | 32 GB | 8+ cores |

**Мониторинг потребления ресурсов:**

```bash
# Потребление ресурсов Docker-контейнерами (узлами kind)
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

# Потребление ресурсов подами внутри кластера
kubectl top nodes
kubectl top pods --all-namespaces --sort-by=memory
```

**Оптимизация для CI/CD:**

```bash
# Минимальный кластер для быстрых тестов
kind create cluster --name ci \
  --image kindest/node:v1.37.0 \
  --config - <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        system-reserved: "cpu=500m,memory=512Mi"
        eviction-hard: "memory.available<256Mi,nodefs.available<10%"
EOF
```

### Очистка и удаление ресурсов

Регулярная очистка неиспользуемых кластеров и образов важна для экономии дискового пространства и ресурсов:

| Действие | Команда | Описание |
| :--- | :--- | :--- |
| **Удаление конкретного кластера** | `kind delete cluster --name <name>` | Удаляет контейнеры, сети и тома, связанные с кластером. |
| **Удаление всех кластеров** | `kind delete clusters --all` | Удаляет все существующие кластеры kind. |
| **Очистка неиспользуемых образов** | `docker image prune -f` | Удаляет "висячие" (dangling) образы Docker. |
| **Полная очистка Docker** | `docker system prune -a --volumes` | Удаляет все неиспользуемые образы, контейнеры, сети и тома. **Внимание:** удалит все кэшированные образы kind. |
| **Проверка размера Docker** | `docker system df` | Показывает потребление дискового пространства Docker. |

**Скрипт автоматической очистки (для CI/CD):**

```bash
#!/bin/bash
# cleanup-kind.sh — удаление всех кластеров kind и неиспользуемых ресурсов

echo "Удаление всех кластеров kind..."
kind delete clusters $(kind get clusters 2>/dev/null) 2>/dev/null || true

echo "Очистка неиспользуемых Docker-ресурсов..."
docker container prune -f
docker network prune -f
docker volume prune -f
docker image prune -f

echo "Проверка дискового пространства..."
docker system df

echo "Очистка завершена."
```

**Экспорт данных перед удалением:**

```bash
# Экспорт kubeconfig
kind export kubeconfig --name my-cluster --kubeconfig ./kubeconfig-backup.yaml

# Экспорт логов для анализа
kind export logs ./kind-logs-backup --name my-cluster

# Экспорт всех ресурсов кластера (для отладки)
kubectl get all --all-namespaces -o yaml > cluster-resources-backup.yaml
```

**Удаление зависимых ресурсов:**

```bash
# Удаление PersistentVolumeClaim и связанных данных
kubectl delete pvc --all --all-namespaces

# Удаление всех подов (включая системные)
kubectl delete pods --all --all-namespaces

# Принудительное удаление кластера при зависании
docker rm -f $(docker ps -q --filter "label=io.x-k8s.kind.cluster" --filter "name=kind") 2>/dev/null || true
kind delete cluster --name my-cluster
```

---

## Дополнительная информация

### Требования к системе

| Компонент | Версия / Требование | Примечание |
| :--- | :--- | :--- |
| **Docker** | 18.09+ | Рекомендуемая среда. Требуется минимум 4-8 GB RAM. |
| **Podman** | 3.0+ | Альтернатива Docker для Linux/macOS. |
| **kubectl** | Совместимая | Версия должна быть +/- 1 минорная версия от K8s в кластере. |
| **ОС** | Linux / macOS / Windows | Windows поддерживается через WSL2 или Docker Desktop. |

### Ссылки

- [Официальная документация kind](https://kind.sigs.k8s.io/)
- [GitHub репозиторий kubernetes-sigs/kind](https://github.com/kubernetes-sigs/kind)
- [kind — практические сценарии](./kind_practical_scenarios.md) — установка, создание кластеров, примеры команд
- [kind — конфигурация](./kind_configuration.md) — подробное описание YAML и проброса портов
- [MetalLB в kind](https://kind.sigs.k8s.io/docs/user/loadbalancer/) — настройка типа LoadBalancer локально
- [Local Path Provisioner](../../Storage/local-path-provisioner.md) — локальное хранилище для PVC в kind
- [metrics-server](https://github.com/kubernetes-sigs/metrics-server) — сбор метрик CPU/RAM для HPA и `kubectl top`
