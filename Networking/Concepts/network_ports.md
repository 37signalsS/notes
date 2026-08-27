# Сетевые порты

## Определения

- **Порт (Network Port):** 16-битное беззнаковое целое число (0–65535), находящееся в заголовке [транспортного уровня (L4)](../OSI_TCP_IP_Model/transport_layer.md) (TCP, UDP, SCTP, DCCP). Порты позволяют операционной системе различать сетевой трафик для разных приложений (процессов), работающих на одном IP-адресе.

    **Структура заголовка TCP (порты):**
    ```
    0                   1                   2                   3
    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |          Source Port          |       Destination Port        |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                        Sequence Number                        |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    ...
    ```
    - **Source Port (16 бит):** Порт отправителя (обычно эфемерный для клиента).
    - **Destination Port (16 бит):** Порт получателя (обычно известный для сервера).

    Заголовок UDP аналогичен, но короче (8 байт): поля Source Port, Destination Port, Length, Checksum.

- **Сетевой интерфейс (Network Interface):** Программный или аппаратный шлюз, через который трафик входит в систему и выходит из нее. Примеры: `eth0` (проводная сеть), `wlan0` (Wi-Fi), `lo` (локальная петля/localhost). Один порт может быть привязан к конкретному интерфейсу или ко всем сразу.

- **Сокет (Socket):** Программный интерфейс, представляющий собой конечную точку соединения. На сетевом уровне сокет однозначно идентифицируется «пятеркой параметров» (5-tuple): `{Протокол, IP источника, Порт источника, IP назначения, Порт назначения}`. Подробнее: [Socket API](./socket_api.md).

- **Эфемерный порт (Ephemeral Port):** Временный порт из динамического диапазона, назначаемый ОС для исходящего соединения клиента. После закрытия соединения порт освобождается, но может находиться в состоянии `TIME_WAIT` (см. ниже).

- **Port Exhaustion (Исчерпание портов):** Состояние, при котором ОС не может выделить новый эфемерный порт для исходящего соединения. Обычно возникает на высоконагруженных прокси-серверах из-за большого количества соединений в состоянии `TIME_WAIT`.

- **Состояния портов (Port States):** В отличие от состояний TCP-соединений, состояния портов определяются с точки зрения сканирования и файрвола:

    | Состояние | Описание |
    | :--- | :--- |
    | **open** | Порт слушается, служба активно принимает соединения. |
    | **closed** | Порт доступен, но ни одно приложение не слушает. |
    | **filtered** | Пакеты блокируются файрволом, состояние неизвестно. |
    | **unfiltered** | Порт доступен, но сканер не может определить open/closed. |

    Подробнее о состояниях: [nmap — сканирование портов](../../Linux/Diagnostics/Networking/nmap.md).

## Основные концепции

### Мультиплексирование и демультиплексирование

Порты обеспечивают ключевой механизм транспортного уровня — **мультиплексирование** (multiplexing):

- **Демультиплексирование (на приемной стороне):** Ядро ОС использует поле Destination Port в заголовке TCP/UDP для маршрутизации входящего сегмента к правильному процессу (через сокет). Без портов все данные попадали бы в одно приложение.
- **Мультиплексирование (на отправляющей стороне):** Несколько приложений могут одновременно использовать сеть через разные порты источника. ОС гарантирует уникальность 5-tuple для каждого соединения.

**Пример:** На одном сервере могут одновременно работать:
- Веб-сервер на порту 80/443
- SSH-сервер на порту 22
- База данных на порту 5432

Все они используют один IP-адрес, но разные порты.

### Классификация диапазонов (IANA)

Согласно стандартам IANA, порты разделены на три группы:

| Диапазон | Название | Описание |
| :--- | :--- | :--- |
| **0–1023** | **Well-Known (Системные)** | Зарезервированы для стандартных сервисов (HTTP, SSH, DNS). Для их открытия требуются привилегии root или `CAP_NET_BIND_SERVICE`. |
| **1024–49151** | **Registered (Зарегистрированные)** | Используются для специфических приложений и баз данных (например, 3306 для MySQL). |
| **49152–65535** | **Dynamic/Private (Динамические)** | Предназначены для эфемерных портов и частного использования. |

**Дополнительные категории IANA:**

| Категазия | Диапазон | Назначение |
| :--- | :--- | :--- |
| **Well-Known** | 0–1023 | Назначаются IANA, строгий контроль |
| **Registered** | 1024–49151 | Зарегистрированы в IANA по запросу |
| **Dynamic/Ephemeral** | 49152–65535 | Для временного использования, не назначаются |

**Особенности реализации в Linux:**
Диапазон эфемерных портов в Linux по умолчанию (`32768–60999`) отличается от рекомендаций IANA. На высоконагруженных системах его рекомендуется расширять:
```bash
# Просмотр текущего диапазона
sysctl net.ipv4.ip_local_port_range
# → net.ipv4.ip_local_port_range = 32768	60999

# Увеличение диапазона (например, 1024-65535)
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"

# Для постоянного применения:
echo "net.ipv4.ip_local_port_range = 1024 65535" | sudo tee /etc/sysctl.d/99-ports.conf
sudo sysctl --system
```

**Сравнение диапазонов в разных ОС:**

| ОС | Диапазон эфемерных портов по умолчанию |
| :--- | :--- |
| Linux | 32768–60999 (28232 порта) |
| Windows (старые) | 1025–5000 |
| Windows (современные) | 49152–65535 |
| macOS | 49152–65535 |

### Привязка к интерфейсам (Binding)

Приложение может слушать порт на разных адресах:
- **`0.0.0.0` (INADDR_ANY):** Принимает входящие соединения на всех доступных сетевых интерфейсах хоста. Опасно с точки зрения безопасности, если порт не должен быть доступен извне.
- **`127.0.0.1` (Loopback):** Порт доступен только внутри самого хоста. Идеально для локальных баз данных или sidecar-контейнеров.
- **Конкретный IP:** Приложение слушает только на одном интерфейсе (например, внутреннем IP в VPC).

**Важно:** Один порт может быть занят несколько раз при использовании `SO_REUSEADDR` или `SO_REUSEPORT` (см. ниже), или если привязан к разным IP-адресам.

### Проблема исчерпания портов (Port Exhaustion)

Когда клиент закрывает TCP-соединение, сокет переходит в состояние `TIME_WAIT` (обычно на 60 секунд). В этот период пара `[Local IP]:[Local Port] : [Remote IP]:[Remote Port]` не может быть использована повторно. На нагруженных балансировщиках (Nginx, HAProxy) это приводит к отказу в новых соединениях.

**Математический лимит:**
```
Максимальный RPS < (Количество свободных портов) / 60
```
При 30 000 доступных портах и RPS > 500 система начнет выдавать ошибку `EADDRNOTAVAIL`.

**Методы решения:**
1.  **Использование нескольких IP-адресов** для исходящего трафика (умножает количество доступных портов).
2.  **Включение повторного использования сокетов:** `sysctl -w net.ipv4.tcp_tw_reuse=1`.
3.  **Увеличение диапазона эфемерных портов.**
4.  **Connection Pooling:** Повторное использование TCP-сессий (Keep-Alive) снижает частоту открытий/закрытий.
5.  Подробнее: [Управление состоянием TIME_WAIT в Linux](../../Linux/Networking/Concepts/tcp_tuning/tcp_time_wait_management.md).

### Управление сокетами: SO_REUSEADDR и SO_REUSEPORT

При разработке высоконагруженных сервисов используются специальные флаги [Socket API](./socket_api.md):

| Опция | Описание | Сценарий использования |
| :--- | :--- | :--- |
| **`SO_REUSEADDR`** | Позволяет серверу мгновенно «занять» порт, который находится в состоянии `TIME_WAIT` после перезапуска процесса. | Перезапуск сервера без ожидания освобождения порта. |
| **`SO_REUSEPORT` (Linux 3.9+)** | Позволяет нескольким независимым процессам или потокам биндиться на один и тот же порт. Ядро автоматически распределяет входящие пакеты (балансировка) между ними. | Горизонтальное масштабирование сервера (например, Nginx с несколькими worker'ами). |

**Различия:**
- `SO_REUSEADDR` решает проблему «Address already in use» при перезапуске.
- `SO_REUSEPORT` решает проблему бутылочного горлышка на одном `accept()`-потоке и позволяет масштабировать сервер на несколько процессов.

**Пример на Python:**
```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('0.0.0.0', 8080))
sock.listen(128)
```

### Справочник портов DevOps и SRE (2025–2026)

| Порт | Сервис / Инструмент | Протокол | Назначение |
| :--- | :--- | :--- | :--- |
| **22** | SSH | TCP | Удаленное управление. |
| **53** | DNS | UDP/TCP | Разрешение имен. |
| **80 / 443** | HTTP / HTTPS | TCP/UDP | Веб-трафик (UDP используется для HTTP/3 QUIC). |
| **2379 / 2380** | etcd | TCP | API и коммуникация между узлами etcd (Kubernetes). |
| **5432 / 6379** | PostgreSQL / Redis | TCP | СУБД и In-memory кэш. |
| **8200 / 8201** | HashiCorp Vault | TCP | API и репликация секретов. |
| **8500** | HashiCorp Consul | TCP/UDP | Service Discovery и UI. |
| **9090 / 9100** | Prometheus / Node Exporter | TCP | Сбор метрик. |
| **10250** | Kubelet | TCP | Управление узлом Kubernetes. |
| **15000 / 15021** | Envoy / Istio | TCP | Admin interface и Health checks. |
| **30000–32767** | Kubernetes NodePort | TCP/UDP | Диапазон портов для сервисов NodePort. |

**Полный список Well-Known портов:** [IANA Port Numbers](https://www.iana.org/assignments/service-names-port-numbers/service-names-port-numbers.xhtml)

## Практические сценарии

### Сканирование портов с помощью nmap

**Предварительные требования:**
- Установленный `nmap`: `sudo apt install nmap` или `sudo dnf install nmap`
- Root-доступ для SYN-сканирования (`-sS`) и определения ОС (`-O`)
- Целевой хост или сеть для сканирования

**Шаг 1: Обнаружение активных хостов**
```bash
# Ping-сканирование подсети (без сканирования портов)
nmap -sn 192.168.1.0/24
# → Nmap scan report for 192.168.1.1
# → Host is up (0.0032s latency).
# → MAC Address: AA:BB:CC:DD:EE:FF (Router)
```

**Шаг 2: Быстрое сканирование популярных портов**
```bash
# Сканирование 100 самых популярных портов
nmap --top-ports 100 192.168.1.10
# → PORT     STATE SERVICE
# → 22/tcp   open  ssh
# → 80/tcp   open  http
# → 443/tcp  open  https
```

**Шаг 3: Полное сканирование всех портов**
```bash
# Сканирование всех 65535 портов (требует времени)
sudo nmap -p- 192.168.1.10
# → PORT      STATE SERVICE
# → 22/tcp    open  ssh
# → 80/tcp    open  http
# → 3306/tcp  open  mysql
# → 8080/tcp  open  http-proxy
```

**Шаг 4: Определение версий сервисов**
```bash
# Определение версий на открытых портах
sudo nmap -sV -p 22,80,443 192.168.1.10
# → PORT   STATE SERVICE VERSION
# → 22/tcp open  ssh     OpenSSH 8.9p1 Ubuntu 3ubuntu0.1
# → 80/tcp open  http    nginx 1.18.0
```

**Валидация:**
```bash
# Проверка, что порт действительно открыт
nc -zv 192.168.1.10 22
# → Connection to 192.168.1.10 22 port [tcp/ssh] succeeded!

# Проверка через curl для HTTP-портов
curl -I http://192.168.1.10:80
# → HTTP/1.1 200 OK
# → Server: nginx/1.18.0
```

**Подробнее:** [nmap — полное руководство](../../Linux/Diagnostics/Networking/nmap.md)

---

### Проброс портов (Port Forwarding)

**Предварительные требования:**
- Два сетевых интерфейса (или доступ к шлюзу)
- Root-доступ
- Включенный IP Forwarding: `echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward`

**Сценарий: Проброс порта 8080 на внешнем интерфейсе к внутреннему серверу 192.168.1.10:80**

**Шаг 1: Включение IP Forwarding (постоянно)**
```bash
echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-forward.conf
sudo sysctl --system
```

**Шаг 2: Настройка DNAT через iptables**
```bash
# Проброс порта 8080 -> 192.168.1.10:80
sudo iptables -t nat -A PREROUTING -i eth0 -p tcp --dport 8080 \
  -j DNAT --to-destination 192.168.1.10:80

# Разрешить форвардинг этого трафика
sudo iptables -A FORWARD -i eth0 -o eth1 -p tcp --dport 80 \
  -d 192.168.1.10 -j ACCEPT

# Маскарадинг для ответного трафика
sudo iptables -t nat -A POSTROUTING -o eth1 -s 0.0.0.0/0 \
  -d 192.168.1.10 -j MASQUERADE
```

**Шаг 3: Альтернатива через nftables**
```bash
sudo nft add table ip nat
sudo nft add chain ip nat prerouting { type nat hook prerouting priority 0 \; }
sudo nft add rule ip nat prerouting iifname "eth0" tcp dport 8080 \
  dnat to 192.168.1.10:80
```

**Шаг 4: Настройка через firewalld (CentOS/RHEL)**
```bash
sudo firewall-cmd --permanent --zone=external \
  --add-forward-port=port=8080:proto=tcp:toport=80:toaddr=192.168.1.10
sudo firewall-cmd --reload
```

**Валидация:**
```bash
# С внешнего хоста
curl http://<external_ip>:8080
# → Должен вернуть ответ от внутреннего сервера

# На шлюзе: проверка conntrack
sudo conntrack -L -p tcp --dport 80
# → tcp  6 431999 ESTABLISHED src=203.0.113.5 dst=<external_ip> sport=54321 dport=8080 src=192.168.1.10 dst=203.0.113.5 sport=80 dport=54321 [ASSURED]
```

**Сохранение правил:**
```bash
# Debian/Ubuntu
sudo apt install iptables-persistent
sudo netfilter-persistent save

# RHEL/CentOS
sudo service iptables save

# Nftables
sudo nft list ruleset | sudo tee /etc/nftables.conf
```

---

### Настройка firewall для управления портами

**Предварительные требования:**
- `iptables` или `nftables` (или `ufw` для упрощенной настройки)
- Root-доступ

**Сценарий: Открытие порта 8080 для конкретной подсети**

**Через UFW (Ubuntu):**
```bash
# Открыть порт 8080 только для подсети 10.0.0.0/24
sudo ufw allow from 10.0.0.0/24 to any port 8080 proto tcp
# → Rule added

# Проверка
sudo ufw status verbose
# → To                         Action      From
# → --                         ------      ----
# → 8080/tcp                   ALLOW IN    10.0.0.0/24
```

**Через firewalld (CentOS/RHEL):**
```bash
# Создать зону для доверенной подсети
sudo firewall-cmd --permanent --new-zone=trusted
sudo firewall-cmd --permanent --zone=trusted --add-source=10.0.0.0/24
sudo firewall-cmd --permanent --zone=trusted --add-port=8080/tcp
sudo firewall-cmd --reload

# Проверка
sudo firewall-cmd --zone=trusted --list-all
# → trusted (active)
# → sources: 10.0.0.0/24
# → ports: 8080/tcp
```

**Через nftables (универсальный):**
```bash
sudo nft add table inet filter
sudo nft add chain inet filter input { type filter hook input priority 0 \; policy drop \; }
sudo nft add rule inet filter input tcp dport 8080 ip saddr 10.0.0.0/24 accept
```

**Валидация:**
```bash
# С разрешенной подсети (должно работать)
nc -zv <server_ip> 8080
# → Connection to <server_ip> 8080 port [tcp/*] succeeded!

# С запрещенной подсети (должно быть заблокировано)
nc -zv <server_ip> 8080
# → nc: connect to <server_ip> port 8080 (tcp) failed: Connection timed out
```

---

### Диагностика портов в Linux

**Предварительные требования:**
- Утилиты `ss`, `lsof`, `nc` (входят в стандартную поставку)
- Root-доступ для просмотра всех процессов

**Шаг 1: Просмотр всех слушающих портов**
```bash
sudo ss -tulpn
# → Netid  State   Recv-Q  Send-Q  Local Address:Port  Peer Address:Port  Process
# → tcp    LISTEN  0       128     0.0.0.0:22          0.0.0.0:*          users:(("sshd",pid=1234))
# → tcp    LISTEN  0       511     [::]:80             [::]:*             users:(("nginx",pid=5678))
```

**Флаги:**
- `-t` — TCP, `-u` — UDP, `-x` — Unix sockets
- `-l` — только listening, `-a` — все сокеты
- `-p` — показать процесс (требует root)
- `-n` — числовой формат (без DNS-резолва)

**Шаг 2: Поиск процесса, занимающего порт**
```bash
sudo lsof -i :443
# → COMMAND   PID  USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
# → nginx    5678  root    6u  IPv4  12345      0t0  TCP *:https (LISTEN)

# Альтернатива через ss
sudo ss -tlnp | grep :443
```

**Шаг 3: Проверка доступности порта на удаленном хосте**
```bash
# Через nc (netcat)
nc -zv 192.168.1.10 22
# → Connection to 192.168.1.10 22 port [tcp/ssh] succeeded!

# Через /dev/tcp (встроено в bash)
echo > /dev/tcp/192.168.1.10/22 && echo "Port is open" || echo "Port is closed"
```

**Шаг 4: Анализ состояний соединений**
```bash
# Сводная статистика
ss -s
# → Total: 156 (kernel 180)
# → TCP:   24 (estab 1, closed 1, orphaned 0, timewait 0)

# Подсчет TIME_WAIT
ss -tan state time-wait | wc -l
# → 42

# Подсчет ESTABLISHED для конкретного порта
ss -tan state established | grep :443 | wc -l
# → 15
```

**Шаг 5: Мониторинг портов в реальном времени**
```bash
# Через watch
watch -n 1 'ss -tulpn | grep LISTEN'

# Через tcpdump (перехват трафика на порт)
sudo tcpdump -i any port 8080 -nn
```

---

### Устранение исчерпания портов (Port Exhaustion)

**Предварительные требования:**
- Linux (ядро 4.x+)
- Root-доступ для изменения sysctl

**Шаг 1: Диагностика проблемы**
```bash
# Проверка количества TIME_WAIT
ss -tan state time-wait | wc -l
# → 2847 (высокое значение — проблема)

# Проверка текущего диапазона эфемерных портов
sysctl net.ipv4.ip_local_port_range
# → net.ipv4.ip_local_port_range = 32768	60999 (только 28232 порта)

# Проверка ошибок исчерпания
nstat -az | grep -E 'TcpExtTCPTimeWaitOverflow|TcpExtListenOverflows'
```

**Шаг 2: Применение быстрых исправлений**
```bash
# Включение переиспользования TIME_WAIT
sudo sysctl -w net.ipv4.tcp_tw_reuse=1

# Расширение диапазона эфемерных портов
sudo sysctl -w net.ipv4.ip_local_port_range="1024 65535"

# Включение TCP Timestamps (обязательно для tcp_tw_reuse)
sudo sysctl -w net.ipv4.tcp_timestamps=1
```

**Шаг 3: Постоянная конфигурация**
```bash
cat <<EOF | sudo tee /etc/sysctl.d/99-port-exhaustion.conf
# Расширение диапазона эфемерных портов
net.ipv4.ip_local_port_range = 1024 65535

# Включение переиспользования TIME_WAIT
net.ipv4.tcp_tw_reuse = 1

# TCP Timestamps (обязательно для tw_reuse)
net.ipv4.tcp_timestamps = 1

# Уменьшение таймаута FIN-WAIT-2
net.ipv4.tcp_fin_timeout = 15

# Лимит корзин TIME_WAIT
net.ipv4.tcp_max_tw_buckets = 262144
EOF

sudo sysctl --system
```

**Валидация:**
```bash
# Проверка применения настроек
sysctl net.ipv4.tcp_tw_reuse net.ipv4.ip_local_port_range
# → net.ipv4.tcp_tw_reuse = 1
# → net.ipv4.ip_local_port_range = 1024 65535

# Мониторинг после применения
watch -n 1 'ss -tan state time-wait | wc -l'
```

**Важно:** Параметр `tcp_tw_recycle` удален из ядра Linux 4.12+ и не должен использоваться (ломает NAT).

**Подробнее:** [Управление TIME_WAIT в Linux](../../Linux/Networking/Concepts/tcp_tuning/tcp_time_wait_management.md)

---

## Валидация и диагностика

### Проверка доступности портов

| Задача | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| Порт слушается локально | `ss -tlnp \| grep :80` | Строка с LISTEN и процессом |
| Порт доступен удаленно | `nc -zv <IP> 80` | `succeeded!` |
| Порт заблокирован файрволом | `nc -zv <IP> 80` | `Connection timed out` |
| Порт закрыт (нет службы) | `nc -zv <IP> 80` | `Connection refused` |

### Анализ состояний сокетов

```bash
# Распределение по состояниям
ss -tan | awk '{print $1}' | sort | uniq -c | sort -rn
# →    125 ESTAB
# →     42 TIME-WAIT
# →     12 LISTEN
# →      3 CLOSE-WAIT
```

**Интерпретация:**
- Большое количество `TIME_WAIT` — проблема исчерпания портов
- Большое количество `CLOSE_WAIT` — утечка ресурсов в приложении (не вызывается `close()`)
- Большое количество `SYN_RECV` — возможна SYN-flood атака

### Мониторинг в реальном времени

```bash
# Мониторинг новых соединений
sudo tcpdump -i any 'tcp[tcpflags] & tcp-syn != 0' -nn

# Мониторинг конкретного порта
watch -n 1 'ss -tan | grep :443 | wc -l'

# Мониторинг через nstat
nstat -az | grep -E 'TcpExtTCPTimeWaitOverflow|TcpExtListenOverflows'
```

---

## Устранение неполадок

### Проблема: "Address already in use" (EADDRINUSE)

**Причины:**
- Порт занят другим процессом
- Сокет находится в состоянии `TIME_WAIT`
- Приложение не использует `SO_REUSEADDR`

**Диагностика:**
```bash
# Найти процесс, занимающий порт
sudo lsof -i :8080
# → COMMAND  PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
# → python  1234 root    3u  IPv4  12345      0t0  TCP *:8080 (LISTEN)

# Или через ss
sudo ss -tlnp | grep :8080
```

**Решение:**
```bash
# Вариант 1: Завершить процесс
sudo kill 1234

# Вариант 2: Использовать SO_REUSEADDR в коде
# Вариант 3: Подождать освобождения (60 секунд для TIME_WAIT)
```

### Проблема: Порт не доступен извне

**Причины:**
- Служба слушает только на 127.0.0.1
- Файрвол блокирует порт
- Неправильная маршрутизация

**Диагностика:**
```bash
# Проверка, на каком адресу слушает порт
sudo ss -tlnp | grep :80
# → LISTEN 0 128 127.0.0.1:80  ← Только localhost (проблема!)
# → LISTEN 0 128 0.0.0.0:80    ← Все интерфейсы (OK)

# Проверка файрвола
sudo iptables -L INPUT -n | grep :80
# → DROP tcp -- 0.0.0.0/0 0.0.0.0/0 tcp dpt:80  ← Блокировка!

# Проверка доступности с удаленного хоста
nc -zv <server_ip> 80
```

**Решение:**
```bash
# Изменить binding в конфигурации приложения на 0.0.0.0
# Или открыть порт в файрволе
sudo ufw allow 80/tcp
# или
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --reload
```

### Проблема: Исчерпание портов

**Признаки:**
- Ошибка `EADDRNOTAVAIL` в логах приложений
- Большое количество `TIME_WAIT` соединений
- Невозможность установить новые соединения

**Диагностика:**
```bash
# Подсчет TIME_WAIT
ss -tan state time-wait | wc -l

# Проверка диапазона эфемерных портов
sysctl net.ipv4.ip_local_port_range
```

**Решение:** См. сценарий "Устранение исчерпания портов" выше.

### Проблема: Конфликт портов при запуске нескольких экземпляров

**Решение:** Использовать `SO_REUSEPORT`:
```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
sock.bind(('0.0.0.0', 8080))
sock.listen(128)
```

---

## Безопасность

### Привилегированные порты и контейнеры
Порты ниже 1024 считаются системными. В **Rootless-контейнерах** (Docker/Podman) приложение не может слушать порт 80 или 443 напрямую без специальных настроек ядра:
```bash
# Разрешить непривилегированным пользователям биндить порты с 80
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80

# Для постоянного применения
echo "net.ipv4.ip_unprivileged_port_start = 80" | sudo tee /etc/sysctl.d/99-unprivileged-port.conf
```

**Альтернативы:**
- Использовать `setcap 'cap_net_bind_service=+ep' /path/to/binary`
- Пробросить порт через iptables: `iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080`
- Использовать reverse proxy (Nginx, Traefik)

### Скрытие и защита
1.  **Port Knocking / SPA:** Скрытие порта (например, SSH) за «секретной» последовательностью пакетов. Пакеты с неправильной последовательностью игнорируются, порт выглядит закрытым.
2.  **Binding к Loopback:** Всегда биндите сервисы (JMX, RabbitMQ management, Redis без пароля) на `127.0.0.1`, если к ним не требуется внешний доступ.
3.  **NetworkPolicies:** В Kubernetes используйте политики для ограничения доступа к портам на уровне подов. См. [NetworkPolicy: Практические сценарии](../../Kubernetes/Networking/Network/NetworkPolicy/practical_scenarios.md).
4.  **Fail2ban:** Автоматическая блокировка IP после неудачных попыток подключения к SSH, FTP и другим сервисам.
5.  **Принцип минимальных привилегий:** Открывайте только необходимые порты, остальные блокируйте.

### Аудит открытых портов

```bash
# Регулярный аудит открытых портов
sudo ss -tulpn | awk '{print $5}' | grep -oP ':\K[0-9]+' | sort -n | uniq

# Сравнение с эталонным списком
diff <(echo "22 80 443") <(sudo ss -tlnp | awk '{print $5}' | grep -oP ':\K[0-9]+' | sort -n | uniq)
```

---

## Дополнительная информация

- [Транспортный уровень модели OSI](../OSI_TCP_IP_Model/transport_layer.md) — протоколы TCP/UDP, мультиплексирование
- [Socket API: Практическое руководство](./socket_api.md) — программирование сокетов
- [Тюнинг TCP стека в Linux](../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md) — оптимизация параметров
- [Управление состоянием TIME_WAIT в Linux](../../Linux/Networking/Concepts/tcp_tuning/tcp_time_wait_management.md) — подробности о TIME_WAIT
- [Диагностика сокетов: утилита ss](../../Linux/Diagnostics/Networking/ss.md) — команды и фильтры
- [nmap — сканирование сетей](../../Linux/Diagnostics/Networking/nmap.md) — аудит безопасности
- [NAT — практические сценарии](./nat/practical_scenarios.md) — проброс портов, DNAT/SNAT
