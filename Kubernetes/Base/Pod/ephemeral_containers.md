# Ephemeral Containers в Kubernetes

**Актуально для:** Kubernetes 1.30–1.35

## Определения

* **Ephemeral Container (Эфемерный контейнер)** — временный вспомогательный контейнер, добавляемый в уже запущенный Pod через специализированный subresource API (`pods/ephemeralcontainers`) для интерактивного траблшутинга, профилирования и инспекции состояния без перезапуска или остановки основных рабочих процессов.
* **Подресурс `pods/ephemeralcontainers`** — эндпоинт Kubernetes API (`PUT /api/v1/namespaces/{namespace}/pods/{name}/ephemeralcontainers`), через который выполняется добавление эфемерных контейнеров. В отличие от основного манифеста Pod, доступен в режиме добавления (append-only).
* **Target Container (`--target`)** — целевой контейнер внутри Pod, с которым эфемерный контейнер связывается на уровне PID-пространства имен ядра Linux (`container-sharing PID namespace`). Позволяет процессу отладчика инспектировать память, файловую систему (`/proc/<PID>/root`) и дескрипторы целевого приложения.
* **Distroless-образ** — сверхминималистичный образ контейнера, содержащий исключительно бинарный исполняемый файл приложения и минимальные runtime-зависимости (без командных оболочек `/bin/sh`, `/bin/bash`, утилит `coreutils` и пакетных менеджеров). Отладка таких образов невозможна стандартным `kubectl exec`.
* **Профили отладки (Debug Profiles)** — встроенные шаблоны `securityContext` утилиты `kubectl debug` (GA с v1.30), позволяющие автоматически подстраивать параметры безопасности контейнера (`capabilities`, `runAsUser`, `seccomp`, доступ к host-пространствам) под уровень Pod Security Standards (PSS/PSA).
* **Кастомные профили отладки (`--custom`)** — механизм конфигурирования отладочного контейнера через внешний YAML-манифест (v1.31+), позволяющий монтировать тома, пробрасывать переменные окружения и задавать произвольные параметры безопасности.
* **Отладочная копия Pod (`--copy-to`)** — режим `kubectl debug`, создающий новый Pod-клон с возможностью динамического изменения спецификации контейнеров (`command`, `args`, `image`, `shareProcessNamespace`), сохраняющий изоляцию production-окружения.

---

## Базовые концепции и архитектура

### Принцип работы и взаимодействие с CRI

Эфемерные контейнеры функционируют за счет встроенных возможностей интерфейса контейнеризации CRI (Container Runtime Interface, например `containerd` или `CRI-O`). Они запускаются внутри того же самого пространства изоляции ядра Linux (Pod Sandbox), что и основные контейнеры Pod.

```
+-----------------------------------------------------------------------------------------+
| Kubernetes Worker Node (Linux Kernel)                                                   |
|                                                                                         |
|  +-----------------------------------------------------------------------------------+  |
|  | Pod Sandbox (cgroup: /sys/fs/cgroup/.../pod<UID>/)                                 |  |
|  | Shared Namespaces: Network (netns), IPC (ipcns), UTS (utsns)                      |  |
|  |                                                                                   |  |
|  |  +---------------------------+        +----------------------------------------+  |  |
|  |  | App Container (Distroless)|        | Ephemeral Container (Netshoot/Alpine)  |  |  |
|  |  | - PID: 1 (in container ns)|        | - Injected via pods/ephemeralcontainers|  |  |
|  |  | - Filesystem: minimal     |        | - Has /bin/sh, curl, gdb, tcpdump      |  |  |
|  |  +---------------------------+        +----------------------------------------+  |  |
|  |                ^                                          |                       |  |
|  |                |          PID Sharing / Target Container  |                       |  |
|  |                +------------------------------------------+                       |  |
|  |                   (Доступ к FS через /proc/<PID>/root)                            |  |
|  +-----------------------------------------------------------------------------------+  |
|                                            ^                                            |
|                                            | gRPC CreateContainer / StartContainer      |
|  +-----------------------------------------+-----------------------------------------+  |
|  | Kubelet Worker Process                                                            |  |
|  | - Получает Pod.spec.ephemeralContainers через API-Server                          |  |
|  | - Передает запрос в containerd/CRI-O через CRI v1                                  |  |
|  +-----------------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------------+
```

1. **Инициирование:** Администратор или SRE выполняет `kubectl debug` или отправляет запрос к REST API `PUT /api/v1/namespaces/{ns}/pods/{name}/ephemeralcontainers`.
2. **Валидация:** API-Server проверяет RBAC права на подресурс `ephemeralcontainers` и проверяет манифест через Admission-контроллеры (включая Pod Security Admission).
3. **Обновление объекта:** API-Server добавляет запись в список `spec.ephemeralContainers` в etcd. Существующие поля Pod не мутируются.
4. **Реакция Kubelet:** Локальный Kubelet фиксирует изменение спецификации Pod через watch-механизм и отправляет gRPC-вызов `CreateContainer` в CRI-рантайм (containerd или CRI-O), передавая идентификатор существующего Pod Sandbox.
5. **Создание контейнера:** Рантайм подключает новый контейнер к общему сетевому пространству имен (Network Namespace), IPC и при необходимости настраивает PID Namespace (в зависимости от флагов `--target` или `shareProcessNamespace`).

### Сравнение жизненного цикла типов контейнеров

| Характеристика | Application Containers | Init Containers | Native Sidecars (1.28+) | Ephemeral Containers |
| :--- | :--- | :--- | :--- | :--- |
| **Добавление** | При создании Pod | При создании Pod | При создании Pod | В любой момент работы Pod |
| **Жизненный цикл** | Весь срок жизни Pod | До старта App-контейнеров | Параллельно с App-контейнерами | По требованию (ad-hoc) |
| **RestartPolicy** | `Always` / `OnFailure` | `OnFailure` / `Never` | `Always` | **Только `Never`** |
| **Модификация/Удаление** | Через контроллер/манифест | Через контроллер/манифест | Через контроллер/манифест | **Неизменяемы (Append-only)** |
| **Lifecycle Hooks** | `postStart`, `preStop` | Нет | `postStart`, `preStop` | **Запрещены** |
| **Health Probes** | Liveness, Readiness, Startup | Нет | Startup, Liveness, Readiness | **Запрещены** |
| **Сетевые порты** | Поддерживаются (`ports`) | Запрещены | Поддерживаются | **Запрещены** |
| **Влияние на QoS Pod** | Формируют QoS | Формируют QoS | Формируют QoS | **Не влияют** |

### Ограничения спецификации

Хотя эфемерный контейнер описывается структурой `v1.Container`, спецификация Kubernetes жестко ограничивает допустимые поля:

| Поле API | Допустимость | Архитектурная причина |
| :--- | :---: | :--- |
| `name` | **Да** | Уникальный идентификатор контейнера в рамках Pod. |
| `image` | **Да** | Образ с отладочным инструментарием. |
| `command`, `args` | **Да** | Команда запуска процесса (shell, скрипт, утилита). |
| `targetContainerName` | **Да** | Привязка PID namespace к конкретному контейнеру. |
| `env`, `envFrom` | **Да** | Передача переменных окружения (включая Downward API). |
| `volumeMounts` | **Да** | Монтирование томов, уже объявленных в `spec.volumes` Pod. |
| `resources.limits` | **Да** | Ограничение потребления CPU и RAM во избежание сбоя хоста. |
| `resources.requests` | **Игнорируется** | Планировщик (kube-scheduler) не участвует в размещении контейнера. |
| `ports` | **Запрещено** | Предотвращает несанкционированное открытие портов сервиса. |
| `probes` | **Запрещено** | Отладочный процесс не должен влиять на статус готовности Pod. |
| `lifecycle` | **Запрещено** | Запрещены `postStart` и `preStop` хуки. |

### Влияние на ресурсы и планирование

1. **Класс качества обслуживания (QoS Class):**
   * Ресурсы эфемерных контейнеров **не учитываются** при вычислении QoS-класса Pod (`Guaranteed`, `Burstable`, `BestEffort`).
   * Значения `resources.requests` игнорируются kube-scheduler, так как Pod уже размещен на узле.
2. **Лимиты памяти и OOMKilled:**
   * При установке `resources.limits.memory` эфемерный контейнер получает собственный cgroup-лимит памяти внутри общего cgroup дерева Pod.
   * Если отладочный процесс превышает выделенный `limits.memory`, ядро Linux завершает именно процесс эфемерного контейнера (`Exit Code 137, OOMKilled`). **Основной рабочий Pod при этом не падает и не перезапускается.**
   * Если лимит не задан, эфемерный контейнер может исчерпать общую память Pod (вызвав OOMKill критического сервиса) или память рабочей ноды.
3. **Лимиты CPU и Throttling:**
   * CPU limits выделяются через CFS (Completely Fair Scheduler) квоты. Потребление процессора отладчиком суммируется с общим потреблением cgroup Pod. При высокой нагрузке отладчика рабочее приложение может испытывать CPU Throttling.
4. **Дисковое пространство (Ephemeral Storage):**
   * Все временные файлы, создаваемые в корневой файловой системе эфемерного контейнера (writable layer контейнера), расходуют `ephemeral-storage` узла. При переполнении Kubelet инициирует `Eviction` всего Pod.

### Безопасность и профили отладки (Debug Profiles)

В современных версиях Kubernetes (1.30+) `kubectl debug` поддерживает профили безопасности, соответствующие уровням Pod Security Standards (PSS):

| Профиль | Допустимые Capabilities | hostNetwork / hostPID | Запуск от root | Область применения |
| :--- | :--- | :---: | :---: | :--- |
| **`general`** (дефолт) | Базовые (`NET_BIND_SERVICE`) | Нет | Да/Нет | Стандартная диагностика непривилегированных сред |
| **`baseline`** | Минимальные, запрещены опасные | Нет | Да | Namespaces с PSA `enforce: baseline` |
| **`restricted`** | `drop: ["ALL"]`, без эскалации | Нет | **Запрещен** (`runAsNonRoot`) | Production с PSA `enforce: restricted` |
| **`netadmin`** | `NET_ADMIN`, `NET_RAW` | Нет | Да | Анализ трафика (`tcpdump`), iptables, сокеты |
| **`sysadmin`** | `SYS_ADMIN`, `SYS_PTRACE`, `DAC_OVERRIDE` | Да (для узлов) | Да | Глубокая системная трассировка, отладка узла |

---

## Практические сценарии

### Сценарий 1: Интерактивная отладка Distroless-контейнера через `--target`

**Контекст:** Production-приложение собрано на базе distroless/scratch. В контейнере отсутствуют утилиты и командный интерпретатор. Приложение зависает или отдает 500 ошибки.

```bash
# 1. Проверяем точное имя контейнера в Pod
kubectl get pod payment-service-7f89d54b9-x2k4l -o jsonpath='{.spec.containers[*].name}'
# → app

# 2. Подключаем эфемерный контейнер с инструментами сетевого и системного анализа
kubectl debug -it payment-service-7f89d54b9-x2k4l \
  --image=nicolaka/netshoot \
  --target=app \
  --profile=general
# → Targetting container "app". If you don't see processes from this container it may be because the container runtime doesn't support this feature.
# → Defaulting debug container name to debugger-4w9qx.
# → If you don't see a command prompt, try pressing enter.
# → / # 

# 3. Внутри эфемерного контейнера:
# Просмотр процессов целевого контейнера (благодаря --target виден PID 1 приложения)
ps aux
# → PID   USER     TIME  COMMAND
# →   1   10001    0:45  /app/payment-server --config=/etc/payment/config.json
# →  48   root     0:00  zsh
# →  82   root     0:00  ps aux

# 4. Просмотр файловой системы целевого контейнера через procfs ядра Linux:
ls -la /proc/1/root/app/
# → -rwxr-xr-x    1 10001    10001     45182912 Oct 10 12:00 payment-server

# 5. Просмотр реальных переменных окружения процесса приложения:
tr '\0' '\n' < /proc/1/environ | grep -E "DATABASE_|APP_ENV"
# → DATABASE_URL=postgres://db.prod.internal:5432/payments
# → APP_ENV=production

# 6. Проверка открытых файловых дескрипторов и сетевых сокетов процесса 1:
ls -l /proc/1/fd
# → lrwx------ 1 10001 10001 64 Oct 17 14:02 0 -> /dev/null
# → lrwx------ 1 10001 10001 64 Oct 17 14:02 3 -> socket:[8492011]
```

### Сценарий 2: Низкоуровневый анализ сетевого трафика с профилем `netadmin`

**Контекст:** Приложение испытывает спорадические таймауты при запросах к базе данных или стороннему API. Требуется снять дамп трафика интерфейса Pod.

```bash
# Запуск эфемерного контейнера с правами захвата пакетов
kubectl debug -it payment-service-7f89d54b9-x2k4l \
  --image=nicolaka/netshoot \
  --target=app \
  --profile=netadmin
# → Targetting container "app".
# → / #

# Внутри отладочного контейнера:
# 1. Проверка сокетов и соединений
ss -tulpn
# → Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:PortProcess
# → tcp   LISTEN 0      128          0.0.0.0:8080       0.0.0.0:*    users:(("payment-server",pid=1,fd=3))

# 2. Проверка задержки и потерь пакетов до сервиса базы данных
mtr -rw -c 10 postgres-cluster.db.svc.cluster.local
# → Start: 2026-10-17T14:15:02+0300
# → HOST: payment-service-7f89d54b9-x2k4l  Loss%   Snt   Last   Avg  Best  Wrst StDev
# →   1.|-- 10.244.2.1                     0.0%    10    0.1   0.1   0.1   0.2   0.0
# →   2.|-- 10.96.14.88                    0.0%    10    0.4   0.5   0.3   0.8   0.1

# 3. Захват сетевого трафика на интерфейсе eth0 (фильтр по порту 5432)
tcpdump -i eth0 -nn -s 0 port 5432 -w /tmp/db-trace.pcap -c 100
# → tcpdump: listening on eth0, link-type EN10MB (Ethernet), snapshot length 262144 bytes
# → 100 packets captured
# → 100 packets received by filter
# → 0 packets dropped by kernel

# 4. Проверка статистики conntrack для локального пода
conntrack -L | grep -E "10.244" | head -n 5
# → tcp      6 431999 ESTABLISHED src=10.244.1.42 dst=10.96.14.88 sport=48192 dport=5432 ...
```

### Сценарий 3: Профилирование и трассировка системных вызовов (`strace`)

**Контекст:** Процесс приложения заблокирован в состоянии Deadlock или непрерывно грузит CPU на 100%. Требуется перехватить системные вызовы.

```bash
# Запуск с профилем sysadmin (требуется CAP_SYS_PTRACE для подключения к чужому процессу)
kubectl debug -it payment-service-7f89d54b9-x2k4l \
  --image=nicolaka/netshoot \
  --target=app \
  --profile=sysadmin
# → / #

# Внутри отладочного контейнера:
# 1. Трассировка системных вызовов процесса PID 1
strace -p 1 -c -T -f -s 128
# → strace: Process 1 attached with 12 threads
# → ^C
# → % time     seconds  usecs/call     calls    errors syscall
# → ------ ----------- ----------- --------- --------- ----------------
# →  82.14    0.045120          12      3760           epoll_pwait
# →  12.30    0.006752           8       844           read
# →   5.56    0.003051           7       422           futex
# → ------ ----------- ----------- --------- --------- ----------------
# → 100.00    0.054923                  5026           total

# 2. Если приложение написано на Go и включен pprof:
curl -s http://127.0.0.1:6060/debug/pprof/goroutine?debug=1 | head -n 30
# → goroutine profile: total 48
# → 1 @ 0x43b210 0x44af12 0x44aee8 ...

# 3. Снятие дампов для JVM-приложений (через монтирование hsperfdata):
# Доступ к временным файлам Java-процесса осуществляется через /proc/1/root/tmp/
ls -la /proc/1/root/tmp/hsperfdata_*
# → -rw------- 1 10001 10001 32768 Oct 17 14:00 1
```

### Сценарий 4: Добавление эфемерного контейнера через Kubernetes REST API

**Контекст:** Автоматизированная диагностика в CI/CD скриптах, SRE-утилитах или операторах кластера без использования бинарного файла `kubectl debug`.

```bash
# 1. Формируем JSON-манифест эфемерного контейнера
cat << 'EOF' > /tmp/ephemeral-patch.json
{
  "apiVersion": "v1",
  "kind": "Pod",
  "metadata": {
    "name": "payment-service-7f89d54b9-x2k4l",
    "namespace": "production"
  },
  "spec": {
    "ephemeralContainers": [
      {
        "name": "sre-agent-collector",
        "image": "alpine:3.20",
        "command": ["/bin/sh", "-c", "df -h > /tmp/disk.log && sleep 3600"],
        "targetContainerName": "app",
        "resources": {
          "limits": {
            "memory": "128Mi",
            "cpu": "100m"
          }
        }
      }
    ]
  }
}
EOF

# 2. Отправка вызова в API-сервер через kubectl replace --raw
kubectl replace --raw /api/v1/namespaces/production/pods/payment-service-7f89d54b9-x2k4l/ephemeralcontainers \
  -f /tmp/ephemeral-patch.json
# → {"kind":"Pod","apiVersion":"v1","metadata":{"name":"payment-service-7f89d54b9-x2k4l","namespace":"production", ...}}

# 3. Проверка статуса запуска добавленного контейнера
kubectl get pod payment-service-7f89d54b9-x2k4l -n production \
  -o jsonpath='{.status.ephemeralContainerStatuses[?(@.name=="sre-agent-collector")]}'
# → {"containerID":"containerd://...","image":"alpine:3.20","name":"sre-agent-collector","ready":true,"state":{"running":{"startedAt":"2026-10-17T14:22:10Z"}}}
```

### Сценарий 5: Использование кастомных профилей (`--custom`, v1.31+)

**Контекст:** В защищенных корпоративных средах отладочному контейнеру требуется смонтировать существующий PVC, передать токены авторизации или задать специфические лимиты ресурсов.

```yaml
# custom-debug-spec.yaml
securityContext:
  runAsUser: 10001
  runAsNonRoot: true
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
resources:
  limits:
    cpu: "250m"
    memory: "256Mi"
  requests:
    cpu: "50m"
    memory: "64Mi"
volumeMounts:
  - name: shared-data
    mountPath: /data
    readOnly: true
```

Запуск сессии отладки с применением кастомного файла:

```bash
kubectl debug payment-service-7f89d54b9-x2k4l -it \
  --image=alpine:3.20 \
  --custom=custom-debug-spec.yaml
# → / $ 
# → / $ id
# → uid=10001 gid=0(root)
# → / $ ls -la /data
# → -rw-r--r-- 1 10001 10001 4096 Oct 17 14:00 app-transactions.db
```

### Сценарий 6: Отладка падающего Pod через создание изолированной копии (`--copy-to`)

**Контекст:** Pod падает с `CrashLoopBackOff` сразу при старте (`Exit Code 1`). Обычный эфемерный контейнер не успевает подключиться, так как Pod циклически перезапускается.

```bash
# Создание копии Pod с заменой точки входа (entrypoint) на sleep
kubectl debug payment-service-7f89d54b9-x2k4l \
  --copy-to=payment-debug-clone \
  --container=app \
  --share-processes \
  -- /bin/sh -c "sleep 7200"
# → Defaulting debug container name to debugger-m7q4p.
# → If you don't see a command prompt, try pressing enter.

# Проверяем, что клон успешно запустился и изолирован от трафика (отсутствуют сервисные селекторы)
kubectl get pod payment-debug-clone
# → NAME                  READY   STATUS    RESTARTS   AGE
# → payment-debug-clone   1/1     Running   0          14s

# Интерактивное подключение к клону для ручного запуска бинарника и отладки аргументов
kubectl exec -it payment-debug-clone -c app -- /bin/sh
# / # /app/payment-server --config=/etc/payment/config.json
# → panic: invalid configuration: missing SECRET_KEY at /etc/payment/config.json:42
```

### Сценарий 7: Диагностика рабочего узла без прямого SSH (`kubectl debug node/`)

**Контекст:** На узле кластера сбоит демон `containerd` или заполняется диск, но прямой SSH-доступ закрыт политиками безопасности.

```bash
# Запуск привилегированного отладочного Pod на узле worker-node-03
kubectl debug node/worker-node-03 -it \
  --image=ubuntu:24.04 \
  --profile=sysadmin
# → Creating debugging pod node-debugger-worker-node-03-z9h1k with container debugger on node worker-node-03.
# → If you don't see a command prompt, try pressing enter.
# → root@worker-node-03:/#

# 1. Проверяем файловую систему хоста (хостовый корень примонтирован в /host)
chroot /host /bin/bash
# → [root@worker-node-03 /]#

# 2. Проверка статуса локальных служб через systemd
systemctl status containerd --no-pager
# → ● containerd.service - containerd container runtime
# →    Loaded: loaded (/lib/systemd/system/containerd.service; enabled)
# →    Active: active (running) since Thu 2026-10-15 08:30:11 UTC; 2 days ago

# 3. Анализ дискового пространства разделов хоста
df -hT /var/lib/containerd /var/log
# → Filesystem     Type  Size  Used Avail Use% Mounted on
# → /dev/nvme0n1p2 ext4  100G   92G  3.1G  97% /

# 4. Просмотр последних записей журнала Kubelet
journalctl -u kubelet --no-pager -n 30
# → Oct 17 14:30:02 worker-node-03 kubelet[2412]: E1017 14:30:02.112 image_manager.go: Disk usage on image filesystem is at 97%
```

### Сценарий 8: Forensic-анализ инцидента безопасности

**Контекст:** Система обнаружения аномалий зафиксировала подозрительный процесс внутри Pod. Необходимо зафиксировать артефакты до завершения работы Pod.

```bash
# 1. Сохранение текущих логов и манифеста Pod
kubectl get pod compromised-pod-89fd4-c92v1 -o yaml > /tmp/incident-pod-meta.yaml
kubectl logs compromised-pod-89fd4-c92v1 --all-containers=true > /tmp/incident-pod.log

# 2. Подключение forensic-контейнера через target
kubectl debug -it compromised-pod-89fd4-c92v1 \
  --image=alpine:3.20 \
  --target=app \
  --profile=sysadmin
# → / #

# Внутри forensic-контейнера:
# Создаем изолированную директорию для улик
mkdir /tmp/evidence

# Дамп окружения и командной строки всех активных процессов
for pid in $(ls -d /proc/[0-9]* | sed 's/\/proc\///'); do
  echo "PID: $pid" >> /tmp/evidence/process-dump.txt
  cat /proc/$pid/cmdline | tr '\0' ' ' >> /tmp/evidence/process-dump.txt
  echo -e "\nENV:" >> /tmp/evidence/process-dump.txt
  cat /proc/$pid/environ | tr '\0' '\n' >> /tmp/evidence/process-dump.txt
  echo -e "\n---" >> /tmp/evidence/process-dump.txt
done

# Извлечение подозрительного бинарного файла из файловой системы приложения
cp /proc/1/root/tmp/.hidden_miner /tmp/evidence/binary_sample 2>/dev/null || true

# Выгрузка архива доказательств наружу через stdout
tar -czf - /tmp/evidence | base64
```

### Сценарий 9: Настройка RBAC для регламентированного доступа SRE

**Контекст:** Предоставление дежурным инженерам прав на запуск эфемерных контейнеров без выдачи полных прав администратора кластера (`cluster-admin`).

```yaml
# rbac-ephemeral-containers.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: sre-debugger
rules:
  # Права на просмотр подов
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
  # Права на добавление эфемерных контейнеров
  - apiGroups: [""]
    resources: ["pods/ephemeralcontainers"]
    verbs: ["get", "update", "patch"]
  # Права на интерактивное подключение (attach/exec)
  - apiGroups: [""]
    resources: ["pods/attach", "pods/exec"]
    verbs: ["create", "get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: sre-debugger-binding
  namespace: production
subjects:
  - kind: Group
    name: sre-engineers
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: sre-debugger
  apiGroup: rbac.authorization.k8s.io
```

Проверка прав доступа:

```bash
kubectl auth can-i patch pods/ephemeralcontainers --as=engineer1 --as-group=sre-engineers -n production
# → yes
kubectl auth can-i delete pods --as=engineer1 --as-group=sre-engineers -n production
# → no
```

---

## Операции и команды

Справочная таблица типовых операций с `kubectl debug`:

| Команда | Описание | Ожидаемый результат |
| :--- | :--- | :--- |
| `kubectl debug -it <pod> --image=nicolaka/netshoot` | Запуск отладочного контейнера в сетевом пространстве Pod | Открытие интерактивной командной строки отладчика |
| `kubectl debug -it <pod> --image=alpine --target=<container>` | Подключение к PID-пространству целевого контейнера | Доступны процессы и `/proc/<PID>/root` целевого контейнера |
| `kubectl debug -it <pod> --image=alpine --profile=restricted` | Запуск в строгом PSA-пространстве (non-root) | Контейнер успешно стартует без блокировки Admission Webhook |
| `kubectl debug -it <pod> --image=netshoot --profile=netadmin` | Добавление capabilities `NET_ADMIN` и `NET_RAW` | Доступны утилиты `tcpdump`, `iptables`, манипуляции сокетами |
| `kubectl debug <pod> -it --copy-to=<clone> --share-processes` | Создание клона Pod с общим PID-пространством подов | Создан новый Pod `<clone>`, интерактивный вход в шелл |
| `kubectl debug <pod> --copy-to=<clone> --set-image=<c>=<img2>` | Замена образа проблемного контейнера на лету в клоне | Создан Pod `<clone>` с обновленным образом контейнера |
| `kubectl debug node/<node-name> -it --image=ubuntu:24.04` | Отладка хоста узла с монтированием хостового корня в `/host` | Создан привилегированный Pod на узле, доступ к `chroot /host` |
| `kubectl get pod <pod> -o jsonpath='{.status.ephemeralContainerStatuses}'` | Просмотр состояний всех эфемерных контейнеров Pod | JSON-массив со статусами (`running`, `terminated`, `waiting`) |
| `kubectl logs <pod> -c <debugger-name>` | Просмотр логов работы эфемерного контейнера | Вывод stdout/stderr завершенного или активного отладчика |

---

## Поиск и устранение неисправностей (Troubleshooting)

### 1. Ошибка 403 Forbidden: Запрет на уровне RBAC

* **Симптом:**
  ```text
  Error from server (Forbidden): pods "api-prod-58b99-k2x" is forbidden: User "dev-ops" cannot update resource "pods/ephemeralcontainers" in API group "" in the namespace "default"
  ```
* **Причина:** У сервисного аккаунта или пользователя отсутствуют права `update` или `patch` на подресурс `pods/ephemeralcontainers`.
* **Диагностика:**
  ```bash
  kubectl auth can-i update pods/ephemeralcontainers -n default
  # → no
  ```
* **Решение:** Добавьте разрешение на ресурс `pods/ephemeralcontainers` в ClusterRole/Role инженера (см. сценарий 9).

### 2. Отклонение Pod Security Admission (PSA Violation)

* **Симптом:**
  ```text
  Error from server (Forbidden): pods "payment-app" is forbidden: violates PodSecurity "restricted:latest": unrestricted capabilities (container "debugger" must set securityContext.capabilities.drop=["ALL"]), runAsNonRoot != true (container "debugger" must not set runAsUser=0)
  ```
* **Причина:** В Namespace активирована строгая политика безопасности `pod-security.kubernetes.io/enforce: restricted`. Запускаемый по умолчанию образ отладчика пытается стартовать от `root` или требует capabilities, нарушающих профиль.
* **Диагностика:**
  ```bash
  kubectl get ns default -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}'
  # → restricted
  ```
* **Решение:** Используйте флаг `--profile=restricted` или кастомный профиль с `runAsNonRoot: true`:
  ```bash
  kubectl debug -it payment-app --image=alpine:3.20 --profile=restricted
  ```

### 3. Целевой контейнер не найден (`container not found`)

* **Симптом:**
  ```text
  error: container "backend" not found in pod "payment-app"
  ```
* **Причина:** Опечатка в параметре `--target` или попытка привязаться к еще не инициализированному init-контейнеру.
* **Диагностика:**
  ```bash
  kubectl get pod payment-app -o jsonpath='{.spec.containers[*].name}'
  # → server worker
  ```
* **Решение:** Передайте точное имя существующего контейнера из спецификации Pod:
  ```bash
  kubectl debug -it payment-app --image=alpine:3.20 --target=server
  ```

### 4. Не видны процессы целевого контейнера при запуске без `--target`

* **Симптом:** Команда `ps aux` внутри эфемерного контейнера показывает только сам отладчик (`PID 1 /bin/sh`), процессы приложения отсутствуют.
* **Причина:** По умолчанию в Linux и Kubernetes каждый контейнер имеет изолированное пространство имен PID. Без флага `--target` или параметра `spec.shareProcessNamespace: true` контейнеры не видят чужие процессы.
* **Диагностика:**
  ```bash
  kubectl get pod payment-app -o jsonpath='{.spec.shareProcessNamespace}'
  # → (пусто или false)
  ```
* **Решение:**
  1. Обязательно указывайте `--target=<имя_контейнера>` при запуске:
     ```bash
     kubectl debug -it payment-app --image=nicolaka/netshoot --target=server
     ```
  2. Либо создайте копию пода с включенным шерингом процессов:
     ```bash
     kubectl debug payment-app -it --copy-to=debug-pod --share-processes --image=nicolaka/netshoot
     ```

### 5. Ошибка загрузки образа (ImagePullBackOff / ErrImagePull)

* **Симптом:**
  Эфемерный контейнер зависает в статусе `Waiting`, сессия shell не открывается:
  ```bash
  kubectl get pod payment-app -o jsonpath='{.status.ephemeralContainerStatuses[*].state.waiting.reason}'
  # → ImagePullBackOff
  ```
* **Причина:** Узел не имеет прямого доступа к публичному Docker Hub (`nicolaka/netshoot`), отсутствует корпоративный `imagePullSecrets` или указан несуществующий тег.
* **Диагностика:**
  ```bash
  kubectl describe pod payment-app | grep -A 5 "Ephemeral Containers"
  # → debugger:
  # →   State:          Waiting
  # →     Reason:       ImagePullBackOff
  # →   Message:        Failed to pull image "nicolaka/netshoot": rpc error: code = Unknown desc = failed to pull and unpack image
  ```
* **Решение:** Загружайте образы из внутреннего защищенного Container Registry:
  ```bash
  kubectl debug -it payment-app --image=registry.internal.corp/tools/netshoot:latest
  ```

### 6. Аварийное завершение эфемерного контейнера по OOMKilled (Exit Code 137)

* **Симптом:** Сессия отладки внезапно обрывается, контейнер переходит в статус `Terminated`:
  ```bash
  kubectl get pod payment-app -o jsonpath='{.status.ephemeralContainerStatuses[*].state.terminated}'
  # → {"exitCode":137,"reason":"OOMKilled","startedAt":"...","finishedAt":"..."}
  ```
* **Причина:** Запущенная утилита (например, `tcpdump` без лимита буфера или компилятор) превысила лимит оперативной памяти, либо исчерпала остаток памяти Pod cgroup.
* **Диагностика:**
  ```bash
  dmesg -T | grep -i oom | tail -n 10
  # → [Sat Oct 17 14:35:10 2026] Memory cgroup out of memory: Killed process 418291 (tcpdump) total-vm:268435kB
  ```
* **Решение:** Задавайте адекватные лимиты памяти через `--custom` или ограничивайте буферы сетевых утилит (`tcpdump -c 500 -W 2`).

### 7. Ошибка `Read-only file system` при сохранении дампов или логов

* **Симптом:**
  ```text
  / # tcpdump -w /app/capture.pcap
  tcpdump: /app/capture.pcap: Read-only file system
  ```
* **Причина:** Корневая файловая система приложения или монтируемый том защищены флагом `readOnlyRootFilesystem: true`.
* **Решение:** Сохраняйте дампы и артефакты во временную файловую систему самого отладочного контейнера (`/tmp`) или в примонтированный том `emptyDir`:
  ```bash
  tcpdump -i eth0 -w /tmp/capture.pcap
  ```

### 8. Эфемерный контейнер завершился (`Completed`), но висит в манифесте

* **Симптом:** Отладочный контейнер завершил работу, но отображается в `kubectl describe pod` и статусе подов. Попытка запустить его заново с тем же именем возвращает ошибку:
  ```text
  error: ephemeralcontainer "debugger" already exists
  ```
* **Причина:** Согласно архитектуре Kubernetes API, поле `spec.ephemeralContainers` является строго append-only. Завершенный эфемерный контейнер **нельзя удалить или перезапустить** без удаления всего Pod.
* **Решение:**
  1. Запускайте следующий контейнер с новым именем (по умолчанию `kubectl debug` генерирует случайный суффикс автоматически).
  2. Для полной очистки списка отладчиков выполните ротацию или перезапуск Pod (`kubectl rollout restart deployment/<name>`).

### 9. Сбой запуска отладки узла из-за Taints (`node had untolerated taint`)

* **Симптом:**
  ```text
  0/1 nodes available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }.
  ```
* **Причина:** На узле (например, Control Plane) установлен taints `NoSchedule`, а Pod `kubectl debug node/` не имеет соответствующих tolerations.
* **Решение:** Используйте кастомный манифест или передайте tolerations через `--custom`:
  ```yaml
  # tolerations-debug.yaml
  tolerations:
    - operator: Exists
  ```
  ```bash
  kubectl debug node/control-plane-01 -it --image=ubuntu:24.04 --custom=tolerations-debug.yaml
  ```

---

## Сравнение методов отладки Pod

| Метод | Создание нового Pod | Сохранение Pod IP | Доступ к FS целевого контейнера | Перезапуск процесса | Применение в Production |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Ephemeral Container (`kubectl debug <pod>`)** | **Нет** | **Да** | **Да** (через `/proc/<PID>/root`) | **Нет** | Основной инструмент ad-hoc диагностики живых Pod |
| **`kubectl exec`** | Нет | Да | Да (напрямую) | Нет | Быстрая проверка, если в образе есть `/bin/sh` |
| **Pod Clone (`kubectl debug --copy-to`)** | **Да** | Нет (новый IP) | Да (копия FS) | **Да** (любые args/env) | Анализ CrashLoopBackOff и replay сбойных запросов |
| **Node Debug (`kubectl debug node/`)** | Да (на узле) | N/A (хостовая сеть)| Доступ ко всей ноде (`/host`) | N/A | Инспекция ядра, Kubelet, CNI без прямого SSH |
| **`kubectl port-forward`** | Нет | Да | Нет | Нет | Подключение локальных профилировщиков, IDE и метрик |

---

## Best Practices для Production

1. **Принцип наименьших привилегий в RBAC:**
   * Никогда не выдавайте инженерам полные права `pods/exec` и `pods/ephemeralcontainers` на постоянной основе в sensitive namespaces.
   * Ограничивайте права на подресурс `pods/ephemeralcontainers` для конкретных групп SRE через RoleBinding в нужных пространствах имен.
2. **Аудит и контроль отладочных сессий:**
   * Включите аудит Kubernetes (`Audit Policy`) для отслеживания всех запросов к эндпоинту `pods/ephemeralcontainers`. Каждая отладочная сессия должна логироваться с фиксацией пользователя и времени.
   ```yaml
   # audit-policy.yaml
   apiVersion: audit.k8s.io/v1
   kind: Policy
   rules:
     - level: RequestResponse
       resources:
         - group: ""
           resources: ["pods/ephemeralcontainers"]
   ```
3. **Использование корпоративных Toolbox-образов:**
   * Не скачивайте случайные образы из публичных репозиториев на production-ноды во время инцидента (риск Supply Chain атак и таймаутов).
   * Соберите стандартизированный образ (например, `registry.company.local/ops/k8s-debug-toolbox:v1`), предварительно прогрейте (pre-pull) его на рабочих узлах через DaemonSet.
4. **Строгий контроль потребления ресурсов (Resource Limits):**
   * Всегда объявляйте `limits.memory` для эфемерного контейнера. Внезапный скачок памяти отладчика не должен вызывать падение соседнего высоконагруженного сервиса.
5. **Соответствие Pod Security Standards (PSA):**
   * Для namespaces уровня `restricted` используйте флаг `--profile=restricted`. Контейнер должен быть настроен на запуск от непривилегированного пользователя (`runAsNonRoot: true`).
6. **Гигиена кластера и очистка:**
   * Помните, что завершившийся эфемерный контейнер остается в метаданных Pod до момента его полного удаления.
   * После завершения сложной диагностики или профилирования запланируйте ротацию Pod (`kubectl delete pod <name>`), чтобы не накапливать отработавшие метаданные.

---

## Дополнительная информация

### Связанные темы в базе знаний

- [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — фазы Pod, статусы контейнеров и влияние cgroups.
- [Безопасность Pod Security Context](../../Security/pod_security_context.md) — уровни PSS/PSA, capabilities и параметры изоляции.
- [Реагирование на инциденты безопасности](../../Security/incident_response.md) — регламент сбора цифровых доказательств и forensic-анализ.
- [Практические команды управления Pod](./pod_practical_scenarios_commands.md) — манипуляции с подами и диагностика.
- [Паттерны Sidecar-контейнеров](./pod_sidecar_patterns.md) — сравнение нативных sidecar (1.28+) и вспомогательных контейнеров.
- [Общая методология Troubleshooting](../../Troubleshooting/troubleshooting_overview.md) — классификация и пошаговые алгоритмы локализации сбоев в Kubernetes.
- [Отладка образов Distroless](../../../Docker/Docker_troubleshooting/debugging_distroless.md) — специфика работы с контейнерами без shell в Docker/CRI.
