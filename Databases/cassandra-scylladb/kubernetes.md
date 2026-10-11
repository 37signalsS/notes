# Развёртывание и масштабирование в Kubernetes

**Актуально для:** ScyllaDB 2026.x / Scylla Operator 1.22.x / Apache Cassandra 5.0.x / cass-operator 1.28.x / K8ssandra Operator 1.33.x

## Определения

| Термин | Определение |
| :--- | :--- |
| Operator | Контроллер Kubernetes, реализующий цикл reconcile: непрерывно приводит фактическое состояние кластера БД к объявленному в custom resource |
| CRD (CustomResourceDefinition) | Расширение API Kubernetes пользовательскими ресурсами (`ScyllaCluster`, `CassandraDatacenter`) |
| StatefulSet | Контроллер с устойчивой сетевой идентичностью и хранилищем; Operator создаёт один StatefulSet на rack |
| Scylla Manager | Сервис управления ScyllaDB: расписание backup и repair; агент работает sidecar-контейнером на каждом pod |
| Management API for Apache Cassandra | REST API жизненного цикла в pod Cassandra (cass-operator): bootstrap, restart, decommission |
| PDB (PodDisruptionBudget) | Ограничение одновременных вытеснений pod при обслуживании узлов |
| Discovery Service | Service `<cluster>-client` — единая точка входа для клиентов |

## Выбор оператора

| СУБД | Решение | Основной CRD | Примечания |
| :--- | :--- | :--- | :--- |
| ScyllaDB | Scylla Operator | `ScyllaCluster` (`scylla.scylladb.com/v1`) | Один ресурс на datacenter; rack → StatefulSet |
| Apache Cassandra | cass-operator (в составе K8ssandra) | `CassandraDatacenter` (`cassandra.datastax.com/v1beta1`) | Жизненный цикл через Management API |
| Apache Cassandra + Reaper/Medusa/Stargate | K8ssandra Operator | `K8ssandraCluster` (`k8ssandra.io/v1alpha1`) | Делегирует управление Cassandra cass-operator |

Operator расширяет API Kubernetes CRD и запускает контроллеры, которые непрерывно сверяют объявленное состояние с фактическим. `ScyllaCluster` — стабильный API (`scylla.scylladb.com/v1`): каждый ресурс описывает один datacenter, внутри него объявляются rack'и, а Operator создаёт StatefulSet на каждый rack.

---

## Установка Scylla Operator

**Предварительные требования:** кластер Kubernetes (см. поддержку версий в releases оператора), настроенный `kubectl`, Helm 3+, cert-manager (нужен для TLS webhook'а оператора).

```bash
# 1. Добавить репозиторий Helm-чартов (минимум три чарта: scylla-operator, scylla-manager, scylla)
helm repo add scylla https://scylla-operator-charts.storage.googleapis.com/stable
helm repo update
helm search repo scylla

# 2. Установить оператор
helm install scylla-operator scylla/scylla-operator \
  --create-namespace \
  --namespace scylla-operator

# 3. Проверить готовность
kubectl -n scylla-operator rollout status --timeout=10m deployment.apps/{scylla-operator,webhook-server}
kubectl get crd | grep scylla.scylladb.com
# → scyllaclusters.scylla.scylladb.com
#   nodeconfigs.scylla.scylladb.com
#   scyllaoperatorconfigs.scylla.scylladb.com
#   scylladbmonitorings.scylla.scylladb.com
```

**Ограничения Helm-пути:**
- Поддерживает только single-datacenter развёртывания; для multi-DC используйте путь GitOps.
- Helm не управляет CRD (helm#5871, helm#7735): CRD создаются только при первой установке и никогда не обновляются. При каждом апгрейде оператора CRD нужно обновлять вручную — иначе новые поля CRD недоступны.
- `helm uninstall` не удаляет CRD (см. раздел «Очистка»).

**GitOps-путь (multi-DC, рекомендуемый для production):**

```bash
# Зависимости: cert-manager и CRD Prometheus Operator (нужны даже без стека мониторинга)
kubectl apply --server-side -f=https://raw.githubusercontent.com/scylladb/scylla-operator/v1.20/examples/third-party/cert-manager.yaml
kubectl apply -n prometheus-operator --server-side -f=https://raw.githubusercontent.com/scylladb/scylla-operator/v1.20/examples/third-party/prometheus-operator.yaml
kubectl wait --for condition=established --timeout=60s crd/certificates.cert-manager.io crd/issuers.cert-manager.io

# Сам оператор
kubectl -n=scylla-operator apply --server-side -f=https://raw.githubusercontent.com/scylladb/scylla-operator/v1.20/deploy/operator.yaml
```

Образ оператора в Deployment и значение env `SCYLLA_OPERATOR_IMAGE` должны всегда совпадать; не используйте rolling-теги (`latest`) — рассинхрон версий приводит к некорректному reconcile.

---

## ScyllaCluster CRD

```yaml
# scyllacluster.yaml
apiVersion: scylla.scylladb.com/v1
kind: ScyllaCluster
metadata:
  name: my-scylla-cluster
  namespace: scylla
spec:
  repository: docker.io/scylladb/scylla
  version: 2026.1.1
  agentVersion: 3.10.1
  developerMode: false
  datacenter:
    name: dc1
    racks:
      - name: rack1
        members: 3
        storage:
          capacity: 200Gi
        resources:
          requests:
            cpu: 2
            memory: 8Gi
          limits:
            cpu: 4
            memory: 16Gi
      - name: rack2
        members: 3
        storage:
          capacity: 200Gi
        resources:
          requests:
            cpu: 2
            memory: 8Gi
          limits:
            cpu: 4
            memory: 16Gi
```

```bash
kubectl apply -n scylla -f scyllacluster.yaml
kubectl get scyllaclusters -n scylla
kubectl describe scyllaclusters my-scylla-cluster -n scylla
kubectl get pods -n scylla -w   # ожидайте 2/2 Running: scylla + scylla-manager-agent
```

**Ключевые поля `spec`:**

| Поле | Назначение |
| :--- | :--- |
| `repository`, `version` | Образ ScyllaDB (пиньте тег, не `latest`) |
| `agentRepository`, `agentVersion` | Образ Scylla Manager Agent (sidecar на каждом pod) |
| `developerMode` | Режим разработки: снижает требования к ресурсам. В production — `false` |
| `datacenter.name` | Имя datacenter (записывается в `cassandra-rackdc.properties`) |
| `racks[].name`, `racks[].members` | Имя rack и число узлов в нём (один StatefulSet на rack) |
| `racks[].storage.capacity` | Размер PVC на узел |
| `racks[].resources` | Requests/limits контейнера Scylla |
| `racks[].placement` | `nodeAffinity`, `podAntiAffinity`, `tolerations` — размещение pod |
| `racks[].scyllaConfig` | Имя ConfigMap для кастомизации `scylla.yaml` |
| `racks[].scyllaAgentConfig` | Secret с конфигурацией Scylla Manager Agent |
| `externalSeeds` | Внешние seed-узлы для multi-DC (один ScyllaCluster на Kubernetes-кластер) |
| `forceRedeploymentReason` | Уникальная строка для форсированного rolling update всех rack'ов |
| `scyllaArgs` | Дополнительные аргументы бинарника Scylla (с версии 4.2.0) |
| `enableParallelNodeOperations` | Параллельные операции на узлах; требует ScyllaDB 2026.2+ |
| `minReadySeconds` | Минимум секунд готовности нового узла перед переходом трафика |
| `imagePullSecrets` | Secrets для приватных реестров образов |

**NodeConfig** (cluster-scoped CRD `nodeconfigs.scylla.scylladb.com`) — настройка дисков узлов: RAID, файловая система, sysctl. Обязателен для backing-кластера ScyllaDB Manager. Поля и примеры — в [API-справочнике оператора](https://operator.docs.scylladb.com/stable/reference/api/).

---

## Масштабирование и обновления

```bash
# Масштабирование: изменить members в CR и применить
kubectl patch scyllaclusters my-scylla-cluster -n scylla \
  --type=json -p='[{"op":"replace","path":"/spec/datacenter/racks/0/members","value":4}]'

# Добавить rack: добавить элемент в spec.datacenter.racks[] — создастся новый StatefulSet

# Rolling update (версия, ресурсы): изменить поле и применить — pod обновляются по одному
kubectl set image statefulset/my-scylla-cluster-dc1-rack1 \
  scylla=docker.io/scylladb/scylla:2026.1.1 -n scylla   # иллюстративно; предпочтительнее через CR
```

- **Scale up** — operator добавляет pod и выполняет bootstrap; **scale down** — decommission.
- **Rolling update** — pod обновляются по одному, кластер остаётся доступным при корректном RF.
- Статус задач в `.status.backups` и `.status.repairs` на ScyllaCluster.
- Проверка здоровья: `kubectl get pods -n scylla -w`, затем `nodetool status` (см. «Подключение»).

---

## Бэкап и repair через ScyllaDB Manager

ScyllaDB Manager — companion-сервис с расписанием backup/repair. Operator интегрирует его декларативно: задачи объявляются inline в `ScyllaCluster` и транслируются в CRD `ScyllaDBManagerTask` (`scylla.scylladb.com/v1alpha1`).

**Зависимости:** ScyllaDB Manager (`helm install scylla-manager scylla/scylla-manager --create-namespace --namespace scylla-manager`), применённый NodeConfig и ScyllaDB Local CSI Driver (хранилище для backing-кластера Manager).

```yaml
# Задачи внутри ScyllaCluster
spec:
  backups:
    - name: daily-backup
      location:
        - s3:my-bucket
      keyspace:
        - my_app
      retention: 7
      cron: "0 2 * * *"
      rateLimit:
        - 100
  repairs:
    - name: weekly-repair
      cron: "0 0 * * 0"
```

**Поля задачи backup:** `cron` (расширенный синтаксис: `@daily`, `@every 4h`), `location` (формат `[<dc>:]<provider>:<name>`; провайдеры: `s3`, `gcs`), `keyspace` (glob-шаблоны, напр. `my_app,!my_app.audit_*`), `dc` (glob по datacenter), `retention` (число хранимых копий), `rateLimit` (МиБ/с, `0` — без лимита, по умолчанию 100), `numRetries`, `retryWait` (экспоненциальный backoff), `snapshotParallel`/`uploadParallel`, `startDate` (RFC3339 или `now+3d2h10m`), `timezone`.

**Restore не доступен через декларативный API** — выполняется через `sctool` в pod Manager:

```bash
# Список снапшотов
kubectl -n scylla-manager exec -ti deployment.apps/scylla-manager -- \
  sctool backup list -c <CLUSTER_ID> --all-clusters -L <BACKUP_LOCATION>

# Восстановление: сначала схема, затем данные
kubectl -n scylla-manager exec -ti deployment.apps/scylla-manager -- \
  sctool restore -c <CLUSTER_ID> -L <BACKUP_LOCATION> -T <SNAPSHOT_TAG> --restore-schema
kubectl -n scylla-manager exec -ti deployment.apps/scylla-manager -- \
  sctool restore -c <CLUSTER_ID> -L <BACKUP_LOCATION> -T <SNAPSHOT_TAG> --restore-tables
```

- Если ScyllaDB Manager не установлен, поля `backups`/`repairs` игнорируются.
- Один глобальный экземпляр Manager на кластер Kubernetes; изоляция между кластерами — только токенами авторизации.
- Функциональность Manager за пределами backup/repair (например, healthcheck) через CRD не открыта.

---

## Подключение приложений

Для каждого ScyllaCluster Operator создаёт Discovery Service `<cluster-name>-client` (ClusterIP), который выбирает все готовые pod. Клиент подключается к нему, а драйвер автоматически обнаруживает все узлы кластера.

```bash
# DNS внутри кластера: <cluster-name>-client.<namespace>.svc
kubectl get service/my-scylla-cluster-client -n scylla -o='jsonpath={.spec.clusterIP}'

# cqlsh встроен в каждый pod (контейнер scylla)
kubectl exec -it pod/my-scylla-cluster-dc1-rack1-0 -n scylla -c scylla -- cqlsh
kubectl exec -it service/my-scylla-cluster-client -n scylla -c scylla -- cqlsh

# nodetool
kubectl exec -it pod/my-scylla-cluster-dc1-rack1-0 -n scylla -c scylla -- nodetool status
```

- Именование pod: `<cluster-name>-<datacenter>-<rack>-<ordinal>`; контейнеры: `scylla` + `scylla-manager-agent`.
- **Не патчите** operator-managed Service `<cluster>-client` вручную — operator откатит изменения при reconcile. Для доступа извне создавайте отдельный Service `<cluster>-client-external` типа LoadBalancer с селектором `scylla/cluster: <cluster-name>`, `app: scylla`, `scylla-operator.scylladb.com/pod-type: scylladb-node` и портами 9042 (cql) / 9142 (cql-ssl).
- Настройка драйвера: contact points — DNS discovery Service (не Pod IP); local DC — значение `datacenter.name`; load balancing — token-aware + DC-aware round robin.

---

## Мониторинг в Kubernetes

- `ScyllaDBMonitoring` (namespaced CRD) — стек Prometheus + Grafana для ScyllaDB, управляемый оператором.
- ScyllaDB экспонирует нативный Prometheus endpoint на порту 9180 — метрики и правила сбора в [Мониторинг и observability](./monitoring.md).

---

## Apache Cassandra через cass-operator / K8ssandra

```bash
# 1. Репозиторий и зависимость cert-manager
helm repo add k8ssandra https://helm.k8ssandra.io/stable
helm repo update
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace --set installCRDs=true

# 2. K8ssandra Operator (namespace-scoped по умолчанию;
#    --set global.clusterScoped=true — cluster-scoped)
helm install k8ssandra-operator k8ssandra/k8ssandra-operator \
  -n k8ssandra-operator --create-namespace

# 3. Проверка: должны быть pod k8ssandra-operator и k8ssandra-operator-cass-operator
kubectl get pods -n k8ssandra-operator
```

```yaml
# k8ssandracluster.yaml
apiVersion: k8ssandra.io/v1alpha1
kind: K8ssandraCluster
metadata:
  name: demo
spec:
  cassandra:
    serverVersion: "5.0.0"
    datacenters:
      - metadata:
          name: dc1
        size: 3
        storageConfig:
          cassandraDataVolumeClaimSpec:
            storageClassName: standard
            accessModes:
              - ReadWriteOnce
            resources:
              requests:
                storage: 5Gi
        config:
          jvmOptions:
            heapSize: 512M
```

```bash
kubectl apply -n k8ssandra-operator -f k8ssandracluster.yaml
kubectl get k8cs -n k8ssandra-operator
kubectl get pods -n k8ssandra-operator -w
# → demo-dc1-default-sts-0/1/2  2/2 Running
```

**Анатомия pod Cassandra:** initContainer `server-config-init` рендерит конфигурацию из CR; контейнеры `cassandra` и `server-system-logger` (tail `/var/log/cassandra/system.log`). Сначала стартует Management API for Apache Cassandra — REST API, через который cass-operator выполняет bootstrap, restart, decommission; только затем узлы присоединяются к кластеру. StatefulSet: `<cluster>-<dc>-default-sts`, pod: `<cluster>-<dc>-default-sts-<ordinal>`.

**Проверка кластера и работа с ним:**

```bash
# Учётные данные superuser (K8ssandra создаёт Secret <cluster>-superuser)
CASS_USERNAME=$(kubectl get secret demo-superuser -n k8ssandra-operator -o=jsonpath='{.data.username}' | base64 --decode)
CASS_PASSWORD=$(kubectl get secret demo-superuser -n k8ssandra-operator -o=jsonpath='{.data.password}' | base64 --decode)

kubectl exec -it demo-dc1-default-sts-0 -n k8ssandra-operator -c cassandra -- \
  nodetool -u "$CASS_USERNAME" -pw "$CASS_PASSWORD" status
# → Datacenter: dc1
#   UN  10.244.1.5  96.71 KiB  16  100.0%  4b95036b-...  default

kubectl exec -it demo-dc1-default-sts-0 -n k8ssandra-operator -c cassandra -- \
  cqlsh -u "$CASS_USERNAME" -p "$CASS_PASSWORD" -e "SELECT cluster_name FROM system.local;"
```

**Особенности cass-operator:**
- PodDisruptionBudget создаётся по умолчанию; отключить аннотацией `cassandra.datastax.com/disable-pdb-creation: "true"` на `CassandraDatacenter`.
- Пропуск удаления PVC при удалении `CassandraDatacenter`: аннотация `cassandra.datastax.com/delete-pvc: "false"` (cass-operator 1.25.0+).
- `maxUnavailable` (Kubernetes 1.35+): целое число или процент — параллельные изменения pod, но не более одного rack за раз.
- `readOnlyRootFilesystem` включён по умолчанию для OSS Cassandra 4.1+.
- Компоненты K8ssandra: Reaper (repair), Medusa (backup), Stargate (API), Metrics Collector.
- Standalone cass-operator использует тот же CRD `cassandra.datastax.com/v1beta1` kind `CassandraDatacenter` (поля `clusterName`, `serverVersion`, `serverType: cassandra`, `size`, `storageConfig`, `resources`, `config`).

---

## Поиск и устранение неисправностей

| Симптом | Причина | Диагностика / решение |
| :--- | :--- | :--- |
| Pod в `Pending` | Нет ресурсов или StorageClass | `kubectl describe pod <pod> -n scylla`; `kubectl get storageclass` |
| `CrashLoopBackOff` | Ошибка конфига, нехватка ресурсов | `kubectl logs <pod> -n scylla -c scylla --previous` |
| Operator не reconcile после апгрейда | Helm не обновил CRD | Обновить CRD вручную; `kubectl get crd scyllaclusters.scylla.scylladb.com -o yaml` |
| Webhook не готов | Deployment webhook-server не rollout'нут | `kubectl -n scylla-operator rollout status deployment.apps/webhook-server` |
| `Connection refused` из cqlsh/драйвера | Подключение к Pod IP вместо discovery Service | Использовать `<cluster>-client.<namespace>.svc` |
| PVC застрял в `Terminating` | Finalizer, pod не удалён | Убедиться, что pod удалён, затем проверить PVC |
| Задачи backup не создаются | ScyllaDB Manager не установлен | Установить Manager; без него `backups`/`repairs` игнорируются |
| `nodetool` требует авторизации | Включена аутентификация | Извлечь creds из Secret superuser (см. пример выше) |
| Pod `2/2 Running` | Норма: `scylla` + `scylla-manager-agent` | — |

Ошибки уровня CQL (NoHostAvailableException, таймауты, tombstones) — в [Поиск и устранение неисправностей](./troubleshooting.md).

---

## Рекомендации и очистка

- Пиньте версии образов (`version`, `agentVersion`); образ оператора и `SCYLLA_OPERATOR_IMAGE` — всегда одинаковые, без rolling-тегов.
- Минимум 3 rack'а в production (RF=3); один rack = один StatefulSet = одна доменная отказоустойчивость.
- `developerMode: false` в production; `resources.requests` = `limits` для контейнера Scylla (CPU pinning).
- Изменяйте кластер только через CR — ручные правки operator-managed ресурсов откатываются.
- Backup: задавайте `retention` и `rateLimit`; регулярно тестируйте restore через `sctool`.

```bash
# Очистка: Helm не удаляет CRD — удалить вручную после uninstall
helm uninstall scylla-operator -n scylla-operator
kubectl delete crd scyllaclusters.scylla.scylladb.com nodeconfigs.scylla.scylladb.com \
  scyllaoperatorconfigs.scylla.scylladb.com scylladbmonitorings.scylla.scylladb.com
```

---

## См. также
- **[Установка и настройка](./installation.md)** — Docker Compose, bare-metal (Cassandra и ScyllaDB), cassandra.yaml.
- **[Обзор и моделирование данных](./overview.md)** — архитектура, Primary Key, типы данных.
- **[Мониторинг и observability](./monitoring.md)** — метрики, Prometheus endpoint 9180.
- **[Бэкап и восстановление](./backup-recovery.md)** — снапшоты, PITR, ScyllaDB Manager, Medusa, restore.
- **[Обслуживание и эксплуатация](./operations.md)** — Repair, Compaction.
- **[Поиск и устранение неисправностей](./troubleshooting.md)** — ошибки CQL.
- **[Безопасность](./security.md)** — TLS, аутентификация, RBAC.
