# Ошибки загрузки образов (Image Pull Errors): Сетевые проблемы

## Определения

**Сетевые проблемы (в контексте Image Pull)** — совокупность факторов на уровне сетевой инфраструктуры узла или кластера, препятствующих успешному обмену данными между агентом `kubelet` (через Container Runtime) и реестром образов.

**MTU (Maximum Transmission Unit)** — максимальный размер полезного блока данных одного пакета. Несоответствие MTU (например, из-за оверхеда инкапсуляции VXLAN/Geneve в CNI) часто приводит к "зависанию" загрузки больших слоев образа или обрыву TLS Handshake.

**Egress Traffic** — исходящий трафик от узлов кластера. Загрузка образов инициируется на уровне ОС узла, поэтому правила фильтрации должны учитывать доступ к внешним эндпоинтам реестра.

**PMTUD (Path MTU Discovery)** — механизм определения минимального MTU на всем пути следования пакета. Блокировка ICMP сообщений (Fragmentation Needed) ломает этот механизм, создавая "черные дыры" в сети.

---

## Основные концепции

### Классификация сетевых сбоев

| Категория | Сообщение об ошибке | Корневая причина |
| :--- | :--- | :--- |
| **DNS** | `no such host` | Неверные upstream DNS на узле или проблемы с резолвом внешних имен. |
| **Маршрутизация** | `no route to host` | Отсутствие маршрута к сети реестра или некорректная таблица маршрутизации. |
| **Таймауты** | `connection timed out` | Блокировка порта 443 на внешнем Firewall или некорректный MTU. |
| **Proxy** | `503 Service Unavailable` | Ошибки на стороне прокси-сервера или отсутствие настроек прокси в рантайме. |
| **TLS/SSL** | `handshake timeout` / `unknown authority` | Проблемы MTU на этапе обмена большими сертификатами или отсутствие CA. |

### Особенности сетевого пути загрузки

Процесс **Image Pull происходит вне сетевого пространства имен пода (Pod Network Namespace)**. Запрос выполняется процессом рантайма (containerd/CRI-O) в сетевом пространстве имен хоста.
- `NetworkPolicy` уровня пода **не влияет** на возможность загрузки образа самим `kubelet`.
- Влияние оказывают только `GlobalNetworkPolicy` (Cilium/Calico) или правила `iptables`/`nftables` хоста.
- **TLS Handshake & MTU:** Пакеты `Server Hello`, содержащие цепочки сертификатов, часто превышают 1500 байт. Если на пути есть туннель (например, VXLAN с MTU 1450) и PMTUD сломан, соединение зависнет именно на этапе Handshake.

### Конфигурация DNS-резолвера на уровне узла

Контейнерный рантайм (`containerd`/`CRI-O`) **не наследует DNS-конфигурацию из CNI / CoreDNS**. Резолв имени реестра выполняется на уровне хоста с использованием `/etc/resolv.conf`, `nsswitch.conf` и активного резолвера. Любая ошибка в этих файлах приводит к `no such host` ещё до попытки TCP-соединения.

**Что проверять в `/etc/resolv.conf`:**

| Параметр | Назначение | Типичная ошибка |
| :--- | :--- | :--- |
| `nameserver` | Upstream DNS-сервер (обычно CoreDNS Service IP `10.96.0.10` или внешний) | Указывает на недоступный адрес; пакет `udp/53` блокируется egress policy. |
| `search` | Домены-суффиксы для коротких имён | Слишком длинный список (5+ записей) → `getaddrinfo` делает десятки попыток. |
| `ndots` | Порог "короткого" имени. Если в имени точек `< ndots`, резолвер сначала пробует `search` | `ndots: 1` по умолчанию → `registry.local` резолвится как `registry.local.svc.cluster.local.svc.cluster.local` прежде чем попробовать A-запись напрямую. |
| `options` | `timeout:N` (по умолчанию 5s), `attempts:N` (по умолчанию 2), `rotate` | `timeout:5 attempts:2` × 3 search-домена = до 30 секунд на одну ошибку. |

**Решение для ускорения резолва в кластере:**

```bash
# Пример оптимизированного /etc/resolv.conf узла Kubernetes
cat /etc/resolv.conf
# nameserver 10.96.0.10        # CoreDNS Service IP
# search kube-system.svc.cluster.local svc.cluster.local cluster.local
# options ndots:5 timeout:2 attempts:2
```

`ndots: 5` — стандартный кластерный `node-local-resolver` паттерн: имена вида `my-svc.my-ns.svc.cluster.local` (4 точки) резолвятся напрямую, короткие имена — через `search`.

**Проверка активного резолвера:**

```bash
# Кто реально обслуживает DNS на узле
systemctl status systemd-resolved
cat /run/systemd/resolve/resolv.conf   # Если активен systemd-resolved
# Иначе напрямую:
cat /etc/resolv.conf

# Какой резолвер отвечает на запрос
dig +short registry.example.com
# → 10.0.0.50   (правильный ответ)
# → ;; connection timed out; no servers could be reached   (проблема)

# Латентность DNS (5 попыток)
for i in $(seq 1 5); do dig +stats +time=2 registry.example.com | grep "Query time"; done
# → Query time: 1 msec
# → Query time: 2 msec     # < 10 мс — норма для in-cluster
# → Query time: 250 msec   # аномалия
```

**Особенности `systemd-resolved`:**

`systemd-resolved` в современных дистрибутивах перехватывает `/etc/resolv.conf` через симлинк на `/run/systemd/resolve/stub-resolv.conf`. Контейнерный рантайм может **не ходить через stub**, если переменные окружения systemd-unit'ы содержат `SYSTEMD_OFFLINE=1` или рантайм явно вызывает `getaddrinfo` напрямую в обход nsswitch. Проверка:

```bash
# Должен возвращать "glibc", НЕ "systemd"
getent hosts registry.example.com
# Если долго — резолвер работает через nss-systemd (дополнительный слой)
# Решение: /etc/nsswitch.conf содержит "hosts: files dns myhostname" (убрать [!unavail] для systemd)
```

### Conntrack: влияние на массовый pull

При pull одного большого образа на 100+ узлах ядро создаёт **N × M** записей в conntrack-таблице (N = число узлов, M = число одновременных TCP-соединений к реестру). При превышении лимита `nf_conntrack_max` новые соединения молча отбрасываются → `connection timed out` без ICMP-ответа.

**Когда это критично:**

- Cluster autoscaler поднимает 10–50 новых узлов одновременно.
- DaemonSet-обновление или HPA-scale → одновременный pull на сотнях подов.
- Pull через NAT-шлюз (все узлы за одним SNAT IP) → лимит на gateway, не на узле.

**Диагностика:**

```bash
# Текущее состояние и лимит
sysctl net.netfilter.nf_conntrack_count
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_count = 48230
# → net.netfilter.nf_conntrack_max = 65536

# Дропы (требует nf_conntrack_acct=1)
sysctl net.netfilter.nf_conntrack_buckets
# Если count/max > 0.75 — на грани переполнения

# Лог переполнений
dmesg | grep -E "nf_conntrack: table full|dropping packet"
# → nf_conntrack: table full, dropping packet   (причина i/o timeout)
```

**Тюнинг (увеличение лимита):**

```bash
cat /etc/sysctl.d/99-conntrack-tuning.conf
# net.netfilter.nf_conntrack_max = 524288        # 512k записей
# net.netfilter.nf_conntrack_buckets = 131072    # max/4 (степень двойки)
# net.netfilter.nf_conntrack_tcp_timeout_established = 7200
# net.netfilter.nf_conntrack_tcp_timeout_time_wait = 60
# net.netfilter.nf_conntrack_tcp_timeout_close_wait = 30
sysctl --system
```

**Тюнинг для pull-операций (ускорение освобождения записей):**

| Параметр | Default | Для pull-heavy кластера | Назначение |
| :--- | :--- | :--- | :--- |
| `nf_conntrack_tcp_timeout_established` | 432000 (5 дней) | 7200 (2 часа) | Долгие keep-alive соединения к реестру редки. |
| `nf_conntrack_tcp_timeout_time_wait` | 120 | 30 | Быстрее освобождает сокеты. |
| `nf_conntrack_tcp_timeout_close_wait` | 60 | 15 | Аналогично. |
| `nf_conntrack_buckets` | max/4 | max/4 | Должен быть степенью двойки; иначе хеш-цепочки деградируют. |

### TCP-таймауты и эфемерные порты

**Эфемерные порты** (`ip_local_port_range`) исчерпываются при массовых параллельных соединениях. По умолчанию в Linux: `32768–60999` (28 232 порта). При pull 100+ слоёв на одном узле через один registry каждое соединение = один порт; на 2-3 минутах можно исчерпать диапазон.

**Диагностика:**

```bash
# Текущий диапазон
sysctl net.ipv4.ip_local_port_range
# → net.ipv4.ip_local_port_range = 32768	60999

# Использование
ss -s
# → TCP:   5000 (estab 4000, closed 800, orphaned 0, timewait 200)
# → TCP выделяет range 32768-60999 → max ~28k сокетов

# Счётчик исчерпания
nstat -az | grep -E "TcpExtListenOverflows|TcpExtListenDrops"
# → TcpExtListenOverflows = 0      # норм
# → TcpExtListenOverflows > 0      # порты кончились, часть connect() не сработала
```

**Тюнинг:**

```bash
cat /etc/sysctl.d/99-tcp-tuning.conf
# net.ipv4.ip_local_port_range = 1024 65535     # расширить до 64k
# net.ipv4.tcp_tw_reuse = 1                     # переиспользовать TIME_WAIT для исходящих (безопасно)
# net.ipv4.tcp_max_tw_buckets = 200000          # не уходить в RST
# net.ipv4.tcp_fin_timeout = 15                 # ускорить TIME_WAIT
# net.ipv4.tcp_slow_start_after_idle = 0        # не сбрасывать cwnd на keep-alive
sysctl --system
```

**TCP_USER_TIMEOUT** — таймаут, после которого ядро закрывает неактивное соединение. Имеет решающее значение, если пакеты теряются (типично для беспроводных / WAF / rate-limiter'ов).

```bash
# По умолчанию: max(20*TCP_RTO_min, 5*TCP_RTO_max) ≈ 30-60 сек
# Для pull через нестабильный канал — увеличить
ip route change default via 10.0.0.1 dev eth0 tcp_user_timeout 300000
# 300 сек — таймаут на бездействие unacked data
# Проверить:
ip route show
ss -ti dst registry.example.com
# → cubic wscale:7,7 rto:204 rtt:1.25/0.75 ato:40 cwnd:10 mss:1448
```

### Offload'ы сетевой карты и их влияние на диагностику

NIC-offload'ы (TSO, GSO, LRO, GRO, Checksum Offload) **прозрачно ускоряют передачу**, но **ломают tcpdump**: большие сегменты на интерфейсе не видны, фрагментация MTU теряется в Wireshark. Это критично при диагностике "зависания" именно на этапе TLS.

**Команды:**

```bash
# Какие offload'ы включены на интерфейсе
ethtool -k eth0 | grep -E "tcp-segmentation|generic-receive|large-receive|scatter-gather|checksum"
# → tcp-segmentation-offload: on
# → generic-receive-offload: on
# → large-receive-offload: off
# → tx-checksumming: on
# → rx-checksumming: on

# Временное отключение для отладки (НЕ применять на production-нагрузке)
ethtool -K eth0 tso off gso off gro off
# После отладки — вернуть:
ethtool -K eth0 tso on gso on gro on
```

**Влияние на pull:**

- **TSO/GSO** — узел собирает большие сегменты (>64k), ядро и MTU-логика работают с ними, но **фактический кадр в проводе** фрагментирован NIC'ом. tcpdump без `-k` не покажет эту фрагментацию.
- **LRO/GRO** — обратная сторона: NIC агрегирует несколько TCP-пакетов в один большой "суперпакет" до передачи в ядро. tcpdump покажет его как один пакет, хотя в проводе их было несколько.
- **RX Checksum Offload** — при приёме пакета с битым чеком NIC отбрасывает его без уведомления tcpdump. Видно как "selective ACK без доставки".

**Практический рецепт для дампа TLS-квика:**

```bash
# Захват TLS Client Hello (запрос с SNI)
tcpdump -ni any -s 0 -w /tmp/pull.pcap "host registry.example.com and tcp port 443"
# -k отключает checksum offload, чтобы видеть битые пакеты
# Дополнительный фильтр на момент pull
crictl pull registry.example.com/my-app:1.0
# Остановить tcpdump, открыть в Wireshark

# Извлечь SNI из pcap
tshark -r /tmp/pull.pcap -Y "tls.handshake.type==1" -T fields -e tls.handshake.extensions_server_name | sort -u
# → registry.example.com
# Если SNI = другой домен — ищем, кто перенаправил трафик (прокси/WAF)
```

### Hairpin NAT для on-prem pull-through cache

В on-prem кластерах с pull-through cache (Harbor, Nexus) часто возникает проблема **hairpin NAT**: pod не может достучаться до registry по ClusterIP сервиса, потому что source-NAT подменяет IP пода, и трафик зацикливается.

**Проблема (на примере Harbor):**

```
Pod (10.244.1.5) → Harbor Service (10.96.50.20:443)
  → kube-proxy DNAT → Pod backend (10.244.1.50:443)
  → Pod backend видит src=10.244.1.5, отвечает напрямую на 10.244.1.5
  → Pod 10.244.1.5 ждёт ответ от 10.96.50.20, получает от 10.244.1.50 → RST
```

**Применимо к pull только частично** (image pull идёт с узла, не из пода), но важно для **второго случая**: встроенный puller подов при `imagePullPolicy: Always` и init-контейнерах, которые тянут дополнительные образы через `Service ClusterIP`.

**Решения:**

| CNI | Параметр | Где задать |
| :--- | :--- | :--- |
| **Calico** | `hairpin` в FelixConfig | `kubectl patch felixconfiguration default --type=merge -p '{"spec":{"hairpinEnabled":true}}'` |
| **Cilium** | `enable-hairpin` (по умолчанию true) | Helm values `enable-hairpin: true` |
| **Flannel** | Не поддерживается нативно | Только hostPort + ExternalIP |
| **Generic (kube-proxy IPVS)** | `sysctl net.ipv4.vs.nexthdr` / Hairpin через iptables MASQUERADE | `iptables -t nat -A POSTROUTING -s 10.244.0.0/16 ! -d 10.244.0.0/16 -j MASQUERADE` |

**Альтернатива для pull:** выделить отдельный `ServiceExternalIP` или `Endpoint` registry с прямым IP и подключать через `hostAliases` на узле.

### Резюме: анатомия сетевого пути image pull

```
┌─────────────────────── Узел (host network namespace) ───────────────────────┐
│                                                                              │
│  1. containerd                                                              │
│     └─ getaddrinfo("registry.example.com")  ← /etc/resolv.conf, nsswitch    │
│     └─ connect(IP:443)                       ← ip_local_port_range, conntrack│
│        └─ IP-маршрутизация                  ← ip rule, ip route             │
│           └─ iptables/nftables OUTPUT       ← egress filtering              │
│              └─ HTTP/HTTPS-прокси?          ← http_proxy env, NO_PROXY      │
│                 └─ ICMP Fragmentation Needed?  ← PMTUD, MTU на пути         │
│                    └─ TLS Client Hello + cert chain                         │
│                       └─ TCP RST / 5xx / chunked download                   │
│                                                                              │
│  NIC Offload'ы: TSO/GSO/LRO/GRO/CHECKSUM                                   │
│  Конкуренция за порты: ip_local_port_range, tcp_tw_buckets                 │
│  Конкуренция за conntrack: nf_conntrack_max, hashsize                      │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

Диагностика ВСЕГДА начинается с проверки **порядка слоёв** сверху вниз: сначала DNS (`dig`/`getent`), потом маршрут (`ip route get`), потом TCP-соединение (`curl -v` / `crictl pull --debug`), потом трафик на проводе (`tcpdump -k`).

---

## Практические сценарии

### Сценарий 1: Диагностика MTU и TLS Handshake

**Симптом:** Маленькие слои скачиваются, но на больших загрузка "зависает". Или соединение обрывается сразу после `Client Hello`.

**1. Проверка MTU через ping (DF bit):**
```bash
# Тест для стандартного Ethernet (1500 - 28 байт заголовков = 1472)
ping -s 1472 -M do registry.example.com
# Если пакеты не проходят, ищем лимит (например, 1422 для VXLAN)
ping -s 1422 -M do registry.example.com
```

**2. Прямая проверка TLS через openssl:**
```bash
openssl s_client -connect registry.example.com:443 -showcerts
```
*Если команда зависает после вывода "CONNECTED", это верный признак проблемы с MTU на этапе передачи сертификатов.*

**Решение:** Установите MTU 1450 (или ниже) в конфигурации CNI (Calico/Cilium) и на сетевых интерфейсах узлов.

### Сценарий 2: Настройка Proxy для containerd и CRI-O

Переменные окружения должны быть заданы в systemd-юните рантайма.

**1. Для containerd:**
Создайте файл `/etc/systemd/system/containerd.service.d/http-proxy.conf`:
```ini
[Service]
Environment="HTTP_PROXY=http://proxy.local:3128"
Environment="HTTPS_PROXY=http://proxy.local:3128"
Environment="NO_PROXY=localhost,127.0.0.1,10.96.0.0/12,192.168.0.0/16,<NODE_IPS>,.svc,.cluster.local"
```

**2. Для CRI-O:**
Аналогично в `/etc/systemd/system/crio.service.d/http-proxy.conf`.

**Важно по NO_PROXY:**
- Должны быть включены CIDR подов и сервисов.
- **Обязательно** включите IP-адреса всех узлов кластера и API Server, иначе Kubelet не сможет взаимодействовать с рантаймом через прокси.

**Применение:**
```bash
systemctl daemon-reload && systemctl restart containerd # или crio
```

### Сценарий 3: Оптимизация резолва (IPv4 Precedence)

Если узел имеет IPv6 адрес, но внешняя сеть его не поддерживает, попытки резолва `AAAA` записей могут вызывать задержки.

**Диагностика:**
```bash
time dig AAAA registry.example.com
```

**Решение (Принудительный приоритет IPv4):**
Отредактируйте `/etc/gai.conf`, раскомментировав или добавив строку:
```text
precedence ::ffff:0:0/96 100
```
Это заставит системный резолвер предпочитать IPv4 при наличии обоих типов записей.

### Сценарий 4: Тестирование связности через crictl

`crictl` позволяет исключить влияние логики Kubernetes и проверить рантайм напрямую.

```bash
# Пулл с замером времени и детальным выводом
time crictl pull registry.example.com/my-app:1.0
```
*Если crictl скачивает образ успешно, но Pod висит в ImagePullBackOff — проверьте imagePullSecrets в манифесте.*

### Сценарий 5: TLS-инспекция на корпоративном прокси ломает pull (x509: signed by unknown authority)

**Симптом:** На тестовом узле (без прокси) pull проходит. На production-узлах с egress-интерцептором — `x509: certificate signed by unknown authority` или `connection reset by peer` на этапе TLS.

**Корневая причина:** Squid/WPAD/Bro/Bluecoat в режиме TLS-инспекции подменяет сертификат сервера своим корпоративным CA. Контейнерный рантайм доверяет только системным CA (`/etc/ssl/certs/ca-certificates.crt` или `/etc/pki/tls/certs/ca-bundle.crt`).

**Пошаговая диагностика:**

```bash
# 1. Проверить, активен ли HTTP_PROXY в окружении containerd
systemctl show containerd | grep -i environment
# → Environment=HTTPS_PROXY=http://proxy.corp:3128

# 2. Какой CA доверяет containerd
ls -la /etc/containerd/certs.d/ 2>/dev/null   # кастомные CA
ls -la /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt 2>/dev/null
# Один из этих файлов должен содержать корпоративный CA

# 3. Достать корпоративный CA из браузера / Puppet / Ansible
# Обычно доступен по http://proxy.corp:8080/ca.crt или в корпоративном GitLab

# 4. Положить CA в доверенное хранилище на каждом узле
sudo cp corp-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates     # Debian/Ubuntu
# или
sudo cp corp-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust            # RHEL/Fedora

# 5. Перезапустить containerd (НЕ kubelet — он читает корневой trust напрямую)
sudo systemctl restart containerd
```

**Альтернативный способ — настройка `NO_PROXY` для исключения реестра из перехвата:**

```ini
# /etc/systemd/system/containerd.service.d/http-proxy.conf
[Service]
Environment="HTTP_PROXY=http://proxy.corp:3128"
Environment="HTTPS_PROXY=http://proxy.corp:3128"
Environment="NO_PROXY=localhost,127.0.0.1,10.96.0.0/12,10.244.0.0/16,.svc,.cluster.local,registry.corp.local"
#                                                       ^^^^^^^^^^^^^^^^ — реестр добавлен
```

**Верификация:**

```bash
# 1. curl через прокси с системным CA
HTTPS_PROXY=http://proxy.corp:3128 curl -vI https://registry.corp.local/v2/
# → SSL connection using TLS_AES_256_GCM_SHA384
# → server certificate: subject: CN=*.corp.local
# → issuer: O=Corp, OU=IT (корпоративный CA — ОК)

# 2. Без прокси должен быть виден оригинальный сертификат
curl -vI https://registry.corp.local/v2/
# → server certificate: subject: CN=*.corp.local
# → issuer: O=Let's Encrypt (или оригинальный CA)

# 3. crictl pull после обновления CA
crictl pull registry.corp.local/my-app:1.0
# → Image is up to date
```

Сценарий полностью соответствует [common_errors → Сценарий 7 (TLS/сертификаты)](./common_errors.md#сценарий-7-проблемы-с-tls-и-сертификатами-x509) и [common_errors → Сценарий 12 (HTTP-прокси с аутентификацией)](./common_errors.md#сценарий-12-http-прокси-с-аутентификацией-squid).

### Сценарий 6: Исчерпание таблицы conntrack при массовом rollout

**Симптом:** При `kubectl rollout` большого Deployment (100+ реплик) или autoscaling-ивенте часть подов получает `connection timed out` или `dial tcp: i/o timeout` несмотря на то, что pull прошёл на других узлах кластера. В логах kubelet: `dial tcp 10.0.0.50:443: i/o timeout`.

**Корневая причина:** Ядро отбрасывает новые соединения при `nf_conntrack: table full`. На gateway-узле (если кластер за NAT) — лимит на gateway.

**Диагностика:**

```bash
# 1. Симптом на проблемном узле
dmesg | tail -50 | grep -i conntrack
# → [Wed Sep 04 12:00:15] nf_conntrack: table full, dropping packet.

# 2. Текущая заполненность
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_count = 65532
# → net.netfilter.nf_conntrack_max     = 65536    # 99.99% заполнен

# 3. Топ соединений
conntrack -L 2>/dev/null | head -20
# → tcp 6 431999 ESTABLISHED src=10.244.1.5 dst=10.0.0.50 sport=42356 dport=443 [...]
#    # 1000+ записей с разных IP к одному dst (registry)
```

**Решение (на каждом узле):**

```bash
# 1. Немедленное (без перезапуска)
sysctl -w net.netfilter.nf_conntrack_max=524288
sysctl -w net.netfilter.nf_conntrack_buckets=131072

# 2. Постоянное
cat > /etc/sysctl.d/99-conntrack-tuning.conf <<EOF
net.netfilter.nf_conntrack_max = 524288
net.netfilter.nf_conntrack_buckets = 131072
net.netfilter.nf_conntrack_tcp_timeout_established = 7200
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
EOF
sysctl --system

# 3. На NAT-шлюзе (если применимо) — те же параметры, но max до 2M
```

**Проверка эффекта:**

```bash
# Повторить rollout
kubectl rollout restart deploy/app
# Наблюдать за conntrack
watch -n1 "sysctl net.netfilter.nf_conntrack_count"
# → ... count стабилизируется на 30-40% от max, дропы прекращаются
```

### Сценарий 7: Исчерпание ephemeral port range

**Симптом:** На узле с активным pull pod'ы после N=200 одновременных pull'ов начинают получать `dial tcp: bind: cannot assign requested address` или `dial tcp: address already in use` (редко, но возможно при большом `conntrack` race).

**Корневая причина:** Дефолтный `ip_local_port_range = 32768–60999` (28 232 портов). Каждый TLS handshake к registry занимает один порт; TIME_WAIT удерживает его 60 секунд. При pull > 400 одновременных слоёв на одном узле — пул исчерпан.

**Диагностика:**

```bash
# Текущий range
sysctl net.ipv4.ip_local_port_range
# → 32768	60999

# Использование
ss -s
# → TCP:   28400 (estab 4000, closed 12000, orphaned 0, timewait 12000)
# →       ^^^^^^^^^^                     ^^^^^^^^^
#                  всего сокетов       в TIME_WAIT

# Счётчик переполнений
nstat -az | grep -E "ListenOverflows|ListenDrops"
# → TcpExtListenOverflows = 1243   # <-- проблема
```

**Решение:**

```bash
cat > /etc/sysctl.d/99-tcp-tuning.conf <<EOF
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_max_tw_buckets = 200000
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_slow_start_after_idle = 0
EOF
sysctl --system

# ВАЖНО: проверить, что ничего не слушает на 1024-32767
ss -ltn | awk '$4 ~ /:1[0-9]{3,4}$|:2[0-9]{3,4}$|:3[0-3]{1}[0-9]{2}$/'
# Должно быть пусто. Иначе сужение range до 10000-65535
```

**Альтернативное решение — уменьшить параллелизм на уровне kubelet:**

```bash
# Вместо расширения range — снизить нагрузку
# /var/lib/kubelet/config.yaml
# registryPullQPS: 5    # default
# registryBurst: 10    # default
# При масштабных pull лучше оставить дефолт и расширить range.
```

### Сценарий 8: IPv6-only egress: connection timed out при наличии AAAA-записи

**Симптом:** Узел умеет резолвить имя реестра (dig возвращает A и AAAA), но pull зависает на этапе TCP. `curl -4` работает, `curl -6` — нет. В логах `connection timed out` после 75 секунд (дефолтный TCP retry).

**Корневая причина:** В on-prem сетях внутренний DNS возвращает `AAAA` запись, указывающую на link-local или неработающий IPv6-адрес. Node-local `getaddrinfo` возвращает AAAA первым (RFC 6724), ядро пытается установить TCP по IPv6, через ~75 секунд переключается на IPv4.

**Диагностика:**

```bash
# A и AAAA записи
dig +short registry.example.com A
dig +short registry.example.com AAAA
# → 10.0.0.50          (A)
# → fe80::1234:5678:9abc:def0   (link-local — НЕ маршрутизируется!)

# Проверить доступность каждого
curl -4 -v --max-time 5 https://registry.example.com/v2/    # OK
curl -6 -v --max-time 5 https://registry.example.com/v2/    # timeout

# Время getaddrinfo + connect
time crictl pull registry.example.com/my-app:1.0
# real    1m15.400s   # <-- типичное время отката с IPv6 на IPv4
```

**Решение (выбрать одно):**

```bash
# 1. Принудительный приоритет IPv4 (рекомендуется для on-prem)
echo "precedence ::ffff:0:0/96 100" >> /etc/gai.conf
# Проверить:
getent ahosts registry.example.com
# Должен вернуть IPv4 первым

# 2. Жёсткое отключение IPv6 в ядре (если инфраструктура не использует)
cat > /etc/sysctl.d/99-disable-ipv6.conf <<EOF
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1
EOF
sysctl --system
# ОСТОРОЖНО: некоторые CNI (Calico IPv6 mode) сломаются.

# 3. На уровне containerd (только для image pull)
cat > /etc/containerd/config.toml <<EOF
[plugins."io.containerd.grpc.v1.cri"]
  enable_unprivileged_ports = false
  enable_unprivileged_icmp = false
EOF
# (Эти параметры не управляют IPv6, но иллюстрируют принцип per-plugin override)

# 4. Правильное (на DNS) — удалить AAAA запись для реестра из upstream
# Делать на DNS-сервере, не на узле.
```

Сценарий связан с [common_errors → Сценарий 16 (DNS-имя реестра)](./common_errors.md#сценарий-16-проблемы-с-dns-именем-реестра).

### Сценарий 9: Hairpin NAT — pod не может достучаться до локального pull-through

**Симптом:** Pods, использующие init-container с `wget https://harbor.local/...` или приложения, делающие HTTP-запрос к in-cluster registry Service, получают `connection refused` или `no route to host`. Сам pull через kubelet работает (потому что идёт с узла, а не из пода).

**Корневая причина:** При обращении пода к Service ClusterIP трафик DNAT-ится на backend-pod, ответ уходит напрямую к источнику в обратном обходе → pod получает пакет от неожиданного src.

**Диагностика (Cilium):**

```bash
# Посмотреть hairpin counters
cilium status | grep -i hairpin
# Hubble наблюдение
hubble observe -n production -f "dst.harbor.local" --last 50
# → traffic не доходит до backend
```

**Решение (Cilium):**

```bash
kubectl patch felixconfiguration default --type=merge -p '{"spec":{"hairpinEnabled":true}}'
# Или через Helm values:
# enable-hairpin: true

# Проверить:
kubectl exec -n production <pod> -- curl -vI https://harbor.local/v2/
# → HTTP/1.1 200 OK
```

**Альтернативный workaround без перезапуска CNI:**

```bash
# Использовать ExternalIP / endpoint вместо Service IP
kubectl get svc harbor -n harbor -o jsonpath='{.spec.clusterIP}'
# → 10.96.50.20

# В init-container обращаться напрямую к одному из pod'ов backend (не рекомендуется для production)
# Лучше: настроить NodePort или ExternalIP Service
```

### Сценарий 10: Детальная диагностика через `crictl --debug` + tcpdump

Когда все верхнеуровневые проверки (DNS, маршрут, port, proxy) прошли, но pull всё равно зависает, нужна **packet-level** диагностика. Связка `crictl --debug` + `tcpdump` + `strace` даёт полную картину.

**Пошаговая инструкция:**

```bash
# 1. Запустить tcpdump в фоне на проблемном узле (в отдельном терминале / tmux)
# Отключить offload для достоверного дампа
sudo ethtool -K eth0 tso off gso off gro off
sudo tcpdump -ni eth0 -s 0 -w /tmp/pull-trace.pcap "host registry.example.com and (port 443 or port 80 or icmp)"
# -k в современных версиях: tcpdump -k — не вычислять offloaded checksums
# Записать время старта

# 2. Снять strace с containerd, чтобы увидеть, что он делает в userspace
sudo strace -f -e trace=network,write,read,connect,sendto,recvfrom \
  -o /tmp/containerd-strace.log -p $(pidof containerd)
# Будет много вывода; фильтровать:
# grep "AF_INET" /tmp/containerd-strace.log
# → connect(5, {sa_family=AF_INET, sin_port=htons(443), sin_addr=inet_addr("10.0.0.50")}, 16) = -1 EINPROGRESS

# 3. Запустить crictl с максимальной детализацией
crictl --debug pull registry.example.com/my-app:1.0 2>&1 | tee /tmp/crictl-pull.log
# Ищем в /tmp/crictl-pull.log:
# - "trying to pull" — инициализация
# - "Pulling image" — DNS-резолв и TCP
# - "Get https://...: dial tcp ...:443: i/o timeout" — типичный итог
# - Время операции (если > 60s — точно сетевая проблема)

# 4. Остановить tcpdump (Ctrl+C), изучить дамп
tshark -r /tmp/pull-trace.pcap -q -z conv,tcp | head -20
# → Увидим: сколько соединений, SYN без ACK, RST, retransmissions

# 5. Найти TLS-handshake детали
tshark -r /tmp/pull-trace.pcap -Y "tls.handshake" -T fields \
  -e frame.number -e ip.src -e ip.dst -e tls.handshake.type -e tls.handshake.extensions_server_name
# → 1 10.244.1.5 -> 10.0.0.50 1 (Client Hello) registry.example.com
# → 2 10.0.0.50 -> 10.244.1.5 2 (Server Hello) ...
# Если ответ не пришёл — TCP SYN не дошёл или ответ потерян

# 6. Проверить ICMP (PMTUD!)
tshark -r /tmp/pull-trace.pcap -Y "icmp.type == 3" -T fields \
  -e frame.number -e ip.src -e icmp.type -e icmp.code
# → "3 10.0.0.1 3 4" = Destination Unreachable / Fragmentation Needed
# Если такие пакеты блокируются upstream firewall — у нас PMTUD black hole

# 7. Вернуть offload'ы
sudo ethtool -K eth0 tso on gso on gro on
```

**Чек-лист интерпретации:**

| Наблюдение в tcpdump | Вероятная причина |
| :--- | :--- |
| SYN → нет SYN-ACK | Firewall дропает или не маршрутизирует обратно. |
| SYN-ACK → ACK → TLS Client Hello → нет Server Hello | ICMP Fragmentation Needed дропается (PMTUD). |
| TLS идёт → connection reset by peer | Прокси перехватил и отверг (cert mismatch / auth). |
| Повторные SYN с большим интервалом (3, 9, 27 сек) | Back-off kernel, registry не отвечает. |
| TLS идёт → много [TCP Previous segment not captured] | **LRO/GRO включён на NIC** — отключите offload. |
| Пакеты с неверным TCP checksum | RX Checksum Offload отбрасывает пакет; увидите только через `tcpdump -k`. |

### Универсальный чек-лист сетевой диагностики (от простого к сложному)

| Шаг | Команда | Что проверяет | Ожидаемый результат |
| :--- | :--- | :--- | :--- |
| 1 | `getent hosts registry.example.com` | Резолв имени через системный резолвер | Возвращает IP за < 50 мс |
| 2 | `dig +short registry.example.com A` | Прямая A-запись | Один IP, без записей `SERVFAIL`/`NXDOMAIN` |
| 3 | `ip route get 10.0.0.50` | Маршрут от узла к реестру | Возвращает `via <gateway> dev <iface>` |
| 4 | `ping -c3 -M do -s 1472 registry.example.com` | MTU пути (DF-флаг) | 0% loss, `mtu=1500` |
| 5 | `ping -c3 -M do -s 1422 registry.example.com` | MTU с учётом VXLAN (если есть) | 0% loss |
| 6 | `curl -vI --max-time 5 https://registry.example.com/v2/` | TCP + TLS end-to-end | `HTTP/1.1 200 OK` или `401` |
| 7 | `openssl s_client -connect registry.example.com:443 -showcerts </dev/null` | TLS handshake и цепочка | Цепочка сертификатов без `verify error` |
| 8 | `time crictl pull registry.example.com/my-app:1.0` | Pull на уровне CRI | `< 1 минуты` для 100 MB образа |
| 9 | `sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max` | Conntrack saturation | `count / max < 0.75` |
| 10 | `sysctl net.ipv4.ip_local_port_range` | Ephemeral port range | `1024 65535` или `32768 60999` (по умолчанию) |
| 11 | `nstat -az \| grep -E "ListenOverflows"` | Переполнение портов | `0` (или очень малые значения) |
| 12 | `dmesg \| grep -i "table full\|nf_conntrack"` | Дропы ядра | Пусто (нет переполнений) |
| 13 | `journalctl -u containerd --since "10 min ago" \| grep -iE "timeout|refused|reset"` | Ошибки рантайма | Пусто (если pull успешен) |
| 14 | `tcpdump -ni eth0 -c 100 "host registry.example.com"` | Реальный трафик на проводе | SYN, SYN-ACK, TLS Client Hello, ответы сервера |
| 15 | `crictl --debug pull ...` + `strace -p $(pidof containerd)` | Уровень syscalls | `connect()` возвращает 0, `read()` возвращает данные |

---

## Дополнительная информация

### Связанные темы

- [Пошаговая диагностика](./diagnostics.md) — алгоритм поиска причин ошибок (L1-L5).
- [Распространённые ошибки](./common_errors.md) — разбор TLS, прокси, DNS-резолва и других ошибок реестров.
- [MTU и диагностика PMTUD](../../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) — глубокая теория фрагментации и "черных дыр".

