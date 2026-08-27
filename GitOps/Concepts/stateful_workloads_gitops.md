# Stateful-нагрузки в GitOps: базы данных и операторы

> **Актуальность (2026):** Базы данных в Kubernetes через операторов (CloudNativePG, Zalando Postgres Operator, Strimzi для Kafka) — устоявшаяся production-практика. GitOps при этом управляет конфигурацией и топологией; данные остаются вне Git, и именно на стыке этих миров возникает большинство аварий.

## Предварительные требования

| Компонент | Требование |
| :--- | :--- |
| Kubernetes | 1.28+; StorageClass с `volumeBindingMode: WaitForFirstConsumer` |
| Оператор | Под вашу СУБД: CloudNativePG / Postgres Operator (Zalando) / Strimzi / RabbitMQ Cluster Operator |
| Бэкапы | Встроенные механизмы оператора (barman/pgBackRest) или Velero — обязательно с проверенным restore |
| GitOps-агент | Argo CD v3.x / Flux v2.9.x |

## Определения

- **Stateful workload**: Нагрузка, чья идентичность и данные переживают пересоздание пода: СУБД, брокеры сообщений, системы с кворумом.
- **Operator pattern**: CRD + контроллер, кодирующий эксплуатационные знания о сервисе: репликация, failover, бэкапы, обновления версий.
- **VolumeClaimTemplates**: Шаблон PVC в StatefulSet: каждый реплика получает собственный постоянный том, переживая пересоздание пода.
- **updateStrategy** StatefulSet: `RollingUpdate` (по одному, от старшего ordinal к младшему, опционально `partition`), `OnDelete` (ручное управление), `podManagementPolicy` (`OrderedReady` по умолчанию).
- **Finalizer-каскад CR → кластер**: Удаление кастомного ресурса БД (например, `Cluster`) оператор трактует как «снести кластер базы» — самое опасное место GitOps + stateful.
- **Expand-contract миграции**: Паттерн совместимых изменений схемы: расширить схему → выкатить код → убрать старое после стабилизации. Обязателен, когда код и схема едут разными деплоями.

## Базовые концепции

### Что попадает в Git, а что нет

| В Git (декларативно) | Не в Git |
| :--- | :--- |
| Установка оператора и его настройки | Данные в PVC |
| CR топологии: инстансы, ресурсы, версия, параметры СУБД | Содержимое секретов (только ссылки/SealedSecret/ESO) |
| Расписания и цели бэкапов | Результаты failover'ов (роли primary, лейблы) |
| Пользователи/роли БД через declarative-механизмы оператора | Динамические метаданные томов |

Правило большого пальца: Git описывает **желаемую конфигурацию**, а не фактическое состояние. Все, что оператор мутирует сам (статусы, роли реплик), — кандидат в [ignoreDifferences](../ArgoCD/synchronization/ignore_differences.md).

### Главная опасность: prune и каскадные удаления

```text
git rm apps/billing/db/ && merge
        │
        ▼
Argo CD prune удаляет Cluster CR
        │
        ▼
Оператор видит deletion → финализирует: сносит STS, Pod'ы,
        │                          останавливает кластер БД
        ▼
PVC остаются (если reclaimPolicy Retain) — но кластера больше нет
```

Защиты (в порядке надежности):

1. **Запрет prune для stateful-ресурсов**: аннотация `argocd.argoproj.io/sync-options: Prune=false` на CR/STS/PVC либо `prune: false` у всего приложения баз (подробности — [удаление и очистка](../ArgoCD/argocd_deletion_and_cleanup.md)).
2. **Отдельный AppProject/Kustomization** для данных: свои права, свой sync policy, отдельное ревью.
3. **Процедурно**: любое изменение каталогов с БД проходит через ревью владельца сервиса; CODEOWNERS на пути `apps/**/db/**`.
4. Понимать `deletionPolicy` конкретного оператора (у некоторых есть «orphan»-режим: удалить CR, оставив кластер жить).

### Порядок обновлений StatefulSet

Контроллеры обновляют поды состояния по одному — от старшего ordinal к младшему, дожидаясь Ready каждого:

- **`RollingUpdate.partition: N`**: обновляются только pod'ы с ordinal ≥ N — управляемая staged-раскатка узлов состояния (сначала один тестовый узел).
- **`OnDelete`**: полный ручной контроль — норма для кворумных систем во время сложных апгрейдов.
- **Никогда `podManagementPolicy: Parallel` для кворумных систем** (Kafka/ZooKeeper/etcd): одновременный перезапуск нескольких членов = потеря кворума.

Важно: прямой `kubectl patch sts` будет **откачен оператором** при следующей реконсиляции — это классический дрейф. Staged-обновления настраиваются средствами самого оператора (шаблоны в CR), либо принимается его встроенный порядок.

### Версионные апгрейды БД

| Тип версии | Механизм | Гейт |
| :--- | :--- | :--- |
| Minor/patch (1.21.2 → 1.21.3) | Bump в CR → оператор катит rolling update | Автоматически, но после свежего бэкапа |
| Major (PostgreSQL 16 → 17) | Отдельная процедура: pg_upgrade / logical replication на новый кластер | Sync window + ручной аппрув; drill восстановления заранее |

Правило: **major-апгрейды не едут через обычный автосинк**. Либо отдельный Application с `automated: null`, либо sync window только на согласованное время.

### Drift для stateful-нагрузок

Легитимные мутации, которые надо исключить из сверки:

- Оператор меняет лейблы/аннотации подов при failover (`role=primary/replica`);
- Расширение тома пишет статус и условия в PVC;
- Контроллер добавляет finalizers и status-поля в CR.

Без `ignoreDifferences` это дает вечный OutOfSync и, хуже, попытки SelfHeal «вернуть» primary на старый под.

## Практические сценарии

### Сценарий 1: CloudNativePG кластер через Argo CD (sync waves)

```yaml
# 0. Оператор ставится раньше (wave -1, отдельный Application или wave внутри)
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: billing-db
  namespace: billing
  annotations:
    argocd.argoproj.io/sync-wave: "0"
    argocd.argoproj.io/sync-options: Prune=false   # защита от каскада!
spec:
  instances: 3
  storage:
    size: 100Gi
    storageClass: fast-ssd
  monitoring:
    enablePodMonitor: true
---
# Приложение едет следом и читает креды из auto-generated секрета
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-api
  namespace: billing
  annotations:
    argocd.argoproj.io/sync-wave: "1"
spec:
  template:
    spec:
      containers:
        - name: api
          envFrom:
            - secretRef:
                name: billing-db-app      # создан оператором CNPG
```

Проверка:

```bash
kubectl get clusters.postgresql.cnpg.io -n billing billing-db
# → NAME         AGE   INSTANCES   READY   STATUS                     PRIMARY
# → billing-db   5m    3           3       Cluster in healthy state   billing-db-1

kubectl cnpg status billing-db -n billing
# → Continuous Backup: OK   Last checkpoint: ...
```

Wave `-1 → 0 → 1` гарантирует: CRD оператора существуют до CR, кластер БД готов до приложения ([sync waves](../ArgoCD/synchronization/scenarios/sync_waves_hooks.md)).

### Сценарий 2: Безопасные миграции схемы (PreSync hook + expand-contract)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  namespace: billing
  annotations:
    argocd.argoproj.io/hook: PreSync              # ДО применения нового Deployment
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: flyway
          image: flyway/flyway:10
          args:
            - -url=jdbc:postgresql://billing-db-rw.billing.svc:5432/app
            - -connectRetries=10
            - migrate
          envFrom:
            - secretRef: {name: billing-db-migration}
```

Миграция пишется по expand-contract: шаг N добавляет колонку и пишет в обе (код совместим со старой схемой), шаг N+1 переключает чтение, шаг N+2 (через релиз) удаляет старое. Тогда откат деплоя безопасен в любой момент — старый код работает на новой схеме. Провал hook'а останавливает синхронизацию до разбора ([фазы и хуки](../ArgoCD/synchronization/scenarios/sync_waves_hooks.md)).

### Сценарий 3: Защита данных и восстановление

Расписание бэкапов — тоже Git:

```yaml
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: billing-daily
  namespace: velero
spec:
  schedule: "0 2 * * *"
  template:
    includedNamespaces: [billing]
    snapshotVolumes: true
    ttl: 720h
```

Runbook потери кластера БД (порядок фиксированный):

1. Восстановить манифесты из Git (CR вернется при синке — если был удален намеренно, сначала вернуть каталог);
2. Разобраться с данными: restore PVC из Velero snapshot **или** восстановление кластера средствами оператора из barman-бэкапа (предпочтительно: транзакционно целостнее);
3. Проверить целостность приложением-канарейкой до возврата трафика;
4. Постмортем: почему prune/delete дошел до CR — закрыть дыру в защите из раздела выше.

Drill раз в квартал: восстановление тестового кластера БД из бэкапа по таймеру — непроверенный бэкап равен отсутствующему.

### Сценарий 4: Управляемый порядок обновлений узлов Kafka (Strimzi)

Strimzi управляет StatefulSet'ами брокеров сам, но порядок и скорость регулируются через CR и шаблоны:

```bash
# Наблюдение за порядком обновления брокеров
kubectl get pods -n kafka -l strimzi.io/name=my-kafka-kafka -w
# → my-kafka-kafka-2   Terminating   ← старший ordinal первым
# → my-kafka-kafka-2   Running
# → my-kafka-kafka-1   Terminating   ← следующий только после Ready предыдущего
```

Для осторожных раскаток используйте возможности оператора (поэтапное обновление через промежуточные версии, `OnDelete`-режим с ручным перезапуском брокеров по одному):

```bash
kubectl patch kafka my-kafka -n kafka --type=merge \
  -p '{"spec":{"kafka":{"template":{"statefulset":{"podManagementPolicy":"OrderedReady"}}}}}'
```

Прямые патчи StatefulSet'ов поверх оператора — антипаттерн: контроллер вернет свои значения при следующей реконсиляции (дрейф). Все изменения порядка — только через CR оператора.

## Типовые проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| PVC висят в Terminating | Pod еще использует том / finalizer | Найти потребителя (`kubectl get pvc -A -o wide`), снять финализатор осознанно; проверить reclaimPolicy |
| Кластер БД исчез после чистки каталогов в Git | Prune удалил CR → каскад оператора | Аннотация Prune=false + отдельный проект; восстановление из бэкапа по runbook |
| Вечный OutOfSync у CR БД | Оператор мутирует status/labels при failover | ignoreDifferences на `/status` и role-лейблы |
| После апгрейда оператора CR перестал применяться | Новая схема API (CRD обновились позже/раньше) | CRD в отдельной волне/приложении; читать release notes оператора перед bump |
| Major-версия БД уехала автоматически | Автосинк применил bump образа | Major-обновления — вне автосинка: отдельный app/sync window/manual approve |
| Реплики БД собрались в одной зоне | Нет топологической привязанности | topologySpreadConstraints + zone-aware StorageClass; проверить распределение |
| Restore не проверялся никогда | Бэкапы есть, drills нет | Квартальный drill: развернуть копию из бэкапа, прогнать smoke-tests |

## Дополнительная информация

- **Связь с DR**: Git восстанавливает состояние за минуты, данные — по расписанию бэкапов; RTO/RPO планируются раздельно — см. [disaster recovery](../ArgoCD/argocd_disaster_recovery.md) и сценарий 11 [обзора Flux](../flux.md).
- **Секреты БД**: креды через ESO/SOPS/SealedSecrets, ссылки на них в CR — [управление секретами](../secrets_encryption.md).

### См. также

- [Удаление и очистка в Argo CD](../ArgoCD/argocd_deletion_and_cleanup.md) — механика prune и каскадов.
- [Sync waves и hooks](../ArgoCD/synchronization/scenarios/sync_waves_hooks.md) — упорядочивание и миграции.
- [Игнорирование полей](../ArgoCD/synchronization/ignore_differences.md) — легитимный drift операторов.
- [Мульти-кластерные паттерны](./multi_cluster_patterns.md) — различия StorageClass между кластерами флота.
