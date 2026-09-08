# Диагностика ошибок загрузки образов (Image Pull Errors): Пошаговое руководство

## Определения

Основные понятия, термины и архитектурное взаимодействие Kubelet ↔ CRI приведены в разделе [Определения](./definitions.md). Краткая сводка терминов, используемых в данном руководстве:

| Термин | Определение |
| :--- | :--- |
| **ErrImagePull** | Непосредственная ошибка выполнения операции PullImage. Фиксируется в момент неудачной попытки. |
| **ImagePullBackOff** | Состояние ожидания с экспоненциальной задержкой (10s → 300s) после серии неудачных попыток. |
| **CRI** | Container Runtime Interface — gRPC-интерфейс между kubelet и рантаймом (containerd, CRI-O). |
| **imagePullSecret** | Secret типа `kubernetes.io/dockerconfigjson` с credentials для приватных реестров. Область видимости — Namespace. |
| **ImageGC** | Механизм kubelet, автоматически удаляющий неиспользуемые образы при превышении порогов `imagefs`. |

---

## Основные концепции

### Алгоритм системной диагностики

Диагностика в Kubernetes требует последовательного спуска по уровням абстракции — от симптома (Pod в статусе `ImagePullBackOff`) к корневой причине (DNS, TLS, auth, disk, CRI):

```
L1: API/Resource (Pod)
│   kubectl get pod, describe pod, events
│   → Определяем: ErrImagePull или ImagePullBackOff? Какой gRPC-код?
│
├─ L2: Authorization (Secrets)
│   │   Проверка imagePullSecrets, ServiceAccount, RBAC
│   │   → 401/403 → проблема credentials или прав доступа
│   │
│   ├─ L3: Infrastructure (Network)
│   │   │   DNS, Proxy, Firewall, MTU, conntrack
│   │   │   → timeout/refused → проблема сети
│   │   │
│   │   ├─ L4: Runtime Interface (CRI/gRPC)
│   │   │   │   Анализ логов containerd/CRI-O, crictl
│   │   │   │   → snapshotter errors, content verification
│   │   │   │
│   │   │   └─ L5: Host/Storage
│   │   │       Дисковое пространство, inodes, OverlayFS
│   │   │       → no space left, inode pressure
```

**Принцип:** Не пропускайте уровни. Частая ошибка — сразу лезть в `crictl` при проблеме, которая решается проверкой `imagePullSecrets`.

### Анализ статус-кодов gRPC в событиях

При взаимодействии Kubelet с рантаймом через CRI ошибки содержат gRPC-коды. Их понимание критично для быстрой локализации:

| Код gRPC | Интерпретация | Значение для анализа |
| :--- | :--- | :--- |
| `DeadlineExceeded` | Timeout | Проблемы сети, DNS, MTU или прокси. Проверяйте L3. |
| `Unauthenticated` | 401 Unauthorized | Неверный или отсутствующий `imagePullSecret`. Проверяйте L2. |
| `PermissionDenied` | 403 Forbidden | Учетная запись есть, но нет прав на Pull в реестре. |
| `NotFound` | 404 Not Found | Образ или тег не существует в реестре. |
| `ResourceExhausted` | No space | Переполнение диска на узле (`/var/lib/containerd`). |
| `Unavailable` | 429 Too Many Requests | Превышены лимиты частоты запросов (rate limit) реестра. |

### Система принятия решений: быстрая локализация по gRPC-коду

Получив gRPC-код из `kubectl describe pod` или логов, выполните соответствующую ветку:

| gRPC-код | Первый шаг | Второй шаг | Глубокая диагностика |
| :--- | :--- | :--- | :--- |
| `NotFound` | Проверить имя образа и тег в манифесте | `skopeo inspect docker://<image>` | Сценарий 1 |
| `Unauthenticated` | `kubectl get secret <name> -o json \| jq .data` | Проверить ServiceAccount | Сценарий 6 |
| `DeadlineExceeded` | `ping`, `nslookup` из узла | `tcpdump` на порту 443 | Сценарий 2, 7 |
| `ResourceExhausted` | `df -h /var/lib/containerd` | `crictl rmi --prune` | Сценарий 8 |
| `Unavailable` | Проверить rate limit реестра | Использовать authenticated pull | Сценарий 9 |

### Стандартный чек-лист при любом ImagePullBackOff

Независимо от gRPC-кода, первичный осмотр включает:

```bash
# 1. Статус и ожидание
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].state.waiting}'
# → {"reason":"ErrImagePull","message":"..."} — факт ошибки
# → {"reason":"ImagePullBackOff","message":"..."} — в back-off

# 2. Детали из Events
kubectl describe pod <pod-name> | grep -A 20 "Events:"
# Ищите: Failed to pull image, rpc error, Back-off pulling image

# 3. Имя образа и наличие секрета
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].image}{"\n"}{.spec.imagePullSecrets}'
# → nginx:1.25 [map[name:regcred]]
```

---

## Практические сценарии

### Сценарий 1: Инспекция через kubectl (L1-L2)

Первичный сбор данных без доступа к узлу. Этот этап определяет, является ли проблема сетевой или связанной с авторизацией/конфигурацией.

**1. Просмотр текущего статуса и причины ожидания:**
```bash
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].state.waiting}'
```
**Ожидаемый вывод (типичные варианты):**
```json
{"reason":"ErrImagePull","message":"rpc error: code = Unknown desc = failed to pull and unpack image ..."}
{"reason":"ImagePullBackOff","message":"Back-off pulling image \"registry.example.com/app:v1\""}
```

**2. Анализ событий (Events):**
```bash
kubectl get events --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp'
```
*Ищите события `Failed` и сообщения `rpc error`. Типичные паттерны:*
- `Failed to pull image "registry.io/app:v1": rpc error: code = NotFound` → образ/тег не найден
- `Failed to pull image "registry.io/app:v1": rpc error: code = Unauthenticated` → нет credentials
- `Failed to pull image "registry.io/app:v1": rpc error: code = DeadlineExceeded` → проблема сети
- `Back-off pulling image` →進入 ImagePullBackOff (ожидание перед следующей попыткой)

**3. Проверка цепочки секретов:**
```bash
# Проверка домена и auth-данных внутри секрета
kubectl get secret <secret-name> -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .auths
```
**Ожидаемый вывод:**
```json
{
  "auths": {
    "registry.example.com": {
      "auth": "YWRtaW46cGFzc3dvcmQ=",
      "email": ""
    }
  }
}
```
*Если `auths` пустой или отсутствует — Secret создан неверно.*

**4. Проверка ServiceAccount:**
```bash
kubectl get sa <sa-name> -o jsonpath='{.imagePullSecrets}'
```
**Ожидаемый вывод:**
```json
[{"name":"regcred"}]
```
*Если `imagePullSecrets` пустой, секрет не привязан к SA и должен быть указан в каждом Pod-манифесте.*

**5. Проверка типа и структуры Secret:**
```bash
kubectl get secret <secret-name> -o jsonpath='{.type}'
# → kubernetes.io/dockerconfigjson  (правильно)
# → Opaque                        (неверно — Secret создан не через kubectl create secret docker-registry)

# Декодирование и проверка Username:Password
kubectl get secret <secret-name> -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | \
  jq -r '.auths["registry.example.com"].auth' | base64 -d
# → admin:Harbor12345  (ожидаемый формат username:password)
```

### Сценарий 2: Сетевая отладка через эфемерные контейнеры (L3)

Использование `kubectl debug` позволяет запустить отладочный контейнер в сетевом пространстве имен целевого пода.

**Предусловие:** Под должен находиться в��态е `Running` (хотя бы один контейнер). Если все контейнеры в `ErrImagePull`, используйте отдельный под для диагностики:

```bash
kubectl run nettest --image=nicolaka/netshoot --rm -it --restart=Never -- bash
```

**Внутри отладочного контейнера:**

```bash
# 1. Проверка разрешения имён реестра
nslookup registry.example.com
# → Name:      registry.example.com
# → Address 1: 10.0.0.50    (правильно — IP реестра)

# 2. Проверка MTU (частая причина зависания при загрузке больших слоев)
ping -M do -s 1472 registry.example.com
# → Если пакеты не проходят — MTU на пути меньше 1500 (VXLAN, WireGuard)

# 3. Проверка TLS-цепочки и времени handshake
openssl s_client -connect registry.example.com:443 -showcerts </dev/null
# → Verify return code: 0 (ok)  — сертификат валиден
# → certificate chain: ...      — цепочка полная

# 4. Проверка доступности API v2 реестра
curl -sI https://registry.example.com/v2/
# → HTTP/1.1 200 OK             — API доступен
# → HTTP/1.1 401 Unauthorized   — нужна аутентификация (это нормально)
# → curl: (7) Failed to connect — реестр недоступен

# 5. Проверка прокси (если есть)
env | grep -i proxy
# → HTTPS_PROXY=http://proxy.local:3128
# Проверка: curl -x $HTTPS_PROXY -sI https://registry.example.com/v2/
```

**Типичные ошибки и их интерпретация:**
| Команда | Результат | Причина |
| :--- | :--- | :--- |
| `nslookup` | `SERVFAIL` / `NXDOMAIN` | DNS не резолвит реестр. Проверить CoreDNS. |
| `ping -M do -s 1472` | 100% loss | MTU < 1500. Проблема с CNI-туннелем. |
| `openssl s_client` | `handshake failure` | TLS-инспекция прокси подменяет сертификат. |
| `curl -sI` | `connection refused` | Firewall блокирует порт 443. |
| `curl -sI` | `certificate signed by unknown authority` | CA не добавлен в доверенное хранилище узла. |

### Сценарий 3: Глубокая диагностика на узле через crictl (L4)

Если проблема не на уровне Kubernetes (kubectl/kubelet), требуется инспекция рантайма на узле.

**1. Подключение к узлу с системным профилем:**
```bash
kubectl debug node/<node-name> -it --image=busybox --profile=sysadmin
# Внутри: chroot /host
```

**Альтернатива (прямой SSH):**
```bash
ssh <node-name>
# Все команды ниже выполняются от root
```

**2. Проверка статуса рантайма:**
```bash
# containerd работает?
systemctl status containerd
# → active (running)  — OK
# → inactive (dead)   — запустить: systemctl start containerd

# crictl connectivity
crictl info | jq .config.containerd
# → Должна вернуть конфигурацию containerd
```

**3. Инспекция манифеста и архитектуры образа:**
Частая проблема: образ скачан, но не запускается из-за несоответствия архитектуры (например, `arm64` на `amd64`).
```bash
crictl inspecti <image-id> | jq .info.labels
# → "io.containerd.os": "linux"
# → "io.containerd.arch": "amd64"    — архитектура образа
# → Сверить с архитектурой узла: uname -m
```

**4. Ручная проверка Pull с логированием:**
```bash
# Попытка пулла через CRI с явными кредами
crictl pull --creds "user:pass" registry.example.com/my-app:1.0
# → FATA[0000] pulling image: rpc error: code = NotFound
# → Проблема с именем/тегом образа

# Pull с debug-логированием (containerd)
crictl --debug pull registry.example.com/my-app:1.0 2>&1 | tee /tmp/pull-debug.log
# Анализ лога: DNS resolve, TLS handshake, HTTP status codes
```

**5. Проверка локального кэша:**
```bash
# Список образов, доступных рантайму
crictl images | grep my-app
# → registry.example.com/my-app   1.0    abc123def456   150MB  10 seconds ago

# Если образ есть, но pod его не видит — проверьте namespace в containerd
sudo ctr -n k8s.io images ls | grep my-app
# → registry.example.com/my-app:1.0  (должен быть в namespace k8s.io)
```

### Сценарий 4: Отладка Kubelet и CRI (L4-L5)

При сложных ошибках (например, таймауты gRPC или ошибки snapshotter) необходимо повысить уровень логирования Kubelet.

**1. Временное повышение verbosity Kubelet (без перезагрузки):**
```bash
# На узле через SSH/Debug
# ВНИМАНИЕ: Работает только если Kubelet поддерживает runtime-конфигурацию
# (обычно доступно в kubeadm-кластерах)
curl -X PUT http://localhost:10248/debug/flags/v -d "4"
# → OK  (повышен уровень логирования до 4)

# Проверка текущего уровня
curl -s http://localhost:10248/debug/flags/v
# → 4
```

**2. Анализ системных логов:**
```bash
# Логи containerd с фокусом на ошибки snapshotter и pull
journalctl -u containerd -g "error|snapshot|pull" --since "30 min ago"

# Логи Kubelet с фокусом на CRI и pull-операции
journalctl -u kubelet -f | grep -E "PullImage|ErrImagePull|ImagePullBackOff"

# С фильтрацией по конкретному образу
journalctl -u containerd --since "10 min ago" | grep -i "my-app"
```

**3. Проверка состояния OverlayFS/snapshotter:**
```bash
# Проверка использования OverlayFS
df -h /var/lib/containerd
# → /dev/sda1   100G   65G   30G  69% /var/lib/containerd

# Информация о snapshotter
crictl info | jq -r '.config.containerd.plugins."io.containerd.snapshotter.v1.overlayfs"'
# → Должна содержать конфигурацию snapshotter

# Проверка inodes (частая причина "no space left" при достаточном месте)
df -ih /var/lib/containerd
# → /dev/sda1   6.5M   340K   6.2M   6% /var/lib/containerd
# → Если inodes > 90% — проблема с количеством мелких файлов
```

### Сценарий 5: Диагностика DNS для реестра (L3)

DNS — самая частая причина ошибок `no such host` и косвенная причина таймаутов.

**1. Проверка DNS из тестового пода:**
```bash
kubectl run dns-test --image=busybox --rm -it --restart=Never -- \
  nslookup registry.example.com
# → Name:      registry.example.com
# → Address 1: 10.0.0.50
# Или:
# ** server can't find registry.example.com: NXDOMAIN
```

**2. Проверка CoreDNS:**
```bash
kubectl get pods -n kube-system -l k8s-app=kube-dns
# → coredns-abc123   1/1     Running   0   5d

kubectl logs -n kube-system -l k8s-app=kube-dns --tail=20
# Ищите: plugin/errors, SERVFAIL, refused
```

**3. Проверка NodeLocal DNSCache (если используется):**
```bash
kubectl get daemonset -n kube-system node-local-dns
# → node-local-dns   6/6     6       6       6d

kubectl logs -n kube-system -l k8s-app=node-local-dns --tail=20
# Ищите: error, connection refused, timeout
```

**4. Проверка DNS с узла (где работает kubelet):**
```bash
# Резолв имени реестра
nslookup registry.example.com
# → должен вернуть IP

# Проверка /etc/resolv.conf
cat /etc/resolv.conf
# → nameserver 10.96.0.10    (CoreDNS Service IP)
# → search kube-system.svc.cluster.local svc.cluster.local cluster.local
# → options ndots:5 timeout:2 attempts:2

# Латентность DNS
dig +stats registry.example.com | grep "Query time"
# → Query time: 2 msec  (< 10 мс — норма)
# → Query time: 250 msec (аномалия — проверить upstream DNS)
```

**5. Быстрое решение — добавить в /etc/hosts (временно):**
```bash
echo "10.0.0.50 registry.example.com" >> /etc/hosts
# Это обходит DNS. Используйте только для отладки.
```

### Сценарий 6: Диагностика ошибок авторизации (401/403) (L2)

**1. Проверка типа Secret:**
```bash
kubectl get secret <secret-name> -o jsonpath='{.type}'
# → kubernetes.io/dockerconfigjson  (правильно)
# → Opaque                        (неверно — Secret не для registry)
```

**2. Декодирование и валидация credentials:**
```bash
kubectl get secret <secret-name> -o jsonpath='{.data.\.dockerconfigjson}' | \
  base64 -d | jq .
# → Должен содержать валидный JSON с auths и полем auth (base64 username:password)

# Проверка декодированного auth
kubectl get secret <secret-name> -o jsonpath='{.data.\.dockerconfigjson}' | \
  base64 -d | jq -r '.auths["registry.example.com"].auth' | base64 -d
# → admin:Harbor12345  (ожидаемый формат)
```

**3. Проверка домена в Secret:**
```bash
# Имя реестра в Secret должно совпадать с префиксом image в Pod
kubectl get secret <secret-name> -o jsonpath='{.data.\.dockerconfigjson}' | \
  base64 -d | jq '.auths | keys'
# → ["registry.example.com"]

# Имя образа в Pod
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].image}'
# → registry.example.com/my-app:v1.0

# Префикс образа ДОЛЖЕН совпадать с ключом в auths
```

**4. Прямой тест credentials через crictl:**
```bash
# На узле
TOKEN=$(kubectl get secret <secret-name> -o jsonpath='{.data.\.dockerconfigjson}' | \
  base64 -d | jq -r '.auths["registry.example.com"].auth' | base64 -d)
crictl pull --creds "$TOKEN" registry.example.com/my-app:v1.0
# → Image is up to date  (credentials валидны)
# → FATA[0000] unauthorized  (credentials невалидны)
```

**5. Массовая проверка секретов в кластере:**
```bash
# Список всех Secret типа docker-registry
kubectl get secrets -A --field-selector type=kubernetes.io/dockerconfigjson \
  -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,AGE:.metadata.creationTimestamp

# Проверка ServiceAccount с imagePullSecrets
kubectl get sa -A -o json | \
  jq -r '.items[] | select(.imagePullSecrets != null) |
    "\(.metadata.namespace)/\(.metadata.name): \([.imagePullSecrets[].name] | join(", "))"'
# → kube-system/default: regcred-cluster
# → production/app-sa: regcred-prod
```

### Сценарий 7: Сетевая диагностика — таймауты и MTU (L3)

**Симптом:** Pull зависает на длительное время, затем завершается с `i/o timeout` или `DeadlineExceeded`.

**1. Проверка маршрута и связности:**
```bash
# Маршрут до реестра
ip route get 10.0.0.50
# → 10.0.0.50 via 10.0.0.1 dev eth0 src 10.0.0.100

# TCP-тест
curl -vI --max-time 5 https://registry.example.com/v2/
# → HTTP/1.1 200 OK  (связность есть)
# → curl: (28) Operation timed out  (нет связности)
```

**2. Проверка MTU (PMTUD):**
```bash
# Стандартный Ethernet MTU
ping -M do -s 1472 -c 3 registry.example.com
# → 0% packet loss  — MTU >= 1500
# → 100% packet loss — MTU < 1500 (проблема)

# С учётом VXLAN (MTU обычно 1450)
ping -M do -s 1422 -c 3 registry.example.com
# → 0% packet loss  — MTU >= 1450
```

**3. Проверка conntrack (при массовых pull):**
```bash
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → count = 48230, max = 65536  (74% — на грани)
# → count < max * 0.75           (норма)

# Дропы conntrack
dmesg | grep -i "nf_conntrack: table full"
# → nf_conntrack: table full, dropping packet  (проблема)
```

**4. Проверка ephemeral port range:**
```bash
sysctl net.ipv4.ip_local_port_range
# → net.ipv4.ip_local_port_range = 32768  60999  (28 232 портов)

# Использование
ss -s | grep "timewait"
# → TCP:   28400 (estab 4000, closed 12000, orphaned 0, timewait 12000)
# → Если timewait > 20000 — возможны проблемы с портами
```

### Сценарий 8: Диагностика disk pressure и ImageGC (L5)

**Симптом:** Поды получают `ErrImagePull` с `no space left on device`, хотя `df -h` на корне показывает достаточно места.

**1. Проверка disk usage на imagefs:**
```bash
# Проверка раздела с образами
df -h /var/lib/containerd
# → /dev/sda1   100G   92G    5G  95% /var/lib/containerd  (КРИТИЧНО)

# Проверка inodes
df -ih /var/lib/containerd
# → /dev/sda1   6.5M   6.3M   200K  97% /var/lib/containerd  (INODE PRESSURE)
```

**2. Проверка состояния ImageGC:**
```bash
# Сколько образов на узле
kubectl get node <node-name> -o jsonpath='{.status.images[*].names}' | tr ' ' '\n' | wc -l
# → 150  (нормально)
# → 500+  (возможно, GC не работает или пороги слишком высоки)

# Пороги GC в конфигурации kubelet
cat /var/lib/kubelet/config.yaml | grep -A 4 "imageGC"
# → imageGCHighThresholdPercent: 85
# → imageGCLowThresholdPercent: 80
```

**3. Очистка и освобождение места:**
```bash
# Удаление неиспользуемых образов
sudo crictl rmi --prune
# → Removed: sha256:abc123...  (удалены неиспользуемые)

# Принудительная очистка через containerd
sudo ctr -n k8s.io images gc

# Проверка размера кэша образов после очистки
du -sh /var/lib/containerd/
# → 25G /var/lib/containerd/  (было 92G)
```

**4. Проверка условий Node:**
```bash
kubectl get node <node-name> -o json | jq '.status.conditions[] | select(.type | contains("Pressure"))'
# → {"type":"DiskPressure","status":"False",...}  — нет давления
# → {"type":"DiskPressure","status":"True",...}    — есть давление
```

### Сценарий 9: Диагностика rate limit (429 Too Many Requests) (L2-L3)

**Симптом:** Поды падают с `toomanyrequests: You have reached your pull rate limit` (Docker Hub) или `429 Too Many Requests`.

**1. Проверка rate limit (Docker Hub):**
```bash
# Анонимный запрос — лимит 100 pull/6h
curl -sI https://registry-1.docker.io/v2/library/nginx/manifests/latest | grep -i ratelimit
# → X-RateLimit-Limit: 100
# → X-RateLimit-Remaining: 3   (осталось 3 pull)
# → X-RateLimit-Reset: 1693800000  (время сброса)

# Авторизованный запрос — лимит 200 pull/6h
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)
curl -sI -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/manifests/latest | grep -i ratelimit
# → X-RateLimit-Limit: 200
# → X-RateLimit-Remaining: 199
```

**2. Проверка количества pull-секретов:**
```bash
# Все Secret типа docker-registry
kubectl get secrets -A --field-selector type=kubernetes.io/dockerconfigjson | wc -l
# → 5  (нормально)
# → 50+ (возможно, проблемы с ротацией)
```

**3. Решения:**
- Использовать `imagePullSecret` даже для Docker Hub (лимит увеличивается со 100 до 200)
- Настроить pull-through cache (Harbor proxy cache) для локального кэширования
- Перейти на `imagePullPolicy: IfNotPresent` для версионных тегов

### Сценарий 10: Диагностика ошибок Admission Controller (L1-L2)

**Симптом:** Под не создаётся, в Events видно `FailedCreate` или `Error from server (Forbidden)`, но `imagePullSecrets` и образ валидны.

**1. Проверка Events на блокировку:**
```bash
kubectl describe pod <pod-name> | grep -A 10 "Events:"
# → Warning  FailedCreate  Error creating: admission webhook "kyverno-svc.kyverno.svc" denied the request:
#   [require-image-source] pod failed validation: registry 'docker.io' is not in the allowed list
```

**2. Проверка политик Kyverno/OPA/Gatekeeper:**
```bash
# Kyverno
kubectl get cpol -o yaml | grep -A 10 "image"
# → name: restrict-image-registries
# → pattern: harbor.local/* | registry.k8s.io/*

# Gatekeeper
kubectl get constraints -o wide | grep image
```

**3. Проверка ImagePolicyWebhook:**
```bash
# Конфигурация Admission Controller
kubectl get -n kube-system configmap kubeadm-config -o yaml | grep -A 5 "admission"
```

**4. Быстрая проверка — dry-run:**
```bash
kubectl apply -f pod.yaml --dry-run=server 2>&1 | grep -i "denied\|forbidden"
# → error: pods "test-pod" is forbidden: ...  (admission блокирует)
# → pod/test-pod created (dry run)            (admission не блокирует)
```

---

## Дополнительная информация

### Полный чек-лист диагностики ImagePull (от простого к сложному)

| Шаг | Команда | Что проверяет | Ожидаемый результат |
| :--- | :--- | :--- | :--- |
| 1 | `kubectl describe pod <pod>` → Events | Конкретное сообщение ошибки | `manifest unknown`, `unauthorized`, `i/o timeout`, `no space left` |
| 2 | `kubectl get pod -o jsonpath='{.spec.containers[*].image}'` | Имя образа | Корректное имя, тег, registry |
| 3 | `kubectl get secret <name> -o jsonpath='{.data.\.dockerconfigjson}' \| base64 -d` | Валидность credentials | JSON с `auths` и `auth` (base64 username:password) |
| 4 | `kubectl get sa <sa-name> -o jsonpath='{.imagePullSecrets}'` | Привязка секрета к SA | Secret name в списке |
| 5 | `skopeo inspect docker://<image>` (с dev-машины) | Образ доступен в реестре | JSON с метаданными |
| 6 | `crictl pull <image>` (на проблемном узле) | Pull на уровне CRI | `Image is up to date` |
| 7 | `crictl images \| grep <image>` | Образ в локальном кэше | Образ присутствует |
| 8 | `df -h /var/lib/containerd; df -ih /var/lib/containerd` | Дисковое пространство | < 85% использования |
| 9 | `nslookup registry.example.com` (с узла) | DNS-резолв | IP-адрес реестра |
| 10 | `journalctl -u containerd --since "10 min ago"` | Логи рантайма | Нет ошибок TLS/rate limit/snapshotter |
| 11 | `kubectl get cpol` (если Kyverno) | Admission политики | Образ не блокируется политикой |

### Эскалация: сбор диагностического bundle

Если стандартные шаги 1-11 не дали результата:

```bash
# Сбор информации для эскалации
kubectl get pod <pod-name> -o yaml > pod.yaml
kubectl describe pod <pod-name> > pod-describe.txt
kubectl get events --field-selector involvedObject.name=<pod-name> > events.txt
sudo crictl info > crictl-info.txt
sudo crictl images > crictl-images.txt
sudo ctr -n k8s.io images ls > ctr-images.txt
journalctl -u kubelet --since "30 min ago" > kubelet.log
journalctl -u containerd --since "30 min ago" > containerd.log
df -h > disk-usage.txt
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max > conntrack.txt
```

### Связанные темы

- [Определения и базовые концепции](./definitions.md) — терминология, жизненный цикл pull, gRPC-коды.
- [Распространённые ошибки](./common_errors.md) — классификация ошибок (404, 401, 403, 429) и сценарии решений.
- [Сетевые проблемы](./network_issues.md) — настройка DNS, MTU, прокси, conntrack и NIC offload.
- [Лучшие практики](./best_practices.md) — предотвращение ошибок: imagePullPolicy, secrets, ImageGC, мониторинг.
- [Air-gapped кластеры](./airgapped.md) — диагностика и конфигурация в изолированных средах.
- [Интеграция с CI/CD](./ci_cd_integration.md) — race conditions, secret rotation, Wait-for-image.
- [Среды выполнения контейнеров](../../../Concepts/container_runtime.md) — архитектура CRI, containerd и низкоуровневая отладка.
