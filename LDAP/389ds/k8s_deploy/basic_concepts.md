# 389DS в Kubernetes: Основные концепции

## Архитектура развёртывания

389DS в Kubernetes использует:

* **StatefulSet** — для сохранения состояния и стабильных идентификаторов
* **PersistentVolumeClaim** — для персистентных данных (режим RWO)
* **ConfigMap/Secret** — для конфигурации и чувствительных данных
* **Headless Service** — для discovery подов репликации

> **Рекомендуемая последовательность:**
>
> 1. Запустить 389DS в Docker на отдельных машинах
> 2. Настроить кластер и репликацию
> 3. Протестировать failover
> 4. Перенести работающую конфигурацию в Kubernetes
> 5. Создать Helm chart для повторяемости

## Требования к кластеру

| Требование | Описание |
| :--- | :--- |
| **Nodes** | Минимум 2 worker nodes для HA |
| **Storage** | StorageClass с поддержкой RWO |
| **Network** | Ingress/LoadBalancer (MetalLB) для внешнего доступа |
| **Certificates** | cert-manager для TLS-сертификатов (см. [Приватный CA](../../../Kubernetes/ToolsUtilities/cert_manager/Private_CA/scenarios.md)) |

## Компоненты развёртывания

1. **StatefulSet** — управляет подами 389DS с гарантированным порядком развёртывания
2. **Headless Service** — обеспечивает стабильные DNS-имена для подов
3. **LoadBalancer Service** — предоставляет внешний доступ к LDAP
4. **Secret** — хранит пароли администратора и репликации
5. **ConfigMap** — содержит скрипты инициализации
6. **Job** — выполняет однократную инициализацию каталога

---

## Связанные материалы

* [Определения](./definitions.md) — базовые термины
* [Практические сценарии](./practical_scenarios.md) — StatefulSet, сервисы, инициализация
* [Дополнительная информация](./additional_info.md) — troubleshooting, мониторинг, best practices
