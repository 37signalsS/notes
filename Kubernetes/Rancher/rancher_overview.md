# Rancher: Платформа управления Kubernetes

## Определения

**Rancher** — это платформа управления Kubernetes-кластерами, которая предоставляет единый интерфейс для развертывания, настройки, мониторинга и управления несколькими кластерами Kubernetes, развернутыми в различных средах (облако, локальная инфраструктура).

## Базовые концепции

### Зачем нужен Rancher?

1.  **Управление несколькими кластерами**: Централизованное управление Kubernetes-кластерами в различных облаках (AWS, GCP, Azure) и на локальной инфраструктуре.
2.  **Упрощенная установка и настройка**: Предоставляет инструменты для быстрого развертывания Kubernetes-кластеров (RKE, RKE2).
3.  **Безопасность и контроль доступа**: Поддерживает различные методы аутентификации, включая [LDAP (Lightweight Directory Access Protocol)](../../Linux/SystemAdministration/users_management.md#LDAP-Lightweight-Directory-Access-Protocol), Active Directory, GitHub.
4.  **Мониторинг и логирование**: Встроенная поддержка для Prometheus, Grafana и Fluentd.
5.  **Развертывание приложений**: Упрощает развертывание приложений с поддержкой Helm-чартов.

### Как работает Rancher?

*   **Rancher Server**: Центральный компонент, который управляет кластерами, предоставляет веб-интерфейс (UI) и API.
*   **Kubernetes-кластеры**: Могут быть развернуты с помощью Rancher (RKE, RKE2) или импортированы (EKS, AKS, GKE).
*   **Rancher Agents**: Агенты, устанавливаемые в каждом управляемом Kubernetes-кластере.

## Тематические заметки

### Управление кластерами

| Тема | Описание | Файл |
| :--- | :--- | :--- |
| **RKE (Rancher Kubernetes Engine)** | Развертывание и управление кластерами Kubernetes через RKE/RKE2/K3S | [rancher_rke](./rancher_rke.md) |

### Мониторинг и логирование

| Тема | Описание | Файл |
| :--- | :--- | :--- |
| **Мониторинг** | Prometheus, Grafana, Alertmanager через kube-prometheus-stack | [rancher_monitoring](./rancher_monitoring.md) |
| **Логирование** | Fluentd, Logging Operator, Elasticsearch/OpenSearch | [rancher_logging](./rancher_logging.md) |

### CI/CD

| Тема | Описание | Файл |
| :--- | :--- | :--- |
| **Pipelines** | Встроенный CI/CD на базе Jenkins | [rancher_pipelines](./rancher_pipelines.md) |

### Управление и доступ

| Тема | Описание | Файл |
| :--- | :--- | :--- |
| **Установка Rancher** | Методы установки (Helm, Docker), удаление | [rancher_installation](./rancher_installation.md) |
| **RBAC и пользователи** | Управление пользователями, роли, проекты, квоты | [rancher_rbac](./rancher_rbac.md) |

## Дополнительная информация

*   Официальная документация Rancher: [Rancher Documentation](https://rancher.com/docs/rancher/v2.x/en/)
