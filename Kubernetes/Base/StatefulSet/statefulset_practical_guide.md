# StatefulSet: Практическое руководство

## Определения

**StatefulSet: Практическое руководство** — прикладной справочник по развертыванию, настройке и эксплуатации контроллера StatefulSet в кластере Kubernetes. Руководство содержит пошаговые сценарии использования механизмов стабильной идентификации, управления состоянием и решения эксплуатационных задач.

Теоретическую базу и описание механизмов работы см. в разделах **[StatefulSet: Обзор](./statefulset_overview.md)** и **[Ключевые концепции](./statefulset_core_concepts.md)**.

## Предварительные требования

1.  **Версия кластера:** сценарии используют возможности, доступные только в новых релизах: `ordinals` (GA v1.31), `persistentVolumeClaimRetentionPolicy` и метка `apps.kubernetes.io/pod-index` (GA v1.32), нативные Sidecar-контейнеры (стабильны с v1.33). Рекомендуемые стабильные релизы — **v1.35–v1.37**.
2.  **kubectl** совместимой версии с настроенным контекстом и правами на `statefulsets`, `pods`, `persistentvolumeclaims`, `services`, а также `events` и `pods/log` для диагностики.
3.  **StorageClass с динамическим провижинингом** — без него PVC из `volumeClaimTemplates` останутся `Pending`. Для сценариев расширения диска нужен класс с `allowVolumeExpansion: true`. Подробнее: [StorageClass](../../Storage/storageclass.md) и [PV и PVC](../../Storage/pv_and_pvc.md).
4.  **Headless Service** создаётся в каждом сценарии, где он требуется (`serviceName` StatefulSet должен ссылаться на него).

Проверка окружения перед началом:

```bash
kubectl version
kubectl get storageclasses
```

## Основные концепции

Для успешного выполнения практических сценариев необходимо понимание роли следующих компонентов:

*   **Headless Service:** Сервис без ClusterIP, отвечающий за создание индивидуальных DNS-записей для каждого пода через механизм `endpoints`.
*   **PersistentVolumeClaim (PVC):** Декларативный запрос на выделение диска. В StatefulSet PVC генерируются автоматически для каждого индекса пода через шаблон `volumeClaimTemplates`.
*   **Идентификация:** Каждый под получает стабильное имя формата `название-sts-индекс` и FQDN (Fully Qualified Domain Name) формата `имя-пода.имя-сервиса.namespace.svc.cluster.local`.
*   **ControllerRevision:** объект-снапшот шаблона на каждое изменение спецификации — история ревизий для отслеживания и отката. Механизм разобран в **[Ключевых концепциях](./statefulset_core_concepts.md)**.

Подробнее о сетевом взаимодействии: **[Headless Service](../../Networking/Service/service_type_headless.md)**.

## Практические сценарии

### Сценарий 1: Развертывание кластерного веб-сервера (Nginx)

Цель: запустить группу подов, где каждый экземпляр имеет собственную страницу `index.html` и настроенную политику удержания дисков.

#### Шаг 1: Создание сетевой инфраструктуры (Headless Service)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-headless
spec:
  clusterIP: None
  selector:
    app: nginx-stateful
  ports:
  - port: 80
    name: web
```

#### Шаг 2: Создание контроллера StatefulSet (v1.32+)

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web-app
spec:
  serviceName: "nginx-headless"
  replicas: 3
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain  # Сохранить данные при удалении StatefulSet
    whenScaled: Delete   # Удалить диск при уменьшении реплик (Scale down)
  selector:
    matchLabels:
      app: nginx-stateful
  template:
    metadata:
      labels:
        app: nginx-stateful
    spec:
      containers:
      - name: nginx
        image: nginx:1.27
        volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
```

#### Шаг 3: Проверка персистентности данных

```bash
# 1. Запись данных в первый под
kubectl exec web-app-0 -- sh -c 'echo "Pod 0 Data" > /usr/share/nginx/html/index.html'

# 2. Удаление пода
kubectl delete pod web-app-0
# → pod "web-app-0" deleted

# 3. Наблюдение за восстановлением
kubectl get pods -w -l app=nginx-stateful
# → web-app-0   0/1     Pending             0          0s
# → web-app-0   0/1     ContainerCreating   0          1s
# → web-app-0   1/1     Running             0          5s

# 4. Проверка данных
kubectl exec web-app-0 -- cat /usr/share/nginx/html/index.html
# → Pod 0 Data
```

Контроллер пересоздал под с тем же именем `web-app-0` и подключил к нему **прежний PVC** `data-web-app-0`, поэтому данные сохранились. Проверить привязку дисков можно командой:

```bash
kubectl get pvc -l app=nginx-stateful
# → NAME             STATUS   VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → data-web-app-0   Bound    pvc-8f…  1Gi        RWO            local-path      3m
# → data-web-app-1   Bound    pvc-91…  1Gi        RWO            local-path      3m
# → data-web-app-2   Bound    pvc-a3…  1Gi        RWO            local-path      3m
```

> Примечание: `-l app=nginx-stateful` срабатывает, потому что PVC, созданные через `volumeClaimTemplates`, наследуют метки шаблона пода.

---

### Сценарий 2: Развертывание базы данных MySQL (Best Practices)

Использование секретов для паролей, выделенных лимитов ресурсов и Headless Service, на который ссылается `serviceName`.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: mysql
spec:
  clusterIP: None
  selector:
    app: mysql
  ports:
  - port: 3306
    name: mysql
---
apiVersion: v1
kind: Secret
metadata:
  name: mysql-pass
stringData:
  password: "super-strong-password"
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mysql
spec:
  selector:
    matchLabels:
      app: mysql
  serviceName: "mysql"
  replicas: 3
  template:
    metadata:
      labels:
        app: mysql
    spec:
      containers:
      - name: mysql
        image: mysql:8.0
        env:
        - name: MYSQL_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-pass
              key: password
        ports:
        - containerPort: 3306
        startupProbe:
          tcpSocket:
            port: 3306
          initialDelaySeconds: 15
          periodSeconds: 10
          failureThreshold: 30   # окно до 5 минут на старт после сбоя
        readinessProbe:
          exec:
            command: ["sh", "-c", "mysqladmin ping -h 127.0.0.1 -uroot -p$MYSQL_ROOT_PASSWORD"]
          initialDelaySeconds: 10
          periodSeconds: 5
        livenessProbe:
          tcpSocket:
            port: 3306
          failureThreshold: 6
          periodSeconds: 10
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "1"
            memory: "2Gi"
        volumeMounts:
        - name: data
          mountPath: /var/lib/mysql
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

Пояснения к сценарию:

*   **Startup Probe** нужна потому, что MySQL после сбоя долго восстанавливается (InnoDB recovery): пока проба не пройдена, liveness/readiness не выполняются, и контроллер не убивает под. Детали настройки проб — [Пробы (Probes)](../probes.md).
*   **QoS-класс:** приведенный манифест задает `requests < limits` — это класс **Burstable**. Для production-БД рекомендуются равные requests/limits (класс **Guaranteed**), что исключает вытеснение пода при нехватке памяти на узле. Правила подбора — в **[Лучших практиках](./statefulset_best_practices.md)** и **[QoS и управление ресурсами](../../Scheduling/qos_limit_and_requests.md)**.
*   **Ограничение официального образа:** переменные `MYSQL_*` (включая `MYSQL_ROOT_PASSWORD`) используются только при **первичной инициализации единственного экземпляра**. Три реплики из манифеста **не образуют репликацию автоматически** — это три независимых экземпляра со своими дисками. Настройка топологии (реплика mastered-slave, GTID, группа) и операторов кластеризации описана в [MySQL — репликация](../../../Databases/MySQL/replication/overview.md), [MySQL Operator](../../../Databases/MySQL/mysql_operator.md).
*   **Секреты:** храните пароль только в объекте Secret (не в манифесте открытым текстом за пределами `stringData`). Подробнее: [Секреты](../../Base/secrets/using_secrets.md).
*   `readinessProbe` использует `mysqladmin ping`, который возвращает код 0, когда сервер жив (даже при "Access denied") — это типовой паттерн для проб MySQL.

---

### Сценарий 3: Миграция между кластерами через Ordinals

Задача: Запустить поды в новом кластере с индексов 3-5, чтобы избежать конфликтов имен при параллельной работе двух площадок.

```yaml
spec:
  replicas: 3
  ordinals:
    start: 3  # Создаст поды: web-app-3, web-app-4, web-app-5
```

```bash
kubectl apply -f statefulset.yaml
# → statefulset.apps/web-app created

kubectl get pods
# → web-app-3   1/1     Running   0          10s
# → web-app-4   1/1     Running   0          5s
# → web-app-5   1/1     Running   0          1s
```

Правила миграции через `ordinals` (GA v1.31):

1.  **Проверьте диапазоны:** диапазоны ординалов старой и новой площадок не должны пересекаться, пока обе работают параллельно (иначе DNS-имена и FQDN конфликтуют между кластерами).
2.  **Не изменяйте `start` после создания:** поды и их PVC именуются по ординалу (`data-web-app-3` и т.д.). Изменение `start` не переименовывает существующие объекты и оставит их «осиротевшими».
3.  **Валидация:** проверяйте фактический индекс через метку `apps.kubernetes.io/pod-index` (GA v1.32):
    ```bash
    kubectl get pods -L apps.kubernetes.io/pod-index,statefulset.kubernetes.io/pod-name
    # → NAME         READY   STATUS    RESTARTS   AGE   POD-INDEX   POD-NAME
    # → web-app-3    1/1     Running   0          12s   3           web-app-3
    ```
4.  **Перенос данных:** поды переезжают вместе с PVC (диск перейдет по имени). Обеспечьте перенос данных старых PVC частями — методология в **[Резервное копирование и DR](../../Operations/backup-strategies.md)**. Поэтапный перенос тяжелых БД: сначала индексы 3–5, затем 0–2.

---

### Сценарий 4: Нативные Sidecar-контейнеры (v1.29+, стабильно v1.33)

Для вспомогательных процессов (например, аутентифицирующего прокси или сборщика логов). Механизм: `initContainer` с `restartPolicy: Always` — бета с v1.29 (включен по умолчанию), **стабилен (GA) с v1.33**.

```yaml
spec:
  template:
    spec:
      initContainers:
      - name: auth-proxy
        image: oauth2-proxy:latest
        restartPolicy: Always  # Beta v1.29 / стабильно v1.33: работает как Sidecar
        readinessProbe:        # основной контейнер стартует только после готовности прокси
          httpGet:
            path: /ping
            port: 4180
          initialDelaySeconds: 2
```

Что важно знать при использовании в StatefulSet:

*   **Порядок запуска:** нативный sidecar стартует **до** основного контейнера и должен пройти `startupProbe`/`readinessProbe`, прежде чем запустится приложение. Для StatefulSet это означает, что реплика не станет `Ready`, пока прокси/агент не готов — упорядоченный rollout сохраняется.
*   **Порядок завершения:** при удалении/обновлении пода основные контейнеры получают `SIGTERM` первыми; sidecar завершается после них (актуально для корректного дренажа трафика в телеметрию/прокси).
*   **Ограничение:** нативные sidecar не поддерживают `preStop`/`postStart` (lifecycle hooks) — graceful shutdown настраивается через обработку `SIGTERM` в самом процессе.
*   Полный разбор жизненного цикла, QoS-учета и сравнения с классическим sidecar — в **[Sidecar Patterns в Kubernetes](../Pod/pod_sidecar_patterns.md)**.
*   Для секретов в StatefulSet с Vault-агентом примерами являются нативные sidecar-паттерны: **[Vault Agent Sidecar](../../../Vault/guides/vault_agent/sidecar_pattern.md)**.

---

### Сценарий 5: Изменение размера диска (Manual Resizing)

Поскольку `volumeClaimTemplates` иммутабельны, увеличение размера выполняется каскадной процедурой. Есть два разных метода — выбор зависит от цели.

#### Метод 5A: Увеличение размера существующих PVC (без изменения шаблона)

Если менять саму структуру шаблона не нужно, а требуется только увеличить диск:

```bash
# 1. Убедиться, что StorageClass разрешает расширение
kubectl get storageclass <class-name> -o jsonpath='{.allowVolumeExpansion}{"\n"}'
# → true

# 2. Увеличить размер PVC для каждого индекса по очереди
kubectl patch pvc data-web-app-0 -p '{"spec":{"resources":{"requests":{"storage":"2Gi"}}}}'
# → persistentvolumeclaim/data-web-app-0 patched

# 3. Перезапустить под, чтобы том был перемонтирован с новым размером
#    (расширение ФС для RWO-томов выполняется при очередном монтировании)
kubectl delete pod web-app-0
# → pod "web-app-0" deleted (контроллер пересоздаст под с тем же PVC)

# 4. Проверка нового размера
kubectl get pvc data-web-app-0
# → NAME             STATUS   VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → data-web-app-0   Bound    pvc-8f…  2Gi        RWO            local-path      6m
```

> Некоторые CSI-драйверы поддерживают **онлайн-расширение** (ФС растет без перезапуска пода). Тогда достаточно шага 2 и проверки через `df -h` внутри контейнера. Для RWO-томов перезапуск пода — безопасный универсальный путь.

#### Метод 5B: Изменение `volumeClaimTemplates` (структурные изменения)

Применяется, когда нужно изменить сам шаблон (например, **класс хранения** или будущий размер для новых реплик). Существующие PVC и их PV при этом **не** пересоздаются — для них всё равно потребуется метод 5A.

1.  **Обновите PVC напрямую** (размер; если StorageClass поддерживает `allowVolumeExpansion`):
    ```bash
    kubectl patch pvc data-web-app-0 -p '{"spec":{"resources":{"requests":{"storage":"2Gi"}}}}'
    # → persistentvolumeclaim/data-web-app-0 patched
    ```
2.  **Удалите StatefulSet без удаления подов** (Cascade Orphan):
    ```bash
    kubectl delete statefulset web-app --cascade=orphan
    # → statefulset.apps "web-app" deleted (поды остались работать)
    ```
3.  **Обновите YAML** (замените `1Gi` на `2Gi` в `volumeClaimTemplates`) и примените:
    ```bash
    kubectl apply -f statefulset.yaml
    # → statefulset.apps/web-app created
    ```
    Контроллер «усыновит» существующие поды и PVC с новыми параметрами.

4.  При GitOps-подходе оба метода требуют, чтобы изменения были зафиксированы в репозитории (манифест + политики), а ручные `kubectl patch/delete` — исключение, а не норма. Подробнее о правилах роли StatefulSet в GitOps: [GitOps для workload](../../../GitOps/ArgoCD/argocd_overview.md).

---

### Сценарий 6: Валидация StatefulSet перед выкатом в production (SRE-чеклист)

Типовой набор проверок перед переводом workload в production или перед миграцией (смена StorageClass, апгрейд кластера). Полные *рекомендации* (формулы PDB, анти-аффинити, метрики) — в **[Лучших практиках](./statefulset_best_practices.md)**; здесь — только исполняемые проверки.

```bash
# 1. StorageClass: динамический провижининг, WaitForFirstConsumer, расширение
kubectl get storageclass <class> -o custom-columns=NAME:.metadata.name,PROVISIONER:.provisioner,BINDING:.volumeBindingMode,EXPAND:.allowVolumeExpansion

# 2. PDB существует, и его бюджет не ниже кворума (N/2+1 для нечетного N)
kubectl get pdb
kubectl get pdb <pdb-name> -o jsonpath='{.spec.minAvailable}{" "}{.status.desiredHealthy}{"\n"}'

# 3. Пробы и ресурсы заданы для всех контейнеров шаблона
kubectl get statefulset <name> -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{": probe="}{.startupProbe}{"; "}{end}{"\n"}'

# 4. Все PVC Bound и нужного размера
kubectl get pvc -l app=<selector>
kubectl get pvc -l app=<selector> -o jsonpath='{range .items[*]}{.metadata.name}{" → "}{.status.capacity.storage}{"\n"}{end}'

# 5. Все реплики Ready, rollout завершен
kubectl rollout status statefulset/<name> --timeout=5m
kubectl get pods -L statefulset.kubernetes.io/pod-name,apps.kubernetes.io/pod-index

# 6. Нет предупреждений в событиях (FailedMount, VolumeBinding, FailedScheduling)
kubectl get events --field-selector type=Warning --sort-by=.lastTimestamp
```

## Диагностика и устранение неполадок

### Проверка DNS-идентификации

Самый быстрый способ проверить работу Headless Service:
```bash
kubectl run dns-debug --image=busybox:1.36 -it --rm --restart=Never -- nslookup web-app-0.nginx-headless
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      web-app-0.nginx-headless.default.svc.cluster.local
# → Address:   10.244.1.5
```

Если A-записи нет, но Headless Service и `serviceName` настроены верно, проверьте: поды `Ready` (без `publishNotReadyAddresses` DNS публикуется только у готовых) и совпадение labels у селектора Service. SRV-записи для именованных портов и примеры `dig` (в т.ч. bootstrap до готовности) — в **[Ключевых концепциях](./statefulset_core_concepts.md)**.

### Анализ застревания в Pending

Если под не переходит в `Running`:
1.  `kubectl get pvc`: Проверьте статус `Bound`.
2.  `kubectl describe pvc <name>`: Ищите ошибки `VolumeBinding` (например, нехватка места в AZ).
3.  `kubectl describe pod <name>`: Проверьте события планировщика и анти-аффинити правил.
4.  Проверьте `volumeBindingMode` StorageClass: с `WaitForFirstConsumer` том создается только после назначения пода на узел, а с `Immediate` диск может оказаться в другой зоне, чем под (AZ mismatch) — под останется `Pending`. Подробнее: [StorageClass](../../Storage/storageclass.md).

### Безопасное принудительное удаление

Если узел упал и под «завис» в `Terminating`:
1.  **Никогда** не используйте `--force` просто так.
2.  Пометьте узел как неисправный (v1.28+):
    ```bash
    kubectl patch node <node-name> -p '{"metadata":{"labels":{"node.kubernetes.io/out-of-service":"nodeshutdown"}}}'
    ```
3.  Kubernetes безопасно отмонтирует тома и пересоздаст под на другом узле.

Тот же эффект достигается taint-ом `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute`. Механизм (в т.ч. разница label/taint и порядок восстановления узла) разобран в **[Ключевых концепциях](./statefulset_core_concepts.md)** и **[Недоступность узла: поды в Terminating](../../Troubleshooting/Common_Errors/PodTerminating/node_unavailable_issues.md)**. Force-delete (`kubectl delete pod <name> --force --grace-period=0`) допустим **только** после подтверждения `out-of-service`, иначе можно оставить том примонтированным к мертвому узлу и заблокировать PVC.

### Runbook: Типичные инциденты с StatefulSet

Пошаговые инструкции по реагированию на инциденты в production.

---

#### Инцидент 1: Под в `Terminating` на недоступном узле

**Симптом:** `kubectl get pod db-0` показывает `Terminating` или `Unknown`, узел в состоянии `NotReady`.

**Причина:** Узел упал, RWO-том привязан к нему, контроллер не может отмонтировать том.

**Действия:**

```bash
# 1. Диагностика
kubectl get nodes
kubectl get pod db-0 -o wide
kubectl describe pod db-0 | grep -A5 Events

# 2. Если узел восстановился — ждём (под вернётся сам)
kubectl get events --field-selector involvedObject.name=db-0 --watch

# 3. Если узел НЕ вернётся (аппаратная поломка, decommission):
#    Пометить узел taint (v1.28+)
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service=nodeshutdown:NoExecute

# 4. Контроллер безопасно отмонтирует том и пересоздаст под на другом узле
kubectl rollout status statefulset/<name> --timeout=300s

# 5. После восстановления узла — снять taint
kubectl taint nodes <node-name> node.kubernetes.io/out-of-service=nodeshutdown:NoExecute-

# 6. КРАЙНЯЯ МЕРА — только если узел гарантированно мёртв и данные не критичны:
kubectl delete pod db-0 --force --grace-period=0
# ⚠️ Риск: Multi-Attach и повреждение данных, если старый узел ещё пишет в диск
```

**Время реакции:** 5–30 минут (ожидание taint), до 60 минут (восстановление пода).

---

#### Инцидент 2: RollingUpdate застрял

**Симптом:** `kubectl rollout status statefulset/<name>` зависает на `waiting for X pods at revision...`.

**Причина:** Обновлённый под не становится `Ready` (плохой образ, неверный конфиг, ошибка в пробах).

**Действия:**

```bash
# 1. Определить проблемный под
kubectl get pods -l app=<name> -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}'

# 2. Проверить логи
kubectl logs <pod-name> --tail=50
kubectl describe pod <pod-name> | grep -A10 Events

# 3. Если образ плохой — откат к предыдущей ревизии
kubectl rollout undo statefulset/<name>
kubectl rollout status statefulset/<name> --timeout=180s

# 4. Если откат не помог (поды застряли на старой ревизии) — удалить проблемные поды вручную
kubectl delete pod <pod-name>
# Контроллер пересоздаст под на предыдущей (рабочей) ревизии

# 5. Если нужно «заморозить» обновление — установить partition
kubectl patch statefulset <name> -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":10}}}}'
```

**Время реакции:** 5–15 минут.

---

#### Инцидент 3: Все реплики БД не Ready (потеря кворума)

**Симптом:** `kubectl get pods -l app=postgres` показывает все поды в `NotReady` или `CrashLoopBackOff`.

**Причина:** Потеря кворума, неверный конфиг, заполненный диск, блокировки.

**Действия:**

```bash
# 1. Быстрая диагностика
kubectl get pods -l app=postgres
kubectl logs <pod-name> -c postgres --tail=100 | grep -i "error\|fatal\|panic"
kubectl exec <pod-name> -c postgres -- df -h /var/lib/postgresql/data

# 2. Если диск заполнен
kubectl exec <pod-name> -c postgres -- du -sh /var/lib/postgresql/data/pg_wal/
# Очистить WAL или расширить PVC:
kubectl patch pvc data-postgres-0 -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'

# 3. Если лидер не электирован (Patroni)
kubectl exec <pod-name> -c postgres -- patronictl list
# Если нет leader — попробовать ручное повышение:
kubectl exec <pod-name> -c postgres -- patronictl switchover --master <pod-name> --candidate <other-pod>

# 4. Если под в CrashLoopBackOff из-за конфига
kubectl get configmap <config-name> -o yaml
# Исправить конфиг, применить заново
kubectl delete pod <pod-name>  # Пересоздать с новым конфигом

# 5. Если проблема с PVC (Pending, Unbound)
kubectl get pvc -l app=postgres
kubectl describe pvc data-postgres-0
# Проверить StorageClass, пространство в кластере
```

**Время реакции:** 15–60 минут (зависит от типа проблемы).

---

#### Инцидент 4: PVC в `Pending` (нет диска)

**Симптом:** Новый под не стартует, PVC в статусе `Pending`.

**Причина:** Нет StorageClass, нет свободного места, AZ mismatch.

**Действия:**

```bash
# 1. Диагностика PVC
kubectl get pvc data-postgres-0
kubectl describe pvc data-postgres-0 | grep -A10 Events
# → "waiting for a volume to be created..."

# 2. Проверить StorageClass
kubectl get storageclass
kubectl describe storageclass <class-name>

# 3. Если нет StorageClass с динамическим провижинингом — создать
kubectl apply -f storageclass.yaml

# 4. Если нет места в кластере — проверить узлы
kubectl get nodes -o wide
kubectl describe node <node-name> | grep -A5 "Allocated resources"

# 5. Если WaitForFirstConsumer — под не может быть запланирован
# Проверить, есть ли узлы с достаточными ресурсами в нужной зоне
kubectl get nodes -l topology.kubernetes.io/zone=zone-a
```

**Время реакции:** 5–10 минут.

---

#### Инцидент 5: Высокий replication lag

**Симптом:** `pg_stat_replication_lag > 30s` или `mysql_slave_status_seconds_behind_master > 30`.

**Причина:** Высокая нагрузка на master, сеть, малый WAL sender slot.

**Действия:**

```bash
# 1. Проверить replication lag на каждой реплике
kubectl exec postgres-0 -c postgres-exporter -- curl -s http://127.0.0.1:9187/metrics | grep replication_lag

# 2. Проверить нагрузку на master
kubectl exec postgres-0 -c postgres -- psql -U postgres -c "SELECT * FROM pg_stat_activity WHERE state = 'active';"

# 3. Проверить сетевую задержку между репликами
kubectl exec postgres-1 -c postgres -- ping -c 5 postgres-0.postgres

# 4. Если lag растёт из-за тяжёлых транзакций — оптимизировать или отложить обновления

# 5. Если lag критичный (> 5 минут) — принудительная пересинхронизация
kubectl exec postgres-1 -c postgres -- psql -U postgres -c "SELECT pg_reload_conf();"
# Или перезапустить реплику
kubectl delete pod postgres-1
```

**Время реакции:** 5–15 минут.

---

#### Инцидент 6: Заполнение диска (Disk Pressure)

**Симптом:** Алерт `(1 - kubelet_volume_stats_available_bytes / kubelet_volume_stats_capacity_bytes) * 100 > 85`.

**Действия:**

```bash
# 1. Определить, какой под заполняет диск
kubectl exec <pod-name> -- df -h /var/lib/postgresql/data

# 2. Найти большие файлы
kubectl exec <pod-name> -- du -sh /var/lib/postgresql/data/* | sort -rh | head -5

# 3. Для PostgreSQL — очистка WAL
kubectl exec <pod-name> -c postgres -- psql -U postgres -c "SELECT pg_switch_wal();"
# Или удалить старые WAL (если archiving не используется)
kubectl exec <pod-name> -- find /var/lib/postgresql/data/pg_wal -name "*.backup" -delete

# 4. Расширить PVC (если StorageClass поддерживает expansion)
kubectl patch pvc data-postgres-0 -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'

# 5. Если expansion невозможен — миграция на новый PVC
#    (см. Сценарий 5 в Практическом руководстве)
```

**Время реакции:** 5–10 минут (очистка), 30–60 минут (расширение/миграция).

---

### Рекомендации

*   Всегда используйте **Startup Probes** для БД с длительным восстановлением после сбоя.
*   Никогда не храните конфиги внутри образа; используйте **ConfigMap** и монтируйте их как файлы.
*   Для production-БД согласуйте `requests == limits` (QoS **Guaranteed**) и настраивайте **PodDisruptionBudget** — формулы и примеры в [Лучших практиках](./statefulset_best_practices.md) и [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md).
*   Периодически проверяйте, что резервное копирование рассчитано на RPO/RTO и восстановление реально тестируется: [Резервное копирование и DR в Kubernetes](../../Operations/backup-strategies.md).

### Полная очистка окружения (декомиссия)

Порядок удаления критичен: сначала контроллер, потом диски, и только после проверки, что данные не нужны.

```bash
# 1. Убедиться в политике удержания PVC, чтобы не потерять данные невзначай
kubectl get statefulset web-app -o jsonpath='{.spec.persistentVolumeClaimRetentionPolicy}{"\n"}'
# → {"whenDeleted":"Retain","whenScaled":"Delete"}

# 2. Удалить StatefulSet (поды удаляются каскадно)
kubectl delete statefulset web-app
# если нужно сохранить поды работающими (например, для анализа) — используйте --cascade=orphan

# 3. Удалить PVC (вместе с ними освобождаются PV и тома — по reclaimPolicy)
kubectl delete pvc data-web-app-0 data-web-app-1 data-web-app-2

# 4. Удалить Headless Service
kubectl delete service nginx-headless

# 5. Если создавались снапшоты — удалить их отдельно
kubectl get volumesnapshot
kubectl delete volumesnapshot <name>
```

При `whenDeleted: Retain` шаг 2 не удалит диски — их удаление в шаге 3 должно быть осознанным: восстановить данные будет невозможно.

### См. также

*   **[Обзор StatefulSet](./statefulset_overview.md)** — основы и архитектура.
*   **[Ключевые концепции](./statefulset_core_concepts.md)** — детальное описание механизмов.
*   **[Лучшие практики](./statefulset_best_practices.md)** — рекомендации по настройке HA и безопасности.
*   **[Local PV vs CSI](./statefulset_local_pv_vs_csi.md)** — выбор хранилища для БД.
*   **[Exporter Sidecar](./statefulset_exporter_sidecar.md)** — мониторинг БД через Prometheus.

### Алгоритм безопасного обновления PostgreSQL

Пошаговый алгоритм обновления PostgreSQL в Kubernetes без потери данных и с минимальным даунтаймом:

1. **Canary через `partition: N-1`** — обновить только последний под (replica).
   ```bash
   kubectl patch statefulset postgres -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":2}}}}'
   kubectl set image statefulset/postgres postgres=postgres:16.3
   ```

2. **Проверить** логи, метрики, replication lag на обновленном поде.
   ```bash
   kubectl logs postgres-2 --tail=50
   kubectl exec postgres-2 -c postgres-exporter -- curl -s http://127.0.0.1:9187/metrics | grep replication_lag
   ```

3. **Снять `partition`** (установить 0) для обновления остальных.
   ```bash
   kubectl patch statefulset postgres -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'
   kubectl rollout status statefulset/postgres --timeout=300s
   ```

4. **Использовать Startup Probe** с `failureThreshold: 30` (окно ~5 минут на WAL replay), чтобы Liveness-проба не убила под во время инициализации.

5. **Задать `terminationGracePeriodSeconds: 120-300`** для сброса WAL и передачи лидерства.

6. **Использовать `preStop`-хук** для `SELECT pg_promote()` или передачи leader election.

7. **Не обновлять все поды одновременно** — `maxUnavailable > 1` нарушает кворум. Для 3 реплик безопасное значение = `1`.

Подробнее: [Лучшие практики — Сценарий: Обновление с минимальным риском](./statefulset_best_practices.md#сценарий-обновление-с-минимальным-риском-canary).

### Алгоритм миграции PostgreSQL между кластерами Kubernetes

Пошаговый алгоритм zero-downtime миграции:

1. **Подготовить новый кластер** с CloudNativePG и StorageClass.
2. **Настроить логическую репликацию** или физический базовый бэкап (pgBackRest) из старого кластера в новый.
3. **Использовать `ordinals.start`** (GA v1.31) для запуска подов с индексами 3-5 в новом кластере, избегая конфликтов DNS.
4. **Дождаться синхронизации** replication lag → 0.
5. **Переключить трафик** (обновить Service selector или DNS).
6. **Удалить старый StatefulSet** с `--cascade=orphan` (поды продолжают работать).
7. **Удалить старые PVC** после подтверждения работоспособности нового кластера.

Подробнее: [Сценарий 3: Миграция через Ordinals](#сценарий-3-миграция-между-кластерами-через-ordinals).

### Чек-лист для проверки StatefulSet перед production

Перед переводом workload в production или перед миграцией убедитесь, что:

1.  **StorageClass**: динамический провижининг, `WaitForFirstConsumer`, `allowVolumeExpansion: true`
2.  **PDB**: существует и его бюджет не ниже кворума (`minAvailable: ⌈N/2⌉`)
3.  **Пробы**: `startupProbe`, `readinessProbe`, `livenessProbe` заданы для всех контейнеров
4.  **Ресурсы**: `requests == limits` (QoS Guaranteed) для production-БД
5.  **PVC**: все в статусе `Bound` и нужного размера
6.  **Реплики**: все `Ready`, rollout завершен
7.  **NetworkPolicy**: изолирован трафик к БД (Default Deny + backend-only)
8.  **Секреты**: в Secret, не в открытом виде в манифесте
9.  **Exporter**: postgres_exporter/mysqld_exporter как sidecar, ServiceMonitor настроен
10. **Алерты**: PrometheusRule для down, replication lag, disk pressure, connections
11. **Бэкапы**: VolumeSnapshot или pgBackRest настроен и протестирован
12. **Chaos-тесты**: удаление пода, drain узла, заполнение диска — выполнены хотя бы einmal