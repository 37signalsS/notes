# Подготовка окружения для развёртывания LGTM и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)** ← текущий
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

## Определения

**Docker** — платформа для разработки, доставки и запуска приложений в контейнерах. Используется Minikube в качестве container runtime. Полная документация: **[Docker overview](../../../Docker/docker_overview.md)**.

**Git** — распределённая система управления версиями для клонирования репозиториев с примерами кода. Полная документация: **[Git basics](../../../Git/git_basics.md)**.

**Minikube** — инструмент для запуска локального однонодового кластера Kubernetes. Предназначен для разработки, тестирования и обучения. Полная документация: **[Minikube concepts](../../Installation/minikube/minikube_concepts.md)**.

**kubectl** — CLI-утилита для управления кластером Kubernetes. Используется для выполнения команд (`kubectl get`, `kubectl apply`, `kubectl describe`). Полная документация: **[Kubernetes overview](../../kubernetes_overview.md)**.

**Helm** — пакетный менеджер для Kubernetes для установки чартов (Prometheus, Loki, Tempo, OTel). Полная документация: **[Helm overview](../../ToolsUtilities/Helm/helm_overview.md)**.

**kubeconfig** — YAML-файл (`~/.kube/config`), содержащий информацию о кластерах, пользователях и контекстах для подключения к Kubernetes. Minikube автоматически добавляет свой контекст при создании кластера.

---

## Основные концепции

### Архитектура окружения

```
┌─────────────────────────────────────────────────────────────┐
│                    Рабочая станция                          │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │   Docker    │  │    Git      │  │      Minikube       │ │
│  │  (runtime)  │  │  (clone)    │  │  (Kubernetes cluster)│ │
│  └─────────────┘  └─────────────┘  └──────────┬──────────┘ │
│                                                │            │
│  ┌─────────────┐  ┌─────────────┐             │            │
│  │    kubectl  │  │    Helm     │◀────────────┘            │
│  │  (manage)   │  │  (install)  │                          │
│  └─────────────┘  └─────────────┘                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Требования к ресурсам

| Компонент | Минимум | Рекомендовано |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4 ядра |
| **Память** | 4 ГБ | 8 ГБ |
| **Диск** | 20 ГБ | 40 ГБ |

**Minikube для стека LGTM:** `--cpus 4 --memory 8192mb`

### Необходимые Helm-репозитории

| Репозиторий | URL | Назначение |
| :--- | :--- | :--- |
| **prometheus-community** | `https://prometheus-community.github.io/helm-charts` | kube-prometheus-stack |
| **grafana** | `https://grafana.github.io/helm-charts` | Loki, Tempo, Mimir |
| **jetstack** | `https://charts.jetstack.io` | cert-manager |
| **twuni** | `https://helm.twun.io` | Docker Registry |
| **open-telemetry** | `https://open-telemetry.github.io/opentelemetry-helm-charts` | OTel Operator |

---

## Практические сценарии

### Сценарий: Подготовка окружения для развёртывания стека

**Цель:** Установить и настроить все необходимые инструменты для развёртывания стека наблюдаемости LGTM + OpenTelemetry.

#### Шаг 1: Проверка установленных инструментов

```bash
# Проверка Docker
docker --version
docker system info

# Проверка Minikube
minikube version

# Проверка kubectl (или использовать minikube kubectl)
kubectl version --client

# Проверка Helm
helm version

# Проверка Git
git --version
```

**Ожидаемый результат:** Все команды возвращают версии установленных инструментов.

#### Шаг 2: Клонирование репозиториев с примерами

```bash
# Репозиторий с примерами OpenTelemetry
git clone https://github.com/open-telemetry/opentelemetry-java-examples.git

# Репозиторий с практикой наблюдаемости
git clone https://github.com/memori-dev/observability-practice.git
```

#### Шаг 3: Добавление Helm-репозиториев

```bash
# Добавление репозиториев
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add jetstack https://charts.jetstack.io
helm repo add twuni https://helm.twun.io
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts

# Обновление кэша репозиториев
helm repo update
```

**Проверка:**

```bash
helm repo list
```

#### Шаг 4: Запуск Minikube

```bash
minikube start \
  --cpus 4 \
  --memory 8192mb \
  --addons ingress \
  --insecure-registry "10.0.0.0/24" \
  --driver=docker
```

**Параметры:**

- `--cpus 4 --memory 8192mb` — рекомендуемые ресурсы для стабильной работы стека
- `--addons ingress` — включает Ingress-контроллер (nginx) для внешнего доступа
- `--insecure-registry "10.0.0.0/24"` — позволяет использовать локальный Docker Registry без HTTPS
- `--driver=docker` — использует Docker в качестве драйвера виртуализации

#### Шаг 5: Верификация кластера

```bash
# Проверка статуса Minikube
minikube status

# Проверка узлов
kubectl get nodes

# Проверка системных Pod
kubectl get pods -n kube-system

# Проверка аддонов
minikube addons list
```

**Ожидаемый результат:**

```
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Updated

NAME       STATUS   ROLES           AGE   VERSION
minikube   Ready    control-plane   5m    v1.28.3
```

---

## Дополнительная информация

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **minikube start зависает** | Недостаточно ресурсов | Закрыть лишние приложения, увеличить лимиты VM |
| **Docker daemon не запущен** | Служба остановлена | `sudo systemctl start docker`, `sudo systemctl enable docker` |
| **kubectl permission denied** | Нет прав на `~/.kube/config` | `chmod 600 ~/.kube/config`, проверить владельца |
| **Helm repo update fails** | Проблемы с сетью | Проверить прокси, DNS, доступ к GitHub |
| **Ingress addon не включается** | Конфликт портов | `minikube addons disable ingress`, затем `enable` |

### Диагностика

```bash
# Логи Minikube
minikube logs

# Проверка Docker
docker ps
docker system df

# Проверка контекста kubectl
kubectl config current-context
kubectl config get-contexts

# Проверка сети кластера
minikube ip
kubectl get svc -A
```

### Альтернативные драйверы Minikube

| Драйвер | Требования | Преимущества |
| :--- | :--- | :--- |
| **docker** | Docker Desktop | Быстрый старт, низкие накладные расходы |
| **kvm2** | KVM, libvirt | Нативная виртуализация Linux |
| **virtualbox** | VirtualBox | Кроссплатформенность |
| **hyperkit** | HyperKit (macOS) | Нативный для macOS |
| **none** | Bare metal | Прямая установка на хост (не рекомендуется) |

### Ссылки на SSoT

- **[Docker overview](../../../Docker/docker_overview.md)** — основы Docker
- **[Git basics](../../../Git/git_basics.md)** — работа с Git
- **[Minikube concepts](../../Installation/minikube/minikube_concepts.md)** — архитектура и возможности Minikube
- **[Kubernetes overview](../../kubernetes_overview.md)** — основы Kubernetes
- **[Helm overview](../../ToolsUtilities/Helm/helm_overview.md)** — управление пакетами Helm

### Ресурсы

- **[Minikube Documentation](https://minikube.sigs.k8s.io/docs/)**
- **[Helm Documentation](https://helm.sh/docs/)**
- **[Kubernetes Documentation](https://kubernetes.io/docs/)**

---

**Навигация по руководству:**

- **[Развертывание вспомогательных компонентов →](./lgtm_otel_minikube_auxiliary_components.md)**
