# Reloader — Runbooks и реагирование на инциденты

## Определения

**Runbook** — пошаговая инструкция по реагированию на конкретный тип инцидента, минимальизирующая время восстановления (MTTR) и исключающая зависимость от индивидуального опыта инженера. В контексте Reloader — это процедуры диагностики и устранения проблем, специфичных для контроллера автоматической перезагрузки конфигураций.

**Основной источник:** [Мониторинг и лучшие практики](./reloader_monitoring_and_best_practices.md)

---

## Основные концепции

### Структура runbook

Каждый runbook следует формату:

1. **Симптом** — что видит оператор (алерт, жалоба пользователя, метрика)
2. **Влияние** — что не работает и для кого
3. **Диагностика** — пошаговые команды для определения причины
4. **Решение** — конкретные действия по устранению
5. **Верификация** — как убедиться, что проблема решена
6. **Профилактика** — как предотвратить повторение

### Эскалация

| Уровень | Ответственный | Когда эскалировать |
| :--- | :--- | :--- |
| L1 | Дежурный SRE | Первичная диагностика, runbook не помог |
| L2 | Platform Engineer | Проблема с RBAC, ресурсами или конфигурацией контроллера |
| L3 | Vendor (Stakater) | Баг в Reloader, нестандартное поведение |

---

## Runbook 1: Reloader массово перезапускает поды

### Симптом

- Алерт `ReloaderHighReconcileRate` или `ReloaderReconcileErrors`
- Пользователи сообщают о частых перезапусках сервисов
- Метрика `reloader_success_reload_total` резко возрастает

### Влияние

Деградация или недоступность сервисов из-за постоянных Rolling Update. Риск потери данных в stateful-приложениях.

### Диагностика

```bash
# 1. Определить, какие поды перезапускаются
kubectl get events --field-selector reason=ReloaderTriggered --since=30m -A | \
  awk '{print $1, $3, $6, $7}' | sort | uniq -c | sort -rn | head -20
# → result: Показывает namespace/name с количеством перезапусков

# 2. Найти источник изменений
kubectl get events --field-selector reason=ConfigMapUpdated --since=30m -A
kubectl get events --field-selector reason=SecretUpdated --since=30m -A

# 3. Проверить логи Reloader
kubectl logs -n reloader-system -l app=reloader --since=30m | \
  grep -i "triggering" | tail -20

# 4. Проверить, нет ли внешнего агента, меняющего ConfigMap
kubectl get configmaps -A -o json | \
  jq -r '.items[] | select(.metadata.annotations["kubectl.kubernetes.io/last-applied-configuration"] != null) | .metadata.namespace, .metadata.name'
```

### Решение

**Если изменение легитимное (CI/CD пайплайн):**
```bash
# Добавить debounce к impacted Deployments
kubectl annotate deployment <name> -n <namespace> \
  deployment.reloader.stakater.com/pause-period="5m"
```

**Если изменение не легитимное (внешний агент):**
```bash
# Временно игнорировать affected resources
kubectl annotate deployment <name> -n <namespace> \
  reloader.stakater.com/ignore="true"
```

**Если шторм вызван обновлением внешнего хранилища секретов:**
```bash
# Временно отключить CSI-интеграцию
kubectl patch deployment reloader -n reloader-system -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"reloader","args":["--enable-csi-integration=false"]}]}}}}'
```

### Верификация

```bash
# Проверить, что перезапуски прекратились
kubectl get events --field-selector reason=ReloaderTriggered --since=5m -A
# → result: (пусто — нет новых перезапусков)

# Проверить стабильность подов
kubectl get pods -n <namespace> -l app=<app> --no-headers | awk '{print $3}' | sort | uniq -c
# → result: Все поды в Running
```

### Профилактика

- Всегда настраивать `pause-period` для критических сервисов
- Мониторить `reloader_success_reload_total` rate > порога
- Использовать явные аннотации вместо `auto` для production

---

## Runbook 2: Reloader не перезапускает поды при изменении ConfigMap/Secret

### Симптом

- Изменён ConfigMap/Secret, но под не перезапустился
- Пользователи жалуются, что конфигурация не подхватывается
- Приложение работает со старыми данными

### Влияние

Приложение использует устаревшую конфигурацию. Возможна деградация или security risk (старые секреты).

### Диагностика

```bash
# 1. Проверить аннотации на целевом Deployment
kubectl get deployment <name> -n <namespace> -o jsonpath='{.metadata.annotations}' | jq .
# → result: Должны присутствовать reloader.stakater.com/auto или configmap.reloader.stakater.com/reload

# 2. Проверить, видит ли Reloader изменения
kubectl logs -n reloader-system -l app=reloader --since=10m | \
  grep -i "<configmap-name-or-namespace>"
# → result: Должны быть записи о processing events

# 3. Проверить RBAC
kubectl auth can-i patch deployments \
  --as=system:serviceaccount:reloader-system:reloader \
  -n <namespace>
# → result: yes (иначе — проблема с RBAC)

# 4. Проверить namespace filtering
kubectl get deployment reloader -n reloader-system -o jsonpath='{.spec.template.spec.containers[0].args}'
# → result: Проверить --namespaces-to-select / --namespaces-to-ignore

# 5. Проверить, что ConfigMap/Secret действительно изменился
kubectl get configmap <name> -n <namespace> -o jsonpath='{.data}' | md5sum
kubectl get configmap <name> -n <namespace> -o jsonpath='{.metadata.resourceVersion}'
```

### Решение

**Если отсутствуют аннотации:**
```bash
# Добавить auto-режим
kubectl annotate deployment <name> -n <namespace> \
  reloader.stakater.com/auto="true"

# ИЛИ явное указание ресурсов
kubectl annotate deployment <name> -n <namespace> \
  configmap.reloader.stakater.com/reload="<configmap-name>"
```

**Если Reloader не видит namespace:**
```bash
# Проверить и исправить namespace filtering
kubectl get deployment reloader -n reloader-system -o jsonpath='{.spec.template.spec.containers[0].args}' | jq .

# Если namespace исключён — добавить в include
kubectl patch deployment reloader -n reloader-system -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"reloader","args":["--namespaces-to-select=prod,staging,team-alpha"]}]}}}}'
```

**Если проблема с RBAC:**
```bash
# Добавить права на patch deployments в целевом namespace
kubectl apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: reloader-role-<namespace>
  namespace: <namespace>
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "daemonsets", "statefulsets"]
    verbs: ["list", "get", "watch", "update", "patch"]
  - apiGroups: [""]
    resources: ["secrets", "configmaps"]
    verbs: ["list", "get", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: reloader-binding-<namespace>
  namespace: <namespace>
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: reloader-role-<namespace>
subjects:
  - kind: ServiceAccount
    name: reloader
    namespace: reloader-system
EOF
```

### Верификация

```bash
# Инициировать тестовое изменение
kubectl patch configmap <name> -n <namespace> \
  -p '{"data":{"test-key":"test-value-verification"}}'

# Проверить логи Reloader
kubectl logs -n reloader-system -l app=reloader --tail=10 | grep -i "triggering"
# → result: level=info msg="Triggering rolling upgrade for Deployment '<name>' in namespace '<namespace>'"

# Проверить, что под перезапустился
kubectl get pods -n <namespace> -l app=<app> --sort-by='.metadata.creationTimestamp' | tail -3
# → result: Новый под с текущим timestamp
```

---

## Runbook 3: Reloader не стартует (CrashLoopBackOff)

### Симптом

- Pod Reloader в статусе `CrashLoopBackOff` или `Error`
- Контроллер не обрабатывает события
- Алерт `ReloaderNotReady`

### Влияние

Полное отсутствие автоматической перезагрузки конфигураций. Все依赖ые приложения работают со старыми конфигами.

### Диагностика

```bash
# 1. Проверить статус пода
kubectl get pods -n reloader-system -l app=reloader -o wide
# → result: CrashLoopBackOff, Один под, restart count > 5

# 2. Проверить логи
kubectl logs -n reloader-system -l app=reloader --previous
# → result: Причина падения (image pull, RBAC, resource limits)

# 3. Проверить события
kubectl describe pod -n reloader-system -l app=reloader | tail -30

# 4. Проверить ресурсы
kubectl top pods -n reloader-system -l app=reloader

# 5. Проверить конфигурацию
kubectl get deployment reloader -n reloader-system -o yaml | grep -A20 "containers:"
```

### Решение

**ImagePullBackOff:**
```bash
# Проверить доступность реестра
kubectl get events -n reloader-system --field-selector reason=Failed | tail -5

# Создать imagePullSecret если нужно
kubectl create secret docker-registry regcred \
  --docker-server=ghcr.io \
  --docker-username=<user> \
  --docker-password=<token> \
  -n reloader-system

# Обновить Deployment
kubectl patch deployment reloader -n reloader-system -p \
  '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"regcred"}]}}}}'
```

**Недостаточно ресурсов (OOMKill):**
```bash
# Увеличить лимиты
kubectl patch deployment reloader -n reloader-system -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"reloader","resources":{"limits":{"memory":"512Mi","cpu":"500m"}}}]}}}}'
```

**Невалидная конфигурация (bad args):**
```bash
# Проверить текущие args
kubectl get deployment reloader -n reloader-system -o jsonpath='{.spec.template.spec.containers[0].args}' | jq .

# Исправить на валидные
kubectl patch deployment reloader -n reloader-system -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"reloader","args":["--reload-strategy=annotations","--log-level=info"]}]}}}}'
```

### Верификация

```bash
# Дождаться статуса Running
kubectl wait --for=condition=available deployment/reloader \
  -n reloader-system --timeout=120s
# → result: deployment.apps/reloader condition met

# Проверить health endpoints
kubectl exec -it <reloader-pod> -n reloader-system -- \
  wget -qO- http://localhost:9090/healthz
# → result: ok
```

---

## Runbook 4: Reloader и ArgoCD конфликт (OutOfSync)

### Симптом

- ArgoCD показывает приложение в статусе `OutOfSync`
- Diff показывает изменение аннотации `reloader.stakater.com/last-reloaded-from` или переменной `STAKATER_RELOADER_*`
- ArgoCD пытается откатить изменения Reloader

### Влияние

Петля синхронизации: Reloader обновляет под → ArgoCD видит diff → откатывает → Reloader обновляет снова.

### Диагностика

```bash
# 1. Проверить стратегию Reloader
kubectl get deployment reloader -n reloader-system -o jsonpath='{.spec.template.spec.containers[0].args}'
# → result: Если --reload-strategy=env-vars — это причина конфликта

# 2. Проверить ignoreDifferences в ArgoCD
kubectl get application <app-name> -n argocd -o jsonpath='{.spec.ignoreDifferences}'
# → result: Должна содержать reloader.stakater.com/last-reloaded-from

# 3. Проверить текущий diff
argocd app diff <app-name>
```

### Решение

**Переключиться на annotations strategy:**
```bash
kubectl patch deployment reloader -n reloader-system -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"reloader","args":["--reload-strategy=annotations"]}]}}}}'
```

**Добавить ignoreDifferences в ArgoCD Application:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: <app-name>
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/template/metadata/annotations/reloader.stakater.com~1last-reloaded-from
```

### Верификация

```bash
# Проверить статус ArgoCD
argocd app get <app-name> | grep -i sync
# → result: Synced

# Инициировать изменение ConfigMap и проверить
kubectl patch configmap <name> -n <namespace> -p '{"data":{"key":"new-value"}}'
sleep 30
argocd app get <app-name> | grep -i sync
# → result: Synced (не становится OutOfSync)
```

---

## Runbook 5: Высокое потребление ресурсов Reloader

### Симпptom

- Алерт `ReloaderHighCPUUsage` или `ReloaderHighMemoryUsage`
- `kubectl top pods` показывает рост потребления
- Деградация других подов из-за конкуренции за ресурсы

### Диагностика

```bash
# 1. Проверить потребление
kubectl top pods -n reloader-system -l app=reloader

# 2. Проверить количество отслеживаемых ресурсов
kubectl port-forward svc/reloader -n reloader-system 9090:9090 &
curl -s http://localhost:9090/metrics | grep reloader_watched_resources
# → result: reloader_watched_resources <число>

# 3. Проверить глубину очереди
curl -s http://localhost:9090/metrics | grep workqueue_depth
# → result: workqueue_depth <число>

# 4. Проверить количество отслеживаемых namespace
kubectl get deployment reloader -n reloader-system -o jsonpath='{.spec.template.spec.containers[0].args}'
```

### Решение

**Ограничить namespace:**
```bash
kubectl patch deployment reloader -n reloader-system -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"reloader","args":["--namespaces-to-select=production,staging"]}]}}}}'
```

**Увеличить ресурсы:**
```bash
kubectl patch deployment reloader -n reloader-system -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"reloader","resources":{"limits":{"cpu":"1000m","memory":"1Gi"},"requests":{"cpu":"500m","memory":"512Mi"}}}]}}}}'
```

**Настроить debounce:**
```bash
# Глобально через аргумент контроллера (нет such option)
# Или через аннотацию на конкретных Deployments
kubectl annotate deployment <name> -n <namespace> \
  deployment.reloader.stakater.com/pause-period="5m"
```

---

## Runbook 6: Reloader и CSI Secret Provider — секреты не отслеживаются

### Симптом

- Секреты ротируются во внешнем хранилище (Vault, AWS Secrets Manager)
- Reloader не реагирует на обновления
- Приложение работает со старыми секретами

### Диагностика

```bash
# 1. Проверить флаг CSI-интеграции
kubectl get deployment reloader -n reloader-system -o jsonpath='{.spec.template.spec.containers[0].args}' | grep csi
# → result: Должен быть --enable-csi-integration=true

# 2. Проверить SecretProviderClassPodStatus
kubectl get secretproviderclasspodstatuses -n <namespace>
# → result: Должен присутствовать статус, привязанный к поду

# 3. Проверить, что CSI-драйвер установлен
kubectl get pods -n kube-system -l app=secrets-store-csi-driver

# 4. Проверить логи CSI-драйвера
kubectl logs -n kube-system -l app=secrets-store-csi-driver --tail=20 | grep -i "sync\|rotate"
```

### Решение

**Включить CSI-интеграцию:**
```bash
kubectl patch deployment reloader -n reloader-system -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"reloader","args":["--enable-csi-integration=true"]}]}}}}'
```

**Проверить SecretProviderClass:**
```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: vault-db-creds
  namespace: <namespace>
spec:
  provider: vault
  parameters:
    vaultAddress: "https://vault.internal:8200"
    roleName: "myapp"
    objects: |
      - objectName: "db-password"
        secretPath: "secret/data/myapp/db"
        secretKey: "password"
```

### Верификация

```bash
# Ротировать секрет во внешнем хранилище
# (зависит от провайдера — Vault, AWS SM и т.д.)

# Проверить статус CSI
kubectl get secretproviderclasspodstatuses -n <namespace> -o yaml

# Проверить логи Reloader
kubectl logs -n reloader-system -l app=reloader --tail=10 | grep -i "triggering\|csi"
```

---

## Чек-лист мониторинга Reloader

| Метрика | Порог алерта | Действие |
| :--- | :--- | :--- |
| `ReloaderNotReady` | == 0 доступных реплик > 1 мин | Runbook 3 |
| `reloader_success_reload_total` rate | > 10/мин | Runbook 1 |
| `reloader_failure_reload_total` rate | > 0 за 5 мин | Runbook 2 |
| `workqueue_depth` | > 100 за 5 мин | Runbook 5 |
| `container_memory_working_set_bytes` | > 80% limit | Runbook 5 |
| `reloader_reconcile_errors_total` | > 0 за 5 мин | Runbook 2 |

---

## Дополнительная информация

### Связанные runbooks

- [Incident Response в Kubernetes](../../Security/incident_response.md) — общие процедуры реагирования
- [Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md) — корректное завершение подов
- [PDB Blocking](../../Troubleshooting/Common_Errors/PodTerminating/pdb_blocking.md) — блокировка drain из-за PDB
- [Устранение неполадок Deployment](../../Base/Deployment/troubleshooting.md) — общая диагностика Deployment
