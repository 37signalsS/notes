# Rancher: Платформа управления Kubernetes

## Определения

**Rancher** — это платформа управления Kubernetes-кластерами, которая предоставляет единый интерфейс для развертывания, настройки, мониторинга и управления несколькими кластерами Kubernetes, развернутыми в различных средах (облако, локальная инфраструктура).

## Базовые концепции

### Зачем нужен Rancher?

1. **Управление несколькими кластерами**: Централизованное управление Kubernetes-кластерами в различных облаках (AWS, GCP, Azure) и на локальной инфраструктуре.
2. **Упрощенная установка и настройка**: Предоставляет инструменты для быстрого развертывания Kubernetes-кластеров (RKE, RKE2).
3. **Безопасность и контроль доступа**: Поддерживает различные методы аутентификации, включая [LDAP (Lightweight Directory Access Protocol)](../../Linux/SystemAdministration/users_management.md#LDAP-Lightweight-Directory-Access-Protocol), Active Directory, GitHub.
4. **Мониторинг и логирование**: Встроенная поддержка для Prometheus, Grafana и Fluentd.
5. **Развертывание приложений**: Упрощает развертывание приложений с поддержкой Helm-чартов.

### Как работает Rancher?

* **Rancher Server**: Центральный компонент — управляет кластерами, предоставляет UI и API.
* **Kubernetes-кластеры**: Разворачиваются через Rancher (RKE, RKE2, K3s) или импортируются (EKS, AKS, GKE).
* **Rancher Agents**: Агенты в каждом управляемом кластере, устанавливающие обратное соединение с Rancher Server.

## Практические сценарии

### Типовые workflow

1. **Развёртывание Rancher Server**: Установка в существующий K8s-кластер через Helm или single-node на K3s. Подробности: [rancher_installation](./rancher_installation.md).
2. **Подключение кластера**: Импорт существующего кластера (EKS, AKS, GKE) или развёртывание нового через RKE/RKE2/K3s. Подробности: [rancher_rke](./rancher_rke.md).
3. **Настройка доступа**: Создание пользователей, проектов, ролей через Rancher RBAC. Подробности: [rancher_rbac](./rancher_rbac.md).
4. **Мониторинг**: Включение встроенного стека Prometheus + Grafana. Подробности: [rancher_monitoring](./rancher_monitoring.md).
5. **Логирование**: Настройка сбора логов через Fluent Bit → Fluentd → Elasticsearch/OpenSearch. Подробности: [rancher_logging](./rancher_logging.md).
6. **CI/CD**: Использование встроенных pipelines на базе Jenkins. Подробности: [rancher_pipelines](./rancher_pipelines.md).

## Дополнительная информация

### Актуальность версий

> **Внимание:** Rancher — активно развивающийся продукт SUSE. Поддерживаемые версии — 2.12.x, 2.13.x (на 2026 год). Rancher 2.7.x и ниже — EOL.

| Компонент | Указанная информация | Статус | Рекомендация |
|-----------|---------------------|--------|--------------|
| **Rancher** | v2.13.x (актуальная) | ✅ Поддерживается | [Release Notes](https://github.com/rancher/rancher/releases) |
| **RKE/RKE2** | RKE2 рекомендуется для новых развёртываний | ✅ Актуален | RKE1 — legacy |
| **Kubernetes** | v1.32–v1.34 для Rancher 2.13 | ✅ Актуален | [Support Matrix](https://www.suse.com/suse-rancher/support-matrix/) |

Официальная документация: [Rancher Documentation](https://rancher.com/docs/rancher/v2.x/en/).
