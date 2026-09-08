# kube-proxy: Сетевой прокси Kubernetes

## Определения

**kube-proxy** — сетевой агент, работающий как DaemonSet на каждом узле кластера Kubernetes. Отвечает за реализацию концепции Service, перехватывая трафик, направленный на виртуальные IP-адреса (ClusterIP, NodePort, LoadBalancer) и перенаправляя его на конкретные поды-эндпоинты.

**Userspace режим** — устаревший режим работы kube-proxy, при котором проксирование выполняется в пространстве пользователя (процесс kube-proxy). Использует tcp/udp прокси и устанавливает соединения с подами. Не рекомендуется для production из-за низкой производительности.

**iptables режим** — режим, при котором kube-proxy управляет цепочками правил iptables/netfilter в ядре Linux для перехвата и трансляции пакетов. Является стандартным выбором для большинства кластеров.

**IPVS режим** — высокопроизводительный режим, использующий модуль ядра IPVS (IP Virtual Server) с хеш-таблицами для балансировки трафика. Рекомендуется для кластеров с thousands сервисов.

**nftables режим** — современный режим (Kubernetes 1.31+), заменяющий iptables. Использует фреймворк nftables с атомарными обновлениями правил и O(1) производительностью.

**eBPF режим (kube-proxy replacement)** — режим, при котором функции kube-proxy полностью заменяются eBPF-программами (Cilium, Calico eBPF). Обеспечивает максимальную производительность и расширенные возможности.

**EndpointSlice** — масштабируемый ресурс Kubernetes, разбивающий большие списки эндпоинтов на несколько объектов. Снижает нагрузку на API-сервер и kube-proxy при обновлении.

**conntrack (Connection Tracking)** — подсистема ядра Linux для отслеживания состояния сетевых соединений. Используется kube-proxy для корректной маршрутизации ответных пакетов и реализации NAT.

**DNAT (Destination NAT)** — механизм трансляции целевого IP-адреса в заголовке пакета. Используется kube-proxy для перенаправления трафика от ClusterIP на реальные IP подов.

**SNAT (Source NAT)** — механизм трансляции исходного IP-адреса. Применяется при `externalTrafficPolicy: Cluster` для сохранения обратной маршрутизации.

**Session Affinity** — механизм привязки клиента к конкретному поду по IP-адресу. Реализуется через запись в conntrack или хеш-таблицу IPVS.

---

## Основные концепции

### Архитектура и место в сетевом стеке

kube-proxy работает на каждом узле и взаимодействует с API-сервером для отслеживания изменений в Service и EndpointSlice. При изменении состояния kube-proxy обновляет правила сетевого стека на узле.

```
Клиент → Service ClusterIP → kube-proxy (правила) → Pod IP
```

kube-proxy НЕ обрабатывает трафик напрямую — он лишь настраивает правила в ядре (iptables, IPVS, nftables), которые перехватывают пакеты и перенаправляют их.

### Режимы работы

#### 1. iptables режим (по умолчанию)

**Принцип работы:**
- kube-proxy создает цепочки правил в таблице `nat` и `filter`
- Для каждого ClusterIP создается DNAT-правило
- Балансировка: случайный выбор из доступных эндпоинтов (random)

**Преимущества:**
- Простота настройки и отладки
- Низкие накладные расходы (ядро обрабатывает пакеты)
- Широкая поддержка дистрибутивов Linux

**Недостатки:**
- Линейный поиск правил O(n) — деградация при >5000 сервисов
- Полная перезапись правил при каждом обновлении (кратковременная потеря трафика)
- Ограниченные алгоритмы балансировки (только random)

**Когда использовать:**
- Малые и средние кластеры (<500 сервисов)
- Когда требуется максимальная совместимость
- Ограниченные требования к производительности

#### 2. IPVS режим

**Принцип работы:**
- kube-proxy создает виртуальные сервисы (Virtual Server) в таблице IPVS
- Для каждого ClusterIP создается запись с указанием алгоритма балансировки
- Эндпоинты добавляются как реальные серверы (Real Server)

**Алгоритмы балансировки IPVS:**

| Алгоритм | Код | Описание | Когда использовать |
| :--- | :--- | :--- | :--- |
| Round Robin | rr | Поочередное распределение | По умолчанию, большинство сценариев |
| Weighted Round Robin | wrr | С весами эндпоинтов | Разные мощности подов |
| Least Connection | lc | Наименьшее количество соединений | Долгоживущие соединения |
| Source Hashing | sh | Хеш по Source IP | Session Affinity |
| Destination Hashing | dh | Хеш по Destination IP | Редко используется |
| Shortest Expected Delay | sed | Минимальная ожидаемая задержка | Высоконагруженные сервисы |
| Never Queue | nq | Нет очередей, прямая передача | Максимальная производительность |

**Преимущества:**
- O(1) сложность поиска (хеш-таблицы)
- Инкрементальное обновление правил (без потери трафика)
- Широкий выбор алгоритмов балансировки
- Масштабируемость до десятков тысяч сервисов

**Недостатки:**
- Требует установки дополнительных пакетов (ipset, ipvsadm)
- Зависимость от модулей ядра (ip_vs, nf_conntrack)
- Более сложная отладка по сравнению с iptables

**Когда использовать:**
- Кластеры с >500 сервисов
- Требования к высокой производительности балансировки
- Необходимость разных алгоритмов (lc для БД, sh для сессий)

#### 3. nftables режим (Kubernetes 1.31+)

**Принцип работы:**
- Использует фреймворк nftables вместо iptables
- Атомарные обновления правил (без промежуточных состояний)
- Оптимизированный синтаксис и производительность

**Преимущества:**
- O(1) производительность через sets и maps
- Атомарные обновления (нет деградации при обновлении)
- Современный синтаксис и расширяемость
- Лучшая интеграция с containerd и CRI

**Недостатки:**
- Требует ядро Linux 5.10+ (рекомендуется 5.15+)
- Ограниченная поддержка в старых дистрибутивах
- Меньшее количество документации и сообщества

**Когда использовать:**
- Современные кластеры на Kubernetes 1.31+
- Требования к атомарным обновлениям
- Высокие нагрузки с частыми изменениями сервисов

#### 4. eBPF режим (kube-proxy replacement)

**Принцип работы:**
- kube-proxy полностью отключается
- eBPF-программы (Cilium, Calico eBPF) обрабатывают трафик
- Балансировка, NAT и политики реализуются в ядре

**Преимущества:**
- Максимальная производительность (O(1), без контекстных переключений)
- Расширенные возможности (L7-инспекция, Service Mesh)
- Видимость трафика на всех уровнях
- Замена kube-proxy, iptables, conntrack

**Недостатки:**
- Требует ядро Linux 5.10+ (рекомендуется 6.1+)
- Сложность отладки eBPF-программ
- Зависимость от конкретного CNI (Cilium, Calico)

**Когда использовать:**
- Высоконагруженные кластеры (>1000 узлов)
- Требования к L7-видимости и безопасности
- Использование Cilium или Calico с eBPF

### Взаимодействие с CNI

kube-proxy работает на транспортном уровне (L4), обеспечивая балансировку трафика между подами. CNI-плагин (Calico, Cilium, Flannel) отвечает за сетевую связность между узлами и подами.

**Порядок обработки пакета:**
1. Пакет поступает на сетевой интерфейс узла
2. CNI обрабатывает маршрутизацию (VXLAN/BGP/native)
3. kube-proxy применяет правила DNAT/SNAT
4. Пакет доставляется в network namespace пода

### Conntrack и NAT

kube-proxy полагается на `nf_conntrack` для отслеживания соединений:

- **DNAT**: При первом запросе kube-proxy создает запись conntrack с маппингом ClusterIP → Pod IP
- **Обратный трафик**: Ядро использует запись conntrack для маршрутизации ответа обратно
- **Session Affinity**: Запись conntrack сохраняется на время жизни TCP-соединения

**Проблемы conntrack:**
- Переполнение таблицы при большом количестве соединений
- Race conditions в UDP (особенно для DNS)
- Долгие таймауты для TCP (по умолчанию 5 дней)

### Hairpin NAT

Механизм, позволяющий поду обращаться к ClusterIP сервиса, в котором он участвует:

1. Под отправляет пакет на ClusterIP
2. kube-proxy (DNAT) перенаправляет пакет на тот же под (или другой)
3. Ядро распознает, что источник и цель — один под
4. Пакет маршрутизируется через loopback интерфейс

**Реализация:** `--hairpin-mode=hairpin-veth` (по умолчанию) — создает veth-пару с промискуитетным режимом.

---

## Предварительные требования

### Программные требования

*   **Kubernetes:** Версия 1.20+ для стабильной работы всех режимов
*   **Ядро Linux:**
    *   iptables: 4.19+ (рекомендуется 5.10+)
    *   IPVS: 4.19+ с модулями `ip_vs`, `nf_conntrack`
    *   nftables: 5.10+ (рекомендуется 5.15+)
    *   eBPF: 5.10+ (рекомендуется 6.1+)
*   **Пакеты:**
    *   IPVS: `ipset`, `ipvsadm`
    *   nftables: `nftables`
    *   eBPF: `bpftool` (для диагностики)

### Проверка текущего состояния

```bash
# Проверка версии kube-proxy
kubectl -n kube-system get pods -l k8s-app=kube-proxy -o wide

# Проверка режима работы
kubectl -n kube-system get configmap kube-proxy -o yaml | grep mode

# Проверка наличия CNI с eBPF заменой
kubectl -n kube-system get pods -l k8s-app=cilium -o wide
```

---

## Практические сценарии

### 1. Определение текущего режима работы

```bash
# Проверка ConfigMap
kubectl -n kube-system get configmap kube-proxy -o yaml | grep -A 5 'mode:'

# Проверка логов kube-proxy
kubectl -n kube-system logs -l k8s-app=kube-proxy --tail=50 | grep -i "mode"

# Проверка на узле
sudo iptables-save -t nat | grep KUBE-SVC | head -5
# → Если есть правила KUBE-SVC — это iptables режим

sudo ipvsadm -Ln | head -5
# → Если есть виртуальные сервисы — это IPVS режим

sudo nft list tables | grep kube-proxy
# → Если есть таблица kube-proxy — это nftables режим

sudo bpftool prog list | grep cilium
# → Если есть eBPF-программы Cilium — это eBPF режим
```

### 2. Переключение с iptables на IPVS

**Шаг 1: Подготовка узлов**
```bash
# Установка пакетов на всех узлах
sudo apt-get update && sudo apt-get install -y ipset ipvsadm

# Загрузка модулей ядра
cat <<EOF | sudo tee /etc/modules-load.d/ipvs.conf
ip_vs
ip_vs_rr
ip_vs_wrr
ip_vs_sh
nf_conntrack
EOF

sudo modprobe ip_vs ip_vs_rr ip_vs_wrr ip_vs_sh nf_conntrack
```

**Шаг 2: Обновление ConfigMap**
```bash
kubectl -n kube-system get configmap kube-proxy -o yaml | \
  sed 's/mode: ""/mode: "ipvs"/' | \
  kubectl apply -f -

# Или декларативно:
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: kube-proxy
  namespace: kube-system
data:
  config.conf: |
    kind: KubeProxyConfiguration
    mode: "ipvs"
    ipvs:
      strictARP: true
      scheduler: "rr"
      syncPeriod: 30s
      minSyncPeriod: 2s
EOF
```

**Шаг 3: Перезапуск kube-proxy**
```bash
kubectl -n kube-system rollout restart daemonset/kube-proxy
kubectl -n kube-system rollout status daemonset/kube-proxy
```

**Шаг 4: Валидация**
```bash
# Проверка IPVS сервисов
sudo ipvsadm -Ln
# → Prot LocalAddress:Port Scheduler Flags
#   -> RemoteAddress:Port           Forward Weight ActiveConn InActConn
# TCP  10.96.0.1:443 rr
#   -> 192.168.1.10:6443            Masq    1      0          0

# Проверка conntrack
sudo conntrack -C
# → 342
```

### 3. Включение strictARP для MetalLB

```bash
# Обновление ConfigMap
kubectl -n kube-system get configmap kube-proxy -o yaml | \
  sed 's/strictARP: false/strictARP: true/' | \
  kubectl apply -f -

# Перезапуск
kubectl -n kube-system rollout restart daemonset/kube-proxy

# Проверка
kubectl -n kube-system get configmap kube-proxy -o yaml | grep strictARP
# → strictARP: true
```

### 4. Настройка Session Affinity

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  selector:
    app: my-app
  ports:
  - port: 80
    targetPort: 8080
  sessionAffinity: ClientIP
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 10800  # 3 часа
```

**Проверка:**
```bash
# Для IPVS
sudo ipvsadm -Ln --stats | grep -A 2 "10.96.0.1:80"
# → Все запросы от одного IP идут на один Pod

# Для iptables
sudo iptables-save -t nat | grep KUBE-SEP | grep -A 5 "10.96.0.1:80"
```

### 5. Диагностика проблем с kube-proxy

#### Проблема: Трафик не балансируется

```bash
# Проверка правил kube-proxy
sudo iptables-save -t nat | grep KUBE-SVC | wc -l
# → Должно быть > 0 для каждого сервиса

# Проверка эндпоинтов
kubectl get endpoints my-service
# → Должны быть указаны IP подов

# Проверка логов
kubectl -n kube-system logs -l k8s-app=kube-proxy --tail=100 | grep -i error
```

#### Проблема: IP конфликт

```bash
# Проверка ARP-таблицы
arping -D <ip>
# → 0 = адрес свободен, 1 = адрес занят

# Проверка conntrack
sudo conntrack -L -p tcp --dport 80 | head -10
```

#### Проблема: Высокий CPU на kube-proxy

```bash
# Проверка частоты обновлений
kubectl -n kube-system logs -l k8s-app=kube-proxy | grep -c "syncProxyRules"

# Увеличение интервала синхронизации
kubectl -n kube-system get configmap kube-proxy -o yaml | \
  sed 's/syncPeriod: 30s/syncPeriod: 60s/' | \
  kubectl apply -f -
```

### 6. Переход на nftables (Kubernetes 1.31+)

```bash
# Проверка поддержки ядром
uname -r
# → 5.15.0+ (рекомендуется)

# Проверка наличия nftables
which nft
# → /usr/sbin/nft

# Обновление ConfigMap
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: kube-proxy
  namespace: kube-system
data:
  config.conf: |
    kind: KubeProxyConfiguration
    mode: "nftables"
    nftables:
      syncPeriod: 30s
      minSyncPeriod: 2s
EOF

# Перезапуск
kubectl -n kube-system rollout restart daemonset/kube-proxy
```

### 7. Отключение kube-proxy (eBPF режим)

**Важно:** Отключение kube-proxy возможно только при использовании CNI с поддержкой eBPF (Cilium, Calico eBPF).

```bash
# Установка Cilium с заменой kube-proxy
helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --set kubeProxyReplacement=strict

# Проверка отсутствия kube-proxy
kubectl -n kube-system get pods -l k8s-app=kube-proxy
# → No resources found

# Проверка eBPF-программ
sudo bpftool prog list | grep cilium
# → cilium_xdp
# → cilium_tc
```

---

## Диагностика и устранение неполадок

### Инструменты диагностики

| Инструмент | Назначение | Пример использования |
| :--- | :--- | :--- |
| `iptables-save` | Просмотр правил iptables | `sudo iptables-save -t nat \| grep KUBE` |
| `ipvsadm` | Просмотр таблиц IPVS | `sudo ipvsadm -Ln --stats` |
| `nft` | Просмотр правил nftables | `sudo nft list tables` |
| `conntrack` | Просмотр таблицы соединений | `sudo conntrack -L -p tcp --dport 80` |
| `bpftool` | Просмотр eBPF-программ | `sudo bpftool prog list \| grep cilium` |
| `ip addr` | Просмотр сетевых интерфейсов | `ip addr show kube-ipvs0` |

### Типичные проблемы и решения

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Трафик не балансируется** | kube-proxy не обновил правила | `ipvsadm -Ln`; `kubectl logs -n kube-system -l k8s-app=kube-proxy` | Перезапустить kube-proxy; проверить syncPeriod |
| **Connection timeout** | conntrack переполнен | `conntrack -C` vs `sysctl net.netfilter.nf_conntrack_max` | Увеличить `nf_conntrack_max` |
| **502/503 при удалении пода** | Нет graceful termination | `kubectl describe pod <pod>`; `ipvsadm -Ln --stats` (InActConn растет) | Настроить `terminationGracePeriodSeconds` |
| **ARP-конфликт** | strictARP отключен | `arping -D <vip>`; проверка логов | Включить `strictARP: true` |
| **Высокий CPU на kube-proxy** | Большой churn сервисов | `top`/`htop`; `kubectl get events` | Увеличить `minSyncPeriod`; перейти на nftables/eBPF |
| **Пакеты теряются** | Неправильный MTU | `ping -M do -s 1400 <pod-ip>`; `tcpdump` | Настроить MTU с учетом VXLAN overhead |
| **kube-proxy не стартует** | Отсутствуют модули ядра | `dmesg \| grep -i ip_vs`; `lsmod \| grep ip_vs` | Установить пакеты, загрузить модули |

### Мониторинг kube-proxy

```bash
# Метрики kube-proxy (если включены)
kubectl -n kube-system port-forward svc/kube-proxy-metrics:10249

# Prometheus метрики
# kube_proxy_sync_proxy_rules_duration_seconds
# kube_proxy_sync_proxy_rules_total
# kube_proxy_service_changes_total
# kube_proxy_endpoint_changes_total

# Алерты (пример)
- alert: KubeProxySyncTooSlow
  expr: rate(kube_proxy_sync_proxy_rules_duration_seconds_sum[5m]) > 0.5
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "kube-proxy слишком долго синхронизирует правила"
```

---

## Рекомендации и очистка

### Рекомендации для production

1. **Для кластеров <500 сервисов:** Используйте iptables режим — простота и стабильность
2. **Для кластеров >500 сервисов:** Переключайтесь на IPVS или nftables
3. **Для максимальной производительности:** Используйте eBPF режим (Cilium/Calico)
4. **Всегда включайте strictARP:** При использовании MetalLB L2
5. **Настройте minSyncPeriod:** Увеличьте до 5-10s для снижения нагрузки на API-сервер
6. **Мониторьте conntrack:** Установите алерты на 80% использования `nf_conntrack_max`
7. **Избегайте частых обновлений:** Каждое обновление Service вызывает пересчет правил

### Очистка среды

```bash
# Удаление старых правил iptables (при переключении режимов)
sudo iptables-save | grep -v KUBE | sudo iptables-restore

# Очистка ipset
sudo ipset destroy KUBE-LOOP-BACK
sudo ipset destroy KUBE-MARK-MASQ

# Очистка IPVS
sudo ipvsadm -C

# Очистка conntrack
sudo conntrack -F

# Перезапускkube-proxy для применения изменений
kubectl -n kube-system rollout restart daemonset/kube-proxy
```

---

## Крайние случаи и ограничения

1. **Исчерпание conntrack:** При неверно рассчитанном `nf_conntrack_max` новые соединения будут сбрасываться. Мониторьте `conntrack -C` и настраивайте алерты.

2. **ARP флуд при strictARP: false:** В L2-средах без `strictARP` несколько узлов могут отвечать на ARP-запросы для одного VIP, вызывая флуд и нестабильную работу MetalLB.

3. **UDP и задержки:** Для UDP-трафика (например, CoreDNS) могут возникать race conditions в conntrack. Рекомендуется использовать **NodeLocal DNSCache**.

4. **Совместимость ядра:** Для стабильной работы IPVS требуется ядро 4.19+ с поддержкой `CONFIG_IP_VS` и `CONFIG_NF_CONNTRACK`. Всегда проверяйте `uname -r` и `zgrep CONFIG_IP_VS /boot/config-$(uname -r)`.

5. **Взаимодействие с NetworkPolicy:** kube-proxy отвечает только за балансировку L4. Сетевые политики (`NetworkPolicy`) по-прежнему реализуются CNI-плагином через `iptables`, `ipset` или `eBPF`.

6. **Hairpin NAT в IPVS:** Требует включенного `masquerade` или явной настройки `--hairpin-mode`. Проверяйте с помощью тестового пода внутри того же namespace.

7. **Обновление kube-proxy:** При переключении между режимами (iptables → IPVS) необходим полный перезапуск DaemonSet. During rollout возможны кратковременные задержки в маршрутизации.

---

## Дополнительные сведения

### Сравнение режимов работы

| Критерий | iptables | IPVS | nftables | eBPF |
| :--- | :--- | :--- | :--- | :--- |
| **Масштабируемость** | Низкая (O(n)) | Высокая (O(1)) | Высокая (O(1)) | Очень высокая (O(1)) |
| **Обновление правил** | Полная перезапись | Инкрементально | Атомарно | Мгновенно |
| **Алгоритмы** | Только случайный | Множество | Случайный/Round Robin | Любая логика |
| **Зависимости** | Встроено в ядро | Модули ядра + ipset | Ядро 5.x+ | Ядро 5.10+ |
| **Сложность отладки** | Низкая | Средняя | Средняя | Высокая |
| **Рекомендуемый Kubernetes** | Все версии | 1.20+ | 1.31+ | 1.28+ |

### См. также

- [IPAM в Kubernetes](./ipam.md) — управление IP-адресами подов
- [Cilium: eBPF CNI](./cilium.md) — замена kube-proxy через eBPF
- [IPVS в Kubernetes](./ipvs.md) — детали работы IPVS режима
- [NetworkPolicy](./network_policy.md) — сетевые политики (L3/L4)
- [Service: ClusterIP](../Service/service_type_clusterip.md) — виртуальные IP и балансировка

**[К списку разделов CNI](../cni_kube_proxy_roles.md)**
