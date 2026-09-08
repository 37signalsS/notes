# 389DS в Kubernetes: Развёртывание и администрирование

## Определения

Для понимания архитектуры развёртывания 389 Directory Server (389DS) в кластере Kubernetes используются следующие понятия:

*   **[StatefulSet](../../../Kubernetes/Base/StatefulSet/statefulset_overview.md)** — контроллер для управления инстансами с состоянием (stateful), обеспечивающий стабильные сетевые идентификаторы (hostname), персистентное хранилище и упорядоченное развёртывание/удаление подов.
*   **[Headless Service](../../../Kubernetes/Networking/Service/service_type_headless.md)** — сервис без ClusterIP, необходимый для прямой DNS-адресации подов (например, `389ds-0.389ds-headless`), что критично для работы Multi-Master репликации.
*   **[StartupProbe](../../../Kubernetes/Base/probes.md)** — механизм проверки начального запуска, предотвращающий перезапуск контейнера во время длительной инициализации базы данных или индексации.
*   **LivenessProbe** — проверка работоспособности контейнера. При провале Kubernetes перезапускает под.
*   **ReadinessProbe** — проверка готовности контейнера принимать трафик. При провале под исключается из Service endpoints.
*   **SecurityContext** — набор настроек безопасности пода/контейнера (права доступа к томам, пользователь, capabilities), обеспечивающих запуск процесса от непривилегированного пользователя (UID 389).
*   **DIT (Directory Information Tree)** — иерархическая структура данных LDAP, которая в контейнере инициализируется при первом запуске, если том `/data` пуст.
*   **Init Container** — специальный контейнер, который запускается до основного приложения и выполняет одноразовые задачи (проверка зависимостей, миграции, первоначальная настройка).
*   **ConfigMap** — объект Kubernetes для хранения несекретных конфигурационных данных (файлы `.inf`, скрипты инициализации), которые монтируются в под как файлы или переменные окружения.
*   **PodDisruptionBudget (PDB)** — объект, ограничивающий количество одновременно недоступных подов при плановых работах (обновление узлов, drain), обеспечивая доступность сервиса.
*   **Revision History Limit** — количество сохранённых ревизий StatefulSet для возможного отката (`kubectl rollout undo`).
*   **Rolling Update Strategy** — стратегия обновления подов StatefulSet (параллельная или последовательная с `partition`).
*   **Graceful Termination** — процесс корректного завершения работы пода: отправка `SIGTERM`, выполнение `preStop`-хука, ожидание завершения активных соединений LDAP в течение `terminationGracePeriodSeconds`.
*   **PersistentVolumeClaim (PVC)** — запрос на персистентное хранилище. В StatefulSet используется `volumeClaimTemplates` для автоматического создания PVC для каждого пода.
*   **StorageClass** — описание класса хранилища (провайдер, производительность, режим доступа). Определяет, как dynamically provisioned PVC создаются.

## Базовые концепции

### Архитектура развёртывания

Развёртывание 389DS в Kubernetes (актуально для версии 3.x в 2026 году) строится на следующих принципах:

1.  **Персистентность:** Все данные (конфигурация, БД, логи) хранятся в директории `/data`. Использование `PersistentVolumeClaim` (PVC) в составе `StatefulSet` гарантирует сохранение данных при перезапуске подов. Для production используется SSD/NVMe StorageClass.
2.  **Сетевая идентификация:** Каждый под получает стабильное FQDN вида `pod-name.service-name.namespace.svc.cluster.local`, которое используется для настройки соглашений о репликации (Replication Agreements).
3.  **Безопасность Non-root:** Контейнер должен запускаться от пользователя `dirsrv` (UID 389). Это требует настройки `fsGroup` в `podSecurityContext` для корректного доступа к томам.
4.  **Высокая доступность:** Минимум 2 реплики с `podAntiAffinity` для распределения по разным узлам кластера. Для плановых работ настраивается `PodDisruptionBudget`.

### Жизненный цикл пода

Понимание последовательности этапов необходимо для настройки probes и хуков:

1.  **Init Containers:** Запускаются последовательно до основного контейнера. Используются для однократных операций: проверка доступности хранилища, первоначальная конфигурация через `dsconf`, импорт LDIF.
2.  **StartupProbe:** Активна во время запуска `ns-slapd`. Если сервер не ответит за `failureThreshold * periodSeconds`, под считается Failed и перезапускается. Должна использоваться вместо длинного `initialDelaySeconds` у liveness/readiness.
3.  **LivenessProbe:** Проверяет, что процесс жив. При провале — безусловный перезапуск.
4.  **ReadinessProbe:** Определяет, готов ли сервер обслуживать запросы (порт открыт, база инициализирована). Используется Service для управления endpoints.
5.  **Shutdown:** При удалении пода Kubernetes отправляет `SIGTERM`. Сначала выполняется `preStop`-хук (например, раз регистрация из Service или завершение репликации), затем процесс должен успеть остановить `ns-slapd` за `terminationGracePeriodSeconds` (обычно 30–60 секунд).

### Управление конфигурацией

Конфигурация 389DS делится на секреты (пароли, сертификаты) и обычные данные (`.inf`-файлы, параметры `dse.ldif`). В Kubernetes рекомендуется:

*   **Секреты (Secret):** `DS_DM_PASSWORD`, сертификаты TLS, ключи.
*   **ConfigMap:** Файлы `.inf` для `dsconf` или `setup.inf`, скрипты инициализации, LDIF для начального импорта.
*   **Монтирование:** ConfigMap монтируется как read-only volume в `/data/config/init/` или `/etc/389ds/`. При этомentrypoint-скрипт контейнера автоматически обрабатывает переменные окружения и файлы инициализации.

### Выбор хранилища

LMDB критически зависит от задержек диска и объёма разделяемой памяти. Рекомендации:

*   **Диск:** SSD или NVMe с поддержкой `ReadWriteOnce` (RWO). Избегайте NFS/SMB для файлов БД.
*   **Shared Memory:** В Kubernetes `/dev/shm` по умолчанию равен 64 МБ. Для LMDB необходимо явно указать `emptyDir.medium: Memory` в `volumeMounts` или увеличить `shm_size` через `securityContext`.
*   **StorageClass:** Выбирайте StorageClass с `volumeBindingMode: WaitForFirstConsumer` для динамического provisioning на нужном узле.

### Обновление и откат

StatefulSet поддерживает два режима обновления:
*   **RollingUpdate (default):** Поды обновляются последовательно (от большего индекса к меньшему) или параллельно, в зависимости от `partition`. `partition: N` означает, что поды с индексом < N остаются старой версии, а >= N обновляются.
*   **OnDelete:** Требует ручного удаления пода для запуска новой версии.

Для отката используйте `kubectl rollout undo statefulset/389ds --to-revision=2`. Количество сохраняемых ревизий контролируется `revisionHistoryLimit`.

### Сетевая идентификация и безопасность

*   **Headless Service:** Обеспечивает стабильный DNS. Для Multi-Master каждый под должен иметь уникальное сетевое имя.
*   **PodAntiAffinity:** Распределяет поды по разным узлам, снижая риск одновременного отказа.
*   **RBAC:** Если подам требуется доступ к API Kubernetes (например, для автоматического получения сертификатов через cert-manager), создайте ServiceAccount, ClusterRole и ClusterRoleBinding с минимальными правами.

### Требования к ресурсам

В 2026 году для стабильной работы 389DS в Production рекомендуются следующие параметры:

| Ресурс | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **Память (RAM)** | от 4Gi до 8Gi | LMDB требует значительного объема для кэширования (Memory Mapped Files). Значение `DS_MEMORY_PERCENTAGE=50` позволяет серверу автоматически подстраивать кэш под лимит пода. |
| **Процессор (CPU)** | от 2 до 4 ядер | Высокая параллельность при обработке запросов и работе плагинов. |
| **Диск** | SSD/NVMe (RWO) | Критично для производительности транзакционного лога LMDB. |
| **SHM** | 2–4 ГБ | Разделяемая память для memory-mapped файлов. В контейнере настраивается через `emptyDir` или `securityContext`. |

## Практические сценарии

### Развёртывание StatefulSet (Production-Ready 2026)

Манифест ниже включает SecurityContext, probes, PDB, ConfigMap и стратегию обновления.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: 389ds
  namespace: ldap
spec:
  serviceName: 389ds-headless
  replicas: 2
  revisionHistoryLimit: 5
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 0
      maxUnavailable: 1
  selector:
    matchLabels:
      app: 389ds
  template:
    metadata:
      labels:
        app: 389ds
    spec:
      securityContext:
        fsGroup: 389
        supplementalGroups: [389]
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: 389ds
              topologyKey: kubernetes.io/hostname
      initContainers:
        - name: init-check
          image: quay.io/389ds/dirsrv:latest
          command: ["/bin/sh", "-c"]
          args:
            - |
              echo "Checking /data volume..."
              test -w /data || (echo "/data not writable"; exit 1)
              echo "Init container completed"
          volumeMounts:
            - name: data
              mountPath: /data
      containers:
        - name: 389ds
          image: quay.io/389ds/dirsrv:latest
          env:
            - name: DS_DM_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: 389ds-secrets
                  key: dm-password
            - name: DS_SUFFIX_NAME
              value: "dc=example,dc=com"
            - name: DS_MEMORY_PERCENTAGE
              value: "50"
            - name: LDAP_PW
              valueFrom:
                secretKeyRef:
                  name: 389ds-secrets
                  key: dm-password
          ports:
            - containerPort: 3389
              name: ldap
            - containerPort: 3636
              name: ldaps
            - containerPort: 9100
              name: metrics
          resources:
            requests:
              cpu: "1"
              memory: "4Gi"
            limits:
              cpu: "2"
              memory: "8Gi"
          volumeMounts:
            - name: data
              mountPath: /data
            - name: shm
              mountPath: /dev/shm
          startupProbe:
            exec:
              command: ["/usr/sbin/dsctl", "localhost", "status"]
            initialDelaySeconds: 15
            failureThreshold: 30
            periodSeconds: 10
          livenessProbe:
            tcpSocket:
              port: ldap
            initialDelaySeconds: 60
            periodSeconds: 20
            failureThreshold: 3
          readinessProbe:
            exec:
              command: ["/usr/sbin/dsctl", "localhost", "status"]
            initialDelaySeconds: 10
            periodSeconds: 10
            failureThreshold: 3
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 5 && /usr/sbin/dsctl localhost stop"]
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: "ssd-rwo"
        resources:
          requests:
            storage: 20Gi
  volumes:
    - name: shm
      emptyDir:
        medium: Memory
        sizeLimit: 4Gi
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: 389ds-pdb
  namespace: ldap
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: 389ds
```

**Валидация:**
```bash
# Проверка создания PVC и Pods
kubectl get pvc -n ldap
kubectl get pods -n ldap -w

# Проверка статуса StatefulSet
kubectl rollout status statefulset/389ds -n ldap
# → statefulset rolling rollout complete: 2 pods...

# Проверка DNS Headless
kubectl exec -n ldap 389ds-0 -- nslookup 389ds-1.389ds-headless.ldap.svc.cluster.local
# → Name: 389ds-1.389ds-headless.ldap.svc.cluster.local
# → Address: 10.x.x.x

# Проверка Working Directory и UID внутри контейнера
kubectl exec -n ldap 389ds-0 -- id -u
# → 389
```

### Init Container для предварительной проверки

Init container запускается перед основным контейнером и гарантирует, что хранилище доступно и имеет правильные права. В примере выше init container проверяет записываемость `/data`. Дополнительные сценарии:
*   Запуск `dsctl localhost status` для ожидания готовности внешней зависимости.
*   Применение LDIF-файлов из ConfigMap при первом запуске (с проверкой флага-файла на PVC).

### Настройка безопасности и TLS

В 2026 году для управления сертификатами рекомендуется использовать `cert-manager`. Сертификаты монтируются как секреты, а 389DS настраивается на их использование через `.inf` файл или `dsconf`.

**Рекомендуемый подход:**
1.  Выпуск сертификата через `cert-manager` для каждого пода (используя DNS-имя Headless-сервиса).
2.  Монтирование секрета в `/data/tls`.
3.  Настройка LDAPS через ConfigMap с `.inf`-файлом:
    ```bash
    # dsconf внутри контейнера (может выполняться init container)
    dsconf -D "cn=Directory Manager" ldap://localhost:3389 security tls set \
        --certificate-file /data/tls/tls.crt \
        --key-file /data/tls/tls.key \
        --ca-certificate-file /data/tls/ca.crt
    ```
4.  Принудительное отключение небезопасного LDAP (если требуется):
    ```bash
    dsconf -D "cn=Directory Manager" ldap://localhost:3389 config replace nsslapd-allow-anonymous-access=off
    ```

### Резервное копирование (Backup)

Для бэкапа LDAP в Kubernetes используется `CronJob`, который выполняет экспорт данных в LDIF-формат. Важно использовать ординальный индекс пода (`0, 1, ...`) вместо жёсткого имени, чтобы CronJob работал при перезапуске пода.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: 389ds-backup
  namespace: ldap
spec:
  schedule: "0 2 * * *" # Ежедневно в 02:00
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: quay.io/389ds/dirsrv:latest
            command:
            - /bin/sh
            - -c
            - |
              ORDINAL=$(hostname | awk -F'-' '{print $NF}')
              dsconf -D "cn=Directory Manager" ldap://389ds-${ORDINAL}.389ds-headless.ldap.svc:3389 \
                backend export userRoot \
                --output-file /data/backups/backup-$(date +%F).ldif
              echo "Backup completed: backup-$(date +%F).ldif"
            env:
            - name: LDAP_PW
              valueFrom:
                secretKeyRef:
                  name: 389ds-secrets
                  key: dm-password
            volumeMounts:
            - name: data
              mountPath: /data
          restartPolicy: OnFailure
          volumes:
          - name: data
            persistentVolumeClaim:
              claimName: data-389ds-0
```

**Валидация:**
```bash
# Принудительный запуск Job
kubectl create job --from=cronjob/389ds-backup manual-backup -n ldap
kubectl logs job/manual-backup -n ldap
# → Backend userRoot: Export started.
# → Backup completed: backup-2026-09-04.ldif

# Проверка наличия файла
kubectl exec -n ldap 389ds-0 -- ls -la /data/backups/
```

### Восстановление из резервной копии (Restore)

Восстановление выполняется в режиме offline: под останавливается, данные удаляются, выполняется импорт LDIF.

```bash
# 1. Масштабирование StatefulSet до 0 (остановка всех подов)
kubectl scale statefulset/389ds --replicas=0 -n ldap

# 2. Удаление данных в PVC (выполняется из отвязанного пода или через внешний контейнер)
kubectl run tmp-restore --image=quay.io/389ds/dirsrv:latest --restart=Never -n ldap --rm -it \
  --command -- sh -c "rm -rf /data/db/* /data/config/*"

# 3. Импорт LDIF (используем тот же tmp-поды или Job)
kubectl create job restore-389ds --image=quay.io/389ds/dirsrv:latest -n ldap \
  -- /bin/sh -c "sleep 10 && dsconf -D 'cn=Directory Manager' ldap://localhost:3389 backend import userRoot /data/backups/backup-2026-09-04.ldif"

# 4. Возврат реплик
kubectl scale statefulset/389ds --replicas=2 -n ldap
```

**Валидация:**
```bash
# Проверка записи после восстановления
kubectl exec -n ldap 389ds-0 -- ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -w "$(kubectl get secret 389ds-secrets -n ldap -o jsonpath='{.data.dm-password}' | base64 -d)" \
  -b "dc=example,dc=com" "(objectClass=*)"
```

### Обновление образа (Rolling Update)

Для контролируемого обновления с возможностью быстрого отката используйте `partition`:

```bash
# Обновление только подов с индексом >= 1 (389ds-1 обновится первым)
kubectl patch statefulset 389ds -n ldap -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":1}}}}'

# После успешной проверки 389ds-1 — обновление 389ds-0
kubectl patch statefulset 389ds -n ldap -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'

# Откат к предыдущей ревизии
kubectl rollout undo statefulset/389ds -n ldap
```

**Валидация:**
```bash
kubectl rollout status statefulset/389ds -n ldap
kubectl describe statefulset 389ds -n ldap | grep -A5 "UpdateStrategy"
```

### Валидация после деплоя

После создания или обновления StatefulSet выполните SRE-чеклист:

1.  **Поды в Running:** `kubectl get pods -n ldap -l app=389ds`
2.  **PVC привязаны:** `kubectl get pvc -n ldap`
3.  **Headless DNS резолвится:** `kubectl exec -n ldap 389ds-0 -- nslookup 389ds-0.389ds-headless.ldap.svc.cluster.local`
4.  **LDAP отвечает:** `kubectl exec -n ldap 389ds-0 -- ldapsearch -x -H ldap://localhost:3389 -D "cn=Directory Manager" -w "$PASS" -b "dc=example,dc=com" "(objectClass=*)"`
5.  **Replication Agreement активен (если настроено):** `kubectl exec -n ldap 389ds-0 -- dsconf localhost repl-agmt status --suffix "dc=example,dc=com" "agmt-to-ldap-01"`
6.  **Метрики доступны:** `kubectl exec -n ldap 389ds-0 -- curl -s http://localhost:9100/metrics | head`

### Статический PersistentVolume

Если кластер не поддерживает динамическое provisioning, создайте PV вручную:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: data-389ds-0
spec:
  capacity:
    storage: 20Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: "ssd-rwo"
  local:
    path: /mnt/ssd/389ds/data-389ds-0
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values:
                - k8s-worker-01
```

### NetworkPolicy

Для защиты LDAP-сервера ограничьте доступ только доверенным клиентам иnamespace.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: 389ds-allow-ldap
  namespace: ldap
spec:
  podSelector:
    matchLabels:
      app: 389ds
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              allow-ldap: "true"
        - namespaceSelector:
            matchLabels:
              team: backend
      ports:
        - protocol: TCP
          port: 3389
        - protocol: TCP
          port: 3636
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 53 # DNS
        - protocol: UDP
          port: 53
```

## Дополнительная информация

### Мониторинг

389DS 3.x включает встроенный экспортер метрик в формате Prometheus (обычно на порту 9100 или через LDAP-интерфейс).

*   **ServiceMonitor:** Используйте для интеграции с Prometheus Operator.
*   **Ключевые метрики:**
    *   `ds_connection_current_total` — текущие соединения.
    *   `ds_operation_search_total` — количество поисковых операций.
    *   `ds_backend_entry_cache_hit_ratio` — эффективность кэша (должна быть >90%).
    *   `ds_disk_usage` — использование диска.
*   **Алерты (Prometheus Rule пример):**
    ```yaml
    - alert: 389DSCacheHitRatioLow
      expr: ds_backend_entry_cache_hit_ratio < 0.85
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Low cache hit ratio on {{ $labels.instance }}"
    ```

### Логирование и аудит

*   **Access log:** Содержит `etime` (время выполнения операции), `notes=U` (неиндексированные поиски), IP клиента. По умолчанию в stdout.
*   **Errors log:** Содержит предупреждения и ошибки сервера. По умолчанию в stderr.
*   **Audit log:** Файл `/data/logs/audit` содержит детальную историю изменений. Для отправки в централизованную систему (Loki, ELK) используйте sidecar-контейнер или fluentd DaemonSet с чтением файлов из `/data/logs`.
*   **JSON-логирование:** Включается через `dsconf config replace nsslapd-accesslog-level=...` и форматирование логов.

### Устранение неполадок (Troubleshooting)

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **StartupProbe failure** | Долгая проверка БД после падения | Увеличить `failureThreshold` или `periodSeconds` в `startupProbe`. |
| **Permission denied на /data** | Неверный `fsGroup` | Убедитесь, что в `podSecurityContext` указан `fsGroup: 389`. |
| **Replication lags** | Проблемы с DNS Headless-сервиса | Проверить резолвинг: `nslookup 389ds-1.389ds-headless`. |
| **OOMKill** | Некорректный `DS_MEMORY_PERCENTAGE` или недостаток `limits.memory` | Снизить значение переменной или увеличить `limits.memory`. Убедиться, что `requests.memory == limits.memory` для QoS Guaranteed. |
| **CrashLoopBackOff** | Недостаток `shm_size` или повреждение LMDB | Увеличить `emptyDir.medium: Memory` до 4Gi. Проверить логи: `kubectl logs 389ds-0 -n ldap`. |
| **LMDB: Map failed** | Недостаточно виртуальной памяти на узле | Проверить `vm.max_map_count` на узле (должен быть > 262144). |
| **Pod stuck in Terminating** | Долгое завершение LDAP-соединений | Увеличить `terminationGracePeriodSeconds` до 60–120. Проверить, что `preStop`-хук корректно останавливает сервер. |
| **DNS resolution fails** | Корректный Headless Service, но поды не резолвятся | Проверить `kube-dns`/`CoreDNS` в namespace `kube-system`. Проверить `ndots` в `dnsConfig` пода. |
| **Backup CronJob не работает** | Жёстко задано имя пода | Использовать `$(hostname | awk -F'-' '{print $NF}')` для получения ординального номера. |

### Best Practices

1.  **QoS Guaranteed:** Всегда задавайте `requests == limits` для CPU и Memory. Это защищает пода от удаления при нехватке ресурсов и обеспечивает стабильную производительность.
2.  **PodDisruptionBudget:** Настраивайте `minAvailable: 1` для Production, чтобы предотвратить полную недоступность при drain узлов.
3.  **Revision History:** Устанавливайте `revisionHistoryLimit: 5` для возможности отката на несколько версий назад.
4.  **Rolling Update Partition:** Используйте `partition` для канареечного обновления: сначала 1 пода, затем остальные.
5.  **Graceful Shutdown:** Настраивайте `preStop`-хук и `terminationGracePeriodSeconds` для корректного завершения репликации и сохранения данных.
6.  **ConfigMap для несекретных данных:** Храните `.inf`-файлы и скрипты в ConfigMap, а не в Secret. Это упрощает аудит и версионирование.
7.  **Валидация после каждого изменения:** Автоматизируйте проверку `dsctl status`, `ldapsearch` и репликации в CI/CD пайплайне.
8.  **StorageClass:** Выбирайте StorageClass с `WaitForFirstConsumer`, чтобы PVC создавались на узле, где будет запущен под.

## См. также
*   [Обзор 389 Directory Server](../overview.md) — общие принципы и архитектура.
*   [Репликация в 389DS](../replication.md) — детальное описание механизмов Multi-Master.
*   [389DS в Docker](../docker.md) — альтернативный вариант развёртывания.
*   [StatefulSet: Обзор](../../../Kubernetes/Base/StatefulSet/statefulset_overview.md) — теория и практика контроллера StatefulSet.
*   [Пробы (Probes) в Kubernetes](../../../Kubernetes/Base/probes.md) — детальная настройка проверок здоровья.
