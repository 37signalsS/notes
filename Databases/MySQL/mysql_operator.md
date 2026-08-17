# MySQL Operator для Kubernetes

## Определения

**MySQL Operator for Kubernetes** — специализированный контроллер, реализующий паттерн **Operator**, который автоматизирует управление жизненным циклом InnoDB Cluster в Kubernetes. Он берет на себя задачи инициализации, масштабирования, резервного копирования и восстановления, используя декларативный подход.

**InnoDB Cluster** — нативное высокодоступное решение от Oracle, объединяющее **Group Replication** (синхронная репликация на базе Paxos), **MySQL Router** (прокси для маршрутизации трафика) и **MySQL Shell** (инструмент администрирования).

**Reconciliation Loop (Цикл согласования)** — основной механизм работы оператора, который непрерывно сравнивает текущее состояние ресурсов в кластере с желаемым (описанным в YAML) и выполняет действия по их приведению в соответствие.

**Custom Resource Definition (CRD)** — расширение API Kubernetes, позволяющее оператору создавать и управлять специфичными для MySQL объектами (`InnoDBCluster`, `MySQLBackup` и др.) как стандартными ресурсами K8s.

## Базовые концепции

### 1. Архитектура управления
Оператор состоит из центрального контроллера, который наблюдает за CRD, и набора Sidecar-контейнеров внутри подов с базой данных.
*   **InnoDBCluster CR**: Определяет топологию (Single-Primary по умолчанию), версию СУБД, количество узлов и требования к хранилищу.
*   **MySQL Router CR**: Развертывается как отдельный Deployment или DaemonSet. Он обеспечивает прозрачный Read/Write Split: запросы на запись идут на Primary узел, запросы на чтение — на Secondary узлы.
*   **Storage Management**: Оператор использует `VolumeClaimTemplates` для создания уникальных Persistent Volume Claims (PVC) для каждого узла. При удалении пода оператор гарантирует, что новый под привяжется к тому же PVC, сохраняя данные.

### 2. Group Replication и консенсус
В отличие от классической репликации, InnoDB Cluster в Kubernetes использует Group Replication:
- **Кворум:** Для работы кластера требуется большинство узлов (минимум 2 из 3).
- **Автоматический Failover:** Если мастер-под падает, оставшиеся узлы выбирают нового лидера через протокол консенсуса. Оператор обновляет конфигурацию MySQL Router, чтобы трафик мгновенно переключился на новый адрес.

### 3. Предварительные требования (Prerequisites)
- **Kubernetes**: Версия 1.27+ (рекомендуется).
- **StorageClass**: Должен поддерживать динамическое создание томов с `accessModes: [ReadWriteOnce]`. Для Production критически важна поддержка быстрых SSD/NVMe.
- **Resources**: Минимум 2 ГБ RAM на каждый узел MySQL для стабильной работы Group Replication.

## Практические сценарии

### 1. Расширенная установка через Helm

Установка оператора с настройкой глобальных параметров безопасности.

```bash
# Добавление репозитория
helm repo add mysql-operator https://mysql.github.io/mysql-operator/
helm repo update

# Установка с ограничением прав (Namespace-scoped)
helm install mysql-operator mysql-operator/mysql-operator \
  --namespace mysql-operator \
  --create-namespace \
  --set installRouter=true
```

### 2. Развертывание кластера с Affinity и Ресурсами

Пример для Production: использование Anti-Affinity, чтобы узлы базы данных не попадали на один физический хост, и лимитов ресурсов.

```yaml
apiVersion: mysql.oracle.com/v2
kind: InnoDBCluster
metadata:
  name: main-db
  namespace: database
spec:
  instances: 3
  version: "8.4.10"
  secretName: mysql-credentials
  # Правила размещения для обеспечения HA
  podSpec:
    affinity:
      podAntiAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
                - key: "mysql.oracle.com/cluster"
                  operator: In
                  values: ["main-db"]
            topologyKey: "kubernetes.io/hostname"
    resources:
      requests:
        cpu: "1"
        memory: "2Gi"
      limits:
        cpu: "2"
        memory: "4Gi"
  # Конфигурация роутера
  router:
    instances: 2
    httpServerPort: 8443
  # Шаблон хранилища
  datadirVolumeClaimTemplate:
    storageClassName: local-ssd
    resources:
      requests:
        storage: 50Gi
```

### 3. Горизонтальное и вертикальное масштабирование

**Горизонтальное (изменение кол-ва узлов):**
Просто измените параметр `spec.instances` в манифесте и примените его (`kubectl apply`). Оператор автоматически добавит новый узел, инициирует `Clone Plugin` для копирования данных и введет его в группу.

**Вертикальное (изменение ресурсов):**
Обновите `spec.podSpec.resources`. Оператор будет выполнять **Rolling Update**, поочередно перезапуская узлы (сначала Secondary, затем Primary после перевыборов), минимизируя простой.

### 4. Управление секретами и паролями

Не храните пароли в YAML. Создайте секрет заранее:

```bash
kubectl create secret generic mysql-credentials \
  --from-literal=rootUser=root \
  --from-literal=rootPassword=$(openssl rand -base64 12) \
  --from-literal=rootHost='%'
```
*Примечание: Оператор автоматически синхронизирует эти данные с внутренними таблицами пользователей MySQL.*

## Диагностика и устранение неисправностей

### Типовые состояния кластера
- **`ONLINE`**: Кластер полностью исправен.
- **`RECOVERING`**: Узел присоединяется к группе и синхронизирует данные (используется Clone Plugin).
- **`OFFLINE` / `UNREACHABLE`**: Узел недоступен. Проверьте состояние пода и сетевую связность.

### Команды отладки
```bash
# Проверка детального статуса кластера (включая топологию Group Replication)
kubectl get innodbcluster main-db -o yaml

# Доступ к встроенному логу ошибок MySQL
kubectl logs main-db-0 -c mysql

# Проверка статуса MySQL Router
kubectl logs -l component=router
```

### Решение проблем с кворумом (Split-Brain)
Если более половины узлов вышли из строя, кластер перейдет в режим `Read-Only` для защиты данных.
1. Убедитесь, что PVC не повреждены.
2. Проверьте логи оператора на наличие ошибок `Waiting for quorum`.
3. При необходимости выполните принудительную инициализацию через MySQL Shell внутри пода (только для экспертов).

## Дополнительная информация

### Рекомендации (Best Practices)
1.  **Anti-Affinity**: Всегда используйте `podAntiAffinity`, чтобы выход из строя одного гипервизора не убил весь кластер.
2.  **PDB**: Настраивайте `PodDisruptionBudget` для предотвращения одновременного удаления слишком большого количества узлов при обслуживании K8s.
3.  **Бэкапы**: Используйте `MySQLBackup` с расписанием (`CronJob` стиль) и выгрузкой в S3 для защиты от потери данных всего региона.

### Краевые случаи (Edge Cases)
- **Имя узлов**: Оператор использует StatefulSet, поэтому имена подов (`db-0`, `db-1`) фиксированы. Не пытайтесь менять их вручную.
- **Обновление сертификатов**: Если `tlsUseSelfSigned: true`, оператор сам ротирует сертификаты. При использовании внешних CA следите за сроком их действия в секретах.

### См. также
*   **[Официальная документация MySQL Operator](https://dev.mysql.com/doc/mysql-operator/en/)**
*   **[MySQL: Обзор и сравнение форков](./overview.md)** — архитектура InnoDB и Group Replication.
*   **[Репликация в MySQL: Обзор](./replication/overview.md)** — теоретические основы GTID и Binlog.
*   **[StatefulSet: Лучшие практики](../../Kubernetes/Base/StatefulSet/statefulset_best_practices.md)** — специфика работы с stateful-приложениями.
