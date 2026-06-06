# Установка Rancher Server

## Определения

**Rancher Server** — центральный компонент платформы Rancher, предназначенный для управления кластерами Kubernetes. Он предоставляет графический интерфейс пользователя (UI — User Interface) и программный интерфейс приложения (API — Application Programming Interface) для взаимодействия с инфраструктурой.

**Helm** — менеджер пакетов для Kubernetes, используемый для определения, установки и обновления сложных приложений.

## Базовые концепции

### Методы развертывания

Существует два основных способа установки Rancher Server:

1. **Установка в существующий кластер Kubernetes через Helm**: рекомендуемый метод для производственных (production) сред, обеспечивающий высокую доступность (HA — High Availability).
2. **Установка в Docker-контейнер**: упрощенный метод, предназначенный исключительно для тестирования или ознакомления с платформой.

### Системные требования

Для стабильной работы Rancher Server в кластере Kubernetes необходимы следующие компоненты:

* **Контроллер Ingress (Ingress Controller)**: обеспечивает маршрутизацию внешнего трафика к интерфейсу и API Rancher (например, Nginx Ingress Controller).
* **Cert Manager**: инструмент для автоматизации управления сертификатами безопасности (TLS — Transport Layer Security).
* **Балансировщик нагрузки (Load Balancer)**: точка входа для внешнего трафика. В локальных (bare-metal) средах часто применяется [MetalLB](../../Kubernetes/Networking/metallb.md).

## Практические сценарии

### Развертывание в существующем кластере через Helm

Процесс установки включает следующие этапы:

1. **Добавление репозитория Rancher**:

    ```bash
    helm repo add rancher-stable https://releases.rancher.com/server-charts/stable
    helm repo update
    ```

2. **Подготовка пространства имен (Namespace)**:

    ```bash
    kubectl create namespace cattle-system
    ```

3. **Установка через Helm**:

    ```bash
    helm upgrade --install rancher rancher-stable/rancher \
      --namespace cattle-system \
      --set hostname=rancher.example.com \
      --set bootstrapPassword=your_initial_password \
      --set ingress.ingressClassName=nginx \
      --set ingress.tls.source=rancher \
      --set replicaCount=3
    ```

**Описание ключевых параметров:**

* `hostname`: доменное имя для доступа к панели управления.
* `bootstrapPassword`: временный пароль для первой авторизации администратора.
* `ingress.ingressClassName`: идентификатор используемого класса Ingress.
* `ingress.tls.source=rancher`: использование встроенного механизма Rancher для генерации самоподписанных сертификатов.
* `replicaCount`: количество экземпляров приложения. Значение `3` рекомендуется для обеспечения отказоустойчивости.

### Установка через Docker (для ознакомительных целей)

Команда для быстрого запуска:

```bash
docker run -d --name=rancher --restart=unless-stopped \
  -p 80:80 -p 443:443 \
  rancher/rancher:latest
```

**Ограничения Docker-установки:**

* **Архитектура**: внутри контейнера запускается встроенный легковесный дистрибутив Kubernetes (K3s).
* **Надежность**: метод не обеспечивает отказоустойчивость и не рекомендуется для критических задач.
* **Альтернатива**: для стабильной работы на одном узле рекомендуется установка на полноценный [K3s](../Installation/k3s_dev_environment/k3s_architecture.md).

### Совместимость и безопасность

* **Версии**: необходимо сверяться с матрицей поддержки (Support Matrix). Rancher v2.13.x совместим с Kubernetes v1.32–v1.34.
* **Безопасность**: в актуальных версиях Kubernetes вместо устаревших политик безопасности подов (PSP — Pod Security Policy) используется встроенный механизм контроля допуска (PSA — Pod Security Admission). Подробности в разделе [Контекст безопасности подов](../Security/pod_security_context.md).

### Удаление компонентов

**Полная очистка K3s**:

```bash
/usr/local/bin/k3s-uninstall.sh
```

**Удаление агента Rancher (на управляемых узлах)**:

```bash
# Для агента в Docker:
docker rm -f <container_name>

# Для системного агента:
/usr/local/bin/rancher-system-agent-uninstall.sh
```

## Дополнительная информация

* [Обзор Rancher](./rancher_overview.md) — общие принципы и возможности платформы.
* [Официальная матрица поддержки](https://www.suse.com/suse-rancher/support-matrix/) — проверка совместимости версий.
