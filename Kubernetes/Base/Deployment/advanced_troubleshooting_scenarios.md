# Продвинутые сценарии диагностики Deployment

**Актуально для:** Kubernetes 1.30–1.32+

Практическое руководство для инженеров DevOps, SRE и системных администраторов по диагностике и ликвидации сложных инцидентов развертывания Deployment в Kubernetes. Включает детальный разбор механики сбоев на уровне ядра Linux, сети, рантайма контейнеров и контроллеров кластера. Фокус на on-premise и bare-metal инсталляциях без облачных абстракций.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes v1.30+ (vanilla/kubeadm/RKE2 на bare-metal или виртуальных машинах).
- Настроенный `kubectl` с правами на просмотр и изменение ресурсов групп `apps/v1`, `core/v1`, `networking.k8s.io/v1`, `policy/v1`.
- Системный доступ к узлам кластера (SSH, права `sudo`, утилиты `crictl`, `journalctl`, `conntrack`, `dmesg`, `sysctl`) для анализа инфраструктурных сбоев на уровне ОС и рантайма.
- Установленные утилиты диагностики: `jq`, `curl`, `stern`, `k9s`.
- Базовое понимание жизненного цикла [Deployment](./index.md), типовых проблем [Устранение неполадок Deployment](./troubleshooting.md) и параметров [Манифест Deployment](./deployment_manifest.md).

## 1. Определения

- **Incident (Инцидент)** — незапланированное прерывание или деградация качества работы сервиса. В контексте Deployment выражается в росте ошибок (HTTP 5xx), увеличении задержек (latency spike), недоступности сетевых эндпоинтов или блокировке процесса обновления.
- **Root Cause Analysis (RCA)** — структурированный процесс выявления первопричины сбоя, исключающий работу только со следствиями. Требует перехода от поверхностного симптома (например, `CrashLoopBackOff`) к фундаментальному системному фактору (например, переполнение таблицы conntrack или deadlock блокировок базы данных).
- **Blast Radius (Область поражения)** — доля пользователей, запросов или системных компонентов, затронутых сбоем. Контролируется стратегиями выкатки (`maxUnavailable`, `maxSurge`), канареечным разделением трафика и бюджетами доступности (`PodDisruptionBudget`).
- **Thundering Herd Problem (Проблема громоподобного стада)** — ситуация, при которой массовый одновременный старт новых реплик создает лавинообразную нагрузку на зависимые сервисы (базы данных, кэши, DNS), приводя к каскадному отказу всей цепочки.
- **Graceful Termination & Draining Lag** — временной зазор между отправкой сигнала `SIGTERM` процессу в контейнере и фактическим удалением IP-адреса пода из сетевой маршрутизации (EndpointSlice, iptables/IPVS, Ingress upstream), вызывающий потери активных клиентских соединений.
- **Deployment Rollover** — процесс наложения одного обновления на другое, когда изменение спецификации (`spec.template`) применяется до завершения предыдущего rollout.
- **PDB Deadlock** — состояние взаимной блокировки, при котором контроллер не может удалить старые реплики из-за ограничений `PodDisruptionBudget`, а новые поды не могут запуститься или стать готовыми из-за дефицита ресурсов кластера.
- **Config Drift & Stale Mount** — рассинхронизация конфигурации, при которой разные реплики приложения работают с несовместимыми версиями ConfigMap/Secret либо используют устаревшие кэшированные файлы из-за задержек синхронизации монтируемых томов.
- **cgroup v2 Memory Pressure & OOMKilled** — механизм ядра Linux по изоляции памяти контейнеров: различие между принудительным завершением процесса по сигналу `SIGKILL` (код 137 при превышении `memory.max`) и скрытой деградацией производительности через CPU throttling при работе около границы `memory.high`.
- **Multi-Attach Conflict (RWO)** — ошибка планирования и монтирования постоянного хранилища, возникающая при попытке параллельного запуска пода со статусом тома `ReadWriteOnce` на новом узле до полного освобождения диска на прежнем узле.

## 2. Архитектура и методология диагностики

### Иерархия уровней отказа

Диагностика инцидентов Deployment выполняется по модели «снизу вверх» или «сверху вниз» в зависимости от первичного триггера (алерт мониторинга либо сбой выполнения команды):

```text
[Симптом: Алерты SLO / Ошибки пользователей / Зависший rollout status]
                                  ↓
Уровень 1: Control Plane & Deployment Controller
           - Status Conditions (Progressing, Available, ReplicaFailure)
           - ObservedGeneration vs Generation
           - Распределение реплик между ReplicaSets (Desired / Current / Ready)
                                  ↓
Уровень 2: Планировщик и квоты (Scheduler & Quotas)
           - Хватает ли ресурсов на узлах (Node CPU/RAM, Affinity, Taints)
           - Ограничения ResourceQuota и LimitRange
           - Взаимодействие с PodDisruptionBudget (PDB)
                                  ↓
Уровень 3: Сеть и сервисное обнаружение (Network & Service Mesh)
           - Статус EndpointSlice и Endpoints
           - Задержка обновления iptables/IPVS и Ingress-контроллера
           - Правила NetworkPolicy (блокировка Egress/Ingress/DNS)
                                  ↓
Уровень 4: Рантайм контейнера и узел (CRI, Kubelet, OS)
           - Состояние Kubelet, PLEG, containerd gRPC сокет
           - cgroup v2 лимиты, системный OOM Killer ядра, conntrack
           - Том и CSI драйвер (Detach/Attach задержки)
                                  ↓
Уровень 5: Приложение и зависимости (Workload & Dependencies)
           - Зонды доступности (StartupProbe, LivenessProbe, ReadinessProbe)
           - Ошибки инициализации, миграции схемы БД, пулы соединений
           - Обработка сигналов SIGTERM и жизненный цикл соединений
```

### Категории инцидентов и матрица приоритетов

| Уровень инцидента | Характеристика | Примеры сценариев | Целевой MTTR |
|:---|:---|:---|:---|
| **SEV-1 (Критический)** | Полная недоступность сервиса или массовая потеря пользовательского трафика | Race Condition при Graceful Shutdown (массовый 502), каскадный отказ пула БД, Rollover со сломанной схемой | < 15 минут |
| **SEV-2 (Высокий)** | Частичная деградация, сбои при обновлении критического компонента | Циклический OOMKilled части реплик, PDB Deadlock при drain узла, изоляция CoreDNS через NetworkPolicy | < 30 минут |
| **SEV-3 (Средний)** | Зависшее обновление без немедленного влияния на продуктивный трафик | Зависание StartupProbe, ConfigMap drift (поды не подхватили конфиг), Multi-Attach конфликт RWO | < 2 часов |
| **SEV-4 (Низкий)** | Неоптимальная конфигурация, нестабильность метрик | Осцилляция реплик HPA (Flapping), мелкие предупреждения планировщика | Плановое исправление |

## 3. Практические сценарии

### Сценарий 1: Каскадный отказ при деплое (Thundering Herd и исчерпание пула соединений БД)

**Симптомы:** При выполнении RollingUpdate первые новые поды успешно переходят в статус `Running`, но после переключения трафика сервис начинает массово возвращать HTTP 500/503. Старые поды начинают падать по `ReadinessProbe`, а новые поды входят в `CrashLoopBackOff`.

**Системная диагностика:**
```bash
# 1. Проверка распределения статусов подов
kubectl get pods -l app=order-service -o wide
# → order-service-7f8d6-a1b2c   Running   0/1   CrashLoopBackOff   4   3m   10.244.2.45   node-2
# → order-service-7f8d6-d4e5f   Running   0/1   CrashLoopBackOff   4   3m   10.244.3.89   node-3
# → order-service-5c9b4-x7y8z   Running   0/1   Running            0   2d   10.244.1.12   node-1

# 2. Проверка событий пода
kubectl describe pod order-service-7f8d6-a1b2c | grep -A8 "Events:"
# → Warning  Unhealthy  2m   kubelet  Readiness probe failed: HTTP probe failed with statuscode: 503
# → Warning  BackOff    1m   kubelet  Back-off restarting failed container

# 3. Анализ логов нового пода
kubectl logs order-service-7f8d6-a1b2c --tail=50
# → FATAL: remaining connection slots are reserved for non-replication superuser connections
# → org.postgresql.util.PSQLException: FATAL: sorry, too many clients already

# 4. Проверка числа соединений на узле СУБД (PostgreSQL / PgBouncer)
sudo ss -tan state established '( dport = :5432 )' | wc -l
# → 500 (достигнут max_connections)
```

**Корневая причина:** Новая версия приложения инициализирует пул соединений с размером `pool_size: 50` на под. При `maxSurge: 50%` и 10 репликах кластер попытался открыть одновременно до 750 соединений к PostgreSQL, где лимит `max_connections` составлял 500. Новые поды исчерпали лимит базы данных, заблокировали обработку запросов старыми подами, вызвали падение их readiness-зондов и привели к каскадному отказу всего сервиса.

**Пошаговое решение и восстановление:**
```bash
# 1. Экстренная остановка лавины — заморозка выкатки и временное масштабирование сбойного RS в 0
kubectl rollout pause deployment/order-service
kubectl scale rs/order-service-7f8d6 --replicas=0
# → deployment.apps/order-service paused
# → replicaset.apps/order-service-7f8d6 scaled

# 2. Восстановление доступности старого ReplicaSet
kubectl scale rs/order-service-5c9b4 --replicas=10
# → replicaset.apps/order-service-5c9b4 scaled

# 3. Дождаться восстановления старых подов
kubectl rollout status deployment/order-service --timeout=120s
# → deployment "order-service" successfully rolled out

# 4. Системное исправление в манифесте: внедрение пулера (PgBouncer/ProxySQL) и ограничение maxSurge
kubectl patch deployment order-service --type='json' -p='[
  {"op": "replace", "path": "/spec/strategy/rollingUpdate/maxSurge", "value": 1},
  {"op": "replace", "path": "/spec/strategy/rollingUpdate/maxUnavailable", "value": 0}
]'
# → deployment.apps/order-service patched
```

**Превентивные меры:**
- Установка connection pooler на стороне инфраструктуры (PgBouncer в режиме transaction pooling).
- Жесткий расчет: `(replicas + maxSurge) * pool_size < db_max_connections - administrative_reserve`.
- Использование постепенного разогрева пула соединений (Lazy connection allocation) вместо создания всех коннектов при старте.

---

### Сценарий 2: OOMKilled цикл и cgroup v2 memory throttling (Exit Code 137)

**Симптомы:** Поды под высокой нагрузкой спонтанно перезапускаются с кодом 137. При этом графики Prometheus показывают, что использование памяти не доходило до `limits.memory`. Приложение (JVM, Node.js, Go) демонстрирует резкие всплески latency перед падением.

**Системная диагностика:**
```bash
# 1. Проверка причины завершения контейнера
kubectl get pod payment-service-86b4d57b-j2k9l -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'
# → {"containerID":"containerd://...","exitCode":137,"finishedAt":"2026-10-13T15:20:00Z","reason":"OOMKilled","startedAt":"2026-10-13T15:00:00Z"}

# 2. Проверка реальных лимитов cgroup v2 на рабочем узле
ssh node-2
crictl inspect --output json $(crictl ps --name payment-service -q) | jq '.info.runtimeSpec.linux.resources.memory'
# → { "max": 1073741824, "high": 966367641 } # 1GiB max

# 3. Анализ системных событий dmesg на узле
dmesg -T | grep -E -i "oom[-_]killer|killed process" | tail -n 5
# → [Tue Oct 13 15:20:00 2026] Memory cgroup out of memory: Killed process 384912 (java) total-vm:2458920kB, anon-rss:1048400kB, file-rss:32kB, shmem-rss:0kB oom_score_adj:998
```

**Корневая причина:** Разработчики задали JVM-опцию `-XX:MaxRAMPercentage=75.0` при `limits.memory: 1Gi`. Однако JVM учитывает только размер кучи (Heap = 768MiB). Память вне кучи (Metaspace, CodeCache, thread stacks, direct memory buffers для сетевого I/O Netty) потребовала более 300MiB. Общий объем анонимной памяти превысил лимит `memory.max` в cgroup v2 (1024MiB), и ядро Linux мгновенно послало `SIGKILL`.

**Пошаговое решение и восстановление:**
```bash
# 1. Проверка текущих настроек ресурсов
kubectl get deployment payment-service -o jsonpath='{.spec.template.spec.containers[0].resources}'
# → {"limits":{"memory":"1Gi"},"requests":{"cpu":"500m","memory":"1Gi"}}

# 2. Корректировка параметров памяти: согласование JVM Heap и cgroup limits
kubectl patch deployment payment-service --type='strategic' -p='
spec:
  template:
    spec:
      containers:
      - name: payment-service
        resources:
          limits:
            memory: "2Gi"
          requests:
            memory: "2Gi"
        env:
        - name: JAVA_TOOL_OPTIONS
          value: "-XX:MaxRAMPercentage=60.0 -XX:+ExitOnOutOfMemoryError"
'
# → deployment.apps/payment-service patched

# 3. Валидация применения новой конфигурации
kubectl rollout status deployment/payment-service --timeout=180s
# → deployment "payment-service" successfully rolled out
```

**Превентивные меры:**
- Установка `requests.memory == limits.memory` (Guaranteed Quality of Service класс) для предотвращения вытеснения по `NodeAllocatable`.
- Для JVM-стека устанавливать `MaxRAMPercentage` не более 60–65%, резервируя остаток под Metaspace, GC-структуры и DirectByteBuffers.
- Мониторинг метрики ядра: `container_memory_working_set_bytes` в отношении к `container_spec_memory_limit_bytes`.

---

### Сценарий 3: Зависший rollout из-за взаимной блокировки PodDisruptionBudget (PDB Deadlock)

**Симптомы:** При выполнении планового обслуживания узлов (`kubectl drain node-3`) параллельно запущенный rollout Deployment зависает навсегда. Команда `kubectl rollout status` блокируется на выводе `Waiting for deployment "api-gateway" rollout to finish: 2 of 4 updated replicas are available...`.

**Системная диагностика:**
```bash
# 1. Проверка состояния Deployment conditions
kubectl describe deployment api-gateway | grep -A6 "Conditions:"
# → Type           Status  Reason
# → ----           ------  ------
# → Available      True    MinimumReplicasAvailable
# → Progressing    False   ProgressDeadlineExceeded  (ReplicaSet "api-gateway-6d8f" has timed out progressing)

# 2. Проверка состояния PDB в неймспейсе
kubectl get pdb -l app=api-gateway
# → NAME              MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → api-gateway-pdb   4               N/A               0                     45d

# 3. Инспекция распределения реплик
kubectl get deployment api-gateway -o wide
# → NAME          READY   UP-TO-DATE   AVAILABLE   AGE
# → api-gateway   4/4     2            4           45d

# 4. Анализ блокировки эвикшена в событиях
kubectl get events --field-selector reason=DisruptionBudgetViolation --sort-by='.metadata.creationTimestamp' | tail -n 3
# → Warning  DisruptionBudgetViolation  pod/api-gateway-5c7a-xyz  The pod cannot be evicted because of disruption budget api-gateway-pdb
```

**Корневая причина:** Для Deployment настроено `replicas: 4`, `maxSurge: 0`, `maxUnavailable: 1`. При этом PDB требует `minAvailable: 4` (100%). При `maxSurge: 0` контроллер обязан сначала удалить 1 под старой версии, чтобы освободить место. Но PDB запрещает удаление даже 1 пода (`ALLOWED DISRUPTIONS: 0`). Дополнительно `kubectl drain` узла пытается вытеснить под и блокируется тем же PDB. Возникает классический deadlock планирования.

**Пошаговое решение и восстановление:**
```bash
# 1. Анализ текущей спецификации PDB
kubectl get pdb api-gateway-pdb -o yaml | grep -E "minAvailable|maxUnavailable"
# → minAvailable: 4

# 2. Временная корректировка PDB для разблокировки ротации (разрешение 1 недоступного пода)
kubectl patch pdb api-gateway-pdb --type='merge' -p '{"spec":{"minAvailable":null,"maxUnavailable":1}}'
# → poddisruptionbudget.policy/api-gateway-pdb patched

# 3. Разрешение ситуации в Deployment: включение временного maxSurge
kubectl patch deployment api-gateway --type='strategic' -p '
spec:
  strategy:
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
'
# → deployment.apps/api-gateway patched

# 4. Проверка разблокировки выкатки
kubectl rollout status deployment/api-gateway --timeout=120s
# → deployment "api-gateway" successfully rolled out
```

**Превентивные меры:**
- Никогда не использовать `minAvailable: 100%` или `minAvailable: N` при общем числе реплик `N`. Всегда оставлять как минимум 1 слот для ротации (`maxUnavailable: 1` или `maxUnavailable: 20%`).
- Если требуется строго `maxUnavailable: 0`, необходимо разрешать `maxSurge >= 1` и иметь запас ресурсов CPU/RAM на узлах.

---

### Сценарий 4: Сетевая изоляция и DNS-сбои (NetworkPolicy блокирует CoreDNS и conntrack)

**Симптомы:** После развертывания новой версии Deployment поды не переходят в `Ready 0/1`. Приложение сообщает об ошибках `UnknownHostException` или `i/o timeout` при обращении к внутренним службам по именам вида `auth-service.production.svc.cluster.local`. При этом IP-адрес службы пингуется.

**Системная диагностика:**
```bash
# 1. Проверка состояния проб нового пода
kubectl describe pod auth-client-7f99b9544-p9xrt | grep -A5 "Readiness"
# → Warning  Unhealthy  1m   kubelet  Readiness probe failed: Get "http://10.244.2.14:8080/health": dial tcp: lookup auth-service: i/o timeout

# 2. Запуск эфемерного отладочного контейнера для проверки резолвинга
kubectl debug -it auth-client-7f99b9544-p9xrt --image=curlimages/curl:8.10.1 --target=app -- sh
# Inside debug container:
nslookup kubernetes.default.svc.cluster.local 10.96.0.10
# → ;; communications error to 10.96.0.10#53: timed out

# 3. Инспекция активных NetworkPolicy для пода
kubectl get networkpolicy -n production -l app=auth-client
# → NAME                  POD-SELECTOR      AGE
# → default-deny-egress   app=auth-client   5m

# 4. Проверка системной таблицы conntrack на узле (sysadmin контекст)
ssh node-2 sudo conntrack -S
# → cpu=0   found=0 invalid=1244 ignore=0 insert=45112 insert_failed=0 drop=0 early_drop=0
```

**Корневая причина:** В неймспейсе была применена строгая политика безопасности `Egress: default-deny`. Инженеры разрешили исходящий трафик на порт базы данных (5432) и API (8080), но забыли явно разрешить UDP/TCP трафик на порт 53 неймспейса `kube-system` для взаимодействия с CoreDNS.

**Пошаговое решение и восстановление:**
```bash
# 1. Проверка текущей ошибочной NetworkPolicy
kubectl get networkpolicy default-deny-egress -n production -o yaml

# 2. Добавление обязательного правила Egress для CoreDNS (порт 53 UDP/TCP)
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-coredns-egress
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: auth-client
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector: {}
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
EOF
# → networkpolicy.networking.k8s.io/allow-coredns-egress created

# 3. Проверка восстановления резолвинга
kubectl rollout restart deployment/auth-client -n production
kubectl rollout status deployment/auth-client -n production --timeout=90s
# → deployment "auth-client" successfully rolled out
```

**Превентивные меры:**
- Создание кластерного шаблона NetworkPolicy по умолчанию с разрешенным egress к `k8s-app: kube-dns`.
- Настройка `NodeLocal DNSCache` в кластере для уменьшения сетевых переходов на порт 53 и защиты от сбросов conntrack.

---

### Сценарий 5: Конфликт HPA с ручным/GitOps масштабированием и осцилляция реплик (Scaling Flapping)

**Симптомы:** Количество реплик Deployment хаотично меняется каждые 1–2 минуты: скачет между 3 и 15 репликами. Происходит постоянное создание и уничтожение подов, что приводит к перегрузке планировщика и постоянным холодным стартам приложения.

**Системная диагностика:**
```bash
# 1. Мониторинг изменения числа реплик
kubectl get deployment worker-service -w
# → worker-service   3/3     3     3     10m
# → worker-service   3/12    12    3     11m
# → worker-service   12/12   12    12    12m
# → worker-service   3/3     3     3     13m

# 2. Инспекция поля managedFields в манифесте Deployment
kubectl get deployment worker-service -o json | jq '.metadata.managedFields[] | {manager: .manager, operation: .operation, time: .time, fields: .fieldsV1."f:spec"."f:replicas"}'
# → { "manager": "horizontal-pod-autoscaler", "operation": "Update", "fields": {} }
# → { "manager": "argocd-application-controller", "operation": "Update", "fields": {} }

# 3. Проверка условий HPA
kubectl describe hpa worker-service-hpa
# → Reference:                                          Deployment/worker-service
# → Metrics:                                            ( current / target )
# →   resource cpu on pods  (as a percentage of request): 88% / 60%
# → Min replicas:                                       3
# → Max replicas:                                       15
# → Events:
# →   Normal  SuccessfulRescale  2m   horizontal-pod-autoscaler  New size: 12; reason: cpu resource above target
```

**Корневая причина:** Двухфакторная проблема:
1. В манифесте Git-репозитория жестко зафиксировано `spec.replicas: 3`. Контроллер GitOps (ArgoCD / Flux) в режиме автоматической синхронизации (`selfHeal: true`) принудительно возвращает `replicas: 3`. Затем HPA видит, что 3 пода перегружены (CPU 88%), и скейлит Deployment до 12. GitOps снова перезаписывает значение на 3.
2. В самом HPA отсутствует стабилизационное окно `behavior.scaleDown.stabilizationWindowSeconds`, из-за чего при кратковременном падении нагрузки автоскейлер мгновенно схлопывает реплики.

**Пошаговое решение и восстановление:**
```bash
# 1. Удаление поля spec.replicas из целевого GitOps манифеста либо настройка ignoreDifferences
# Пример патча для исключения реплик из контроля:
kubectl patch deployment worker-service --type='json' -p='[{"op": "remove", "path": "/spec/replicas"}]' 2>/dev/null || true

# 2. Настройка продвинутого поведения HPA с окнами стабилизации (Behavior)
cat <<EOF | kubectl apply -f -
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: worker-service-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: worker-service
  minReplicas: 3
  maxReplicas: 15
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 60
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 20
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
EOF
# → horizontalpodautoscaler.autoscaling/worker-service-hpa configured
```

**Превентивные меры:**
- Никогда не фиксировать поле `spec.replicas` в манифесте Deployment при использовании HPA. Управлять количеством реплик исключительно через `minReplicas`/`maxReplicas` в манифесте HPA.
- Всегда задавать `scaleDown.stabilizationWindowSeconds: 300` (5 минут) для сглаживания микропиков.

---

### Сценарий 6: Неконсистентность конфигурации и частичное обновление (ConfigMap/Secret Drift)

**Симптомы:** Конфигурация в ConfigMap была отредактирована (`kubectl edit configmap app-config`), однако поды приложения продолжают работать со старыми параметрами. При выборочном ручном перезапуске части подов кластер переходит в состояние «раскола конфигурации»: половина подов работает по новому протоколу, половина — по старому.

**Системная диагностика:**
```bash
# 1. Проверка истории ревизий Deployment
kubectl rollout history deployment/backend-api
# → REVISION  CHANGE-CAUSE
# → 5         Update image to v2.4.0
# (Новой ревизии нет, так как spec.template Deployment не менялся)

# 2. Проверка способа монтирования ConfigMap в поде
kubectl get deployment backend-api -o jsonpath='{.spec.template.spec.containers[0].envFrom}'
# → [{"configMapRef":{"name":"app-config"}}]  # Использованы переменные окружения!

# 3. Проверка значений внутри запущенного пода
kubectl exec deployment/backend-api -- env | grep FEATURE_FLAG
# → FEATURE_FLAG=false (в ConfigMap уже выставлено true!)
```

**Корневая причина:** Переменные окружения (`env`, `envFrom`), полученные из `ConfigMap` или `Secret`, инициализируются ядром контейнера **только в момент создания процесса**. Kubernetes API не отслеживает изменения ConfigMap для автоматического триггера контроллера Deployment. Если же ConfigMap смонтирован как том (`volumeMounts`), он обновляется асинхронно через kubelet sync loop (с задержкой до 60–120 секунд), что приводит к временной рассинхронизации файлов на диске без рестарта процесса приложения.

**Пошаговое решение и восстановление:**
```bash
# Вариант А: Быстрый перезапуск подов через изменение метаданных шаблона (Ad-hoc)
kubectl rollout restart deployment/backend-api
kubectl rollout status deployment/backend-api --timeout=120s
# → deployment "backend-api" successfully rolled out

# Вариант Б: Архитектурное решение — внедрение контрольной суммы конфигурации в аннотации
# Вычисление sha256 хеша манифеста ConfigMap:
CONFIG_HASH=$(kubectl get configmap app-config -o json | jq -S .data | sha256sum | awk '{print $1}')

# Применение аннотации в spec.template:
kubectl patch deployment backend-api -p "{\"spec\":{\"template\":{\"metadata\":{\"annotations\":{\"config-hash\":\"${CONFIG_HASH}\"}}}}}"
# → deployment.apps/backend-api patched (инициирован контролируемый RollingUpdate)
```

**Превентивные меры:**
- Использование генераторов неизменяемых конфигураций Kustomize (`configMapGenerator`) с добавлением уникального хеша в имя ресурса (`app-config-7b8f9m2`). При изменении конфига генерируется новое имя, что автоматически меняет `spec.template` в Deployment и запускает чистый RollingUpdate.
- Внедрение контроллера `Reloader` (см. [Reloader Runbooks](../../ToolsUtilities/reloader/reloader_runbooks.md)) для автоматического отслеживания аннотаций `reloader.stakater.com/auto: "true"`.

---

### Сценарий 7: Rollover и пропуск промежуточных версий (Schema Evolution Breakage)

**Симптомы:** Инженер применил деплой версии v2, но через 10 секунд заметил баг и сразу применил v3. Выкатка v3 завершилась с ошибкой: новые поды v3 падают с фатальной ошибкой `DatabaseException: Column 'user_uuid' does not exist in table 'users'`. При этом откат на v1 (`kubectl rollout undo`) также не работает.

**Системная диагностика:**
```bash
# 1. Проверка истории и состояния ReplicaSets
kubectl get rs -l app=account-service
# → NAME                             DESIRED   CURRENT   READY   AGE
# → account-service-v1-6f7d8         0         0         0       5d
# → account-service-v2-5b9c4         0         0         0       3m  # Остановлен в процессе!
# → account-service-v3-8d2a1         3         3         0       2m  # CrashLoopBackOff

# 2. Анализ журнала миграций базы данных
kubectl logs -l job-name=migrate-v2
# → Error from server (NotFound): pods "migrate-v2" not found (миграция v2 не успела выполниться!)

# 3. Чтение логов пода v3
kubectl logs account-service-v3-8d2a1-q7z4m --previous
# → CRITICAL: Liquibase/Flyway failed: Precondition failed: Column 'user_uuid' required by version 3 was not created in version 2.
```

**Корневая причина:** Механика Deployment Rollover в Kubernetes оптимизирована по ресурсам: если спецификация обновляется до завершения текущего обновления, контроллер немедленно останавливает масштабирование промежуточного ReplicaSet (v2) и перенаправляет ресурсы на целевой ReplicaSet (v3). Если промежуточная версия содержала обязательный шаг двухфазной миграции схемы данных (Expand Phase), пропуск этой версии оставляет базу в несогласованном состоянии.

**Пошаговое решение и восстановление:**
```bash
# 1. Немедленная фиксация деплоя на безопасной паузе
kubectl rollout pause deployment/account-service

# 2. Ручной запуск пропущенной миграции v2
kubectl create job --from=cronjob/db-migration-template manual-migration-v2 \
  --dry-run=client -o yaml | \
  sed 's/latest/v2-migration/g' | kubectl apply -f -
kubectl wait --for=condition=complete job/manual-migration-v2 --timeout=180s
# → job.batch/manual-migration-v2 condition met

# 3. Запуск миграции v3
kubectl create job --from=cronjob/db-migration-template manual-migration-v3 \
  --dry-run=client -o yaml | \
  sed 's/latest/v3-migration/g' | kubectl apply -f -
kubectl wait --for=condition=complete job/manual-migration-v3 --timeout=180s
# → job.batch/manual-migration-v3 condition met

# 4. Снятие с паузы и продолжение rollout v3
kubectl rollout resume deployment/account-service
kubectl rollout status deployment/account-service --timeout=120s
# → deployment "account-service" successfully rolled out
```

**Превентивные меры:**
- Правило неразрывной схемы БД (Expand/Contract Pattern): любая версия кода N обязана уметь работать со схемой базы данных N-1 и N+1.
- Блокировка повторного деплоя в CI/CD пайплайнах до тех пор, пока предыдущий rollout не перешел в стабильный статус (`kubectl rollout status --timeout=600s`).

---

### Сценарий 8: Deadlock зондов готовности (StartupProbe vs LivenessProbe vs ReadinessProbe)

**Симптомы:** Тяжелое приложение (Java Spring Boot, спарсенные ML-модели, объемный локальный кэш) циклически падает на этапе инициализации. В логах пода видны множественные события перезапуска контейнера (`Restart Count: 15`), при этом само приложение не успевает даже напечатать лог успешного старта HTTP-порта.

**Системная диагностика:**
```bash
# 1. Проверка интервалов проб в спецификации пода
kubectl get deployment core-app -o jsonpath='{.spec.template.spec.containers[0].livenessProbe}' | jq .
# → { "failureThreshold": 3, "initialDelaySeconds": 15, "periodSeconds": 10, "timeoutSeconds": 2 }
# Окно на выживание: 15 + (3 - 1) * 10 = 35 секунд!

# 2. Проверка реального времени старта приложения при локальном запуске или в логах
kubectl logs core-app-79f8d-4b2c1 --previous | grep -i "started application in"
# → Started Application in 54.821 seconds (JVM running for 58.123)

# 3. Проверка событий Kubelet
kubectl describe pod core-app-79f8d-4b2c1 | grep -E "Killing|Liveness"
# → Warning  Unhealthy  1m   kubelet  Liveness probe failed: HTTP probe failed with statuscode: 503
# → Normal   Killing    1m   kubelet  Container core-app failed liveness probe, will be restarted
```

**Корневая причина:** Классическая ошибка конфигурации проб без учета фазы холодного старта. `LivenessProbe` активируется через 15 секунд после старта. Приложению требуется 55 секунд для инициализации контекста Spring и прогрева JIT. На 35-й секунде Kubelet фиксирует 3 последовательных сбоя Liveness-пробы и принудительно убивает контейнер по SIGKILL, входя в бесконечный цикл рестартов.

**Пошаговое решение и восстановление:**
```bash
# 1. Внедрение StartupProbe для изоляции холодного старта от Liveness/Readiness
kubectl patch deployment core-app --type='strategic' -p '
spec:
  template:
    spec:
      containers:
      - name: core-app
        startupProbe:
          httpGet:
            path: /actuator/health/liveness
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 10
          failureThreshold: 30
        livenessProbe:
          httpGet:
            path: /actuator/health/liveness
            port: 8080
          periodSeconds: 15
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /actuator/health/readiness
            port: 8080
          periodSeconds: 5
          failureThreshold: 2
'
# → deployment.apps/core-app patched

# Бюджет ожидания старта теперь составляет: 10 + (30 - 1) * 10 = 300 секунд (5 минут).
# При этом LivenessProbe начнет опрашиваться только ПОСЛЕ первого успеха StartupProbe!

# 2. Валидация успешного запуска
kubectl rollout status deployment/core-app --timeout=360s
# → deployment "core-app" successfully rolled out
```

**Превентивные меры:**
- Разделение ответственности зондов: `StartupProbe` — для медленной инициализации; `LivenessProbe` — только для детекции зависания потоков (deadlock); `ReadinessProbe` — для управления включением пода в Service Endpoints.
- Запрет на проверку внешних зависимостей (баз данных, очередей) внутри `LivenessProbe`. Сбой БД не должен вызывать перезапуск локального пода приложения.

---

### Сценарий 9: Race Condition при Graceful Shutdown (HTTP 502 / Connection Reset во время RollingUpdate)

**Симптомы:** Во время планового обновления Deployment под продуктивной нагрузкой на Ingress-контроллере (ingress-nginx) фиксируется всплеск ошибок `502 Bad Gateway` и `504 Gateway Time-out`. Ошибки длятся от 2 до 8 секунд и прекращаются сразу после завершения rollout.

**Системная диагностика:**
```bash
# 1. Анализ логов Ingress-контроллера во время деплоя
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail=100 | grep "502"
# → [13/Oct/2026:15:40:12 +0000] "POST /api/v1/checkout HTTP/1.1" 502 157 "-" "Mozilla/5.0" 45 0.002 [prod-web-8080] [] 10.244.3.56:8080: connect() failed (111: Connection refused) while connecting to upstream

# 2. Сравнение таймстемпов удаления пода и ошибки Ingress
kubectl get events --sort-by='.metadata.creationTimestamp' | grep -E "Killing|ScalingReplicaSet"
# → 15:40:12 Normal Killing pod/web-app-old-hash Stopping container web-app

# 3. Инспекция параметров жизненного цикла пода в Deployment
kubectl get deployment web-app -o jsonpath='{.spec.template.spec.containers[0].lifecycle}'
# → null (preStop хук не настроен!)
```

**Корневая причина:** Асинхронность архитектуры ядра Kubernetes. Когда старый под выводится из эксплуатации контроллером ReplicaSet:
1. Kubelet получает сигнал на удаление пода и **немедленно** отправляет процессу контейнера сигнал `SIGTERM`.
2. Параллельно EndpointSlice-контроллер замечает изменение и обновляет объект `EndpointSlice`.
3. Ingress-контроллеры и `kube-proxy` на узлах должны получить обновление по API Watch и перестроить таблицы маршрутизации Nginx/iptables.
Задержка распространения сетевых правил составляет от 1 до 5 секунд. Приложение, получив `SIGTERM`, мгновенно закрывает слушающий сокет (`listen socket`). Запросы, отправленные Ingress-контроллером в этот интервал времени, приходят на закрытый порт пода и получают TCP RST, превращающийся в HTTP 502 для клиента.

**Пошаговое решение и восстановление:**
```bash
# 1. Внедрение preStop хука и корректировка terminationGracePeriodSeconds
kubectl patch deployment web-app --type='strategic' -p '
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 45
      containers:
      - name: web-app
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 5"]
'
# → deployment.apps/web-app patched

# Как работает фикс:
# 1. При удалении пода Kubelet сначала вызывает preStop (sleep 5).
# 2. Процесс приложения продолжает работать и принимать запросы в течение 5 секунд.
# 3. За эти 5 секунд EndpointSlice гарантированно исключает IP пода из Ingress upstream.
# 4. По истечении 5 секунд посылается SIGTERM, приложение корректно завершает in-flight запросы.
```

**Превентивные меры:**
- Обязательное использование `preStop: exec: command: ["/bin/sh", "-c", "sleep 5"]` (или `sleep 10` для крупных кластеров) для всех HTTP/gRPC сервисов за Ingress.
- Обеспечение поддержки честного Graceful Shutdown внутри кода сервиса: ожидание завершения активных запросов при получении `SIGTERM` в пределах таймаута `terminationGracePeriodSeconds`.

---

### Сценарий 10: Multi-Attach Error с томами ReadWriteOnce (RWO) при RollingUpdate

**Симптомы:** После изменения образа или переменных окружения новый под зависает в статусе `ContainerCreating`. Приложение недоступно, старый под удален или находится в `Terminating`. В событиях пода фиксируется ошибка `Multi-Attach error for volume`.

**Системная диагностика:**
```bash
# 1. Проверка статуса подов
kubectl get pods -l app=single-worker -o wide
# → single-worker-new-hash   0/1   ContainerCreating   0   8m   <none>        node-4
# → single-worker-old-hash   1/1   Terminating         0   12m  10.244.1.80   node-1

# 2. Инспекция событий пода
kubectl describe pod single-worker-new-hash | grep -A8 "Events:"
# → Warning  FailedAttachVolume  2m   attachdetach-controller  Multi-Attach error for volume "pvc-9a8b7c" Volume is already exclusively attached to one node and can't be attached to another

# 3. Проверка объектов VolumeAttachment на уровне кластера
kubectl get volumeattachment | grep pvc-9a8b7c
# → csi-attacher-pvc-9a8b7c   csi.ceph.com   node-1   true   12m
```

**Корневая причина:** По умолчанию в Deployment используется стратегия `RollingUpdate` с параметрами `maxSurge: 25%` и `maxUnavailable: 25%`. Контроллер пытается запустить новый под параллельно со старым. Планировщик Kubernetes размещает новый под на `node-4`, в то время как старый под все еще примонтирован к `node-1`. Поскольку постоянный том (Ceph RBD, SAN iSCSI, локальный LVM) имеет режим доступа `ReadWriteOnce`, CSI-драйвер и контроллер `attachdetach-controller` блокируют подключение к двум узлам одновременно для предотвращения разрушения файловой системы.

**Пошаговое решение и восстановление:**
```bash
# 1. Экстренное исправление зависания старого пода (если процесс на узле node-1 уже завершен)
# Проверка процесса на узле node-1:
ssh node-1 "sudo crictl ps | grep single-worker" || true
# Если контейнер уже остановлен, но том не отмонтирован kubelet:
ssh node-1 "sudo umount /var/lib/kubelet/pods/*/volumes/kubernetes.io~csi/pvc-9a8b7c/mount" 2>/dev/null || true

# 2. Настройка корректной стратегии развертывания для Deployment с RWO-томами:
# Вариант 1: Использование стратегии Recreate (гарантированное удаление старого пода перед стартом нового)
kubectl patch deployment single-worker --type='strategic' -p '
spec:
  strategy:
    type: Recreate
    rollingUpdate: null
'
# → deployment.apps/single-worker patched

# Вариант 2: Если необходим RollingUpdate, строго запретить одновременный всплеск подов
kubectl patch deployment single-worker --type='strategic' -p '
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 0
      maxUnavailable: 1
'
# → deployment.apps/single-worker patched
```

**Превентивные меры:**
- Приложения, требующие монопольного дискового хранилища с сохранением состояния, следует развертывать через `StatefulSet` либо строго со стратегией `strategy.type: Recreate` в Deployment.
- Для шардированных распределенных систем хранения использовать режим `ReadWriteMany` (CephFS, NFS) там, где архитектура допускает параллельный доступ.

---

### Сценарий 11: PLEG Timeout и перегрузка рантайма containerd при массовом деплое

**Симптомы:** При одновременном запуске конвейеров CI/CD и обновлении нескольких тяжелых Deployment сразу несколько рабочих узлов переходят в статус `NotReady`. Команда `kubectl get nodes` возвращает `Ready,SchedulingDisabled` или `NotReady`. Логи Kubelet переполнены ошибками `PLEG is not healthy`.

**Системная диагностика:**
```bash
# 1. Проверка статуса узлов
kubectl get nodes -o wide
# → node-2   NotReady   worker   18m   v1.31.2   192.168.10.12   Ubuntu 24.04   containerd://1.7.23

# 2. Инспекция состояния Kubelet на проблемном узле через SSH
ssh node-2
sudo journalctl -u kubelet --since "10 min ago" --no-pager | grep -E "PLEG|runtime" | tail -n 6
# → W1013 15:50:01.123456  kubelet.go:2234] PLEG is not healthy: relist period was too long: 3m12s
# → E1013 15:50:05.654321  kubelet_node_status.go:450] Error updating node status: PLEG is not healthy

# 3. Анализ дисковой подсистемы и I/O wait на узле
iostat -xz 1 3 | grep -E "Device|nvme|sda"
# → r/s     w/s     rkB/s    wkB/s   await  %util
# → 120.0   1840.0  4500.0   95000.0 85.4   99.8%  # Диск перегружен на 100%!

# 4. Проверка параллельных операций containerd
sudo crictl stats
```

**Корневая причина:** Массовый деплой десятков подов с образами объемом более 2–3 ГБ вызвал одновременное скачивание и распаковку слоев файловой системы OverlayFS на одном дисковом накопителе. Дисковая очередь (`await > 80ms`, `%util 100%`) заблокировала системные вызовы рантайма `containerd`. Поток PLEG (Pod Lifecycle Event Generator) внутри `kubelet`, обязанный опрашивать состояние всех контейнеров каждую секунду, не смог завершить опрос в течение таймаута (180 секунд), и Kubelet объявил узел `NotReady`.

**Пошаговое решение и восстановление:**
```bash
# 1. Снижение нагрузки: временный cordoning проблемного узла для предотвращения новых задач
kubectl cordon node-2
# → node/node-2 cordoned

# 2. На узле: стабилизация containerd и принудительная очистка неиспользуемых слоев
ssh node-2
sudo systemctl restart containerd
sudo crictl rmi --prune
# → Проверка восстановления статуса PLEG в логах Kubelet:
sudo journalctl -u kubelet -f --no-pager | grep "PLEG is healthy"
# → I1013 15:55:00.123456 kubelet.go:2240] PLEG is healthy

# 3. Возврат узла в строй
kubectl uncordon node-2
# → node/node-2 uncordoned

# 4. Тюнинг kubelet конфигурации (/var/lib/kubelet/config.yaml):
# serializeImagePulls: true (запрет параллельного скачивания образов, снижает I/O нагрузку)
# imageGCHighThresholdPercent: 80
# imageGCLowThresholdPercent: 70
```

**Превентивные меры:**
- Разделение дисковых разделов: перенос `/var/lib/containerd` и `/var/lib/kubelet` на выделенные высокопроизводительные NVMe-накопители отдельно от корневой файловой системы ОС.
- Настройка локального кэширующего реестра (Registry Pull-Through Cache / Harbor) на периметре сети bare-metal кластера.
- Установка параметра `serializeImagePulls: true` в конфигурации Kubelet на узлах с медленной дисковой подсистемой.

## 4. Операции и команды: SRE Triage Matrix

Сводная матрица экстренных действий дежурного инженера при авариях развертывания Deployment:

| Симптом инцидента | Быстрая команда проверки | Что искать в выводе | Первичное стабилизирующее действие |
|:---|:---|:---|:---|
| **Rollout завис** | `kubectl describe deployment <name>` | `ProgressDeadlineExceeded` в `Conditions` | `kubectl rollout pause deployment/<name>` |
| **502 на Ingress** | `kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail=50` | `111: Connection refused` к старому IP | Добавить `preStop: sleep 5` в `spec.template` |
| **Exit Code 137** | `kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'` | `"reason": "OOMKilled"` | Увеличить `limits.memory` или JVM MaxRAM |
| **Поды Pending** | `kubectl describe pod <pod>` | `0/N nodes available: Insufficient cpu/memory` | Проверить `ResourceQuota` и распределение по нодам |
| **PDB Blocked** | `kubectl get pdb -A` | `ALLOWED DISRUPTIONS: 0` | Временно пропатчить `maxUnavailable: 1` в PDB |
| **DNS timeout** | `kubectl exec <pod> -- nslookup <svc>` | `connection timed out` | Проверить Egress правила в `NetworkPolicy` |
| **Multi-Attach** | `kubectl get volumeattachment` | Том примонтирован к другому узлу | Переключить Deployment на `strategy: Recreate` |
| **Конфликт HPA** | `kubectl get deployment <name> -o json \| jq .metadata.managedFields` | Обновления от `argocd` и `horizontal-pod-autoscaler` | Удалить `spec.replicas` из GitOps манифеста |

## 5. Типичные ошибки диагностики (Antipatterns)

При ликвидации аварий инженеры нередко совершают действия, усугубляющие масштаб инцидента:

1. **Слепое принудительное удаление подов (`kubectl delete pod --force --grace-period=0`):**
   - *Ошибка:* Принудительное удаление пода в статусе `Terminating` удаляет объект из etcd, но не завершает процесс на узле.
   - *Последствие:* Если у пода был примонтирован RWO диск или открыты транзакции в БД, возникает конфликт блокировки тома (Multi-Attach) или повреждение данных.
   - *Правильно:* Диагностировать причину зависания на узле через `crictl`, проверить `preStop` хуки и отмонтировать том штатными средствами.
2. **Экстренный откат (`kubectl rollout undo`) без проверки схемы БД:**
   - *Ошибка:* Выполнение немедленного отката кода при аварии релиза без проверки выполненных миграций базы данных.
   - *Последствие:* Если новая версия успела применить деструктивную миграцию схемы (удаление полей, переименование типов), старая версия приложения упадет при старте с фатальной ошибкой.
   - *Правильно:* Сначала заблокировать трафик / перевести сервис в maintenance, проверить совместимость базы данных и только затем откатывать ревизию.
3. **Игнорирование поля `managedFields`:**
   - *Ошибка:* Попытка исправить масштаб или аннотации Deployment императивной командой `kubectl edit` / `kubectl scale` при работающем GitOps-операторе.
   - *Последствие:* Возврат конфигурации через 30 секунд контроллером ArgoCD/Flux с повторным возникновением аварии.
   - *Правильно:* Проверять менеджера полей через `managedFields` и вносить изменения через ветку Git или флаг `ignoreDifferences`.
4. **Слепое увеличение ресурсов вместо профилирования:**
   - *Ошибка:* Увеличение CPU/RAM лимитов в 4 раза при фиксации OOMKilled или высокого CPU.
   - *Последствие:* Если в коде присутствует утечка памяти (Memory Leak) или зацикливание потоков, увеличенный под лишь дольше выходит на пик потребления, после чего роняет весь узел из-за нехватки системной памяти.
   - *Правильно:* Анализировать дампы кучи (Heap Dump), метрики Prometheus и логи ядра Linux перед изменением сайзинга.

## 6. Лучшие практики и превентивные меры (Best Practices)

- **Контракт Graceful Shutdown:**
  - Каждый веб-сервис обязан содержать хук `preStop` с задержкой от 5 до 10 секунд для компенсации задержки обновления сетевых правил.
  - Значение `terminationGracePeriodSeconds` рассчитывается по формуле: `preStop_delay + max_in_flight_request_time + 10s`.
- **Изоляция и валидация зондов (Probes Hygiene):**
  - Использовать `StartupProbe` для всех сервисов со временем старта более 15 секунд.
  - В `LivenessProbe` проверять только жизнеспособность процесса (HTTP `/healthz` или проверка PID), полностью исключая запросы в базу данных, Redis или внешние API.
  - Проверку зависимостей выносить исключительно в `ReadinessProbe`.
- **Конфигурационная безопасность:**
  - Использовать неизменяемые ConfigMap/Secret с добавлением суффикса-хеша через Kustomize или Helm.
  - Для автоматического перезапуска использовать аннотацию с SHA-256 хешем содержимого конфигурации.
- **Расчет параметров обновления:**
  - Для приложений без локального состояния: `maxSurge: 25%`, `maxUnavailable: 0` (при наличии свободных ресурсов кластера).
  - Для приложений с RWO томами: строго `maxSurge: 0`, `maxUnavailable: 1` либо `strategy.type: Recreate`.
  - Значение `progressDeadlineSeconds` должно превышать максимальное время старта всех реплик (рекомендуется не менее 600 секунд).
- **Метрики и мониторинг (Prometheus Alerts):**
  - `kube_deployment_status_replicas_unavailable > 0` (в течение 10 минут) — сигнал о зависшем rollout.
  - `rate(container_cpu_cfs_throttled_periods_total[5m]) / rate(container_cpu_cfs_periods_total[5m]) > 0.2` — жесткий троттлинг CPU.
  - `increase(kube_pod_container_status_restarts_total[15m]) > 3` — частые перезапуски контейнеров.

## 7. Дополнительная информация

### Полезные инструменты диагностики

| Инструмент | Назначение | Команда установки / запуска |
|:---|:---|:---|
| **k9s** | Терминальный UI для навигации по ресурсам, событиям и логам | `brew install derailed/k9s/k9s` |
| **stern** | Потоковый сбор логов с нескольких подов и регулярных выражений | `brew install stern` |
| **kubectl-debug** | Запуск эфемерных контейнеров с сетевыми утилитами | `kubectl debug -it <pod> --image=nicolaka/netshoot` |
| **crictl** | Управление и инспекция контейнеров на уровне узла (CRI) | Предустановлен с containerd (`/usr/local/bin/crictl`) |
| **conntrack-tools** | Анализ и сброс записей таблицы трансляции соединений Linux | `apt-get install conntrack` / `conntrack -L` |

### См. также

- [Устранение неполадок Deployment](./troubleshooting.md) — базовый алгоритм диагностики и коды завершения.
- [Продвинутые стратегии отката](./advanced_rollback_strategies.md) — техники безопасного отката ревизий и GitOps-синхронизация.
- [Манифест Deployment и лучшие практики](./deployment_manifest.md) — эталонные шаблоны и разбор полей.
- [Управление жизненным циклом Deployment](./lifecycle_management.md) — пауза, возобновление и история ревизий.
- [Production Checklist](./production_checklist.md) — предрелизный контрольный список готовности сервиса.
- [OOMKilled Pods](../../Troubleshooting/Common_Errors/oomkilled_pods.md) — глубокое руководство по устранению нехватки памяти.
- [PDB Blocking](../../Troubleshooting/Common_Errors/PodTerminating/pdb_blocking.md) — разбор тупиковых ситуаций с бюджетами доступности.
- [Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md) — детальный разбор жизненного цикла завершения подов.
- [Практические сценарии NetworkPolicy](../../Networking/Network/NetworkPolicy/practical_scenarios.md) — шаблоны изоляции сетевого трафика.
- [Диагностика сбоев Kubelet и PLEG](../../Troubleshooting/Common_Errors/NodeUnavailability/kubelet_issues.md) — траблшутинг рантайма на уровне узла.
