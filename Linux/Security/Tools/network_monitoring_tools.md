# Инструменты сетевого мониторинга для безопасности

## Определения и терминология

**Инструменты сетевого мониторинга** — утилиты для перехвата, анализа и диагностики сетевого трафика в реальном времени или из сохранённых дампов. В контексте безопасности используются для обнаружения подозрительной активности, анализа инцидентов, проверки сетевых политик и аудита трафика.

> **Примечание:** Данный файл фокусируется на применении инструментов для задач безопасности. Для подробного описания технических деталей, архитектуры и диагностики см. соответствующие файлы в разделе Диагностика.

### Основные инструменты

| Инструмент | Описание | Уровень | Подробности |
| :--- | :--- | :--- | :--- |
| **tcpdump** | Консольный перехватчик пакетов на основе libpcap. Стандартный инструмент в большинстве Linux-дистрибутивов. | L2-L4 | **[tcpdump — диагностика](../../Diagnostics/Networking/tcpdump.md)** |
| **tshark** | Консольная версия Wireshark для анализа протоколов. Поддерживает декодирование сотен протоколов. | L2-L7 | **[Wireshark](../../../Networking/ServicesAndTools/Wireshark/definitions.md)** |
| **ss (Socket Statistics)** | Современная замена netstat для отображения информации о сокетах и соединениях. | L4 | **[ss — диагностика](../../Diagnostics/Networking/ss.md)** |
| **nstat / netstat** | Утилиты для отображения статистики сетевых интерфейсов и соединений. | L3-L4 | **[netstat — диагностика](../../Diagnostics/Networking/netstat.md)** |
| **iftop** | Мониторинг сетевого трафика в реальном времени по хостам. | L3-L4 | — |
| **nethogs** | Мониторинг сетевого трафика по процессам. | L3-L4 | — |

### Уровни модели OSI для перехвата

| Уровень | Описание | Инструменты |
| :--- | :--- | :--- |
| **L2 (Data Link)** | Ethernet фреймы, MAC-адреса, VLAN теги | tcpdump, tshark |
| **L3 (Network)** | IP-пакеты, маршрутизация, ICMP | tcpdump, tshark |
| **L4 (Transport)** | TCP/UDP сегменты, порты, соединения | tcpdump, tshark, ss |
| **L7 (Application)** | Протоколы приложений (HTTP, DNS, SSH) | tshark, Wireshark |

## Основные концепции

### Применение в безопасности

1. **Обнаружение вторжений:** Перехват подозрительного трафика (сканирование портов, C2-каналы, exfiltration)
2. **Анализ инцидентов:** Реконструкция событий из pcap-файлов
3. **Проверка политик:** Верификация работы межсетевых экранов и правил
4. **Аудит:** Сохранение доказательств для forensic-анализа
5. **Диагностика:** Поиск сетевых проблем и утечек

### Фильтры BPF (Berkeley Packet Filter)

BPF — язык для создания фильтров перехвата пакетов. Используется в tcpdump, tshark и других инструментах.

**Синтаксис:**
```
protocol direction type expression
```

**Примеры:**
- `host 192.168.1.100` — только трафик с/на указанный хост
- `port 22` — только SSH-трафик
- `tcp port 80` — только HTTP
- `src net 10.0.0.0/8` — только исходящий трафик из сети 10.0.0.0/8
- `dst port 443 and not host 10.0.0.1` — HTTPS к любому хосту кроме 10.0.0.1

## Практические сценарии

### tcpdump — перехват трафика

**Базовый синтаксис:**
```bash
# Интерфейс для перехвата
tcpdump -i eth0

# Сохранение в файл
tcpdump -i eth0 -w capture.pcap

# Чтение из файла
tcpdump -r capture.pcap

# Числовые порты (не разрешать имена)
tcpdump -n -i eth0

# Без DNS-резолва
tcpdump -nn -i eth0

# Ограничение пакетов
tcpdump -c 100 -i eth0  # Первые 100 пакетов

# Увеличение детализации
tcpdump -v -i eth0   # -v, -vv, -vvv
```

**Фильтрация:**
```bash
# По хосту
tcpdump -i eth0 host 192.168.1.100
tcpdump -i eth0 src host 192.168.1.100
tcpdump -i eth0 dst host 192.168.1.100

# По порту
tcpdump -i eth0 port 22
tcpdump -i eth0 src port 80
tcpdump -i eth0 dst port 443

# По протоколу
tcpdump -i eth0 tcp
tcpdump -i eth0 udp
tcpdump -i eth0 icmp

# Комбинированные фильтры
tcpdump -i eth0 'host 192.168.1.100 and port 22'
tcpdump -i eth0 'tcp port 80 or tcp port 443'
tcpdump -i eth0 'not port 22'  # Всё кроме SSH
```

**Сценарии безопасности:**
```bash
# Обнаружение сканирования портов
tcpdump -i eth0 'tcp[tcpflags] & (tcp-syn) != 0 and tcp[tcpflags] & (tcp-ack) == 0' -nn

# Подозрительный DNS-трафик (большие ответы)
tcpdump -i eth0 'udp port 53 and len > 512' -nn

# SSH-brute force (много SYN на порт 22)
tcpdump -i eth0 'tcp port 22 and tcp[tcpflags] & (tcp-syn) != 0' -nn

# HTTP-трафик без шифрования
tcpdump -i eth0 'tcp port 80' -A  # ASCII вывод содержимого

# Telnet (незашифрованный)
tcpdump -i eth0 'tcp port 23' -A
```

**Сохранение и анализ:**
```bash
# Сохранение с фильтрацией
tcpdump -i eth0 -w suspicious.pcap 'not port 22 and not port 443'

# Чтение с фильтрацией
tcpdump -r suspicious.pcap 'host 10.0.0.5'

# Конвертация форматов
tcpdump -r input.pcap -w output.pcap 'tcp port 80'
```

### tshark — анализ протоколов

**Базовый синтаксис:**
```bash
# Интерфейс для перехвата
tshark -i eth0

# Сохранение в файл
tshark -i eth0 -w capture.pcap

# Чтение из файла
tshark -r capture.pcap

# Числовые порты
tshark -n -i eth0

# Ограничение пакетов
tshark -c 100 -i eth0
```

**Фильтры;display filters (отличаются от BPF):**
```bash
# По хосту
tshark -r capture.pcap -Y 'ip.addr == 192.168.1.100'

# По порту
tshark -r capture.pcap -Y 'tcp.port == 22'

# По протоколу
tshark -r capture.pcap -Y 'http'
tshark -r capture.pcap -Y 'dns'

# Комбинированные фильтры
tshark -r capture.pcap -Y 'http && ip.src == 192.168.1.100'
tshark -r capture.pcap -Y 'dns && dns.flags.response == 1'
```

**Извлечение данных:**
```bash
# Извлечение HTTP-запросов
tshark -r capture.pcap -Y 'http.request' -T fields -e http.host -e http.request.uri

# Извлечение DNS-имён
tshark -r capture.pcap -Y 'dns.qr == 0' -T fields -e dns.qry.name

# Извлечение IP-адресов
tshark -r capture.pcap -T fields -e ip.src -e ip.dst

# Извлечение портов
tshark -r capture.pcap -T fields -e tcp.srcport -e tcp.dstport

# Статистика по хостам
tshark -r capture.pcap -q -z io,phs

# Статистика по протоколам
tshark -r capture.pcap -q -z io,ps
```

**Сценарии безопасности:**
```bash
# Обнаружение DNS-туннелирования (большие запросы)
tshark -r capture.pcap -Y 'dns && dns.qry.name.len > 50'

# Поиск HTTP Basic Auth (незашифрованные учётные данные)
tshark -r capture.pcap -Y 'http.authorization'

# Обнаружение картинирования (ICMP с данными)
tshark -r capture.pcap -Y 'icmp && data.len > 48'

# Анализ TLS-соединений (без расшифровки)
tshark -r capture.pcap -Y 'tls.handshake.type == 1' -T fields -e tls.extensions_server_name

# Поиск подозрительных User-Agent
tshark -r capture.pcap -Y 'http.user_agent contains "curl"'
```

### ss — статистика сокетов

**Базовый синтаксис:**
```bash
# Все соединения
ss -a

# TCP-соединения
ss -t

# UDP-соединения
ss -u

# Listening-сокеты
ss -l

# Процессы (PID/имя)
ss -p

# Числовые порты
ss -n

# DNS-резолв
ss -r

# Группировка по состоянию
ss -s
```

**Фильтрация:**
```bash
# По состоянию
ss -t state established
ss -t state time-wait
ss -t state listening

# По порту
ss -tn sport = :22
ss -tn dport = :443

# По хосту
ss -tn src 192.168.1.100
ss -tn dst 10.0.0.5

# Комбинированные фильтры
ss -tn state established '( sport = :22 or sport = :443 )'
ss -tn dst 10.0.0.5 dport = :8080
```

**Сценарии безопасности:**
```bash
# Обнаружение скрытых listening-сокетов
ss -tlnp | grep -v -E ':(22|80|443|8080)'

# Поиск необычных соединений
ss -tnp | grep -v -E ':(22|80|443|53)'

# Мониторинг соединений в реальном времени
watch -n 1 'ss -tn state established | wc -l'

# Подсчёт соединений по хостам
ss -tn | awk '{print $5}' | cut -d: -f1 | sort | uniq -c | sort -rn

# Подсчёт соединений по портам
ss -tn | awk '{print $4}' | rev | cut -d: -f1 | rev | sort | uniq -c | sort -rn
```

### netstat — статистика сетей (устаревший, но ubiquitous)

**Базовый синтаксис:**
```bash
# Все соединения
netstat -a

# TCP-соединения
netstat -t

# UDP-соединения
netstat -u

# Listening-сокеты
netstat -l

# Процессы (PID/имя)
netstat -p

# Числовые порты
netstat -n

# Маршрутизация
netstat -r

# Интерфейсы
netstat -i

# Счётчики
netstat -s
```

**Сравнение ss и netstat:**
```bash
# netstat: показать соединения
netstat -tnp | grep ESTABLISHED

# ss: аналогичный запрос (быстрее)
ss -tnp state established

# netstat: listening-сокеты
netstat -tlnp

# ss: listening-сокеты
ss -tlnp
```

**Примечание:** `ss` значительно быстрее `netstat` на системах с большим количеством соединений.

## Дополнительная информация

### Инструменты для мониторинга в реальном времени

**iftop:**
```bash
# Установка (Debian/Ubuntu)
apt install iftop

# Установка (RHEL/CentOS)
yum install iftop

# Запуск
iftop -i eth0

# Без DNS-резолва
iftop -n -i eth0

# Фильтрация по порту
iftop -f "port 22" -i eth0
```

**nethogs:**
```bash
# Установка (Debian/Ubuntu)
apt install nethogs

# Установка (RHEL/CentOS)
yum install nethogs

# Запуск
nethogs eth0

# Обновление каждые 2 секунды
nethogs -d 2 eth0
```

### Безопасные практики

1. **Ограничение времени перехвата:** Всегда используйте `-c` для ограничения количества пакетов или `-G` для ротации файлов
2. **Фильтрация:** Минимизируйте область перехвата с помощью BPF-фильтров
3. **Хранение:** pcap-файлы могут содержать пароли и конфиденциальные данные
4. **Права доступа:** Перехват требует root-привилегий или `CAP_NET_RAW`
5. **Производительность:** Перехват на высоконагруженных интерфейсах может вызвать проблемы

### Интеграция с другими инструментами

```bash
# Сохранение для анализа в Wireshark
tcpdump -i eth0 -w evidence.pcap

# Передача по сети
tcpdump -i eth0 -w - | ssh remote 'cat > capture.pcap'

# Автоматический мониторинг
while true; do
  ss -tn state established | wc -l >> connection_count.log
  sleep 60
done
```

### Типичные ошибки при анализе трафика

1. **Отсутствие фильтров:** Перехват всего трафика на нагруженных интерфейсах
2. **Неправильный порядок фильтров:** BPF и display-фильтры имеют разный синтаксис
3. **Игнорирование шифрования:** TLS/SSH-трафик недоступен для анализа содержимого
4. **Недостаточная детализация:** Использование `-n` без понимания последствий
5. **Отсутствие timestamps:** Не добавлен `-tttt` для человекочитаемых временных меток

## Дополнительная информация

### См. также

- **[tcpdump — диагностика](../../Diagnostics/Networking/tcpdump.md)** — технические детали, архитектура, диагностика потерь пакетов
- **[ss — диагностика](../../Diagnostics/Networking/ss.md)** — подробное описание работы с сокетами, очереди Recv-Q/Send-Q
- **[netstat — диагностика](../../Diagnostics/Networking/netstat.md)** — устаревшая утилита, но важна для legacy-систем
- **[Wireshark](../../../Networking/ServicesAndTools/Wireshark/definitions.md)** — GUI-анализатор протоколов
- **[Инцидент-респонс](../Concepts/incident_response.md)** — процедуры реагирования на инциденты