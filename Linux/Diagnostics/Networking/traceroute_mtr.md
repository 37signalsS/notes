# Трассировка сетевого пути: traceroute, mtr и tracepath

## Определения

**`traceroute`** — классическая консольная утилита для определения маршрута следования IP-пакетов. Она отображает цепочку промежуточных узлов (маршрутизаторов) и задержку до каждого из них.

**`mtr`** (My Traceroute) — интерактивный инструмент, объединяющий возможности `traceroute` и `ping`. В отличие от разовой проверки, `mtr` выполняет постоянное зондирование всех узлов маршрута, предоставляя динамическую статистику по потерям и стабильности задержек.

**`tracepath`** — упрощенный аналог `traceroute`, предназначенный для поиска **Path MTU**. Не требует прав суперпользователя (`root`) и использует только UDP-пакеты.

**`trippy`** — современная (Next-gen) альтернатива `mtr` с богатым TUI, поддержкой графиков, анализом номеров автономных систем (AS) и поддержкой различных протоколов зондирования.

**UDP-зондирование (по умолчанию в Linux)** — отправка UDP-датаграмм на порты `33434–33534` с возрастающим TTL. Маршрутизатор, уменьшая TTL до 0, возвращает **ICMP Time Exceeded** (Type 11, Code 0).

**ICMP-зондирование (`-I`)** — отправка ICMP Echo Request (Type 8), аналогично `tracert` в Windows. Используется, когда UDP-трафик блокируется.

**TCP-зондирование (`-T`)** — отправка TCP SYN на указанный порт (например, 80 или 443). Самый эффективный метод обхода Firewall, так как большинство политик разрешают estabilished/TCP-трафик.

**Happy Eyeballs** — механизм (RFC 8305), который при наличии dual-stack подключения предпочитает быстрый IPv6, но резервирует IPv4 на случай зависания. Утилиты трассировки могут использовать этот принцип для выбора адресного семейства.

Используется при обнаружении «зависающих» сессий:
- SSH работает, но `SCP` обрывается.
- HTTPS-трафик виснет на этапе TLS Handshake.
- API не принимает POST-запросы с большими данными.

Подробная диагностика и симптомы: **[MTU, PMTUD и диагностика в VPN](../../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)**.

## Основные концепции

### Механизм TTL (Time To Live) / Hop Limit

Обе утилиты используют поле **TTL** в заголовке IP-пакета (или **Hop Limit** в IPv6) для обнаружения хопов:

1.  Отправитель посылает пакет с `TTL=1`.
2.  Первый маршрутизатор уменьшает TTL до 0, отбрасывает пакет и возвращает отправителю сообщение **[ICMP Time Exceeded](../../../Networking/Protocols/ICMP/icmp_time_exceeded.md)**.
3.  Отправитель фиксирует IP-адрес этого маршрутизатора (первый хоп).
4.  Процесс повторяется с `TTL=2`, `TTL=3` и т.д., пока пакет не достигнет цели или не будет достигнут лимит (`max-hops`).

**IPv4 vs IPv6:** В IPv4 поле называется **TTL** (8 бит), изначально задумывалось как время в секундах, но де-факто является счетчиком хопов. В IPv6 поле переименовано в **Hop Limit** (8 бит) для точного отражения функции.

**Формула расчета хопов:** `Кол-во маршрутизаторов = Начальный_TTL - Полученный_TTL`. Стандартные начальные TTL: Linux/macOS — 64, Windows — 128, маршрутизаторы (Cisco/Juniper) — 255.

### Типы зондирующих пакетов (Probes)

Выбор протокола критичен для обхода брандмауэров:

| Протокол | Флаг | Порт/Тип | Описание |
| :--- | :--- | :--- | :--- |
| **UDP** | По умолчанию | 33434–33534 | Стандарт для Linux. Часто блокируется на конечных хостах или ISP. |
| **ICMP** | `-I` | Type 8 (Echo Request) | Аналогично `tracert` в Windows. Если UDP блокируется. |
| **TCP** | `-T` | Указанный порт (80/443/22) | TCP SYN на конкретный порт. Самый эффективный метод обхода Firewall. |

```bash
# UDP-режим (по умолчанию в Linux)
traceroute 8.8.8.8

# ICMP-режим (аналог Windows tracert)
sudo traceroute -I -n 8.8.8.8

# TCP-режим через порт 443 (обход firewall)
sudo traceroute -T -p 443 -n google.com
```

### DNS, PTR-записи и nsswitch

По умолчанию `traceroute` и `mtr` пытаются выполнить обратный DNS-запрос (PTR) для каждого IP-адреса на пути, чтобы отображать читаемые имена роутеров. Это создает несколько проблем:

- **Задержки:** DNS-запросы увеличивают время прохождения теста, особенно если резолвер медленный или недоступен.
- **Неточности:** Ошибки резолвинга могут выглядеть как потери пакетов.
- **Зависимость от внешних сервисов:** Если в пути нет доступа к DNS, вывод будет тормозить или зависать.

**Решение:** Используйте флаг `-n` (no DNS) для отключения резолвинга. В `mtr` дополнительно доступен `--no-dns`.

```bash
# traceroute без DNS-резолвинга
traceroute -n 8.8.8.8

# mtr без DNS
mtr -n --no-dns 8.8.8.8
```

**nsswitch и `/etc/hosts`:** Порядок разрешения имен определяется `nsswitch.conf` (`hosts: files dns`). Если в `/etc/hosts` есть локальные PTR-записи, они будут использованы сначала. Для диагностики используйте `getent hosts <ip>` или `dig -x <ip>`.

### Dual-stack и Happy Eyeballs

В средах с одновременным IPv4 и IPv6 утилиты могут по-разному выбирать адресное семейство:

- **По умолчанию:** `traceroute` и `mtr` обычно следуют порядку разрешения имени (AAAA → A), но могут зависнуть на IPv6-хопе, если он unreachable.
- **Принудительный выбор:** Флаги `-4` и `-6` позволяют тестировать конкретное семейство независимо от DNS-ответа.

```bash
# Принудительный IPv4
traceroute -4 8.8.8.8

# Принудительный IPv6
traceroute -6 2001:4860:4860::8888

# mtr с принудительным IPv6
mtr -6 google.com
```

### Влияние NAT, Firewall и ICMP Rate Limiting

**NAT:** Трассировка показывает путь только до NAT-шлюза. За NAT видна внутренняя сеть провайдера или корпоративного firewall, но не топология конечного сегмента.

**Firewall:** Мiddlebox могут блокировать:
- ICMP Type 11 (Time Exceeded) → `* * *` на всех промежуточных хостах.
- UDP-трафик на порты 33434+ → стандартный `traceroute` не работает.
- TCP SYN на нестандартные порты → используйте порт 443 или 80.

**ICMP Rate Limiting:** Маршрутизаторы ограничивают скорость ICMP-сообщений для защиты Control Plane (подробнее: **[ICMP Time Exceeded](../../../Networking/Protocols/ICMP/icmp_time_exceeded.md)**). Эффект: в `mtr` видны `* * *` или потери на промежуточных узлах при стабильной конечной цели. Это нормально, а не признак проблемы.

### ECMP (Equal-Cost Multi-Path)

В крупных сетях трафик может распределяться по нескольким равнозначным маршрутам. `traceroute` может отображать несколько разных IP-адресов на одном хопе (например, `1. 10.0.0.1, 10.0.0.2`). Это нормально и означает наличие балансировки на уровне L3.

**Диагностика ECMP:** Используйте `mtr` для нескольких запусков — разные пробы могут уходить разными путями. Для анализа hash-политики используйте `ip -d route show` (ядро 5.3+). Подробнее: **[Практические сценарии маршрутизации](../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/routing_scenarios.md)**.

### Асимметричная маршрутизация

Трассировка показывает только **путь "туда"**. Обратный путь от сервера к вам может проходить через совершенно другие узлы. Проблемы с задержками могут быть вызваны именно обратным путем, который классические утилиты не видят.

**Детектирование:** Запустите `traceroute` в обе стороны (с клиента на сервер и с сервера на клиент). Если пути различаются — асимметрия подтверждена. Для автоматизации используйте скрипт в разделе практических сценариев.

### MPLS (Multiprotocol Label Switching)

Многие провайдеры используют MPLS. `mtr` с флагом `-e` позволяет увидеть MPLS-метки, что критично для диагностики внутри операторских сетей.

```bash
# Отображение MPLS-меток в выводе mtr
mtr -e -n -c 5 8.8.8.8
# →  2: 10.0.1.1  0.1ms  {0.0.0.0:100:100:100} MPLS
#   ^^^ MPLS метка 100, TTL 100, Traffic Class 100
```

Подробнее о расширениях ICMP для MPLS: **[ICMP Time Exceeded](../../../Networking/Protocols/ICMP/icmp_time_exceeded.md)**.

## Интерпретация метрик mtr

| Метрика | Описание | SRE-интерпретация |
| :--- | :--- | :--- |
| **Loss%** | Процент потерь. | Потери в середине маршрута при их отсутствии на финальном узле обычно указывают на **ICMP Rate Limiting** на конкретном маршрутизаторе и не являются признаком проблемы. Потери >1% на последнем хопе требуют внимания. |
| **Snt** | Количество отправленных запросов. | Для production-диагностики используйте минимум 100–500 циклов (`-c 100`). |
| **Last** | Текущая задержка (RTT). | Резкие скачки на конкретном хопе указывают на перегрузку маршрутизатора или очередь. |
| **Avg** | Средняя задержка. | Базовый показатель стабильности пути. Сравнивайте Avg на соседних хопах — резкий рост означает "узкое место". |
| **Best** | Минимальная задержка. | Показывает лучший возможный RTT через данный узел (без перегрузок). |
| **Wrst** | Максимальная задержка. | Высокое значение (>3× Avg) указывает на перегрузки или jitter. |
| **StDev** | Среднеквадратичное отклонение. | Высокое значение (>30 ms) указывает на нестабильность канала (**jitter**). Для голоса/видео StDev >10 ms уже критичен. |

## Практические сценарии

### Выбор инструмента

| Инструмент | Когда использовать | Ключевые особенности |
| :--- | :--- | :--- |
| **traceroute** | Быстрая разовая проверка пути. | Простота, повсеместная доступность, поддержка UDP/ICMP/TCP. |
| **mtr** | Диагностика нестабильности, потерь, jitter. | Непрерывное зондирование, статистика по хопам, JSON-вывод. |
| **tracepath** | Диагностика MTU без root. | Автоматическое определение PMTU, не требует привилегий. |
| **trippy** | Визуализация, анализ AS, современный TUI. | Графики, WHOIS, поддержка TCP/UDP/ICMP, ASN. |
| **tcptraceroute** | Обход firewall, когда ICMP/UDP заблокированы. | Чистый TCP SYN без установления соединения. |

### Глубокая диагностика через mtr

Рекомендуется запускать тест минимум на 100 циклов для получения достоверных данных:

```bash
# Подробный отчет с номерами автономных систем (AS) и MPLS
mtr -rwzec 100 8.8.8.8

# Вывод статистики в формате JSON для автоматизации
mtr -j -c 10 1.1.1.1 > mtr_report.json

# Без DNS-резолвинга (стабильнее в production)
mtr -n --no-dns -c 50 8.8.8.8

# TCP-режим через порт 443 (обход firewall)
sudo mtr -T -P 443 -c 30 google.com
```

### Обход Firewall с помощью traceroute

Если обычный `traceroute` показывает только звездочки (`* * *`):

```bash
# Использование TCP SYN на порт 443 (имитация HTTPS)
sudo traceroute -n -T -p 443 google.com

# Использование ICMP вместо UDP
sudo traceroute -n -I google.com

# TCP SYN на порт 22 (SSH)
sudo traceroute -n -T -p 22 <server>

# TCP SYN на порт 3389 (RDP)
sudo traceroute -n -T -p 3389 <server>
```

### Использование Trippy для визуализации

```bash
# Запуск trippy с анализом AS и TUI интерфейсом
trippy google.com

# Запуск с TCP-зондированием на порт 443
trippy -T -p 443 google.com

# Экспорт в JSON
trippy --format json -c 20 google.com > trippy_report.json
```

### Диагностика IPv4/IPv6

Обе утилиты поддерживают dual-stack нативно:

```bash
# Принудительный IPv4
traceroute -4 8.8.8.8
mtr -4 1.1.1.1

# Принудительный IPv6
traceroute -6 2001:4860:4860::8888
mtr -6 google.com

# tracepath6 (если traceroute6 отсутствует)
tracepath6 -n google.com
```

### Быстрая проверка MTU через tracepath

```bash
# Определение минимального MTU на всем пути
tracepath -n ya.ru
# →  1?: [LOCALHOST]     pmtu 1500
# →  1:  192.168.1.1      0.412ms
# →  2:  10.0.0.1         5.230ms pmtu 1492
# → Резюме: MTU снизился до 1492 на втором хопе.

# Ограничение количества хопов
tracepath -n -m 15 8.8.8.8
```

### Автоматизация и скрипты

#### Скрипт базового health-check маршрута

```bash
#!/usr/bin/env bash
# traceroute_healthcheck.sh — базовый скрипт для SRE-мониторинга
set -euo pipefail

TARGET="${1:?Usage: $0 <host> [count]}"
COUNT="${2:-20}"
INTERFACE="${3:-}"

if [[ -n "$INTERFACE" ]]; then
    MTR_CMD=(sudo mtr -i 0.2 -c "$COUNT" -n --no-dns -e -r "$TARGET")
else
    MTR_CMD=(mtr -i 0.2 -c "$COUNT" -n --no-dns -e -r "$TARGET")
fi

echo "=== mtr report for $TARGET ==="
"${MTR_CMD[@]}"

echo ""
echo "=== TCP traceroute on 443 ==="
sudo traceroute -n -T -p 443 -q 2 -w 1 "$TARGET" || true

echo ""
echo "=== Path MTU check ==="
tracepath -n -m 30 "$TARGET" | tail -5 || true
```

#### Скрипт сравнения маршрутов (до/после изменений)

```bash
#!/usr/bin/env bash
# traceroute_compare.sh — сравнение двух snapshot'ов маршрута
set -euo pipefail

BEFORE="${1:?Usage: $0 <before.txt> <after.txt>}"
AFTER="${2:?}"

echo "=== Differences ==="
diff -u "$BEFORE" "$AFTER" || true

echo ""
echo "=== New hosts in after ==="
grep -E '^[[:space:]]*[0-9]+:' "$AFTER" | awk '{print $2}' | sort -u > /tmp/after_hosts.txt
grep -E '^[[:space:]]*[0-9]+:' "$BEFORE" | awk '{print $2}' | sort -u > /tmp/before_hosts.txt
comm -23 /tmp/after_hosts.txt /tmp/before_hosts.txt || true
```

#### JSON-анализ mtr (Python)

```python
#!/usr/bin/env python3
import json, sys

def analyze_mtr_json(path):
    with open(path) as f:
        data = json.load(f)
    
    for hop in data.get("report", {}).get("hops", []):
        loss = hop.get("loss", {}).get("avg", 0)
        if loss > 5:
            print(f"WARNING: Hop {hop['id']} ({hop['host']}) loss={loss:.1f}%")

if __name__ == "__main__":
    analyze_mtr_json(sys.argv[1])
```

### Корреляция с другими инструментами

#### traceroute + tcpdump

Захват именно traceroute-пакетов позволяет анализировать, какие именно пакеты отправляются и ответы от роутеров:

```bash
# Захват ICMP Time Exceeded (traceroute ICMP mode)
sudo tcpdump -i eth0 'icmp[0] == 11' -nn -c 10

# Захват UDP-пакетов с портов traceroute (33434+)
sudo tcpdump -i eth0 'udp and portrange 33434-33534' -nn -c 10

# Захват TCP SYN (traceroute TCP mode)
sudo tcpdump -i eth0 'tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0' -nn -c 10
```

#### traceroute + ss

Перед трассировкой проверьте, что целевой порт слушается на конечном хосте:

```bash
# Проверка, слушает ли сервер порт 443
ssh user@target "ss -lntp | grep :443"

# Трассировка только если порт открыт
if ssh user@target "ss -lntp | grep -q ':443 '"; then
    sudo traceroute -n -T -p 443 target
else
    echo "Port 443 is not listening on target"
fi
```

### Production сценарии

#### Сценарий 1: SSH работает, но SCP/rsync зависает

Симптом указывает на **Path MTU** проблему в туннеле или VPN.

```bash
# 1. Трассировка до цели
traceroute -n target

# 2. Проверка MTU на пути
tracepath -n target

# 3. Тест с DF-битом (определяет PMTU Black Hole)
ping -M do -s 1472 -c 3 target
# Если нет ответа → MTU < 1500 или ICMP Type 3/4 заблокирован

# 4. Проверка MSS в TCP SYN
sudo tcpdump -i eth0 'tcp[tcpflags] & tcp-syn != 0' -c 10 -nn | grep -E "mss|target"
```

**Решение:** MSS Clamping или уменьшение MTU на VPN-интерфейсе. Подробнее: **[MTU, PMTUD и диагностика в VPN](../../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)**.

#### Сценарий 2: HTTPS зависает на TLS Handshake

```bash
# 1. TCP traceroute на порт 443 (имитация HTTPS)
sudo traceroute -n -T -p 443 target

# 2. Проверка MTU через tracepath
tracepath -n target

# 3. Захват TLS handshake
sudo tcpdump -i eth0 -nn -s 0 -w /tmp/tls_handshake.pcap 'host target and tcp port 443'
# Анализ в Wireshark: ищем Alert или Handshake Failure
```

#### Сценарий 3: Диагностика асимметричного маршрута

```bash
# Маршрут A → B
traceroute -n -q 2 target > /tmp/trace_a2b.txt

# Маршрут B → A (выполняется на целевом хосте)
traceroute -n -q 2 client > /tmp/trace_b2a.txt

# Сравнение
diff -u /tmp/trace_a2b.txt /tmp/trace_b2a.txt || true
```

**Решение:** Настройка Policy-Based Routing или отключение `rp_filter=1` (осторожно). Подробнее: **[Практические сценарии маршрутизации](../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/routing_scenarios.md)**.

#### Сценарий 4: Потери пакетов только на промежуточных хостах

```bash
# mtr с 100 циклами для статистики
mtr -n --no-dns -c 100 target

# Если Loss% >0 только на хопах 3–5, а на целевом узле 0%:
# → ICMP Rate Limiting на маршрутизаторах (не проблема сети)

# TCP traceroute для подтверждения
sudo traceroute -n -T -p 443 -q 3 target
# Если TCP показывает стабильную задержку без потерь → ICMP Rate Limiting
```

#### Сценарий 5: Anycast и географическая балансировка

```bash
# Трассировка к Anycast-IP из разных точек
traceroute -n 1.1.1.1
traceroute -n 8.8.8.8

# В разных регионах/IP-средах путь может отличаться — это нормально.
# mtr покажет стабильность до ближайшего узла.
mtr -n -c 30 1.1.1.1
```

#### Сценарий 6: NAT и firewall блокируют traceroute

```bash
# Если стандартный traceroute показывает * * * на всех хопах:
# 1. Проверьте локальный firewall
sudo iptables -L OUTPUT -v -n | grep -i icmp

# 2. TCP traceroute через порт 443
sudo traceroute -n -T -p 443 target

# 3. Альтернатива: hping3 TCP traceroute
sudo hping3 --traceroute -T -p 443 target

# 4. Если даже TCP не работает → проблема на 1-м хопе (локальный firewall или шлюз)
```

#### Сценарий 7: Мониторинг jitter для Voice/Video

```bash
# mtr с коротким интервалом (0.5 сек) для оценки jitter
mtr -i 0.5 -c 100 -n target

# StDev > 10 ms — проблемы для VoIP/WebRTC
# Loss% > 1% — требуется вмешательство
```

### Traceroute в контейнерах и netns

```bash
# В стандартном Docker-контейнере traceroute может отсутствовать
# Используйте nicolaka/netshoot (содержит все сетевые утилиты)
docker run --rm -it nicolaka/netshoot traceroute 8.8.8.8

# В netns
sudo ip netns add test_ns
sudo ip netns exec test_ns traceroute 8.8.8.8
```

### Безопасность и ограничения

- **Блокировка ICMP:** Часто блокируют ICMP «для безопасности», но это приводит к проблемам с Path MTU Discovery и диагностикой. Разрешайте как минимум ICMP Type 11 (Time Exceeded) и Type 3/Code 4 (Fragmentation Needed) на файрволах.
- **ICMP Rate Limiting:** Защита Control Plane от flood-атак. На Linux настраивается через `sysctl net.ipv4.icmp_time_exceeded_rate_limit`.
- **Source Routing:** Отключите `net.ipv4.conf.all.accept_source_route=0` для предотвращения обхода firewall.
- **Traceroute как reconnaissance:** В security-audit traceroute используется для маппинга сети. Разрешайте его только доверенным хостам.

## Дополнительная информация

### Нюансы интерпретации

1.  **"Звездочки" (`* * *`):** Означают, что узел не вернул ICMP Time Exceeded. Причины: Firewall, отключенный ICMP на узле, асимметричный маршрут или ICMP Rate Limiting.
2.  **Потери на последнем хопе:** Если `Loss%` на последнем узле равен 100%, но предыдущие узлы отвечают — хост просто блокирует входящие проверки, но сеть исправна.
3.  **Локальные задержки:** Если задержка резко возрастает на первом-втором хопе и сохраняется до конца — проблема в вашем локальном канале или шлюзе.
4.  **MPLS-метки:** В операторских сетях `* * *` может означать, что оборудование не поддерживает Extended ICMP (RFC 4884) для передачи MPLS-информации. Используйте `mtr -e`.

### Связанные инструменты

-   **[ping](./ping.md)** — базовая проверка доступности (L3).
-   **[tcpdump](./tcpdump.md)** — захват пакетов для анализа причин сброса.
-   **[ss](./ss.md)** — просмотр активных сокетов.
-   **[iproute2](../../../Linux/Networking/Tools/iproute2/overview.md)** — управление таблицами маршрутизации.
-   **[Диагностика MTU](../../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — подробнее о Path MTU Discovery.
-   **[ICMP Time Exceeded](../../../Networking/Protocols/ICMP/icmp_time_exceeded.md)** — механизм сообщений об истечении TTL.
-   **[Практические сценарии маршрутизации](../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/routing_scenarios.md)** — ECMP, PBR, VRF, Anycast.
-   **[Структура IP-пакета (IPv4)](../../../Networking/OSI_TCP_IP_Model/Network_layer/Protocols/ip_packet_structure.md)** — поле TTL и флаги.
-   **[Обзор IP-адресации](../../../Networking/Protocols/IP_addressing/ip_overview.md)** — TTL, фрагментация, диагностика.

### Стандарты

- **RFC 792** — ICMPv4.
- **RFC 4443** — ICMPv6.
- **RFC 1812** — Requirements for IP Version 4 Routers (TTL handling).
- **RFC 4884** — Extended ICMP for MPLS and other technologies.
- **RFC 1191** — Path MTU Discovery для IPv4.
- **RFC 8201** — Path MTU Discovery для IPv6.
- **RFC 8305** — Happy Eyeballs (dual-stack connection establishment).
