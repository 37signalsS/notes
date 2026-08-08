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

**Minikube** — инструмент для запуска локального кластера Kubernetes на персональном компьютере. Подробнее: **[Minikube: Концепции](../../Installation/minikube/minikube_concepts.md)**.

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

Для стабильной работы стека LGTM (Loki, Grafana, Tempo, Mimir/Prometheus) и OpenTelemetry требуются значительные ресурсы. Недостаток памяти часто приводит к аварийному завершению подов (**OOMKill**).

| Компонент | Минимальные | Рекомендуемые |
| :--- | :--- | :--- |
| **CPU** | 4 ядра | 6 ядер |
| **Память (RAM)** | 8 ГБ | 12 ГБ |
| **Дисковое пространство** | 40 ГБ | 60 ГБ |

**Рекомендуемые параметры запуска Minikube:** `--cpus 4 --memory 12288mb` (12 ГБ). Если планируется использование Mimir вместо Prometheus, память следует увеличить до 16 ГБ.

### Используемые Helm-репозитории (состояние на 2026 г.)

С 2026 года многие чарты перешли на использование **OCI-репозиториев** для повышения безопасности и производительности.

| Репозиторий | URL / Идентификатор OCI | Назначение |
| :--- | :--- | :--- |
| **prometheus-community** | `https://prometheus-community.github.io/helm-charts` | kube-prometheus-stack |
| **grafana-community (OCI)** | `oci://ghcr.io/grafana-community/helm-charts` | Loki, Tempo (OSS версии) |
| **grafana** | `https://grafana.github.io/helm-charts` | Grafana, Mimir, Alloy |
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
# Классические репозитории
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add jetstack https://charts.jetstack.io
helm repo add twuni https://twuni.github.io/docker-registry.helm
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update

# Примечание: OCI-репозитории (loki, tempo) не требуют выполнения 'helm repo add'.
# Они используются напрямую в командах 'helm install' или 'helm upgrade'.
```

#### Шаг 4: Запуск кластера Minikube

Для работы стека LGTM, Ingress-контроллера и локального реестра требуются специфические параметры.

```bash
minikube start \
  --cpus 4 \
  --memory 12288mb \
  --disk-size 50g \
  --addons ingress,metrics-server \
  --insecure-registry "10.0.0.0/24" \
  --driver=docker
```

> **Важно:** Использование драйвера `docker` является рекомендуемым. При использовании других драйверов (например, `virtualbox` или `qemu`) может потребоваться дополнительная настройка сети для доступа к `insecure-registry`.

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
| **Ошибка при запуске Minikube** | Недостаточно оперативной памяти | Закройте ресурсоемкие приложения. Минимальный порог для LGTM — 8 ГБ. |
| **Docker daemon не найден** | Docker не запущен | Запустите Docker Desktop или `sudo systemctl start docker`. |
| **ImagePullBackOff (registry)** | Ошибка `insecure-registry` | Убедитесь, что параметр `--insecure-registry` указан верно при `minikube start`. |
| **kubectl: connection refused** | Кластер не запущен или упал | Выполните `minikube status`. Если упал из-за ресурсов — увеличьте лимиты. |

### См. также

- **[Minikube: Практические сценарии](../minikube/minikube_practical_scenarios.md)**
- **[Helm: Обзор](../../ToolsUtilities/Helm/helm_overview.md)**
- **[OpenTelemetry: Обзор](../../../OpenTelemetry/opentelemetry_overview.md)**
- **[Grafana Alloy: Обзор](../../../Grafana/grafana_alloy_overview.md)**

---

**Навигация по руководству:**

- **[Развертывание вспомогательных компонентов →](./lgtm_otel_minikube_auxiliary_components.md)**
