# Диагностика и устранение неисправностей BIND

---

## Определения

**named-checkconf** — специализированная утилита для проверки синтаксиса конфигурационных файлов **BIND (Berkeley Internet Name Domain)**. Она проверяет только структуру файлов, но не проверяет существование файлов зон или корректность записей в них.

**named-checkzone** — утилита для проверки синтаксиса файлов зонных данных. Проверяет соответствие записей стандартам и наличие обязательных записей (**SOA**, **NS**).

**rndc (Remote Name Daemon Control)** — утилита командной строки для безопасного управления запущенным сервером BIND (перезагрузка зон, очистка кэша, просмотр статистики) без остановки службы.

**named-compilezone** — утилита для компиляции текстового файла зоны в бинарный формат (`raw`), что ускоряет загрузку и снижает потребление CPU при старте.

**RCODE (Response CODE)** — 4-битное поле в заголовке DNS-сообщения, указывающее на результат выполнения запроса. Полный перечень кодов определён в **RFC 1035** и расширениях.

**EDE (Extended DNS Errors)** — механизм из **RFC 8914**, позволяющий серверу возвращать детализированные коды ошибок в секции OPT записи, облегчая диагностику проблем с DNSSEC, блокировками и политиками.

**journal файлы BIND** — бинарные файлы с расширением `.jnl`, находящиеся рядом с файлами зон. Содержат изменения, не записанные в текстовый файл зоны. Позволяют восстанавливать зону после сбоя без потери данных.

**Cache Snooping** — утечка информации из кэша рекурсивного резолвера. В BIND контролируется параметром `allow-query-cache`.

---

## Базовые концепции

### Уровни диагностики

Эффективный поиск неисправностей в **DNS (Domain Name System)** требует последовательного анализа от конфигурации к сети:

| Уровень | Назначение | Инструменты |
| :--- | :--- | :--- |
| **Конфигурация** | Проверка синтаксиса файлов и зон | `named-checkconf`, `named-checkzone`, `named-compilezone` |
| **Служба** | Состояние процесса и системные журналы | `systemctl status`, `journalctl`, `ps` |
| **Сеть** | Доступность портов **UDP/TCP 53**, ACL, firewall | `ss`, `tcpdump`, `iptables/nftables`, `firewall-cmd` |
| **Разрешение** | Тестирование корректности ответов | `dig`, `nslookup`, `host`, `delv` |
| **Управление** | Взаимодействие с активным демоном | `rndc` |
| **Кэш** | Состояние кэша, NXDOMAIN-ответы, stale-записи | `rndc dumpdb`, `rndc flush`, `rndc flushtree` |

### Методология диагностики для SRE

При сбое DNS-сервиса применяйте алгоритм **outside-in**:

1. **Триаж:** Определите масштаб (один клиент, подсеть, весь Интернет).
2. **Валидация конфигурации:** Запустите `named-checkconf` и `named-checkzone` перед любыми изменениями.
3. **Анализ логов:** Ищите последнюю ошибку перед сбоем (`grep -E "ERROR|FAIL|SERVFAIL"`).
4. **Сетевая доступность:** Проверьте порт 53/TCP и 53/UDP с удалённого хоста.
5. **Запрос-ответ:** Выполните `dig` с флагами `+trace`, `+dnssec`, `+tcp` для изоляции проблемы.
6. **Статистика:** Соберите метрики через `rndc status` и статистический канал (если настроен).
7. **Исправление и валидация:** Внесите изменения, перезагрузите/примените конфиг, повторите тест.

### Коды ответов DNS (RCODE)

Код ответа (**RCODE**) в заголовке сообщения указывает на результат выполнения запроса:

*   `NOERROR` (0) — успешное выполнение.
*   `FORMERR` (1) — сервер не смог распознать формат запроса (битый пакет, нестандартный флаг).
*   `SERVFAIL` (2) — сервер не смог обработать запрос (ошибки в конфиге зоны, таймауты вышестоящих серверов, проблемы DNSSEC).
*   `NXDOMAIN` (3) — доменное имя не существует.
*   `NOTIMP` (4) — сервер не поддерживает запрошенную функциональность (устаревший тип запроса).
*   `REFUSED` (5) — сервер отклонил запрос по политическим соображениям (ограничения в **ACL**, отключённая рекурсия).
*   `YXDOMAIN` (6) — доменное имя существует, но не должно существовать согласно изменениям в зоне (RFC 2136, DDNS).
*   `YXRRSET` (7) — запись RRset уже существует при попытке добавления.
*   `NXRRSET` (8) — RRset не существует при попытке удаления.
*   `NOTAUTH` (9) — сервер не авторитативен для запрошенной зоны.
*   `NOTZONE` (10) — имя не принадлежит никакой зоне.
*   `BADVERS` / `BADCOOKIE` / `BADSIG` / `BADKEY` / `BADTIME` — ошибки TSIG, EDNS или DNSSEC.

Подробности по формату сообщения: **[Формат сообщений и коды RCODE](../../../../Networking/Protocols/DNS/dns_message_format.md)**.

---

## Практические сценарии

### 1. Проверка конфигурации и строгость зон

Перед перезапуском службы всегда выполняйте синтаксический анализ. Это минимизирует простои при деплое конфигураций.

```bash
# Проверка основного файла и всех включенных файлов (include)
sudo named-checkconf /etc/bind/named.conf
# → (no output means success)

# Проверка зоны с повышенной строгостью (-k fail запрещает любые отклонения)
sudo named-checkzone -k fail example.com /etc/bind/zones/db.example.com
# → zone example.com/IN: loaded serial 2025072501
# → OK

# Компиляция зоны в raw-формат для ускорения загрузки (BIND 9.9+)
sudo named-compilezone example.com /etc/bind/zones/db.example.com /etc/bind/zones/db.example.com.raw -F raw
# → zone example.com/IN: exported 23 records, 1 errors, 0 warnings
```

**Типичные ошибки:**
*   `missing ';' before '}'` — пропущена точка с запятой в конфиге. Номер строки указывается в выводе.
*   `not at top level` — директива `options` находится внутри блока `view` или `zone`.
*   `bad zone file` — файл зоны имеет неверный формат или отсутствует.

### 2. Анализ системных журналов и службы

При сбоях запуска BIND детализирует ошибки в системном журнале.

```bash
# Просмотр логов в реальном времени
sudo journalctl -u bind9 -f
# → named[1234]: /etc/bind/named.conf.local:5: missing ';' before '}'

# Просмотр логов с момента последнего запуска
sudo journalctl -u bind9 --since today
# → Перечисляет все записи с текущей датой

# Просмотр последних ошибок
sudo journalctl -u bind9 -p err -n 50
# → Выводит последние 50 сообщений уровня err и выше
```

**Типичные ошибки:**
*   `permission denied`: служба не может прочитать файл зоны. Проверьте права: `sudo chown -R bind:bind /etc/bind/zones/`.
*   `no TTL specified`: в файле зоны пропущена директива `$TTL` или TTL не указана в SOA-записи.
*   `AppArmor="DENIED"` / `audit: DENIED`: служба блокируется профилем безопасности при попытке прочитать файл вне разрешенных путей. Проверьте `/etc/apparmor.d/usr.sbin.named` или `/var/log/audit/audit.log`.
*   `listen TCP port 53: permission denied`: попытка привязаться к привилегированному порту (<1024) без прав root. Убедитесь, что сервер стартует от `root` и затем сменяет UID на `bind`.

### 3. Диагностика разрешения имён через dig

Утилита `dig` — основной инструмент отладки.

```bash
# Итеративная трассировка запроса от корневых серверов
dig @127.0.0.1 example.com +trace
# → . 518400 IN NS a.root-servers.net.
# → ...
# → example.com. 172800 IN NS ns1.example.com.

# Проверка конкретного RR-типа
dig @127.0.0.1 example.com MX +noall +answer
# → example.com. 3600 IN MX 10 mail.example.com.

# Проверка DNSSEC-валидации
dig @127.0.0.1 example.com +dnssec +noall +answer +ad
# → ad флаг присутствует, если ответ аутентичен

# Проверка с игнорированием DNSSEC (для диагностики)
dig @127.0.0.1 example.com +cd
# → Обходит проверку DNSSEC, полезно для определения SERVFAIL-причины

# Проверка через TCP (если UDP заблокирован)
dig @127.0.0.1 example.com +tcp
# → Использует TCP вместо UDP

# Проверка ECS-поддержки
dig @127.0.0.1 cdn.example.com A +subnet=192.0.2.0/24 +noall +answer
```

**Ключевые флаги в выводе (flags):**
*   `aa` (**Authoritative Answer**) — ответ получен от мастера зоны (не из кэша).
*   `ra` (**Recursion Available**) — сервер поддерживает рекурсивные запросы.
*   `rd` (**Recursion Desired**) — запрошена рекурсия клиентом.
*   `ad` (**Authentic Data**) — сервер верифицировал DNSSEC-подписи.
*   `cd` (**Checking Disabled**) — клиент запросил отключение проверки DNSSEC.

### 4. Проверка трансфера зон (AXFR/IXFR)

Проверка репликации между первичным (**Master**) и вторичным (**Slave**) серверами.

```bash
# Тестирование полного трансфера (всегда использует TCP)
dig @<IP_MASTER> example.com AXFR
# → example.com. 604800 IN SOA ns1.example.com. ...
# → ...
# → example.com. 604800 IN SOA ns1.example.com. ...

# Проверка Incremental Transfer (IXFR)
dig @<IP_MASTER> example.com IXFR=2025090100
# → Сервер вернёт изменения с указанного Serial

# Если трансфер запрещён, сервер вернёт Transfer failed или REFUSED
```

Если трансфер падает с `connection timed out` — проверьте фаервол между узлами (порт 53/TCP). При `TSIG error` — проверьте совпадение ключей и их включение в конфиг.

### 5. Анализ состояния через rndc

Утилита позволяет получить внутренние метрики без перезагрузки.

```bash
sudo rndc status
# → version: BIND 9.18.28-1~deb12u1-Debian (Extended Support Version)
# → server is up and running
# → number of zones: 15
# → recursive clients: 0/0/1000

# Включение лога всех запросов (для временной отладки)
sudo rndc querylog
# → named[1234]: query logging is now on

# Просмотр статуса конкретной зоны
sudo rndc zonestatus example.com
# → zone example.com/IN: loaded serial 2025090101
# →     last loaded: 2026-09-12 10:00:00 UTC
# →     dumpdb: 0x55a3b2c0d000

# Просмотр ключей DNSSEC
sudo rndc signing -list example.com
# → KSK: active, expires 2026-07-27
# → ZSK: active, expires 2025-10-27

# Выгрузка базы данных в файл (для анализа)
sudo rndc dumpdb -zones /tmp/named_dump.db
# → Dumping database to /tmp/named_dump.db

# Очистка конкретного имени из кэша
sudo rndc flushname example.com
# → Cleared cache for example.com

# Добавление Negative Trust Anchor (NTA) для проблемной зоны
sudo rndc nta -add example.com 3600
# → Added NTA for example.com (expires in 3600 seconds)
```

**Расширенные команды rndc для SRE:**

| Команда | Описание |
| :--- | :--- |
| `sudo rndc status` | Вывод статистики и времени работы сервера. |
| `sudo rndc querylog` | Включение/выключение записи всех входящих запросов в системный журнал. |
| `sudo rndc reload` | Полная перезагрузка конфигурации и всех зон. |
| `sudo rndc reload <zone>` | Перезагрузка конкретной зоны. |
| `sudo rndc reconfig` | Применение изменений в `named.conf` без перезагрузки зон. |
| `sudo rndc flush` | Очистка всего кэша резолвера. |
| `sudo rndc flushname <name>` | Очистка конкретного имени из кэша. |
| `sudo rndc flushname <name> <type>` | Очистка конкретного RRset из кэша. |
| `sudo rndc freeze <zone>` | Отключение динамических обновлений зоны (перед бэкапом). |
| `sudo rndc thaw <zone>` | Возобновление динамических обновлений. |
| `sudo rndc sync <zone>` | Принудительная запись изменений из journal в файл зоны. |
| `sudo rndc notify <zone>` | Отправка NOTIFY вторичным серверам. |
| `sudo rndc sign <zone>` | Переподпись всех записей зоны (DNSSEC). |
| `sudo rndc signing -list <zone>` | Просмотр статуса ключей DNSSEC. |
| `sudo rndc dumpdb [-zones|-cache|-adb]` | Выгрузка внутренних баз данных в файл. |
| `sudo rndc zonestatus <zone>` | Подробный статус зоны (Serial, время загрузки, тип). |
| `sudo rndc nta -list` | Просмотр активных NTA. |
| `sudo rndc nta -add <zone> [lifetime]` | Добавление NTA для отключения валидации DNSSEC. |
| `sudo rndc nta -dump` | Выгрузка всех NTA в файл. |

### 6. Сетевая диагностика через tcpdump и ss

Если сервер не отвечает, проверьте, доходят ли пакеты до порта 53, и нет ли аномального трафика.

```bash
# Перехват DNS-пакетов на интерфейсе eth0
sudo tcpdump -ni eth0 port 53
# → 15:40:01.123 IP 192.168.1.10.12345 > 192.168.1.5.53: 5678+ A? google.com. (28)

# Захват с сохранением в pcap для Wireshark
sudo tcpdump -i any -n -vvv port 53 -w /tmp/dns-debug.pcap -c 10000
# → Останавливается после 10000 пакетов или Ctrl+C

# Фильтрация только запросов к нашему серверу
sudo tcpdump -ni eth0 src port 53 and udp

# Анализ догоняющего трафика (петли, штормы)
sudo tcpdump -r /tmp/dns-debug.pcap -nn port 53 | awk '{print $NF}' | sort | uniq -c | sort -rn | head -20
# → 500 example.com. A? ← признак шторма или петли

# Проверка, слушает ли named порт 53
sudo ss -ulnp | grep ':53'
# → UNCONN 0 0 *:53 *:* users:(("named",pid=1234,fd=10))

# Проверка TCP-соединений (активные трансферы, клиенты)
sudo ss -tnp | grep ':53'
```

### 7. Анализ кэша и NXDOMAIN-ответов

Проблемы с кэшем — частая причина некорректного разрешения после изменения записей.

```bash
# Выгрузка содержимого кэша в файл
sudo rndc dumpdb -cache
# → Dumping cache to /var/cache/bind/named_dump.db

# Просмотр NXDOMAIN-записей (отрицательный кэш)
grep -E "NXDOMAIN|NEGATIVE" /var/cache/bind/named_dump.db | head -20

# Очистка всего кэша (агрессивно, вызывает всплеск запросов к апстримам)
sudo rndc flush

# Очистка только поддерева (менее агрессивно)
sudo rndc flushtree example.com

# Проверка TTL в кэше для конкретного имени
dig @127.0.0.1 example.com +noall +answer
# → example.com. 3599 IN A 93.184.216.34
#    TTL уменьшается, если запись в кэше
```

### 8. Диагностика журналов BIND

Конфигурация логирования позволяет изолировать проблемы по категориям. Без настроенного логирования диагностика превращается в угадывание.

```conf
# Пример настройки в named.conf
logging {
    channel query_log {
        file "/var/log/named/query.log" versions 3 size 10m;
        severity info;
        print-time yes;
        print-severity yes;
        print-category yes;
    };
    channel error_log {
        file "/var/log/named/error.log" versions 5 size 5m;
        severity warning;
        print-time yes;
    };
    channel xfer_log {
        file "/var/log/named/xfer.log" versions 3 size 5m;
        severity info;
        print-time yes;
    };

    category queries { query_log; };
    category general { error_log; };
    category xfer-in { xfer_log; };
    category xfer-out { xfer_log; };
    category security { error_log; };
};
```

```bash
# Поиск ошибок трансфера зон
grep -i "transfer" /var/log/named/xfer.log | tail -20
# → xfer-in: zone example.com/IN: transfer from 10.0.0.1#53: failed: timed out

# Поиск проблем с DNSSEC
grep -i "dnssec\|bogus\|validation" /var/log/named/error.log
# → validation failure: example.com. DNSKEY: bad self-sig

# Мониторинг размера логов
du -sh /var/log/named/
# → 45M    /var/log/named/

# Ротация логов вручную (если logrotate не настроен)
sudo systemctl reload bind9
# или
sudo rndc reconfig
```

### 9. Диагностика проблем с DNSSEC

DNSSEC добавляет слой сложности: невалидная подпись, истёкший RRSIG, неверный DS в родительской зоне — всё это приводит к `SERVFAIL` или `BOGUS`.

```bash
# Проверка цепочки доверия
delv @127.0.0.1 example.com A +rtrace
# → Идёт по цепочке DS → DNSKEY → RRSIG
# →; validation state: Secure

# Проверка DS в родительской зоне
dig parent.example.com DS +dnssec +noall +answer
# → parent.example.com. 86400 IN DS 12345 8 2 ABCDEF...

# Проверка DNSKEY на authoritative сервере
dig @ns1.example.com example.com DNSKEY +noall +answer
# → example.com. 3600 IN DNSKEY 257 3 8 ABCD...

# Проверка RRSIG TTL (осталось времени до подписи)
dig @ns1.example.com example.com A +noall +answer +dnssec
# → example.com. 3600 IN A 93.184.216.34
# → example.com. 3600 IN RRSIG A 8 2 3600 20251001000000 20250901000000 12345 example.com.

# Признак истёкшего RRSIG: текущая дата > 20251001000000

# Обход DNSSEC для диагностики
dig @127.0.0.1 example.com +cd
# → cd (Checking Disabled) отключает валидацию на рекурсоре
```

**Типичные ошибки DNSSEC:**
*   `validation failure: unable to find DS` — DS-запись отсутствует в родительской зоне.
*   `bogus` — RRSIG не совпадает с DNSKEY или время истекло.
*   `expired` — RRSIG имеет более ранний expiration date, чем текущее время.
*   ` insecurity proof failed` — сервер не может доказать, что зона не подписана (NSEC/NSEC3 не сходится).

### 10. Диагностика проблем с ACL и правами доступа

```bash
# Проверка, какой ACL применяется к клиенту
dig @127.0.0.1 example.com +noall +comments +additional
# → Смотрите в логах: matched ACL "internal"

# Проверка REFUSED на рекурсивный запрос
dig @127.0.0.1 google.com +noall +header
# → flags: qr rd; status: REFUSED
# → Причина: allow-recursion не включает ваш IP

# Проверка блокировки трансфера
dig @127.0.0.1 example.com AXFR +noall +comments
# → connection timed out; no servers could be reached
# → Или: transfer failed; TSIG error (если требуется ключ)
```

### 11. Диагностика производительности и загрузки

```bash
# Общая статистика сервера
sudo rndc status
# → recursive clients: 150/1000/5000
# →    (current/high-water/total)
# → TCP connections: 12/100

# Проверка размера кэша
sudo rndc dumpdb -cache
grep "cache size" /var/cache/bind/named_dump.db
# → cache size: 123456 (LRU least recently used entries)

# Проверка размера файлов зон ( Slave-сервер )
ls -lh /var/cache/bind/
# → -rw-r--r-- 1 bind bind 2.3M Sep 12 10:00 db.example.com.jnl
# → -rw-r--r-- 1 bind bind 1.8M Sep 12 09:00 db.example.com

# Поиск утечек памяти (long-running named)
ps -p $(pgrep named) -o pid,rss,vsz,etime
# → PID   RSS    VSZ   ELAPSED
# → 1234  512m   2g     15-03:00:00

# Анализ количества запросов в секунду
sudo tcpdump -i eth0 port 53 -c 1000 -w /tmp/qps.pcap
# Остановите через 10 секунд
# QPS ≈ 1000 / elapsed_time
```

### 12. Диагностика проблем с Views

```bash
# Проверка, какой View выбран для клиента
sudo rndc zonestatus example.com
# → zone example.com/IN: class internal
# →     view: internal_view

# Проверка порядка Views (первый совпадающий wins)
# В named.conf.options:
# view internal_view { match-clients { 10.0.0.0/8; }; ... };
# view external_view { match-clients { any; }; ... };
# Клиент из 10.0.0.0/8 получит ответ от internal_view

# Проверка RPZ в рамках View
dig @127.0.0.1 malware.example.com A +noall +answer +additional
# → Если RPZ сработал: вернётся CNAME или Synthetic NXDOMAIN
```

### 13. Диагностика проблем с Catalog Zones (CatZ)

```bash
# Проверка, загружена ли CatZ
sudo rndc zonestatus catalog.example.com
# → zone catalog.example.com/IN: type master

# Принудительная перезагрузка каталога
sudo rndc reload catalog.example.com

# Проверка, появилась ли новая зона в output
sudo rndc status | grep "number of zones"
# → number of zones: 17  ← должно увеличиться

# Логи по CatZ
grep -i "catalog" /var/log/named/error.log
# → zone 'new-zone.example.com' added from catalog 'catalog.example.com'
```

---

## Типовые неисправности: расширенная таблица

### Служба и запуск

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `named: listen TCP port 53: permission denied` | Попытка привязки к порту <1024 без root-прав или порт занят. | Проверьте `ss -ulnp | grep :53`, отключите конфликтующую службу. |
| `permission denied` при чтении зон | Неверные права на файлы или политики AppArmor/SELinux. | `sudo chown -R bind:bind /etc/bind/zones/`, проверьте AppArmor/SELinux. |
| `no TTL specified` | В файле зоны пропущена директива `$TTL`. | Добавьте `$TTL 3600` в начало файла. |
| `not at top level` | Директива `options` находится вне глобального контекста. | Переместите `options { ... };` в корень `named.conf`. |
| `missing ';' before '}'` | Синтаксическая ошибка в конфигурационном файле. | Исправьте строку, указанную в ошибке. |
| Служба стартует, но не отвечает | Порт 53 занят, или `listen-on` не включает нужный интерфейс. | Проверьте `netstat -tulpn | grep named`, настройки `listen-on`. |

### Разрешение имён и ответы

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`SERVFAIL`** | Ошибка в конфигурации зоны, невалидный Serial, таймаут вышестоящих серверов, DNSSEC Bogus. | `named-checkzone`, проверка `journalctl -u named`, `dig` с флагом `+cd` для обхода DNSSEC. |
| **`REFUSED`** | Запрос отклонён ACL (разделённый DNS, закрытая рекурсия). | Проверка `allow-query`, `allow-recursion`, `match-clients` в Views. |
| **`NXDOMAIN`** | Домен не существует или отрицательный кэш устарел. | Проверьте `dig +trace`, убедитесь что делегирование корректно. |
| **`FORMERR`** | Повреждённый пакет, несовместимый EDNS версия. | Проверьте `tcpdump`, отключите EDNS на тестовом клиенте. |
| **Зона не обновляется** | На Master Serial не увеличен, или Slave кэширует старую версию. | `rndc refresh example.com`, проверьте формат Serial (YYYYMMDDNN). |
| `SERVFAIL` только для DNSSEC-доменов | DS-запись не добавлена в родительскую зону, или KSK истёк. | Проверьте `dig parent DS +dnssec`, обновите DS, проверьте RRSIG. |
| Запросы к локальному серверу идут в Интернет | `forwarders` не настроены, рекурсия разрешена. | Настройте `forwarders { 8.8.8.8; 1.1.1.1; };` или отключите рекурсию. |

### Трансфер зон и репликация

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `transfer of '...' failed: connection refused/time out` | Закрыт TCP/53 между узлами. | Трансфер всегда идёт по TCP — проверьте firewall. |
| `dumping master file ... permission denied` | Нет прав на запись в каталог файла Slave-зоны. | `chown bind:bind /var/cache/bind`, проверьте AppArmor. |
| `TSIG error` | Несовпадение ключей или отсутствие ключа в конфигурации. | Проверьте `include "/etc/bind/transfer.key"`, сравнивайте алгоритмы. |
| Slave не видит изменения после правки зоны | Не увеличен Serial на мастере. | Сравните `dig master SOA +short` и `dig slave SOA +short`. |
| IXFR не работает | Slave и Master используют разные форматы Serial (YYYYMMDDNN vs инкремент). | Приведите Serial к единому формату. |

### Производительность и ресурсы

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Высокое потребление памяти | Неограниченный кэш, утечка в QP-trie, DDoS-атака (Water Torture). | Установите `max-cache-size`, `rate-limit`, анализируйте логи. |
| Высокая загрузка CPU | Большое количество рекурсивных запросов, неоптимальные зоны. | Увеличьте `recursive-clients`, включите `prefetch`, проверьте зоны. |
| Медленные ответы | Задержки к апстримам, перегрузка, маленький размер `tcp-clients`. | Проверьте `dig +tcp`, мониторьте RTT до форвардеров. |
| `too many open files` | `max-clients-per-query` или `tcp-clients` превышают лимит файлов. | Увеличьте `ulimit -n` в юните `named.service`, или настройте `max-clients-per-query`. |
| Утечка файловых дескрипторов | Не закрываются journal файлы при частых обновлениях. | Перезапустите службу, обновите пакет BIND. |

### Безопасность и аномалии

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Water Torture` (шторм случайных поддоменов) | DDoS-атака на кэш резолвера. | Включите `rate-limit`, `response-policy` с черными списками. |
| `BOGUS` ответы от авторитатива | Невалидная DNSSEC-цепочка. | Проверьте DS, DNSKEY, RRSIG; добавьте NTA для временного обхода. |
| Внешние клиенты получают внутренние IP | View не покрывает IP, порядок Views нарушен. | Проверьте `match-clients`, порядок `view` в конфигурации. |
| Логи заполняются пустыми запросами | Открытый рекурсивный резолвер атакуют. | Ограничьте `allow-recursion`, включите `rate-limit`. |

---

## Диагностика конкретных компонентов

### named-checkconf: расширенное использование

```bash
# Проверка с выводом всех предупреждений
sudo named-checkconf -p /etc/bind/named.conf
# → Печатает распознанную конфигурацию (полезно для отладки include)

# Проверка конкретного файла
sudo named-checkconf -z /etc/bind/named.conf
# → -z включает проверку существования файлов зон

# Проверка только синтаксиса (без проверки файлов зон)
sudo named-checkconf -t /etc/bind/named.conf
```

### named-checkzone: расширенное использование

```bash
# Проверка с чекбоксом DLV (DNSSEC Lookaside Validation)
sudo named-checkzone -k fail -l dlv.isc.org example.com /etc/bind/zones/db.example.com

# Проверка только SOA/NS записей
sudo named-checkzone -s example.com /etc/bind/zones/db.example.com
# → Печатает только SOA и NS записи

# Проверка с отчётом о всех warning
sudo named-checkzone -r warn example.com /etc/bind/zones/db.example.com
```

### rndc dumpdb: анализ внутренних баз

```bash
# Выгрузка кэша
sudo rndc dumpdb -cache
grep -E "NXDOMAIN|NEGATIVE" /var/cache/bind/named_dump.db | head -20
# → negative entry: example.com. A

# Выгрузка ADB (Address Database)
sudo rndc dumpdb -adb
# → Содержит записи о серверах, к которым обращался BIND

# Выгрузка всех зон
sudo rndc dumpdb -zones
# → Полезно для проверки Serial на running-сервере без dig
grep "example.com" /var/cache/bind/named_dump.db | head -5
```

### dig: расширенные сценарии

```bash
# Проверка, что ответ авторитативен и из кэша
dig @127.0.0.1 example.com +noall +comments +answer +authority +additional
# → ;; flags: qr aa rd ra;  ← aa = authoritative
# → Если aa нет — ответ из кэша или переадресован

# Проверка ANY-записи (RFC 8482: ограниченный ответ)
dig @127.0.0.1 example.com ANY +noall +answer
# → ANY может возвращать ограниченный набор записей (защита от амплификации)

# Проверка на Open Resolver
dig @<your-server> example.com +noall +comments
# → Если у вас нет клиентов из внешней сети, resolver должен быть закрыт:
# → status: REFUSED (для внешних IP)

# Проверка TCP-доступности
dig @127.0.0.1 example.com +tcp +noall +comments
# → Если падает с connection timed out — TCP/53 заблокирован фаерволом
```

### tcpdump и ngrep: расширенные сценарии

```bash
# Поиск шторма ANY-запросов (амплификация)
sudo tcpdump -i eth0 -n port 53 -c 1000 -w /tmp/dns-storm.pcap
# В Wireshark или tshark:
tshark -r /tmp/dns-storm.pcap -Y "dns.flags.recdesired == 1 && dns.qry.type == 255" | wc -l
# → Количество ANY-запросов

# Поиск петлей форвардинга (повторяющиеся запросы)
sudo tcpdump -i eth0 -n port 53 | awk '{print $9}' | sort | uniq -c | sort -rn | head -10
# → 1500 example.com. ← признак петли

# Анализ только ошибочных ответов
sudo tcpdump -i eth0 -n port 53 -A | grep -E "SERVFAIL|REFUSED|FORMERR|NXDOMAIN"
```

### Journal и логи: паттерны для SRE

```bash
# Поиск всех ошибок за последний час
sudo journalctl -u bind9 --since "1 hour ago" -p err | tail -50

# Подсчёт количества SERVFAIL за период
sudo journalctl -u bind9 --since today | grep -c "SERVFAIL"
# → 142

# Поиск конкретной ошибки трансфера
sudo journalctl -u bind9 --since today | grep -i "transfer of"
# → transfer of 'example.com/IN' from 10.0.0.1#53: failed: timed out

# Мониторинг в реальном времени (tail -f аналог)
sudo journalctl -u bind9 -f | grep -E "ERROR|FAIL|SERVFAIL|REFUSED"

# Экспорт логов для анализа
sudo journalctl -u bind9 --since "2026-09-01" > /tmp/bind-logs-sept.txt
wc -l /tmp/bind-logs-sept.txt
# → 12543

# Анализ логов с помощью awk (поиск самых активных клиентов)
sudo journalctl -u bind9 --no-pager -o json | jq -r '.SYSLOG_IDENTIFIER' | sort | uniq -c | sort -rn | head -10
```

---

## Диагностика проблем с journal-файлами зон

Journal-файлы (`.jnl`) содержат динамические изменения, не записанные в текстовый файл зоны. Их повреждение приводит к невозможности загрузки зоны.

```bash
# Проверка размера journal-файла
ls -lh /var/cache/bind/*.jnl
# → -rw-r--r-- 1 bind bind 2.3M Sep 12 10:00 db.example.com.jnl

# Если journal повреждён, синхронизируйте зону
sudo rndc sync example.com
# → Synchronizing zone 'example.com/IN'
# → Journal file synced to master file

# Если sync не помогает, заморозьте зону, сбросьте journal и thaw
sudo rndc freeze example.com
sudo systemctl stop bind9
sudo rm /var/cache/bind/db.example.com.jnl
sudo systemctl start bind9
sudo rndc thaw example.com
# → Zone 'example.com/IN' thawed

# Проверка формата Serial (должен быть YYYYMMDDNN)
dig @127.0.0.1 example.com SOA +short
# → ns1.example.com. admin.example.com. 2025090101 3600 600 604800 300
# → Serial 2025090101: год=2025, месяц=09, день=01, номер=01
```

---

## Мониторинг и алертинг для SRE

### Минимальный набор метрик

```bash
# Доступность службы
systemctl is-active --quiet bind9 && echo "OK" || echo "FAIL"

# Время работы (uptime)
sudo rndc status | grep "server is up"
# → server is up for 15 days 3 hours 2 minutes

# Количество зон
sudo rndc status | grep "number of zones"
# → number of zones: 15

# Загрузка рекурсивных клиентов
sudo rndc status | grep "recursive clients"
# → recursive clients: 0/0/1000

# Размер кэша
sudo rndc dumpdb -cache
grep "cache size" /var/cache/bind/named_dump.db
# → cache size: 123456

# Количество ошибок в логах за 5 минут
sudo journalctl -u bind9 --since "5 minutes ago" | grep -c "ERROR\|SERVFAIL\|FAIL"
# → 0
```

### Примеры скриптов мониторинга

```bash
#!/bin/bash
# bind-health.sh — простой health-check для мониторинга

HOST="127.0.0.1"
DOMAIN="example.com"
EXPECTED_NS="ns1.example.com"

# 1. Доступность
if ! dig @$HOST $DOMAIN +noall +answer +short | grep -q "$EXPECTED_NS"; then
    echo "CRITICAL: DNS not responding or wrong answer"
    exit 2
fi

# 2. DNSSEC (если ожидается)
if ! dig @$HOST $DOMAIN +dnssec +noall +ad | grep -q "ad"; then
    echo "WARNING: DNSSEC validation not working"
fi

# 3. Serial freshness (Slave)
CURRENT=$(dig @$HOST $DOMAIN SOA +short | awk '{print $3}')
# Сравнить с ожидаемым Serial (можно хранить в файле)
echo "OK: Serial=$CURRENT"
```

---

## Постинцидентный анализ (Postmortem)

После устранения инцидента выполните следующие шаги:

1. **Таймлайн:** определите время начала проблемы по первым ошибкам в логах (`journalctl --since "incident_time"`).
2. **Причина:** классифицируйте (конфигурационная ошибка, сбой оборудования, DDoS, человеческий фактор).
3. **Воздействие:** сколько клиентов/зон было затронуто, длительность простоя.
4. **Исправление:** документируйте шаги, которые привели к восстановлению.
5. **Предотвращение:** добавьте мониторинг, измените процесс деплоя (канареечные deployments, `named-checkconf` в CI/CD).

```bash
# Сбор дампа состояния для postmortem
{
    echo "=== rndc status ==="
    sudo rndc status
    echo "=== zones ==="
    sudo rndc zonestatus example.com
    echo "=== recent logs ==="
    sudo journalctl -u bind9 --since "2 hours ago" -p err
    echo "=== cache dump ==="
    sudo rndc dumpdb -cache
    echo "=== network ==="
    sudo ss -ulnp | grep ':53'
} > /tmp/bind-postmortem-$(date +%Y%m%d%H%M).txt
```

---

## Связанные темы

*   **[Обзор BIND](./overview.md)** — архитектура и роли, типичные проблемы и решения.
*   **[Продвинутые возможности](./advanced_topics.md)** — настройка логирования, Views, RPZ, rndc, troubleshooting для CatZ и ECS.
*   **[Установка BIND](./installation.md)** — устранение проблем при установке и первоначальной настройке.
*   **[Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md)** — защита от подмены кэша, DNSSEC, TSIG, DoS-защита.
*   **[Протокол DNS](../../../../Networking/Protocols/DNS/dns.md)** — теоретическая база, RCODE, формат сообщений.
*   **[Диагностика сетевых служб DNS](../../../Diagnostics/Networking/dns/overview.md)** — общие принципы резолвинга в Linux.
*   **[Зоны DNS и SOA](../../../../Networking/Protocols/DNS/dns_zones.md)** — иерархия и управление записью Start of Authority.
