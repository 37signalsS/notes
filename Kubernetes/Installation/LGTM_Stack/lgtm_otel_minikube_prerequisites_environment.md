# Подготовка окружения для развёртывания LGTM и OpenTelemetry на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)** ← текущий
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)**
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

## Определения

**Docker** — платформа для контейнеризации. Подробнее: **[Docker overview](../../../Docker/docker_overview.md)**.

**Git** — система управления версиями. Подробнее: **[Git basics](../../../Git/git_basics.md)**.

**Minikube** — инструмент запуска локального Kubernetes. Подробнее: **[Minikube concepts](../../Installation/minikube/minikube_concepts.md)**.

**kubectl** — утилита управления кластером. Подробнее: **[Kubernetes overview](../../kubernetes_overview.md)**.

**Helm** — пакетный менеджер Kubernetes. Подробнее: **[Helm overview](../../ToolsUtilities/Helm/helm_overview.md)**.

**kubeconfig** — файл параметров подключения. Подробнее: **[Kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)**.

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

**Параметры Minikube для LGTM:** `--cpus 4 --memory 8192mb`

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

**Цель:** Настройка инструментов для работы со стеком LGTM и OpenTelemetry.

#### Шаг 1: Проверка инструментов

```bash
docker --version
minikube version
kubectl version --client
helm version
git --version
```

#### Шаг 2: Клонирование репозиториев

```bash
# Примеры OpenTelemetry
git clone https://github.com/open-telemetry/opentelemetry-java-examples.git

# Практика наблюдаемости
git clone https://github.com/memori-dev/observability-practice.git
```

#### Шаг 3: Добавление репозиториев Helm

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add jetstack https://charts.jetstack.io
helm repo add twuni https://helm.twun.io
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
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

#### Шаг 5: Верификация

```bash
minikube status
kubectl get nodes
minikube addons list
```

---

## Дополнительная информация

### Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Зависание старта** | Нехватка ресурсов | Увеличить лимиты RAM/CPU |
| **Docker не запущен** | Служба остановлена | `sudo systemctl start docker` |
| **Ошибка kubectl** | Права на конфигурацию | `chmod 600 ~/.kube/config` |

### См. также

- **[Minikube: Практические сценарии](../minikube/minikube_practical_scenarios.md)**
- **[Helm: Обзор](../../ToolsUtilities/Helm/helm_overview.md)**
- **[OpenTelemetry: Обзор](../../../OpenTelemetry/opentelemetry_overview.md)**

---

**Навигация по руководству:**

- **[Развертывание вспомогательных компонентов →](./lgtm_otel_minikube_auxiliary_components.md)**
