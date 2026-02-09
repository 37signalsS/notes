## Практические сценарии

### Сценарий: Развертывание стека LGTM и OpenTelemetry на Minikube

#### 1. Предварительные требования

- **[Docker](../../Docker/docker_overview.md)**: Для запуска Minikube.
- **[Git](../../Git/git_basics.md)**: Для клонирования репозиториев.
- **[Minikube](https://minikube.sigs.k8s.io/docs/)**: Локальный кластер [Kubernetes](../../Kubernetes/kubernetes_overview.md).
- **[kubectl](../../Kubernetes/kubernetes_overview.md)**: Утилита командной строки для управления кластерами Kubernetes.
- **[Helm](../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)**: Менеджер пакетов для Kubernetes.

#### 2. Подготовка окружения

##### 2.1. Клонирование репозиториев

```bash
git clone https://github.com/open-telemetry/opentelemetry-java-examples.git
git clone https://github.com/memori-dev/observability-practice.git
```

##### 2.2. Добавление Helm репозиториев

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add jetstack https://charts.jetstack.io
helm repo add twuni https://helm.twun.io
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo update
```

##### 2.3. Запуск Minikube

```bash
minikube start --cpus 4 --memory 8192mb --addons ingress --insecure-registry "10.0.0.0/24" --driver=docker
```

* `--cpus 4 --memory 8192mb`: Рекомендуемые ресурсы для стабильной работы стека.
- `--addons ingress`: Включает Ingress-контроллер.
- `--insecure-registry "10.0.0.0/24"`: Позволяет использовать локальный Docker Registry без HTTPS.
- `--driver=docker`: Использует Docker в качестве драйвера.