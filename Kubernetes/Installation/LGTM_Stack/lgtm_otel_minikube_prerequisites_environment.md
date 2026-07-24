# Подготовка окружения для развертывания LGTM и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)** (текущий)
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

---

## Определения

**Docker** — платформа для разработки, доставки и запуска приложений в контейнерах. Используется как среда выполнения (runtime) для Minikube. Подробнее: **[Docker: Обзор](../../../Docker/docker_overview.md)**.

**Git** — распределенная система управления версиями. Необходима для клонирования демонстрационных репозиториев и конфигураций. Подробнее: **[Git: Основы](../../../Git/git_basics.md)**.

**Minikube** — инструмент, позволяющий запускать локальный кластер Kubernetes на персональном компьютере. Подробнее: **[Minikube: Концепции](../../Installation/minikube/minikube_concepts.md)**.

**kubectl** — утилита командной строки для управления кластерами Kubernetes. Подробнее: **[Kubernetes: Обзор](../../kubernetes_overview.md)**.

**Helm** — пакетный менеджер для Kubernetes, упрощающий развертывание и управление приложениями. Подробнее: **[Helm: Обзор](../../ToolsUtilities/Helm/helm_overview.md)**.

**kubeconfig** — файл конфигурации, содержащий параметры подключения к кластерам Kubernetes. Подробнее: **[Kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)**.

---

## Основные концепции

### Архитектура рабочего окружения

```text
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

Для стабильной работы стека LGTM (Loki, Grafana, Tempo, Mimir/Prometheus) и OpenTelemetry требуются значительные ресурсы.

| Компонент | Минимальные | Рекомендуемые |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4 ядра |
| **Память (RAM)** | 4 ГБ | 8 ГБ |
| **Дисковое пространство** | 20 ГБ | 40 ГБ |

**Рекомендуемые параметры запуска Minikube:** `--cpus 4 --memory 8192mb`.

### Используемые Helm-репозитории (состояние на 2026 г.)

| Репозиторий | URL | Назначение |
| :--- | :--- | :--- |
| **prometheus-community** | `https://prometheus-community.github.io/helm-charts` | kube-prometheus-stack |
| **grafana-community** | `https://grafana-community.github.io/helm-charts` | Loki, Tempo (OSS версии) |
| **grafana** | `https://grafana.github.io/helm-charts` | Grafana, Mimir |
| **jetstack** | `https://charts.jetstack.io` | cert-manager |
| **twuni** | `https://twuni.github.io/docker-registry.helm` | Docker Registry (локальный) |
| **open-telemetry** | `https://open-telemetry.github.io/opentelemetry-helm-charts` | OTel Operator |

---

## Практические сценарии

### Сценарий: Подготовка окружения для развертывания стека

**Цель:** Установка и настройка необходимых инструментов и кластера Minikube.

#### Шаг 1: Проверка установленного ПО

Убедитесь, что все необходимые утилиты установлены и доступны в PATH.

```bash
docker --version
minikube version
kubectl version --client
helm version
git --version
```

#### Шаг 2: Клонирование демонстрационных репозиториев

```bash
# Примеры использования OpenTelemetry
git clone https://github.com/open-telemetry/opentelemetry-java-examples.git

# Практические примеры по наблюдаемости
git clone https://github.com/memori-dev/observability-practice.git
```

#### Шаг 3: Настройка Helm-репозиториев

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add jetstack https://charts.jetstack.io
helm repo add twuni https://twuni.github.io/docker-registry.helm
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
```

#### Шаг 4: Запуск кластера Minikube

Для работы стека LGTM и Ingress-контроллера требуются специфические параметры.

```bash
minikube start \
  --cpus 4 \
  --memory 8192mb \
  --addons ingress \
  --insecure-registry "10.0.0.0/24" \
  --driver=docker
```

#### Шаг 5: Проверка готовности кластера

```bash
minikube status
kubectl get nodes
minikube addons list | grep enabled
```

---

## Дополнительная информация

### Типичные проблемы и их решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Ошибка при запуске Minikube** | Недостаточно свободной оперативной памяти или CPU | Закройте ресурсоемкие приложения или уменьшите параметры `--memory`/`--cpus` (не рекомендуется для LGTM) |
| **Docker daemon не найден** | Служба Docker не запущена | Запустите Docker Desktop или выполните `sudo systemctl start docker` |
| **Ошибка доступа к kubectl** | Неверные права на файл конфигурации | Выполните `chmod 600 ~/.kube/config` или проверьте контекст: `kubectl config current-context` |

### См. также

- **[Minikube: Практические сценарии](../minikube/minikube_practical_scenarios.md)**
- **[Helm: Обзор](../../ToolsUtilities/Helm/helm_overview.md)**
- **[OpenTelemetry: Обзор](../../../OpenTelemetry/opentelemetry_overview.md)**

---

**Навигация по руководству:**

- **[Развертывание вспомогательных компонентов →](./lgtm_otel_minikube_auxiliary_components.md)**
