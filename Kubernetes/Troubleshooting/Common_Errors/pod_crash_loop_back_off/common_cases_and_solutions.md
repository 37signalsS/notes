# Состояние CrashLoopBackOff: Распространенные случаи и решения

## Определения

**Сценарии CrashLoopBackOff** — классифицированный набор типовых неисправностей, приводящих к циклическому перезапуску контейнеров, сгруппированный по технологическим доменам: конфигурация, сеть, права доступа, ресурсы и системные ограничения ядра.

**Решения (Solutions)** — проверенные методы устранения корневых причин сбоев, включающие корректировку манифестов Kubernetes, настройку системных параметров узлов или адаптацию логики инициализации приложения.

Базовые теоретические концепции и системный алгоритм диагностики представлены в разделах:
- **[Определения и концепции](./definitions_and_concepts.md)**
- **[Диагностика и пошаговый чек-лист](./diagnostics.md)**

## Основные концепции

Эффективное устранение `CrashLoopBackOff` требует понимания того, на каком этапе жизненного цикла контейнера происходит сбой. Большинство проблем локализуется в промежутке между запуском процесса (PID 1) и прохождением первой пробы готовности (Readiness Probe).

### Принципы исправления
1. **Изоляция зависимостей:** Проверка доступности внешних ресурсов (БД, API, ConfigMap) до старта основного кода.
2. **Идемпотентность и атомарность:** Обеспечение возможности безопасного повторного запуска приложения после аварийного завершения.
3. **Минимальные привилегии (Least Privilege):** Настройка контекста безопасности (`securityContext`) без избыточных прав, но с достаточным доступом к необходимым ресурсам узла.

## Практические сценарии

### Сценарий 1: Отсутствующие или некорректные конфигурации (ConfigMap/Secret)

**Симптомы:**
- Exit Code: 1.
- Логи: `file not found`, `required environment variable missing`, `failed to load config`.

**Решение:**
1. **Проверка ссылок:** Убедитесь, что все `configMapKeyRef` и `secretKeyRef` указывают на существующие объекты.
2. **Namespace:** Ресурсы конфигурации должны находиться в том же пространстве имен, что и Pod.
3. **Опечатки в путях:** При использовании `volumeMounts` проверьте соответствие `mountPath` в контейнере и физического пути, ожидаемого приложением.
4. **Hot Reload:** Если требуется горячая перезагрузка конфигурации без перезапуска пода, используйте паттерн с sidecar-контейнером (например, `stakater/reloader`) или монтируйте ConfigMap как каталог без `subPath`.

**Верификация:**
```bash
# Проверка наличия и содержимого ConfigMap
kubectl get configmap app-config -o yaml

# Проверка Secrets
kubectl get secret app-secret -o jsonpath='{.data}' | base64 -d

# Проверка, что ресурсы существуют в нужном namespace
kubectl get configmap,secret -n <ns> | grep <name>

# Проверка монтирования volumes
kubectl get pod <pod-name> -o yaml | grep -A 10 "volumeMounts"
kubectl get pod <pod-name> -o yaml | grep -A 10 "volumes"
```

### Сценарий 2: Проблемы сетевой связности и зависимостей

**Симптомы:**
- Логи: `connection refused`, `timeout`, `dial tcp: lookup db-service: no such host`.

**Решение:**
1. **Init-контейнеры:** Использование легковесных образов (например, `busybox` или `alpine`) для блокировки старта основного приложения до готовности зависимости.
2. **Startup Probe:** Для приложений с длительным «прогревом» (Java/Spring, .NET) используйте `startupProbe`, чтобы `livenessProbe` не убивала процесс раньше времени.
3. **NetworkPolicy:** Убедитесь, что между namespace или подами нет запрещающих правил `NetworkPolicy`.
4. **CNI troubleshooting:** Если DNS работает, но соединения падают, проверьте MTU и фрагментацию пакетов в CNI-плагине.

```yaml
initContainers:
- name: wait-for-db
  image: busybox:1.36
  command: ['sh', '-c', 'until nc -z db-service 5432; do echo waiting for db; sleep 2; done']
```

**Верификация:**
```bash
# Ручная проверка эндпоинта health изнутри пода
kubectl exec <pod-name> -- curl -sf http://localhost:<port>/healthz

# Если exec не работает (distroless), используйте ephemeral контейнер
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>
# Внутри:
nslookup kubernetes.default.svc.cluster.local
curl -v http://db-service:5432
```

### Сценарий 3: Ошибки прав доступа к файловой системе

**Симптомы:**
- Exit Code: 1 или 13.
- Логи: `permission denied`, `cannot create directory`.

**Решение:**
1. **Security Context:** Используйте `fsGroup` для автоматического изменения владельца примонтированных томов.
2. **ReadOnlyRootFilesystem:** Если включен режим только для чтения, приложению необходимы `emptyDir` для записи временных файлов (`/tmp`, `/var/run`).
3. **SELinux/AppArmor:** Проверьте, не блокирует ли профиль безопасности запись в определенные пути.

```yaml
securityContext:
  runAsUser: 1000
  runAsGroup: 3000
  fsGroup: 2000
```

**Верификация:**
```bash
# Проверка прав на файлы внутри контейнера
kubectl exec <pod-name> -- ls -la /var/run/secrets/
kubectl exec <pod-name> -- id

# Проверка SELinux контекста (если принудительный режим)
kubectl exec <pod-name> -- ls -Z /tmp
```

### Сценарий 4: Некорректные параметры запуска (Entrypoint/Command)

**Симптомы:**
- Exit Code: 127 (`Command not found`) или 128 (`Invalid argument`).

**Решение:**
1. **Абсолютные пути:** Всегда указывайте полный путь к исполняемому файлу в поле `command`.
2. **Разделение команд и аргументов:** Убедитесь, что параметры разделены правильно (список строк YAML).
3. **Shell wrapper:** Если требуется выполнение нескольких команд или использование переменных окружения в строке запуска, используйте `sh -c`.
4. **Проверка образа:** Убедитесь, что бинарный файл существует в образе и имеет флаг executable.

```yaml
command: ["/bin/sh"]
args: ["-c", "export VAR=val && /usr/local/bin/app --config /etc/config/settings.yaml"]
```

**Верификация:**
```bash
# Проверка содержимого $PATH в образе
kubectl exec <pod-name> -- echo $PATH
kubectl exec <pod-name> -- which <binary-name>

# Проверка существования бинарного файла
kubectl exec <pod-name> -- ls -la /usr/local/bin/app

# Ручной запуск команды из манифеста
kubectl exec <pod-name> -- /bin/sh -c "/usr/local/bin/app --version"
```

### Сценарий 5: Ошибки прав доступа API (RBAC)

**Симптомы:**
- Логи: `Forbidden`, `user system:serviceaccount:... cannot get resource`.

**Решение:**
1. **ServiceAccount:** Проверьте, назначен ли поду верный ServiceAccount (по умолчанию используется `default` с минимальными правами).
2. **RoleBinding:** Убедитесь, что роль предоставляет доступ к нужным API-группам и ресурсам.
3. **ClusterRole vs Role:** Если приложение работает в нескольких namespace, используйте `ClusterRole` с `ClusterRoleBinding`.

```bash
# Проверка прав конкретного ServiceAccount
kubectl auth can-i get pods --as=system:serviceaccount:my-ns:my-sa
kubectl auth can-i get configmaps --as=system:serviceaccount:my-ns:my-sa
kubectl auth can-i create pods --as=system:serviceaccount:my-ns:my-sa

# Если под упал с Forbidden, проверьте ClusterRole/RoleBinding
kubectl describe rolebinding <ns>
kubectl describe clusterrolebinding <binding-name>
```

### Сценарий 6: Ошибки монтирования и квот хранилищ

**Симптомы:**
- Статус: `ContainerCreating` или `CrashLoopBackOff` (если файл не найден).
- События: `FailedMount`, `Volume node mismatch`.

**Решение:**
1. **Multi-attach:** Если используется диск с режимом `ReadWriteOnce`, он не может быть примонтирован к подам на разных узлах одновременно.
2. **StorageClass:** Проверьте доступность провайдера хранилища и соответствие лимитов квотам пространства имен.
3. **SubPath:** При использовании `subPath` в ConfigMap или Secret, путь внутри тома должен существовать. Изменения в ConfigMap/Secret не распространяются на файлы, примонтированные через `subPath`, без перезапуска пода.

**Верификация:**
```bash
# Проверка PVC и PV
kubectl get pv,pvc -n <ns>

# Проверка StorageClass
kubectl get storageclass

# Проверка событий монтирования
kubectl describe pod <pod-name> | grep -A 20 "Events:"
```

### Сценарий 7: Завершение штатного процесса (Batch Jobs в Deployments)

**Симптомы:**
- Exit Code: 0.
- Состояние: `Completed` -> `CrashLoopBackOff`.

**Решение:**
1. **Ресурс Job:** Используйте `Job` или `CronJob` для задач, которые должны завершиться после выполнения. `Deployment` предназначен для долгоживущих процессов и будет бесконечно перезапускать завершившийся контейнер.
2. **RestartPolicy:** Для Deployment установите `restartPolicy: Always` (дефолт). Если контейнер завершается с кодом 0, Deployment считает это сбоем и перезапускает его.

```yaml
# Правильно: Job для разовых задач
apiVersion: batch/v1
kind: Job
metadata:
  name: data-migration
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: migrate
        image: my-app:migrate
```

### Сценарий 8: Недостаточно памяти (OOMKilled)

**Симптомы:**
- Reason: `OOMKilled`, Exit Code: 137.

**Решение:**
1. **Корректировка лимитов:** Увеличьте `limits.memory`.
2. **Настройка рантайма:** Для JVM используйте `-XX:MaxRAMPercentage` вместо фиксированного Xmx, чтобы приложение учитывало лимиты контейнера.
3. **Поиск утечек:** Используйте профилировщики для анализа кучи (heap dump).
4. **QoS Guaranteed:** Для критичных подов установите `requests.memory == limits.memory` для получения класса `Guaranteed` и максимального `oom_score_adj = -997`.

**Верификация:**
```bash
# Проверка потребления памяти
kubectl top pod <pod-name>

# Проверка QoS-класса
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'

# Проверка oom_score_adj
kubectl exec <pod-name> -- cat /proc/1/oom_score_adj
```

### Сценарий 9: Циклическое перенаправление DNS (DNS Loop)

**Симптомы:**
- Логи: `too many open files` (у CoreDNS), бесконечные запросы к самому себе.
- Приложение не может разрешить ни одно имя.

**Решение:**
1. **Loop detection:** Обычно возникает, когда `/etc/resolv.conf` на узле содержит `127.0.0.1` или `::1`. CoreDNS копирует эти настройки и зацикливается.
2. **Forwarding:** Настройте CoreDNS на использование внешних DNS (например, `8.8.8.8`) в обход локального резолвера узла.
3. **ndots:** Убедитесь, что параметр `ndots` в `dnsConfig` не слишком низкий (может вызывать лишние запросы).

Подробный разбор и методы диагностики: **[Петли перенаправления DNS](../../../../Networking/Protocols/DNS/dns_forwarding_loops.md)**.

### Сценарий 10: Проблемы с использованием subPath при монтировании

**Симптомы:**
- Статус: `CreateContainerConfigError`.
- События: `error mounting volume ... subpath ... not found`.

**Решение:**
1. **Существование пути:** При использовании `subPath` в ConfigMap или Secret, путь внутри тома должен существовать.
2. **Обновление ConfigMap:** Изменения в ConfigMap/Secret не распространяются на файлы, примонтированные через `subPath`, без перезапуска пода. Используйте монтирование всего каталога без `subPath`, если требуется горячая перезагрузка (Hot Reload).
3. **Валидация:** Проверяйте манифесты с `kubectl apply --dry-run=client` перед применением.

### Сценарий 11: Ошибки зомби-процессов и PID 1 (Init system)

**Симптомы:**
- Процесс «зависает» или потребляет много ресурсов CPU при завершении.
- Переполнение таблицы процессов.

**Решение:**
1. **Tini / Dumb-init:** Используйте легковесные системы инициализации для корректной обработки сигналов (`SIGTERM`) и удаления дочерних процессов-зомби.
2. **ShareProcessNamespace:** Включите `shareProcessNamespace: true` в манифесте Pod, если требуется взаимодействие между контейнерами на уровне сигналов.

**Верификация:**
```bash
# Проверить, кто является PID 1
kubectl exec <pod-name> -- ps -p 1 -o pid,comm,args

# Если PID 1 — sh/bash, обработка сигналов нарушена
# Используйте tini или dumb-init в Dockerfile:
# ENTRYPOINT ["/sbin/tini", "--"]
# CMD ["my-app"]

# Проверка обработки SIGTERM
kubectl exec <pod-name> -- /bin/sh -c "kill -TERM 1 && sleep 2 && ps -p 1"
```

### Сценарий 12: Нехватка разделяемой памяти (/dev/shm)

**Симптомы:**
- Логи: `Failed to create shared memory segment`, краш приложений типа Chrome или PostgreSQL.

**Решение:**
1. **Memory Medium:** Смонтируйте `emptyDir` с `medium: Memory` в `/dev/shm`. По умолчанию размер `/dev/shm` в контейнере составляет 64MB, чего недостаточно для многих приложений.

```yaml
volumes:
- name: dshm
  emptyDir:
    medium: Memory
volumeMounts:
- name: dshm
  mountPath: /dev/shm
```

### Сценарий 13: Ограничения на использование sysctl параметров

**Симптомы:**
- Статус: `SysctlForbidden`.
- Логи: `failed to create containerd container: ... sysctl ... is not allowed`.

**Решение:**
1. **Safe Sysctls:** Kubernetes позволяет изменять только «безопасные» параметры по умолчанию.
2. **Node Configuration:** Для изменения «опасных» sysctl (например, сетевые буферы `net.core.somaxconn`) необходимо разрешить их в конфигурации `kubelet` на уровне узла (`--allowed-unsafe-sysctls`).

### Сценарий 14: Init:CrashLoopBackOff (падение init-контейнеров)

**Симптомы:**
- Основной контейнер не стартует, статус пода остается `Init:CrashLoopBackOff`.
- Init-контейнеры имеют `restartCount > 0`.

**Решение:**
1. **Логи init-контейнера:** Проверяйте логи именно подготовительных контейнеров, а не основного приложения.
2. **Идемпотентность:** Init-контейнеры могут перезапускаться. Их действия (миграции БД, создание папок) должны быть безопасными при повторном вызове.
3. **Зависимости:** Убедитесь, что init-контейнеры не зависят друг от друга без явного указания порядка через `initContainers` (они выполняются последовательно).

**Верификация:**
```bash
# Проверка статуса init-контейнеров
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].name}{"\t"}{.status.containerStatuses[*].state}{"\n"}'

# Логи init-контейнера
kubectl logs <pod-name> -c <init-container-name> --previous

# Проверка порядка init-контейнеров
kubectl get pod <pod-name> -o yaml | grep -A 30 "initContainers"
```

### Сценарий 15: Ошибки CRI Runtime (Exit Code 125)

**Симптомы:**
- Reason: `RuntimeError`, Exit Code: 125.
- События: `FailedCreateContainerError`, `OCI runtime create failed`.

**Решение:**
1. **Проверка рантайма:** Убедитесь, что `containerd` или `CRI-O` запущен и работоспособен на узле.
2. **Дисковое пространство:** Проверьте место в `/var/lib/containerd` и на корневом разделе.
3. **SELinux/AppArmor:** Ошибки доступа к образу или слоям могут вызывать RuntimeError.
4. **Версии:** Несовместимость версии containerd и Kubernetes API может приводить к ошибкам создания контейнеров.

**Верификация:**
```bash
# На узле, где запущен под (через SSH)
# 1. Статус containerd
systemctl status containerd

# 2. Логи containerd
journalctl -u containerd -n 100 --no-pager

# 3. Использование crictl
crictl ps -a --name <container-name>
crictl logs <container-id>
crictl inspect <container-id> | jq '.info.pid, .info.runtimeType'

# 4. Проверка места на диске
df -h /var/lib/containerd
df -i /var/lib/containerd
```

### Сценарий 16: Native Sidecars не готовы (Kubernetes 1.29+)

**Симптомы:**
- Основной контейнер не стартует, статус Pod: `Init:CrashLoopBackOff` или зависание в `Init:0/1`.
- Native Sidecar имеет `restartPolicy: Always` и не проходит `startupProbe`.

**Решение:**
1. **Startup Probe:** Убедитесь, что Native Sidecar имеет `startupProbe` с достаточным `failureThreshold` для долгого запуска (например, для Istio proxy).
2. **Ресурсы:** Sidecar-контейнеры потребляют ресурсы из того же Pod. Убедитесь, что у них достаточно `requests` и `limits`.
3. **Независимость:** Если Native Sidecar падает во время работы, он перезапускается сам, основной контейнер не трогается. Но если он не проходит startupProbe — основной контейнер не стартует вообще.

```yaml
spec:
  initContainers:
  - name: network-proxy
    image: envoyproxy/envoy:v1.28
    restartPolicy: Always
    startupProbe:
      httpGet:
        path: /ready
        port: 8001
      failureThreshold: 30  # 30 × 10s = 5 минут на запуск
      periodSeconds: 10
```

**Верификация:**
```bash
# Проверка статуса нативного сайдкара
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[?(@.name=="envoy-proxy")].state}'

# Проверка startupProbe сайдкара
kubectl describe pod <pod-name> | grep -A 10 "envoy-proxy"

# Проверка ресурсов sidecar
kubectl get pod <pod-name> -o jsonpath='{.spec.initContainers[*].resources}'
```

### Сценарий 17: Давление на ресурсы (PSI) и троттлинг CPU

**Симптомы:**
- Приложение зависает или отвечает с задержкой, нарушая таймауты `livenessProbe`.
- CPU throttling высокий, `livenessProbe` не проходит, контейнер перезапускается.
- Рост `memory.pressure full` предшествует `OOMKilled`.

**Решение:**
1. **CPU Requests:** Установите `requests.cpu` приближенным к реальному потреблению, чтобы избежать троттлинга на узле с высокой нагрузкой.
2. **Memory High (cgroups v2):** Настройте `memory.high` (через RuntimeClass или на уровне узла) для мягкого throttling вместо жесткого OOM.
3. **Liveness Probe timeouts:** Увеличьте `timeoutSeconds` и `failureThreshold` для `livenessProbe`, если приложение работает на насыщенном узле.

**Верификация:**
```bash
# На хосте или через ephemeral контейнер
# 1. Системное давление на память
cat /proc/pressure/memory

# 2. Давление на CPU
cat /proc/pressure/cpu

# 3. Статистика CPU throttling для пода
POD_UID=$(kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}')
cat /sys/fs/cgroup/kubepods.slice/kubepods-pod${POD_UID}.slice/cpu.stat
# → nr_periods=12345
# → nr_throttled=500    ← высокое значение = проблемы
# → throttled_usec=25000000
```

### Сценарий 18: Silent OOM в cgroups v2

**Симптомы:**
- Контейнер в статусе `Running`, но работает нестабильно: ошибки сегментации, зависания, `CrashLoopBackOff` отдельных процессов.
- В событиях Kubernetes нет `OOMKilled`, но приложение периодически падает.

**Решение:**
1. **Проверка cgroup событий:** В cgroups v2 проверьте счетчики `memory.events` внутри контейнера. Если `oom_kill > 0`, но контейнер жив — это Silent OOM.
2. **Увеличить limits.memory:** Даже если PID 1 жив, дочерние процессы могут убиваться. Увеличьте лимит, чтобы дать запас.
3. **Memory QoS:** Включите `memory.high` для мягкого throttling вместо жесткого убийства процессов.
4. **Групповой OOM:** Для критичных приложений используйте `memory.oom.group=1`, чтобы при OOM убивался весь контейнер целиком (он перезапустится), а не отдельные процессы.

**Верификация:**
```bash
# Внутри контейнера или через nsenter
cat /sys/fs/cgroup/memory.events
# → low: 0, high: 45, max: 2, oom: 1, oom_kill: 1

# Проверка dmesg на убитые процессы
dmesg | grep -i "oom\|killed process"
```

### Сценарий 19: PDB блокирует drain и rolling update

**Симптомы:**
- `kubectl drain <node>` зависает с ошибкой `cannot evict pod as it would violate the pod's disruption budget`.
- Rolling update останавливается, если `minAvailable` не может быть обеспечен.

**Решение:**
1. **unhealthyPodEvictionPolicy:** Начиная с Kubernetes 1.30, добавьте в PDB `unhealthyPodEvictionPolicy: AlwaysAllow`, чтобы нездоровые поды (включая `CrashLoopBackOff`) не блокировали выселение.
2. **Масштабирование:** Временно увеличьте количество реплик, чтобы `currentHealthy >= minAvailable`.
3. **Принудительное удаление:** `kubectl delete pod <pod-name> --grace-period=0 --force` — контроллер создаст новый Pod.

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
spec:
  minAvailable: 2
  unhealthyPodEvictionPolicy: AlwaysAllow  # K8s 1.30+
  selector:
    matchLabels:
      app: my-app
```

**Верификация:**
```bash
# Проверка PDB
kubectl get pdb -n <ns>

# Проверка, сколько подов можно выселить
kubectl get pdb <pdb-name> -o jsonpath='{.status.disruptionsAllowed}'
```

### Сценарий 20: Неправильный QoS класс и oom_score_adj

**Симптомы:**
- Под класса `BestEffort` или `Burstable` с низким `oom_score_adj` системно убивается при нагрузке на узел, хотя его `limits.memory` не превышен.
- Критичные поды жертвуются ради некритичных.

**Решение:**
1. **Guaranteed для критичных подов:** Установите `requests.cpu == limits.cpu` и `requests.memory == limits.memory` для каждого контейнера в поде.
2. **Проверка multi-container:** QoS определяется по «самому слабому звену». Если один контейнер `Guaranteed`, а второй `BestEffort` — весь под становится `Burstable`.
3. **Автоматические requests:** Если указан `limits.memory` без `requests.memory`, под становится `Burstable` (а не `Guaranteed`).

**Верификация:**
```bash
# Проверка QoS-класса пода
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'

# Проверка oom_score_adj внутри работающего пода
kubectl exec <pod-name> -- cat /proc/1/oom_score_adj
# → -997 (Guaranteed), 500 (Burstable), 1000 (BestEffort)

# Проверка текущего oom_score (рейтинг смерти)
kubectl exec <pod-name> -- cat /proc/1/oom_score

# Проверка событий OOM в dmesg
dmesg | grep -i "oom\|killed process"
```

### Сценарий 21: Отсутствие termination message

**Симптомы:**
- Логи пусты или содержат неинформативный вывод.
- `kubectl describe pod` не показывает причину падения в `Last State`.
- Приходится копаться в полном выводе логов для поиска ошибки.

**Решение:**
1. **terminationMessagePath:** Убедитесь, что приложение записывает причину завершения в `/dev/termination-log`.
2. **terminationMessagePolicy:** Используйте `FallbackToLogsOnError`, чтобы Kubernetes автоматически брал последние строки stderr, если файл пуст.
3. **Кастомный путь:** Для пуристых образов без `/dev` используйте `emptyDir` и кастомный путь.

```yaml
containers:
- name: app
  terminationMessagePolicy: FallbackToLogsOnError
  terminationMessagePath: /dev/termination-log
```

**Верификация:**
```bash
# Просмотр termination message
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.message}'

# Просмотр exit code
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.exitCode}'
```

### Сценарий 22: Service Mesh (Istio/Linkerd) — побочные эффекты Sidecar Injection

**Симптомы:**
- Под падает сразу после добавления аннотации для автоматической инъекции sidecar (Istio: `sidecar.istio.io/inject: true`).
- Логи показывают, что основной контейнер завершается до готовности envoy-прокси.
- `kubectl describe pod` показывает `EnvoyCheck` или `istio-proxy` в статусе `Waiting`.

**Решение:**
1. **StartupProbe для sidecar:** Увеличьте `failureThreshold` в `startupProbe` envoy-прокси, чтобы дать ему время на инициализацию.
2. **Порядок завершения:** Istio отправляет `SIGTERM` envoy-прокси первым, затем основному контейнеру. Если envoy не успевает завершить соединения, приложение может упасть.
3. **Ресурсы sidecar:** Envoy потребляет CPU/память из общего лимита Pod. Убедитесь, что `requests` и `limits` достаточны.
4. **LogLevel:** Установите `istio.io/logLevel: warning` для envoy, чтобы снизить нагрузку на CPU.

```yaml
# Исправление: увеличение таймаута envoy-прокси
annotations:
  sidecar.istio.io/inject: "true"
  proxyConfig: |
    proxyMetadata:
      ISTIO_META_DNS_CAPTURE: "true"
spec:
  containers:
  - name: istio-proxy
    startupProbe:
      failureThreshold: 30  # 30 × 10s = 5 минут на запуск
```

**Верификация:**
```bash
# Проверка статуса sidecar
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[?(@.name=="istio-proxy")].state}'

# Проверка логов envoy при падении
kubectl logs <pod-name> -c istio-proxy --previous
```

**Связанные темы:**
- **[Service Mesh: Концепции](../../../../Service_Mesh/service_mesh_concepts.md)** — архитектура sidecar, mTLS.
- **[Native Sidecars в Kubernetes](../../../../Kubernetes/Base/Pod/pod_sidecar_patterns.md)** — K8s 1.29+ нативные сайдкары.

### Сценарий 23: Helm-ошибки при деплое (Template Errors, Values Mismatch)

**Симптомы:**
- Под не создается или создается с некорректной конфигурацией после `helm upgrade`.
- Логи показывают ошибки переменных окружения или монтирования.
- `helm list` показывает статус `failed` или `pending-upgrade`.

**Решение:**
1. **Проверка шаблонов:** Выполните `helm template` для генерации итоговых манифестов и проверьте их валидность.
2. **Синтаксис YAML:** Ошибки в `values.yaml` могут приводить к невалидным манифестам. Используйте `yamllint` или `kubeconform`.
3. **Конфликт значений:** Если `values.yaml` переопределяет значения по умолчанию, убедитесь, что новые значения соответствуют ограничениям LimitRange/ResourceQuota.
4. **Проблемы с CRD:** Если Helm-чарт устанавливает CRD, убедитесь, что CRD применены до релиза.

```bash
# Проверка итоговых манифестов
helm template my-release ./chart --values values.yaml | kubectl apply --dry-run=client -f -

# Валидация YAML
helm template my-release ./chart | kubeconform -strict

# Просмотр изменений перед обновлением
helm upgrade my-release ./chart --values values.yaml --dry-run
```

**Верификация:**
```bash
# Проверка статуса релиза
helm status my-release

# Просмотр последних событий
helm get events my-release

# Откат при ошибке
helm rollback my-release <revision>
```

**Связанные темы:**
- **[Helm: Безопасность](../../../../Kubernetes/ToolsUtilities/Helm/Advanced/security_best_practices.md)** — best practices для production.
- **[Helm: Troubleshooting](../../../../Kubernetes/ToolsUtilities/Helm/Advanced/scenarios.md)** — типовые ошибки.

### Сценарий 24: GitOps-конфликты (ArgoCD/Flux) — Desync между Git и кластером

**Симптомы:**
- ArgoCD показывает статус `OutOfSync`, но поды в `CrashLoopBackOff` из-за некорректных изменений.
- Flux возвращает ошибку при применении манифестов.
- Конфликты при автоматическом слиянии (merge conflict) в GitOps-репозитории.

**Решение:**
1. **Синхронизация:** Принудительная синхронизация через ArgoCD UI или CLI (`argocd app sync`).
2. **Откат через Git:** Измените коммит в Git на предыдущую версию манифестов. GitOps-контроллер автоматически откатит изменения.
3. **Health Checks:** Убедитесь, что в ArgoCD настроены правильные `ignoreDifferences` для полей, которые изменяются runtime (например, `status`).
4. **Конфликты:** При merge conflict в репозитории разрешите его вручную или через CI/CD пайплайн.

```bash
# ArgoCD: принудительная синхронизация
argocd app sync <app-name> --force

# ArgoCD: откат на предыдущий коммит
git revert <commit-hash>
git push origin main

# Flux: проверка статуса
flux get kustomizations
flux trace <resource-name>
```

**Верификация:**
```bash
# ArgoCD: проверка разницы
argocd app diff <app-name>

# Flux: проверка логов
flux logs --follow
```

**Связанные темы:**
- **[ArgoCD: Установка](../../../../GitOps/ArgoCD/argocd_installation_and_setup.md)** — базовая настройка.
- **[GitOps: Политики](../../../../GitOps/Concepts/gitops-policy-management.md)** — управление политиками.

### Сценарий 25: NetworkPolicy блокирует трафик (DNS, Backend, Health Checks)

**Симптомы:**
- Под не может разрешить DNS-имена (`nslookup: can't resolve`).
- Приложение не может подключиться к зависимостям (БД, API).
- `kubectl describe pod` показывает `Liveness probe failed` из-за недоступности health-эндпоинта.

**Решение:**
1. **DNS-политики:** Убедитесь, что `NetworkPolicy` разрешает egress-трафик на порт 53 (TCP/UDP) к CoreDNS.
2. **Default Deny:** Если в namespace применена политика `default-deny`, явно разрешите трафик к зависимостям.
3. **Health Checks:** Разрешите ingress-трафик на порт health-эндпоинта (например, 8080) для liveness/readiness проб.
4. **Имена сервисов:** Используйте полные DNS-имена (`service.namespace.svc.cluster.local`) в политиках.

```yaml
# Разрешение DNS-трафика
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to: []
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

**Верификация:**
```bash
# Проверка DNS изнутри пода
kubectl exec <pod-name> -- nslookup kubernetes.default.svc.cluster.local

# Проверка NetworkPolicy
kubectl get networkpolicy -n <namespace>

# Проверка connectivity до зависимости
kubectl exec <pod-name> -- curl -v http://db-service:5432
```

**Связанные темы:**
- **[NetworkPolicy в Kubernetes](../../../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md)** — определения и концепции.
- **[NetworkPolicy: Практические сценарии](../../../../Kubernetes/Networking/Network/NetworkPolicy/practical_scenarios.md)** — 12 сценариев.

### Сценарий 26: ResourceQuota/LimitRange блокирует запуск подов

**Симптомы:**
- Под остается в статусе `Pending` с событием `FailedCreate` или `Exceeded quota`.
- `kubectl describe pod` показывает `insufficient cpu` или `insufficient memory`.
- Rolling update застревает из-за нехватки квоты.

**Решение:**
1. **Проверка квот:** Убедитесь, что ResourceQuota позволяет временный всплеск ресурсов при `maxSurge`.
2. **LimitRange:** Проверьте, что `requests` и `limits` контейнеров соответствуют min/max в LimitRange.
3. **Разные квоты:** Для разных типов подов (production, staging) используйте отдельные namespace с разными квотами.
4. **Приоритеты:** Используйте `PriorityClass` для критичных подов, чтобы они перезапускались в первую очередь.

```bash
# Проверка ResourceQuota
kubectl describe resourcequota -n <namespace>

# Проверка LimitRange
kubectl describe limitrange -n <namespace>

# Проверка использования квоты
kubectl get resourcequota -n <namespace> -o jsonpath='{.items[*].status.used}'
```

**Верификация:**
```bash
# Проверка доступных ресурсов
kubectl describe node <node-name> | grep -A 5 "Allocated resources"

# Проверка Pending-подов
kubectl get pods -n <namespace> --field-selector=status.phase=Pending
```

**Связанные темы:**
- **[ResourceQuota и LimitRange](../../../../Kubernetes/Scheduling/qos_limit_and_requests.md)** — управление ресурсами.
- **[HPA: Взаимодействие с ResourceQuota](../../../../Kubernetes/Autoscaling/HPA/hpa_advanced.md)** — блокировка масштабирования.

### Сценарий 27: ImagePullSecrets — проблемы с pull образов из приватных реестров

**Симптомы:**
- Под в статусе `ImagePullBackOff` или `ErrImagePull`.
- `kubectl describe pod` показывает `unauthorized: authentication required` или `manifest unknown`.
- Проблемы с ротацией секретов.

**Решение:**
1. **Валидация секрета:** Убедитесь, что Secret типа `kubernetes.io/dockerconfigjson` содержит корректные credentials.
2. **ServiceAccount:** Привяжите `imagePullSecrets` к ServiceAccount для автоматической инъекции во все поды.
3. **Ротация:** При обновлении credentials создайте новый Secret с другим именем, обновите `imagePullSecrets`, затем удалите старый.
4. **Docker Hub лимиты:** Используйте `imagePullSecrets` даже для публичных образов (лимит увеличивается со 100 до 200 pull/6h).

```bash
# Проверка наличия секрета
kubectl get secret <secret-name> -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d

# Проверка привязки к ServiceAccount
kubectl get sa default -o jsonpath='{.imagePullSecrets}'

# Привязка секрета к ServiceAccount
kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "registry-creds"}]}'
```

**Верификация:**
```bash
# Проверка доступа к реестру изнутри пода
kubectl exec <pod-name> -- curl -v https://registry-1.docker.io/v2/

# Проверка логов kubelet на узле
journalctl -u kubelet | grep -i "image pull"
```

**Связанные темы:**
- **[ImagePullErrors: Определения](../../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md)** — типы ошибок.
- **[ImagePullErrors: Best Practices](../../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/best_practices.md)** — безопасная ротация.

### Сценарий 28: Pod Security Standards (PSS/PSA) — блокировка подов на уровне admission

**Симптомы:**
- Под не создается, `kubectl describe pod` не показывает событий (Pod не дошел до планирования).
- `kubectl get events` показывает `Forbidden: violates PodSecurity "restricted:latest"`.
- PSA `enforce` блокирует поды с нарушениями безопасности.

**Решение:**
1. **Проверка меток:** Убедитесь, что namespace имеет корректные метки PSA (`pod-security.kubernetes.io/enforce`).
2. **Двухэтапное включение:** Переключайте `enforce` через `warn`/`audit`, чтобы выявить нарушения до блокировки.
3. **Dry-run:** Используйте `kubectl apply --dry-run=server` для проверки манифестов с учетом PSA.
4. **Исключения:** Для критичных компонентов (monitoring agents) используйте namespace с менее строгим профилем.

```bash
# Проверка PSA-меток на namespace
kubectl get ns <namespace> -o jsonpath='{.metadata.labels}' | grep pod-security

# Проверка манифеста с учетом PSA
kubectl apply -f pod.yaml --dry-run=server

# Просмотр аудит-логов PSA
kubectl get events --field-selector reason=FailedCreate --namespace <namespace>
```

**Верификация:**
```bash
# Проверка текущего enforced-уровня PSA
kubectl get ns -o custom-columns=NAME:.metadata.name,ENFORCE:.metadata.labels.pod-security\.kubernetes\.io/enforce

# Просмотр аудит-событий
kubectl get events --namespace <namespace> --field-selector reason=Warning --watch
```

**Связанные темы:**
- **[Pod Security Standards и Secret](../../../../Kubernetes/Base/secrets/pod_security_and_secrets.md)** — влияние PSA на монтирование секретов.
- **[Pod Security Context](../../../../Kubernetes/Security/pod_security_context.md)** — полное описание Security Context.

### Сценарий 29: PreStop hooks — зависимость от graceful shutdown

**Симптомы:**
- Приложение падает во время обновления или drain узла.
- `kubectl describe pod` показывает `Killing` без предварительного выполнения PreStop hook.
- Приложение не успевает завершить активные соединения.

**Решение:**
1. **PreStop hook:** Добавьте `preStop` команду для ожидания завершения активных соединений (например, `sleep 10`).
2. **terminationGracePeriodSeconds:** Увеличьте время ожидания завершения (по умолчанию 30 секунд).
3. **SIGTERM handling:** Убедитесь, что приложение корректно обрабатывает сигнал `SIGTERM`.
4. **Connection Draining:** Настройте балансировщик (Ingress, Service) на отключение пода от ротации перед завершением.

```yaml
spec:
  terminationGracePeriodSeconds: 60
  containers:
  - name: app
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 10"]
```

**Верификация:**
```bash
# Проверка наличия PreStop hook
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].lifecycle.preStop}'

# Просмотр событий завершения
kubectl get events --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp'
```

**Связанные темы:**
- **[Pod Terminating: Определения](../../../../Kubernetes/Troubleshooting/Common_Errors/PodTerminating/definitions.md)** — жизненный цикл завершения.
- **[Graceful Termination](../../../../Kubernetes/Networking/Network/traffic_path.md)** — настройка drain.

### Сценарий 30: Admission Controllers (Kyverno/OPA Gatekeeper) — блокировка подов

**Симптомы:**
- Под не создается, `kubectl describe pod` показывает ошибку admission-контроллера.
- Ошибки вида `admission webhook "kyverno-svc.kyverno.svc" denied the request`.
- MutatingWebhook не может инжектировать sidecar или добавлять labels.

**Решение:**
1. **Проверка webhook:** Убедитесь, что ValidatingWebhookConfiguration/MutatingWebhookConfiguration активен.
2. **failurePolicy:** Если webhook недоступен, `failurePolicy: Fail` блокирует все запросы. Временно установите `Ignore`.
3. **namespaceSelector:** Проверьте, что политика применяется к нужным namespace (не к `kube-system`).
4. **Логи admission-контроллера:** Проверьте логи Kyverno/Gatekeeper для понимания причины блокировки.

```bash
# Проверка webhook-конфигурации
kubectl get validatingwebhookconfigurations
kubectl get mutatingwebhookconfigurations

# Просмотр логов Kyverno
kubectl logs -n kyverno -l app.kubernetes.io/component=admission-controller --tail=100

# Временное отключение политики (Kyverno)
kubectl label namespace <namespace> pod-security.kubernetes.io/warn=-
```

**Верификация:**
```bash
# Проверка статуса webhook
kubectl get deployment -n kyverno kyverno-admission-controller

# Просмотр аудит-событий
kubectl get events --field-selector reason=Warning --namespace <namespace>
```

**Связанные темы:**
- **[Admission Controllers](../../../../Kubernetes/Concepts/admission_controllers.md)** — архитектура и типы.
- **[Kyverno: Troubleshooting](../../../../Kubernetes/Security/kyverno/troubleshooting.md)** — диагностика политик.

## Решения по стекам технологий

### Java / JVM

```yaml
# Для JVM укажите процент от лимита контейнера вместо фиксированного Xmx
env:
- name: JAVA_OPTS
  value: "-XX:MaxRAMPercentage=75.0 -XX:+UseContainerSupport"
```

- **Симптом:** OOMKilled (exit 137) при старте или после нагрузки.
- **Причина:** JVM по умолчанию использует фиксированный `Xmx` и не видит лимиты cgroup.
- **Решение:** Используйте `-XX:MaxRAMPercentage` (JDK 8u191+, JDK 10+) или `-XX:+UseContainerSupport`.

### Go

```bash
# В Go panic выводится в stderr. Если логи пусты — проверьте:
# 1. GOMEMLIMIT (Go 1.19+) задан ниже лимита контейнера
# 2. GOTRACEBACK=crash для дампа памяти при панике
# 3. NDEBUG или сигналы, подавляющие panic
```

- **Симптом:** Exit 2 или 137, логи содержат `panic: runtime error`.
- **Решение:** Настройте `GOMEMLIMIT` и `GOTRACEBACK`, добавьте `tini` для корректной обработки сигналов.

### .NET

```yaml
env:
- name: DOTNET_GCHeapHardLimit
  value: "0x38400000"  # 900 MiB в hex
# Или автоматически (современные рантаймы):
# DOTNET_GCHeapHardLimitPercent=70
```

- **Симптом:** Ошибка `System.OutOfMemoryException` или OOMKilled перед тем, как .NET GC успевает сработать.
- **Решение:** Начиная с .NET 8/9, рантайм автоматически подстраивается под cgroup-лимиты. Для резких скачков явно ограничьте кучу.

### Python

```bash
# Буферизация вывода (зависит от переменной окружения)
export PYTHONUNBUFFERED=1
```

- **Симптом:** Логи пусты при падении, exit 1.
- **Причина:** Python буферизирует stdout/stderr. При краше буфер не сбрасывается.
- **Решение:** Установите `PYTHONUNBUFFERED=1` или используйте `-u` для запуска интерпретатора.

## Быстрое восстановление (Remediation)

### Остановка циклических перезапусков

```bash
# 1. Масштабирование Deployment до 0 (останавливает цикл)
kubectl scale deployment/<name> --replicas=0

# 2. Исправление конфигурации / образа
kubectl set image deployment/<name> app=<name>:<fixed-tag>
kubectl set env deployment/<name> DB_HOST=<correct-db>

# 3. Возврат реплик
kubectl scale deployment/<name> --replicas=1

# 4. Или откат на предыдущую ревизию
kubectl rollout undo deployment/<name>
kubectl rollout undo deployment/<name> --to-revision=2
```

### Drain узла с подами в CrashLoopBackOff

Если поды в `CrashLoopBackOff` блокируют drain:

```bash
# Проверка PDB
kubectl get pdb -n <ns>

# Вариант 1: Включение AlwaysAllow (Kubernetes v1.31+)
kubectl patch pdb <name> -p '{"spec":{"unhealthyPodEvictionPolicy":"AlwaysAllow"}}'

# Вариант 2: Принудительное удаление пода (контроллер создаст новый)
kubectl delete pod <pod-name> --grace-period=0 --force

# Drain с игнорирование PDB (не рекомендуется в production без анализа)
kubectl drain <node-name> --ignore-daemonsets --delete-local-data --force
```

## Чек-лист быстрого исправления

1. **Анализ логов:** Проверьте `kubectl logs --previous`.
2. **Проверка событий:** Изучите `kubectl describe pod` на наличие `FailedScheduling`, `FailedMount`, `OOMKilled`.
3. **Валидация манифестов:** Проверьте опечатки в именах ConfigMap, Secret и путях монтирования.
4. **Ресурсы:** Убедитесь, что запросы (`requests`) и лимиты (`limits`) соответствуют потребностям приложения.

## Чек-лист профилактики

1. **Конфигурация:** Используйте `kubectl apply --dry-run=client` для валидации манифестов перед применением.
2. **Init-контейнеры:** Обеспечьте идемпотентность — они могут перезапускаться.
3. **Пробы:** Для долго запускающихся приложений всегда используйте `startupProbe` с достаточным `failureThreshold`.
4. **Ресурсы:** Устанавливайте `requests` и `limits` для всех контейнеров. Для критичных подов используйте `Guaranteed` QoS.
5. **RBAC:** Создавайте минимальные `Role`/`RoleBinding` вместо `ClusterRole` где возможно.
6. **Логирование:** Настройте приложение на запись в `/dev/termination-log` и используйте `terminationMessagePolicy: FallbackToLogsOnError`.
7. **Наблюдаемость:** Включите алерты на `CrashLoopBackOff` и `OOMKilled` в системе мониторинга.
8. **Сигналы:** Используйте `tini` или `dumb-init` для корректной обработки `SIGTERM`.
9. **Сторонние образы:** Избегайте образа `latest` в production. Используйте фиксированные теги и `imagePullPolicy: IfNotPresent`.
10. **NetworkPolicy:** Убедитесь, что политики разрешают DNS-трафик и connectivity к зависимостям перед включением strict-режимов.
11. **ResourceQuota:** Настройте квоты с запасом для `maxSurge` при rolling update.
12. **ImagePullSecrets:** Привяжите секреты к ServiceAccount для автоматической инъекции во все поды.
13. **Pod Security Standards:** Включайте `enforce` через `warn`/`audit` в два этапа.
14. **Graceful Shutdown:** Добавьте PreStop hooks и увеличьте `terminationGracePeriodSeconds` для критичных сервисов.
15. **Service Mesh:** Убедитесь, что startupProbe envoy-прокси имеет достаточный `failureThreshold`.
16. **Helm:** Проверяйте шаблоны через `helm template --dry-run` перед деплоем.
17. **GitOps:** Настройте `ignoreDifferences` для runtime-полей в ArgoCD/Flux.

## Дополнительная информация

### См. также

- **[Диагностика CrashLoopBackOff](./diagnostics.md)** — пошаговый алгоритм поиска неисправностей.
- **[Определения и концепции](./definitions_and_concepts.md)** — теория, BackOff, RestartPolicy, коды завершения.
- **[Продвинутые темы](./advanced_topics.md)** — автоматизация, eBPF, Cgroup v2, Native Sidecars.
- **[Runbook: CrashLoopBackOff](./runbook.md)** — шаблон для дежурного инженера.
