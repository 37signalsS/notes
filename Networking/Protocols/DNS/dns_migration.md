# Миграция DNS

## Определения

**Миграция DNS-провайдера** — процесс переноса управления DNS-записями от одного провайдера к другому. Включает экспорт зон, перенос NS-записей на регистраторе, настройку нового сервера, валидацию и откат при необходимости.

**Миграция регистратора** — смена компании-регистратора доменного имени. Основная операция — перенос NS-записей (glue records) и DS-записей (для DNSSEC) на новый регистратор. Домен остаётся в реестре (registry), меняется только точка управления.

**Zone Migration (AXFR/IXFR)** — перенос содержимого зоны между DNS-серверами. Используется при смене серверов, слиянии инфраструктур, миграции с BIND на PowerDNS или Unbound.

**TTL Pre-Lowering** — стратегия снижения TTL за 24-48 часов до миграции. Низкий TTL (60-300 сек) позволяет быстрее распространить изменения по кэшам клиентов при переключении.

**Parallel Run (параллельный запуск)** — метод миграции, при котором старый и новый DNS-серверы работают одновременно. Используется для валидации нового сервера перед отключением старого.

**Cut-Over (переключение)** — финальный этап миграции, при котором NS-записи на регистраторе переключаются на новые серверы.

---

## Базовые концепции

### Типы миграций DNS

| Тип | Что меняется | Сложность | Риск | Downtime |
| :--- | :--- | :--- | :--- | :--- |
| **Миграция провайдера** | NS-записи + содержимое зон | Средняя | Средний | 0-24 ч (зависит от TTL) |
| **Миграция регистратора** | NS-записи + DS-записи | Низкая | Низкий | 0-48 ч (propagation) |
| **Миграция сервера** | IP-адрес авторитативного сервера | Низкая | Низкий | 0-TTL |
| **Слияние зон** | Объединение нескольких зон в одну | Высокая | Высокий | Возможны конфликты |
| **Миграция DNSSEC** | Подписи (RRSIG, DNSKEY, DS) | Высокая | Высокий | Зависит от chain of trust |

### Стратегия TTL Pre-Lowering

**Принцип:** Снизить TTL до минимального значения за 24-48 ч до миграции, чтобы кэши клиентов обновились быстро после переключения.

**Таймлайн:**

```text
T-48 ч:  Снизить TTL с 3600 до 300 сек (все A/AAAA/MX/TXT/NS записи)
         dig @<old-ns> example.com +noall +answer
         Verify TTL = 300

T-24 ч:  Убедиться, что кэши обновились:
         dig @8.8.8.8 example.com +noall +answer
         TTL должен быть < 300

T-0 ч:   Переключить NS-записи на регистраторе
         Обновить содержимое зон на новом сервере

T+1 ч:   Вернуть TTL на 3600 сек
```

**Проверка TTL в кэше:**
```bash
# Проверка через публичный резолвер
dig @8.8.8.8 example.com +noall +answer
# → example.com.    298    IN    A    192.0.2.1  ← TTL уже снижён

# Проверка через Quad9
dig @9.9.9.9 example.com +noall +answer
# → example.com.    156    IN    A    192.0.2.1  ← TTL продолжает уменьшаться
```

### Методы переноса зон

| Метод | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Ручной экспорт/импорт** | Копирование файла зоны в текстовом формате | Маленькие зоны (< 100 записей) |
| **AXFR (zonetransfer)** | Полная передача зоны через DNS протокол | Миграция между серверами |
| **IXFR** | Инкрементальная передача (только изменения) | Частые обновления |
| **API** | Через REST API провайдера | Cloudflare, Route53, Azure DNS |
| **tsig + rndc** | Аутентифицированный трансфер | Продакшен-среда |

### Валидация после миграции

**Чек-лист:**
1. Все записи (A, AAAA, MX, TXT, NS) присутствуют на новом сервере
2. DNSSEC-цепочка доверия корректна (RRSIG, DS, DNSKEY)
3. Обратные зоны (PTR) настроены
4. SOA Serial увеличен
5. Запросы от публичных резолверов (8.8.8.8, 9.9.9.9) возвращают правильные ответы
6. Нет SERVFAIL на критических записях
7. Записи с низким TTL размножились по кэшам

---

## Практические сценарии

### Предусловия

```bash
# Установка инструментов
sudo apt install dnsutils whois jq curl

# Проверка текущего NS
dig example.com NS +short
# → ns1.old-provider.com.
# → ns2.old-provider.com.
```

### 1. Миграция NS-записей на регистраторе (смена регистратора)

**Шаг 1: Подготовка нового регистратора**
```bash
# Зарегистрируйтесь на новом регистраторе
# Добавьте домен (без управления DNS)

# Запомните текущие NS
dig example.com NS +noall +answer
# → example.com.    3600    IN    NS    ns1.old-registrar.com.
# → example.com.    3600    IN    NS    ns2.old-registrar.com.
```

**Шаг 2: Снижение TTL (за 48ч)**
```bash
# На старом DNS-сервере измените TTL всех записей
vim /etc/bind/zones/example.com.db
# Замените 3600 на 300 в SOA и всех записях

# Применение
sudo rndc reload example.com
# Проверка
dig @ns1.old-registrar.com example.com +noall +answer
# → example.com.    300    IN    A    192.0.2.1
```

**Шаг 3: Настройка нового DNS-сервера**
```bash
sudo vim /etc/bind/zones/example.com.db
```

```dns
$TTL 300
@   IN  SOA ns1.new-provider.com. admin.example.com. (
        2026082501  ; Serial
        3600        ; Refresh
        900         ; Retry
        1209600     ; Expire
        300         ; Negative TTL
)

@       IN  NS  ns1.new-provider.com.
@       IN  NS  ns2.new-provider.com.
ns1     IN  A   10.0.0.1
ns2     IN  A   10.0.0.2
@       IN  A   192.0.2.1
@       IN  MX  10 mail.example.com.
mail    IN  A   192.0.2.10
www     IN  A   192.0.2.2
```

```bash
# Валидация
sudo named-checkzone example.com /etc/bind/zones/example.com.db
# → OK

# Перезагрузка
sudo rndc reload example.com
```

**Шаг 4: Валидация нового сервера (параллельный запуск)**
```bash
# Проверка нового сервера
dig @10.0.0.1 example.com +noall +answer
# → example.com.    300    IN    A    192.0.2.1

# Сравнение со старым сервером
diff <(dig @ns1.old-registrar.com example.com AXFR +noall +answer | sort) \
     <(dig @10.0.0.1 example.com AXFR +noall +answer | sort)
# → Нет различий (если всё корректно)
```

**Шаг 5: Переключение NS на регистраторе**
```bash
# В панели нового регистратора установите NS:
# ns1.new-provider.com (10.0.0.1)
# ns2.new-provider.com (10.0.0.2)
# Удалите старые NS записи

# Проверка propagation (может занять 1-48 часов)
watch -n 60 "dig example.com NS +short +dnssec"
# → ns1.new-provider.com.
# → ns2.new-provider.com.
```

**Шаг 6: Восстановление TTL**
```bash
# Через 24 часа после переключения верните TTL
# Замените 300 на 3600 в зонном файле
sudo rndc reload example.com
```

### 2. Миграция между DNS-серверами (BIND -> PowerDNS)

**Экспорт зоны:**
```bash
# Старый сервер (BIND): экспорт через AXFR
dig @old-server example.com AXFR +noauth > /tmp/example.com.zone
# Проверка
wc -l /tmp/example.com.zone
# → 247 /tmp/example.com.zone
```

**Импорт на PowerDNS:**
```bash
# Установка PowerDNS
sudo apt install pdns-server pdns-backend-bind

# Копирование зонного файла
sudo cp /tmp/example.com.zone /etc/powerdns/zones/

# Конфигурация PowerDNS (pdns.conf)
# launch=bind
# bind-config=/etc/powerdns/named.conf
# bind-dnssec-dir=/etc/powerdns/dnssec

# Перезапуск
sudo systemctl restart pdns
```

**Валидация:**
```bash
# Сравнение ответов старого и нового сервера
for record in example.com example.com.MX example.com.TXT example.com.NS; do
  old=$(dig @old-server $record +short)
  new=$(dig @10.0.0.1 $record +short)
  if [ "$old" = "$new" ]; then
    echo "OK: $record"
  else
    echo "MISMATCH: $record (old: $old, new: $new)"
  fi
done
```

### 3. Миграция DNSSEC-подписанной зоны

**Шаг 1: Экспорт DNSSEC-ключей**
```bash
# На старом сервере
cd /etc/bind/keys
ls -la Kexample.com.*
# → Kexample.com.+008+12345.key
# → Kexample.com.+008+12345.private

# Копирование ключей
scp Kexample.com.* new-server:/etc/bind/keys/
```

**Шаг 2: Настройка на новом сервере**
```bash
cd /etc/bind/keys
chown bind:bind Kexample.com.*
chmod 640 Kexample.com.*.private
```

```dns
# named.conf.local:
zone "example.com" {
    type master;
    file "/etc/bind/zones/example.com.db";
    key-directory "/etc/bind/keys";
    auto-dnssec maintain;
    inline-signing yes;
};
```

**Шаг 3: Обновление DS-записи**
```bash
# На новом сервере: генерация нового DS
dnssec-dsfromkey -2 /etc/bind/keys/Kexample.com.+008+12345.key example.com

# Запись новый DS в реестр (через регистратор)
# Старый DS удаляется, новый добавляется
```

**Шаг 4: Валидация DNSSEC**
```bash
# Проверка цепочки доверия
delv @new-server example.com +rtrace
# → должен показать链路 chain of trust до корневого ключа
```

---

## Лучшие практики

*   **Всегда снижайте TTL за 48ч до миграции:** Это критически важно. Если TTL = 3600, кэши будут хранить старые записи до 1 часа. Снизьте до 300 сек.
*   **Делайте backup перед миграцией:** Экспортируйте текущую зону в файл и сохраните его. `dig @server example.com AXFR > backup.zone`.
*   **Валидируйте на новом сервере перед переключением:** Используйте параллельный запуск. Сравнивайте ответы старого и нового сервера через diff.
*   **Мигрируйте в нерабочее время:** Изменения NS-записей могут вызвать brief downtime. Планируйте на выходные или ночное время.
*   **Имейте план отката:** Если что-то пошло не так, верните старые NS-записи на регистраторе. Время отката = старый TTL (поэтому снижение TTL помогает и для отката).
*   **Проверяйте DNSSEC после миграции:** DS-записи на регистраторе должны соответствовать DNSKEY на новом сервере. Несоответствие = SERVFAIL для всех клиентов с DNSSEC.
*   **Мониторьте после миграции:** Настраивайте Blackbox Exporter или аналогичный инструмент для проверки доступности DNS после переключения.
*   **Документируйте все изменения:** Записывайте: старые NS, новые NS, время переключения, результаты валидации, контактное лицо.

---

## Дополнительная информация

### Инструментарий

- **dig:** Диагностика DNS-ответов и зон.
- **AXFR:** Полная передача зон через DNS протокол.
- **named-checkzone / named-checkconf:** Валидация конфигурации BIND.
- **nsupdate:** Динамическое обновление зон (RFC 2136).
- **dnssec-dsfromkey:** Генерация DS-записей из DNSKEY.

### Ключевые RFC

- **RFC 1034 / 1035:** Базовая спецификация DNS.
- **RFC 1996:** NOTIFY (уведомление об обновлении зоны).
- **RFC 2136:** Dynamic Updates (динамические обновления зон).
- **RFC 4033 / 4034 / 4035:** DNSSEC - Implementation and Specification.
- **RFC 9103:** DNS Zone Transfer over TLS (XoT).

### Связанные разделы

- [Протокол DNS](./dns.md) — общая архитектура и порты.
- [Зоны DNS и SOA](./dns_zones.md) — управление структурой зон и трансферами.
- [Безопасность DNS](./dns_security.md) — DNSSEC механизмы (RRSIG, NSEC3, DS).
- [BIND: Master сервер](../../../Linux/Networking/Services/BIND/master_server_local_zone.md) — настройка авторитативного сервера.
- [BIND: Slave сервер](../../../Linux/Networking/Services/BIND/slave_server_configuration.md) — вторичный сервер и трансферы.
- [Мониторинг DNS](./dns_monitoring.md) — проверка доступности после миграции.
