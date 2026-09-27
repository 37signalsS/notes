# Недоступность узла: Проблемы синхронизации времени

Расхождение времени (clock skew) между узлами кластера — одна из самых скрытых и трудноуловимых причин недоступности узлов. Несинхронизированное время приводит к отказу TLS-сертификатов, потере heartbeat-сигналов, рассинхронизации etcd и некорректной работе scheduler. Проблема маскируется как сетевая, сертификатная или проблема рантайма.

## Основные определения

**Clock Skew (Расхождение времени)** — разница во времени между двумя узлами. В Kubernetes допустимое расхождение обычно не превышает **10 секунд** (по умолчанию для `--cluster-signing-duration`). Более серьёзные расхождения вызывают ошибки TLS и отказ API-сервера.

**NTP (Network Time Protocol)** — протокол синхронизации времени через UDP порт 123. Используется для синхронизации часов узла с эталонными серверами времени. В продакшене рекомендуется минимум 2-3 NTP-сервера.

**Chrony** — современная замена ntpd. Более быстрая синхронизация ( секунды вместо минут), лучшая работа за NAT и при нестабильной сети. Рекомендуется для контейнерных сред.

**Leap Second** — високосная секунда, добавляемая для компенсации ускорения вращения Земли. Может вызывать до 1 секунды расхождения при обработке.

## Основные концепции

### Как время влияет на компоненты Kubernetes

| Компонент | Зависимость от времени | Последствие расхождения |
| :--- | :--- | :--- |
| **TLS/SSL** | Сертификаты проверяются по `NotBefore`/`NotAfter` | `x509: certificate has expired or is not yet valid`, `Unauthorized` |
| **etcd** | Raft consensus требует часовую синхронизацию | Лидер не избирается, split-brain, data inconsistency |
| **kube-apiserver** | Проверка timestamp запросов | Отклонение запросов, `Forbidden` ошибки |
| **kubelet** | Heartbeat (Lease) обновляется с timestamp | Узел помечается как `Unknown`, taint-based eviction |
| **scheduler** | Предпочтение узлов с меньшей нагрузкой | Некорректное планирование на узлы с неправильным временем |
| **controller-manager** | taint timers, graceful shutdown | Раннее или запоздалое выселение подов |
| **Pod security** | ServiceAccount token expirations | Токены отклоняются API-сервером |

### Типичные расхождения и их последствия

| Расхождение | Критичность | Последствие |
| :--- | :--- | :--- |
| < 1 секунда | Нет | Все работает нормально |
| 1-10 секунд | Низкая | Возможны единичные TLS-ошибки |
| 10-60 секунд | Средняя | TLS сертификаты отклоняются, heartbeat задерживается |
| 1-5 минут | Высокая | Узел уходит в `Unknown`, kubelet отключается от API |
| > 5 минут | Критическая | Массовое выселение подов, etcd теряет лидеров |

### Механизмы отслеживания времени в Kubernetes

| Механизм | Источник | Что отслеживает |
| :--- | :--- | :--- |
| **Lease renewTime** | kubelet → API | Время последнего heartbeat |
| **Node Status lastHeartbeatTime** | kubelet → API | Время обновления статуса |
| **Certificate expiration** | kube-apiserver | `NotBefore`/`NotAfter` сертификатов |
| **etcd leader election** | etcd cluster | Кворум и лидерство |
| **Pod terminationGracePeriodSeconds** | kubelet | Graceful shutdown |

## Практические сценарии

### Сценарий 1: TLS-ошибки из-за clock skew

**Симптом**: Kubelet не может авторизоваться в API-сервере. Логи: `x509: certificate has expired or is not yet valid`. Узел уходит в `Unknown`.

**Диагностика:**
```bash
# 1. Проверка времени на узле
date
# → Thu Sep  4 17:30:00 UTC 2026   ← может быть wrong

# 2. Проверка NTP-синхронизации
timedatectl status
# → Local time: Thu 2026-09-04 17:30:00 UTC
# → Universal time: Thu 2026-09-04 17:30:00 UTC
# → RTC time: Thu 2026-09-04 14:30:00   ← RTC отстаёт на 3 часа!
# → NTP service: active
# → Clock synchronized: no   ← НЕ синхронизирован!

# 3. Проверка chrony
chronyc tracking
# → Reference ID    : 0.0.0.0 ()
# → Last update     : 0 seconds ago
# → Leap status     : Not synchronised   ← НЕ синхронизирован!

# 4. Проверка временного расхождения с API-сервером
date -u && kubectl get nodes -o jsonpath='{.items[0].status.conditions[?(@.type=="Ready")].lastHeartbeatTime}'
# → Thu Sep  4 17:30:00 UTC 2026
# → 2026-09-04T14:30:00Z   ← расхождение 3 часа

# 5. Проверка сертификатов kubelet
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -text -noout | grep -A 2 "Validity"
# → Not Before: Sep  4 2025 17:30:00 GMT
# → Not After : Sep  4 2026 17:30:00 GMT
# Если текущее время > Not After — сертификат просрочен
```

**Решение:**
```bash
# 1. Немедленная синхронизация (если chrony установлен)
sudo chronyc makestep
# → 200 OK   ← время синхронизировано

# 2. Если chrony не установлен — ntpd
sudo ntpd -gq
# → -g: разрешить较大 расхождение при первом запуске

# 3. Ручная установка времени (если NTP недоступен)
sudo date -s "$(curl -s https://timeapi.io/api/time/current/zone?timeZone=UTC | jq -r .dateTime)"

# 4. Проверка восстановления
chronyc tracking | grep "Leap status"
# → Leap status     : Normal

# 5. Проверка TLS
kubectl get nodes
# → NAME    STATUS   ROLES    AGE   VERSION
# → node-1  Ready    worker   30d   v1.31.0
```

---

### Сценарий 2: etcd leader election failure

**Симптом**: Control plane не отвечает. `kubectl get nodes` показывает `The connection to the server was refused`. etcd pod в `CrashLoopBackOff` с ошибками лидер-выбора.

**Диагностика:**
```bash
# 1. Проверка времени на всех control plane узлах
for node in cp1 cp2 cp3; do
  echo "=== $node ==="
  ssh $node "timedatectl | grep 'Local time'"
done
# === cp1 ===
#    Local time: Thu 2026-09-04 17:30:00 UTC
# === cp2 ===
#    Local time: Thu 2026-09-04 17:30:00 UTC
# === cp3 ===
#    Local time: Thu 2026-09-04 17:25:00 UTC   ← отстаёт на 5 минут

# 2. Проверка логов etcd
kubectl logs -n kube-system etcd-cp1 | grep -i "election\|leader\|heartbeat"
# → etcdserver: scheduled election lost (took 5.001s)
# → etcdserver: failed to reach the peer <cp3:2379> (connection refused)

# 3. Проверка etcd через etcdctl
ETCDCTL_API=3 etcdctl endpoint health --endpoints=https://127.0.0.1:2379
# → https://127.0.0.1:2379 is unhealthy: failed to commit proposal:
# →   dial tcp 127.0.0.1:2379: connect: connection refused
```

**Решение:**
```bash
# 1. Синхронизировать время на проблемном узле
ssh cp3 "chronyc makestep"

# 2. Проверить, что etcd восстановился
ETCDCTL_API=3 etcdctl member list --endpoints=https://127.0.0.1:2379
# → 1, b2e1a4b5c6d7e8f0, started, cp1, https://cp1:2380, https://cp1:2379, false
# → 2, c3f2b5a6d7e8f901, started, cp2, https://cp2:2380, https://cp2:2379, false
# → 3, d4a3c6b7e8f90a12, started, cp3, https://cp3:2380, https://cp3:2379, false

# 3. Если etcd не восстановился — принудительный leave/join
etcdctl member remove <member-id> --endpoints=https://127.0.0.1:2379
etcdctl member add <node-name> --peer-urls=https://cp3:2380 --endpoints=https://127.0.0.1:2379
```

---

### Сценарий 3: Kubelet heartbeat задерживается

**Симптом**: Узел периодически переходит в `Unknown` на несколько минут, затем восстанавливается. События: `NodeUnknown`, `TaintManagerEviction`.

**Диагностика:**
```bash
# 1. Проверка времени Lease
kubectl get lease -n kube-node-lease <node> -o jsonpath='{.spec.renewTime}'
# → 2026-09-04T17:25:00Z   ← 5 минут назад

# 2. Проверка разницы времени между узлом и API-сервером
# На проблемном узле:
date +%s
# → 1725456300
# Через API:
kubectl get nodes -o jsonpath='{.items[?(@.metadata.name=="<node>")].status.conditions[?(@.type=="Ready")].lastHeartbeatTime}'
# → 2026-09-04T17:30:00Z
# Разница = 300 секунд = heartbeat обновлялся 5 минут назад

# 3. Проверка NTP на проблемном узле
chronyc tracking
# → System time : 0.000000000 seconds fast of NTP time
# → Last update : 600 seconds ago   ← обновление 10 минут назад
# → Stratum     : 0   ← не подключен к серверу

# 4. Проверка сети до NTP
chronyc sources
# → 210 Source     : 0.0.0.0
# → Reach    : 0   ← не可达
```

**Решение:**
```bash
# 1. Перезапуск chrony
sudo systemctl restart chronyd

# 2. Принудительная синхронизация
sudo chronyc makestep

# 3. Проверка конфигурации chrony
cat /etc/chrony.conf | grep -E "^server|^pool"
# → pool 2.pool.ntp.org iburst
# → pool time.google.com iburst

# 4. Если NTP-серверы недоступны — проверьте DNS
nslookup pool.ntp.org
# → Server:    10.233.0.10
# → Address:   10.233.0.10
# → Name:      pool.ntp.org
# → Address:   169.254.169.254   ← может быть fake IP из-за CoreDNS
```

---

### Сценарий 4: Application timestamp mismatch (Kafka, databases)

**Симптом**: Приложения в подах генерируют события с неправильными временными метками. Kafka consumer не может обработать сообщения. Базы данных отклоняют транзакции из-за расхождения `committed_at`.

**Диагностика:**
```bash
# 1. Проверка времени внутри пода
kubectl exec <pod> -- date -u
# → Thu Sep  4 14:30:00 UTC 2026   ← отстаёт от реального времени

# 2. Проверка NTP в контейнере (если есть)
kubectl exec <pod> -- chronyc tracking 2>/dev/null || echo "chrony не установлен в контейнере"

# 3. Проверка MTU (влияет на NTP-пакеты)
kubectl exec <pod> -- ping -M do -s 1472 pool.ntp.org
# → ping: local error: Message too long   ← MTU проблема

# 4. Проверка, что NTP не блокируется NetworkPolicy
kubectl get networkpolicy -A | grep -i ntp
# → если NetworkPolicy блокирует UDP 123 — NTP не работает
```

**Решение:**
```yaml
# Вариант 1: Добавить NTP в контейнер (если критично)
# spec:
#   containers:
#   - name: app
#     securityContext:
#       capabilities:
#         add: ["SYS_TIME"]   # требует privileged
#     command: ["chronyd", "-d"]

# Вариант 2: Установить hostTime в поде
# spec:
#   hostPID: false
#   hostIPC: false
#   containers:
#   - name: app
#     env:
#     - name: TZ
#       value: "UTC"
```

```bash
# Вариант 3: Добавить исключение NetworkPolicy для NTP
# apiVersion: networking.k8s.io/v1
# kind: NetworkPolicy
# metadata:
#   name: allow-ntp
#   namespace: production
# spec:
#   podSelector: {}
#   policyTypes:
#   - Egress
#   egress:
#   - to: []
#     ports:
#     - protocol: UDP
#       port: 123
```

---

### Сценарий 5: GRUB / RTC clock mismatch после перезагрузки

**Симптом**: После перезагрузки узла время сбивается на несколько часов. chrony не может синхронизироваться из-за большого расхождения.

**Диагностика:**
```bash
# 1. Проверка RTC (Hardware Clock)
hwclock --show
# → 2026-09-04 14:30:00.123456+03:00   ← RTC отстаёт

# 2. Проверка UTC vs Local в timedatectl
timedatectl | grep "RTC\|local"
# → RTC time: Thu 2026-09-04 14:30:00
# → Time zone: Europe/Moscow (MSK, +0300)
# → RTC in local TZ: no   ← правильно

# 3. Проверка dual boot (Windows/Linux)
# Если Windows установлен в localtime, RTC может быть в local time
timedatectl | grep "local"
# → RTC in local TZ: yes   ← проблема!
```

**Решение:**
```bash
# 1. Синхронизировать RTC с системным временем
sudo hwclock --systohc

# 2. Установить UTC для RTC
timedatectl set-local-rtc 0

# 3. Настройка chrony для быстрой синхронизации
echo "makestep 1 3" | sudo tee -a /etc/chrony.conf
# → разрешитьmakestep до 1 секунды в течение 3 перезапусков

# 4. Перезапустить chrony
sudo systemctl restart chronyd
```

## Мониторинг и алертинг

### Метрики времени

| Метрика (node_exporter) | Описание | Типичный порог алерта |
| :--- | :--- | :--- |
| `node_timex_offset_seconds` | Расхождение с NTP | > 0.1持续 5 минут |
| `node_timex_sync_status` | Статус синхронизации (1=sync) | == 0持续 5 минут |
| `node_timex_maxerror_seconds` | Максимальная ошибка времени | > 1持续 |
| `node_ntp_sanity` | Проверка NTP (1=ok) | == 0持续 |

### Примеры алертов (PrometheusRule)

```yaml
groups:
  - name: time-sync
    rules:
      - alert: NodeTimeSkew
        expr: abs(node_timex_offset_seconds) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Расхождение времени на {{ $labels.instance }} > 1 секунды"
          description: "Offset: {{ $value }} секунд. Возможны TLS-ошибки."

      - alert: NodeTimeNotSynchronized
        expr: node_timex_sync_status == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "NTP-синхронизация потеряна на {{ $labels.instance }}"
          description: "Узел не синхронизирован с NTP более 5 минут."

      - alert: NodeTimeSkewCritical
        expr: abs(node_timex_offset_seconds) > 10
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Критическое расхождение времени на {{ $labels.instance }}"
          description: "Offset > 10 секунд — возможны проблемы с etcd и TLS."

      - alert: KubeletLeaseStale
        expr: time() - kube_node_lease_renew_time > 60
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Lease узла {{ $labels.node }} устарел"
          description: "Lease не обновлялся > 1 минуты — возможны проблемы с NTP."
```

## Рекомендации по настройке

### Минимальная конфигурация chrony

```bash
# /etc/chrony.conf
# Источники времени (минимум 2)
pool 2.pool.ntp.org iburst
pool time.google.com iburst

# Разрешить быструю синхронизацию при старте
makestep 1 3

# Сохранять RTC синхронизированным
rtcsync

# Логирование
logdir /var/log/chrony
```

### Проверка после настройки

```bash
# 1. Запустить chrony
sudo systemctl enable --now chronyd

# 2. Дождаться синхронизации (обычно 5-10 секунд)
chronyc tracking | grep "Leap status"
# → Leap status     : Normal

# 3. Проверить sources
chronyc sources -v
# → ^* time.google.com    ...  2   6   377     -     +0ns[   +0ns] +/-    10ms
```

## Дополнительная информация

### Связанные разделы

- **[Проблемы Kubelet](./kubelet_issues.md)** — heartbeat и Lease зависят от синхронизации времени
- **[TLS и сертификаты](../../../Kubernetes/Operations/certificate_management.md)** — сертификаты проверяются по времени
- **[etcd troubleshooting](../../../etcd/troubleshooting.md)** — etcd требует синхронизированных часов
- **[Обслуживание узлов](./maintenance.md)** — время влияет на drain/uncordon
- **[NTP: Протокол](../../../Networking/Protocols/ntp.md)** — теория NTP
- **[Высокая доступность](../../../Concepts/High_Availability/ha_overview.md)** — кворум etcd зависит от времени
