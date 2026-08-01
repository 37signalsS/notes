# Elastic Cloud on Kubernetes (ECK)

## Определения

**Elastic Cloud on Kubernetes (ECK)** — это официальный Kubernetes-оператор от Elastic, предназначенный для автоматизации развертывания, управления и эксплуатации Elastic Stack (Elasticsearch, Kibana, APM Server, Fleet, Elastic Agent и Enterprise Search) в кластерах Kubernetes.

Оператор расширяет API Kubernetes с помощью [CRD (Custom Resource Definitions)](../Kubernetes/Concepts/kubernetes_crd.md), позволяя описывать желаемое состояние компонентов Elastic Stack в декларативном виде.

*   **Репозиторий:** [github.com/elastic/cloud-on-k8s](https://github.com/elastic/cloud-on-k8s)
*   **Назначение:** Обеспечение консистентности, безопасности и масштабируемости Elastic Stack в облачных средах.

## Основные возможности

ECK инкапсулирует эксплуатационные знания Elastic, автоматизируя следующие задачи:

*   **Управление жизненным циклом:** Автоматизация развертывания и настройки Elasticsearch, Kibana и других компонентов.
*   **Обновления и масштабирование:** Безопасное проведение обновлений версий (Rolling Updates) и изменение количества узлов или ресурсов.
*   **Безопасность:**
    *   Автоматическая генерация и управление TLS-сертификатами для защищенного взаимодействия между компонентами.
    *   Настройка аутентификации на базе RBAC.
*   **Мониторинг и логирование:** Встроенные механизмы для сбора метрик и логов самого Elastic Stack.
*   **Управление хранилищем:** Интеграция с Kubernetes Persistent Volumes для обеспечения сохранности данных.
*   **Snapshot & Restore:** Упрощение процесса резервного копирования и восстановления данных.

## Архитектура и компоненты

### Ключевые Custom Resources (CR)

| Ресурс | Описание |
| :--- | :--- |
| **Elasticsearch** | Управление кластером Elasticsearch (роли узлов, топология, ресурсы). |
| **Kibana** | Развертывание и связь инстанса Kibana с кластером Elasticsearch. |
| **ApmServer** | Настройка сервера мониторинга производительности приложений. |
| **Beat** | Управление агентами сбора данных (Filebeat, Metricbeat и др.). |
| **Agent** | Управление унифицированным Elastic Agent. |

### Процесс работы

1.  **Декларация:** Пользователь создает манифест (например, `kind: Elasticsearch`).
2.  **Сверка (Reconciliation):** Оператор обнаруживает ресурс и создает необходимые объекты Kubernetes: StatefulSets для узлов данных, Services для доступа, Secrets для паролей и сертификатов.
3.  **Поддержка состояния:** Оператор постоянно отслеживает здоровье кластера и автоматически восстанавливает узлы при сбоях.

## Практические сценарии

### Пример развертывания Elasticsearch и Kibana

```yaml
# Elasticsearch кластер
apiVersion: elasticsearch.k8s.elastic.co/v1
kind: Elasticsearch
metadata:
  name: quickstart
spec:
  version: 8.12.0
  nodeSets:
  - name: default
    count: 3
    config:
      node.store.allow_mmap: false

---
# Kibana
apiVersion: kibana.k8s.elastic.co/v1
kind: Kibana
metadata:
  name: quickstart
spec:
  version: 8.12.0
  count: 1
  elasticsearchRef:
    name: quickstart
```

## Дополнительная информация

*   **[Официальная документация ECK](https://www.elastic.co/guide/en/cloud-on-k8s/current/index.html)**
*   **[Kubernetes Operators](../Kubernetes/Concepts/kubernetes_operators.md)** — общие принципы работы операторов.
*   **[ELK Stack Overview](./elk_stack_overview.md)** — архитектура и компоненты Elastic Stack.
