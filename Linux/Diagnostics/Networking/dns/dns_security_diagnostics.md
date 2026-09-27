# Диагностика безопасности DNS: DNSSEC, DoH/DoT, DDoS

## Определения

**DNSSEC Validation Failure** — ситуация, при которой резолвер не может проверить цифровую подпись DNS-записи (RRSIG) из-за отсутствия ключа (DNSKEY), несоответствия DS-записи в родительской зоне или истечения срока действия подписи. Проявляется как SERVFAIL для легитимных доменов.

**DNSSEC Signature Expiration** — истечение срока действия RRSIG-подписи. Происходит при неработающем механизме автоматического обновления подписей (раннере). Проявляется как SERVFAIL через 24–48 часов после последнего обновления.

**DoT Handshake Failure** — ошибка установки TLS-соединения на порту 853. Причины: просроченный или недоверенный сертификат резолвера, блокировка порта 853 файрволом, несовпадение версий TLS.

**DNS Tunneling Detection** — обнаружение необычного DNS-трафика, характерного для туннелирования данных (длинные имена, высокая частота TXT-запросов, высокая энтропия имён). Используется для обнаружения C2-каналов и утечки данных.

> **Примечание:** Определения DNS Amplification, RRL и других атак см. в [Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md).

## Базовые концепции

### Алгоритм диагностики DNS-проблем безопасности

| Шаг | Действие | Цель |
| :--- | :--- | :--- |
| **1** | `dig example.com +dnssec +cd +short` | Проверить, работает ли домен без DNSSEC-валидации |
| **2** | `dig example.com +dnssec +short` | Проверить, возвращает ли резолвер DNSSEC-данные |
| **3** | `dig example.com DNSKEY +dnssec` | Проверить наличие ключей DNSKEY |
| **4** | `dig example.com DS +short` | Проверить DS-запись в родительской зоне |
| **5** | `dig example.com RRSIG +short` | Проверить наличие и корректность подписей |
| **6** | `date -u` | Проверить системные часы (RRSIG имеет inception/expiration) |
| **7** | `openssl s_client -connect 1.1.1.1:853` | Проверить DoT-соединение |

### Симптомы и их классификация

| Симптом | Категория | Вероятная причина |
| :--- | :--- | :--- |
| **SERVFAIL для всех доменов** | DNSSEC | Повреждён trust anchor или неправильные часы |
| **SERVFAIL только для подписанных зон** | DNSSEC | Истёк RRSIG или неверный DS |
| **REFUSED на порту 853** | DoT | Сертификат резолвера недоверен |
| **Таймаут на порту 853** | DoT | Порт 853 заблокирован файрволом |
| **Внезапный рост трафика на UDP/53** | DDoS | DNS-амплификация |
| **Рост SERVFAIL в логах** | DDoS/RRL | RRL отбросил legitimate-запросы |
| **Длинные имена в логах** | Tunneling | DNS-туннелирование |

### Проверка DNSSEC-цепочки доверия

```bash
# 1. Проверка от корня до домена
dig . DNSKEY +dnssec +short | head -2
# → Должны быть корневые ключи (KSK с флагом 257)

# 2. Проверка DS-записи родительской зоны
dig com DS +short
# → Хеш KSK зоны .com

# 3. Проверка DNSKEY целевого домена
dig example.com DNSKEY +dnssec +short
# → Ключи ZSK (флаг 256) и KSK (флаг 257)

# 4. Проверка подписей
dig example.com A +dnssec +multiline
# → Должен содержать RRSIG с inception/expiration

# 5. Валидация через delv (если установлен)
delv example.com A +rtrace
# → Показывает полную цепочку валидации
```

## Практические сценарии

### Сценарий 1: SERVFAIL из-за истёкшего RRSIG

**Симптом:** Клиенты получают SERVFAIL для конкретного домена, хотя раньше всё работало.

**Диагностика:**

```bash
# 1. Проверка с отключённой валидацией
dig @8.8.8.8 example.com +cd +short
# → Если возвращает IP — проблема в DNSSEC

# 2. Проверка подписей
dig @8.8.8.8 example.com A +dnssec +multiline
# → Ищем RRSIG: signatures: 0 (или нет RRSIG)

# 3. Проверка authoritarian NS
dig @ns1.example.com example.com A +dnssec +short
# → Если authoritative не отдаёт RRSIG — проблема на сервере зоны

# 4. Проверка DS-записи
dig example.com DS +short
# → Если DS есть, но DNSKEY не совпадает — проблема с ключами

# 5. Проверка часов
date -u
# → Если время сильно отличается — RRSIG может быть «ещё не действителен» или «просрочен»
```

**Решение:** Обновить RRSIG на authoritative сервере (`rndc signing -z example.com` для BIND), проверить cron/раннер обновления подписей.

### Сценарий 2: SERVFAIL для всех доменов (повреждён trust anchor)

**Симптом:** Все DNS-запросы возвращают SERVFAIL, включая Google.

**Диагностика:**

```bash
# 1. Проверка с +cd (без валидации)
dig @8.8.8.8 google.com +cd +short
# → Если работает — проблема в trust anchor

# 2. Проверка корневых ключей
dig . DNSKEY +dnssec +short
# → Если пусто — trust anchor повреждён

# 3. Проверка для systemd-resolved
resolvectl dnssec example.com
# → Проверить статус DNSSEC

# 4. Проверка для Unbound
unbound-control list_stubs | grep "."
# → Должен содержать trust anchor
```

**Решение:** Обновить trust anchor: `unbound-anchor -a /var/lib/unbound/root.key` или `dnssec-settime -K /etc/bind/keys -I now .` для BIND.

### Сценарий 3: DoT-соединение не устанавливается

**Симптом:** `dig +tls @1.1.1.1 example.com` возвращает ошибку соединения.

**Диагностика:**

```bash
# 1. Проверка доступности порта 853
nc -zv 1.1.1.1 853
# → Connection refused или timeout

# 2. Проверка сертификата
openssl s_client -connect 1.1.1.1:853 -servername 1.1.1.1
# → Смотрим на ошибки проверки сертификата

# 3. Проверка версии TLS
openssl s_client -connect 1.1.1.1:853 -tls1_3
# → Если ошибка — сервер не поддерживает TLS 1.3

# 4. Проверка через tcpdump
sudo tcpdump -i any port 853 -nn -c 5
# → Если пакетов нет — файрвол блокирует

# 5. Проверка systemd-resolved
resolvectl status | grep -i "dns over tls\|dot"
```

**Решение:** Открыть порт 853/TCP в файрволе, проверить сертификаты CA, обновить системные корневые сертификаты.

### Сценарий 4: Подозрение на DNS-амплификацию (DDoS)

**Симптом:** Резкий рост входящего UDP-трафика на порту 53, сервер отвечает медленно или не отвечает.

**Диагностика:**

```bash
# 1. Проверка количества UDP-соединений
ss -unp | grep :53 | wc -l
# → Если > 10000 — возможна атака

# 2. Анализ пакетов
sudo tcpdump -i any port 53 -nn -c 100 -w dns_attack.pcap
# → Анализировать в Wireshark: source IPs, query types

# 3. Проверка логов BIND
journalctl -u named | grep -c "rate limit"
# → Если много rate-limited — RRL срабатывает

# 4. Проверка RRL-конфигурации
rndc stats
cat /var/cache/bind/named.stats | grep "rate"
```

**Решение:** Включить/настроить RRL в BIND: `rate-limit { responses-per-second 10; window 5; };`. Внешняя защита: CDN (Cloudflare, Akamai), upstream фильтрация провайдера.

### Сценарий 5: Обнаружение DNS-туннелирования

**Симптом:** Аномальный DNS-трафик — длинные имена, много TXT-запросов, необычный объём.

**Диагностика:**

```bash
# 1. Анализ логов на длинные имена
journalctl -u named -f | awk '{print length, $0}' | sort -rn | head -20
# → Имена > 50 символов подозрительны

# 2. Поиск аномальных TXT-запросов
tcpdump -i any port 53 -nn 'udp[10] & 0x80 == 0 and udp[11] & 0xff == 16' -l | \
  awk '{print $NF}' | sort | uniq -c | sort -rn | head -20
# → TXT-запросы с высокой частотой

# 3. Проверка энтропии имён
# (Аномальные имена имеют высокую энтропию — случайные символы)
cat /var/log/named/queries.log | \
  awk '{print $NF}' | \
  awk '{n=gsub(/[^a-zA-Z0-9]/,"",$1); print n/length($1), $0}' | \
  sort -rn | head -20

# 4. Проверка IP-адресов с высоким QPS
cat /var/log/named/queries.log | \
  awk '{print $1}' | sort | uniq -c | sort -rn | head -20
```

**Решение:** Настроить RPZ (Response Policy Zones) для блокировки подозрительных доменов, увеличить логирование, настроить алерты на аномалии.

### Сценарий 6: RRL блокирует легитимных клиентов

**Симптом:** Легитимные клиенты получают REFUSED или пустые ответы при высокой нагрузке.

**Диагностика:**

```bash
# 1. Проверка RRL-статистики
rndc stats
# → Смотрим «rate-limited responses»

# 2. Тест с одного IP
for i in $(seq 1 100); do
  dig @server example.com +short +time=1 +tries=1
done | sort | uniq -c
# → Если часть запросов отклонена — RRL слишком агрессивен

# 3. Проверка RRL-конфигурации
grep -A5 "rate-limit" /etc/bind/named.conf.options
```

**Решение:** Увеличить `responses-per-second` в RRL-конфиге, добавить `expires` для legitimate-клиентов, увеличить `window`.

### Сценарий 7: Диагностика DNSSEC после делегирования зоны

**Симптом:** После передачи зоны на новый authoritative сервер DNSSEC перестал работать.

**Диагностика:**

```bash
# 1. Проверка DS-записи у регистратора
dig example.com DS +short
# → Если нет DS — делегирование без DNSSEC

# 2. Проверка DNSKEY на новом сервере
dig @ns1.newprovider.com example.com DNSKEY +short
# → Если нет ключей — DNSSEC не настроен

# 3. Проверка подписей
dig @ns1.newprovider.com example.com A +dnssec +short
# → Если нет RRSIG — зона не подписана

# 4. Проверка_SYNCMD (для автоматического обновления DS)
dig example.com CDNSKEY +short
# → Если есть — автоматическое делегирование DNSSEC
```

## Best Practices

### По DNSSEC

1. **Настройте автоматическое обновление подписей** — используйте `dnssec-policy` в BIND 9.18+ или `auto-dnssec maintain;`.
2. **Мониторьте сроки действия RRSIG** — алерт при оставшемся TTL < 10% от общего срока.
3. **Проверяйте DS-запись** после любых операций с делегированием.
4. **Для внутренних зон** рассмотрите отключение DNSSEC на локальном резолвере (снижение нагрузки).

### По DoH/DoT

1. **Проверяйте порт 853/443** в файрволе при проблемах с DoH/DoT.
2. **Используйте `openssl s_client`** для диагностики TLS-соединений.
3. **Настройте systemd-resolved** на DoT для приватности: `DNSOverTLS=yes` в `/etc/systemd/resolved.conf`.
4. **Мониторьте метрики** DoH/DoT через Prometheus (latency, errors).

### По DDoS-защите

1. **Включите RRL** на всех авторитативных серверах BIND.
2. **Ограничьте `recursive-clents`** и `fetches-per-zone`.
3. **Используйте `rate-limit`** для защиты от water-torture атак.
4. **Настройте алерты** на аномальный рост UDP-трафика.
5. **Используйте CDN** для поглощения волюметрических атак.

## Дополнительная информация

- [Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md) — теория DNSSEC, DoH, DoT, DANE, атаки.
- [BIND: Управление ключами TSIG](../../../../Linux/Networking/Services/BIND/tsig-key-management.md) — аутентификация трансферов.
- [BIND: DoH/DoT сервер](../../../../Linux/Networking/Services/BIND/dot-doh-server.md) — настройка шифрованного сервера.
- [BIND: RPZ (Response Policy Zones)](../../../../Linux/Networking/Services/BIND/advanced_topics.md) — DNS-фаервол.
- [Продвинутые сценарии DNS](../../../../Networking/Protocols/DNS/dns_advanced.md) — EDE, Split-horizon, ECS.
- [Базовая диагностика DNS](./basic_diagnostics.md) — общий алгоритм поиска неисправностей.
- [Диагностика DNS-серверов](./dns_server_diagnostics.md) — проблемы серверов BIND/Unbound/CoreDNS.
