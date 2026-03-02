# Установка Rancher Server

## Определения

**Rancher Server** — центральный компонент платформы Rancher, который управляет кластерами, предоставляет веб-интерфейс (UI) и API для взаимодействия.

## Базовые концепции

### Методы установки

1.  **Установка Rancher Server в существующий кластер Kubernetes (Helm)** — наиболее рекомендуемый и отказоустойчивый способ.
2.  **Установка в Docker** — для тестирования/ознакомления.

### Предварительные требования для установки в Kubernetes

Для стабильной работы Rancher Server в кластере Kubernetes необходимо наличие:

*   **Ingress Controller**: Для маршрутизации внешнего трафика к Rancher UI и API (например, Nginx Ingress Controller).
*   **Cert Manager**: Для автоматического управления TLS-сертификатами.
*   **Load Balancer (Балансировщик нагрузки)**: Для обеспечения внешнего доступа к Ingress Controller. На Bare Metal кластерах часто используется [MetalLB](../../Networking/LoadBalancing/metallb_overview.md).

## Практические сценарии

### 1. Установка Rancher Server в существующий кластер Kubernetes (Helm)

#### Процесс установки

1.  **Добавление Helm репозитория Rancher:**
    ```bash
    helm repo add rancher-stable https://releases.rancher.com/server-charts/stable
    helm repo update
    ```

2.  **Создание Namespace для Rancher:**
    ```bash
    kubectl create namespace cattle-system
    ```

3.  **Установка Rancher Server с помощью Helm:**
    ```bash
    helm upgrade --install rancher rancher-stable/rancher \
      --namespace cattle-system \
      --set hostname=rancher.yourdomain.com \
      --set bootstrapPassword=your_initial_admin_password \
      --set ingress.ingressClassName=nginx \
      --set ingress.tls.source=rancher \
      --set replicaCount=3 # Рекомендуется для High Availability
    ```

Параметры:
*   `hostname`: Доменное имя, по которому будет доступен Rancher UI.
*   `bootstrapPassword`: Начальный пароль администратора.
*   `ingress.ingressClassName`: Указывает класс Ingress Controller.
*   `ingress.tls.source=rancher`: Rancher автоматически генерирует самоподписанные TLS-сертификаты.
*   `replicaCount`: Количество реплик пода Rancher Server. Рекомендуется `3`.

#### Особенности развертывания

*   **Создание дополнительных Namespace:** Rancher Server при запуске создает множество служебных `namespaces` (например, `cattle-fleet`, `cattle-fleet-local-system`, `cattle-system`).
*   **Совместимость с Kubernetes:** Критически важно проверять совместимость версии Rancher с версией целевого кластера Kubernetes. Проблемы с `PodSecurityPolicy` (PSP) в Kubernetes 1.25+ являются примером.

### 2. Установка в Docker (для тестирования/ознакомления)

```bash
docker run -d --name=rancher --restart=unless-stopped \
  -p 80:80 -p 443:443 \
  rancher/rancher:latest
```

**Особенности и ограничения:**
*   **Внутренняя структура:** Rancher в Docker-контейнере запускается в многослойной архитектуре: внутри контейнера разворачивается легковесный Kubernetes (например, K3S).
*   **Нестабильность:** Не рекомендуется для production-сред.
*   **Альтернатива для Single-Node:** Более стабильным подходом является прямая установка Rancher на [K3S](../../Kubernetes/k3s/k3s_overview.md).

**Важное замечание по совместимости:** Rancher, особенно до версии 2.7.x, имеет строгие требования к версии Kubernetes. Часто требовалась Kubernetes версия **ниже 1.25** из-за деприкации `PodSecurityPolicy` (PSP) в Kubernetes 1.25.

### 3. Удаление компонентов Rancher/K3S

*   **Удаление K3S (полная очистка кластера):**
    ```bash
    /usr/local/bin/k3s-uninstall.sh
    ```

*   **Удаление агента K3S (Worker Node):**
    ```bash
    /usr/local/bin/k3s-agent-uninstall.sh
    ```

*   **Удаление агента Rancher (на узлах, добавленных в RKE-кластер):**
    ```bash
    # Если агент запущен через docker run:
    docker rm -f <container_id_или_имя_rancher_agent>

    # Или, если установлен как сервис:
    /usr/local/bin/rancher-system-agent-uninstall.sh
    ```

## Дополнительная информация

См. также: [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
