# Crossplane: Типовые аварийные паттерны (Incident Patterns)

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

## Определения

**Incident Pattern (аварийный паттерн)** — воспроизводимая последовательность «симптом → первопричина → диагностика → восстановление», описывающая характерный отказ Crossplane в эксплуатации.

**Herd Reconcile (лавинная сверка)** — явление, при котором одновременный старт/рестарт пода провайдера или снятие паузы провоцирует очередную сверку сотен Managed Resources за короткое окно, создавая пиковую нагрузку на внешнее API и kube-apiserver.

**OOMKill (Out-of-Memory Kill)** — принудительное завершение контейнера планировщиком Kubernetes при превышении `spec.containers[].resources.limits.memory`; в логах пода провайдера отсутствуют записи после остановки.

**Finalizer Deadlock** — состояние `Terminating`, при котором объект MR не удаляется, поскольку контроллер провайдера не может выполнить физическое удаление внешнего ресурса и удерживает `finalizer.managedresource.crossplane.io`.

**Пауза сверки (crossplane.io/paused)** — системная аннотация, временно отключающая reconcile конкретного ресурса; ошибочное «зависшее» состояние паузы является частой первопричиной «ржавеющих» MR после инцидентов.

**API-серверный кризис (control-plane degradation)** — деградация `kube-apiserver` / etcd управляющего кластера, вызванная ростом числа CRD/ревизий Crossplane и лавинными watch/LIST запросами провайдеров.

## Базовые концепции: классификация инцидентов

| Класс | Примеры | Критичность |
|---|---|---|
| **Состояние провайдера** | OOMKill, CrashLoopBackOff, зависший `PackagePullBackOff` | Высокая — контроллер не сверяет инфраструктуру |
| **Состояние ресурса** | Finalizer deadlock, `Synced=False` без видимой причины, «прилипшая» пауза | Высокая при удалении, средняя при сверке |
| **Состояние control plane** | etcd quota exceeded, API-server OOM/latency, CRD-взрыв | Критическая — влияет на весь кластер |
| **Каскадные эффекты** | Herd reconcile после рестарта, лавинные удаления при Git rollback | Средняя/Высокая |

## Практические сценарии и регламенты

### Сценарий 1: OOMKill пода провайдера

**Симптомы:** под провайдера периодически рестартует; MR встают в `Synced` stale на 1–5 минут; логи обрываются без ошибок.

**Диагностика:**

```bash
kubectl get pod -n crossplane-system -l pkg.crossplane.io/provider=<name>
# → NAME                              READY   STATUS             RESTARTS      AGE
# → provider-upbound-family-xyz       0/1     CrashLoopBackOff   5 (90s ago)   12m

kubectl describe pod -n crossplane-system provider-upbound-family-xyz | grep -A5 "Last State"
# →   Last State:     Terminated
# →     Reason:       OOMKilled
# →     Exit Code:    137
```

Проверка потребления и числа MR:

```bash
kubectl top pod -n crossplane-system
kubectl get managed -A | wc -l
```

**Восстановление:**

1. Временно увеличить лимит через `DeploymentRuntimeConfig`:

```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: provider-family-tuned
spec:
  deploymentTemplate:
    spec:
      template:
        spec:
          containers:
            - name: package-runtime
              resources:
                requests:
                  memory: 512Mi
                limits:
                  memory: 2Gi
```

2. Уменьшить число активных MR (разбить провайдер на микро-провайдеры, MRAP в v2) и увеличить poll interval.
3. Мониторинг: алерт на `kube_pod_container_status_restarts_total` в `crossplane-system`.

**Профилактика:** ограничивать число MR на один провайдер; не использовать монолитные family-провайдеры там, где достаточно микро-провайдеров.

### Сценарий 2: Herd Reconcile после массовой операции

**Симптомы:** пик `apiserver_request_total` и 429 на целевых системах сразу после: рестарта пода провайдера, снятия `crossplane.io/paused` у групп MR, массового `git push` с тысячи Claim.

**Диагностика:**

```bash
# Пики LIST/WATCH на Crossplane-ресурсы
kubectl get events -n crossplane-system --sort-by=.lastTimestamp | tail -20

# Throttling в логах провайдера
kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=<name> --tail=1000 | grep -i "throttl\|429"
```

**Восстановление (если API целевой системы перегружен):**

1. Включить паузу на части MR:

```bash
kubectl annotate managed -n <ns> <name> crossplane.io/paused="true" --overwrite
```

2. Постепенно снимать паузу группами по 50–100 MR с интервалом, контролируя `429` в логах провайдера.
3. Увеличить `--poll` и уменьшить `--max-reconcile-rate` в DRC.

**Профилактика:** никогда не снимать паузу у всех MR одновременно; при рестарте провайдера в пиковые часы смотреть на целевые rate limit.

### Сценарий 3: Finalizer Deadlock (MR завис в Terminating)

**Симптомы:** `kubectl delete` не удаляет MR; статус `Terminating` держится часами; финализатор в `metadata.finalizers`.

**Диагностика:**

```bash
kubectl get managed <name> -o yaml | grep -A3 finalizers
# → finalizers:
# →   - finalizer.managedresource.crossplane.io

kubectl describe managed <name> | grep -A5 Events
# → Warning  CannotDelete  ... cannot delete external resource: 403 Forbidden
```

**Восстановление (по порядку):**

1. **Внешний ресурс уже удалён вручную** — снять финализатор:

```bash
kubectl patch managed <name> --type=merge -p '{"metadata":{"finalizers":null}}'
```

2. **Нужно сохранить физический ресурс** — переключить политику удаления и удалить MR:

```bash
kubectl patch managed <name> --type=merge -p '{"spec":{"deletionPolicy":"Orphan"}}'
kubectl delete managed <name>
```

3. **Внешний ресурс жив, удаление реально требуется** — восстановить доступ (ProviderConfig секрет, сетевой путь) и дать контроллеру завершить удаление; не снимать финализатор вручную без аудита, иначе появится «сирота» во внешней системе.

**Профилактика:** критичные ресурсы — `deletionPolicy: Orphan` по умолчанию (см. [Обновление и миграция](./upgrade_migration.md), [Защита зависимостей (Usage)](./usage_protection.md)).

### Сценарий 4: «Залипшая» пауза сверки

**Симптомы:** MR не реагирует на изменения в Git; после аварии `Synced` остаётся старым; в `metadata.annotations` висит `crossplane.io/paused: "true"`.

**Диагностика:**

```bash
kubectl get managed -A -o json | jq '.items[] | select(.metadata.annotations["crossplane.io/paused"]=="true") | .metadata.name'
```

**Восстановление:**

```bash
kubectl annotate managed <name> crossplane.io/paused-
```

**Профилактика:** пауза — инструмент с обязательным TTL; после каждого инцидента в чеклист выхода включать пункт «снять все paused-аннотации».

### Сценарий 5: Деградация etcd / API-сервера (CRD-взрыв)

**Симптомы:** таймауты `LIST/WATCH` на Crossplane-ресурсы, рост размера etcd, память `kube-apiserver`, деградация всех подов кластера.

**Диагностика:**

```bash
# Размер базы etcd (приближение)
etcdctl endpoint status --write-out="table"
# → DB SIZE  4.1 GiB  (quota 8 GiB — при 50% и выше начать чистку)

# Число CRD от провайдеров
kubectl get crd | grep -cE 'crossplane|pkg\.'
kubectl get providerrevisions
```

**Восстановление:**

1. Установить/подтвердить `revisionHistoryLimit: 1` во всех `Provider`/`Function`.
2. Очистить неактивные ревизии (см. [Capacity Planning](./capacity_planning.md)).
3. При кризисе — временно деактивировать неиспользуемых провайдеров (`ProviderRevision.spec.desiredState: Inactive`).
4. Вынести тяжёлых провайдеров в отдельный управляющий кластер (шардирование control plane).

**Профилактика:** ежеквартальный аудит CRD/ревизий, MRAP в v2 для активации только нужных типов MR.

### Сценарий 6: Каскадное удаление при Git rollback

**Симптомы:** после `git revert` коммита с тысячами Claims/MR внешние ресурсы начинают удаляться; события `Delete` в логах провайдеров.

**Диагностика и остановка:**

```bash
# 1. Немедленно заморозить удаление
kubectl annotate managed <name> crossplane.io/paused="true"

# 2. Для массовой заморозки (критичный инцидент)
kubectl get managed -A -l '<label>' -o name | \
  xargs -I{} kubectl annotate {} crossplane.io/paused="true"

# 3. Переключить политику на Orphan на затронутых MR
kubectl patch managed <name> --type=merge -p '{"spec":{"deletionPolicy":"Orphan"}}'
```

**Восстановление:** вернуть коммит, дождаться сверки, затем снимать паузу группами; физически удалённое восстанавливать из резервных копий (см. [Резервное копирование и DR](./backup_dr.md)).

## Операции и команды (шпаргалка SRE)

| Задача | Команда |
|---|---|
| Все MR с ошибкой сверки | `kubectl get managed -A -o json \| jq '.items[] \| select(.status.conditions[]? \| select(.type=="Synced" and .status=="False")) \| .metadata.name'` |
| MR на паузе | `kubectl get managed -A -o json \| jq '.items[] \| select(.metadata.annotations["crossplane.io/paused"]=="true") \| .metadata.name'` |
| Принудительный reconcile | `kubectl annotate managed <name> crossplane.io/reconcile-time="$(date +%s)" --overwrite` |
| Трассировка инцидентного XR | `crossplane beta trace <kind>/<name> -n <ns>` |
| Логи провайдера с фильтром ошибок | `kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=<name> \| grep -E "ERROR\|OOM\|429\|timeout"` |
| Рестарт пода провайдера | `kubectl rollout restart deploy/<provider-deploy> -n crossplane-system` |
| Снятие финализатора (только с аудитом) | `kubectl patch managed <name> --type=merge -p '{"metadata":{"finalizers":null}}'` |

## Устранение неполадок: сводная матрица

| Симптом | Первопричина | Быстрая команда/фикс |
|---|---|---|
| Под провайдера OOMKilled | Лимит памяти < footprint при сотнях MR | Увеличить limits в DRC; разбить провайдер |
| Пики 429 на целевом API | Herd reconcile / малый poll interval | Пауза группами; увеличить poll; снизить reconcile rate |
| MR в Terminating часами | Finalizer deadlock | Аудит внешнего ресурса → Orphan или ручной снятие финализатора |
| MR не обновляется после Git | Залипшая paused-аннотация | `kubectl annotate ... crossplane.io/paused-` |
| etcd растёт, API деградирует | Накопление ревизий/CRD | `revisionHistoryLimit: 1`; чистка ревизий; MRAP |
| Удаление после rollback | `deletionPolicy: Delete` + реверт | Массовая пауза → Orphan → откат коммита |

## Лучшие практики (Best Practices)

1. **Инцидентный чеклист выхода:** снять все `paused`, проверить `Synced/Ready` MR-выборки, проверить `HEALTHY/ACTIVE` провайдеров, убрать временные финализатор-патчи.
2. **Пауза только с TTL** — записывать в инцидент, когда и кем поставлена.
3. **Ограничить blast radius:** выделенные узлы для провайдеров (nodeSelector), отдельный управляющий кластер для тяжёлых провайдеров.
4. **Тестировать rollback-сценарии** (откат коммита, откат ревизии провайдера) на staging-контуре — каскадные удаления не репетируются в проде (см. [Обновление и миграция](./upgrade_migration.md), [Тестирование платформы](./testing_crossplane.md)).
5. **Связывать с runbook:** каждый паттерн из этого файла — кандидат в корпоративный runbook с указанием владельца и дедлайна восстановления.

## Дополнительная информация

### Внутренние ссылки

* [Обновление и миграция](./upgrade_migration.md) — регламенты отката провайдеров/композиций, зависшие ревизии.
* [Capacity Planning](./capacity_planning.md) — сайзинг etcd/API, MRAP, тюнинг poll.
* [Observability](./observability.md) — метрики, алерты на рестарты, дрейф, деградацию.
* [Резервное копирование и DR](./backup_dr.md) — восстановление после каскадных удалений.
* [Защита зависимостей (Usage)](./usage_protection.md) — предотвращение каскадного удаления.

### Внешние ресурсы

* [Crossplane Troubleshooting Guide](https://docs.crossplane.io/latest/troubleshooting/) — официальные методы диагностики.
* [Kubernetes OOM debugging](https://kubernetes.io/docs/tasks/debug/debug-application-crashed/) — диагностика OOMKill подов.
