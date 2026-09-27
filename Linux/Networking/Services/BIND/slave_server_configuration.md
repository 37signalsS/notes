# Настройка вторичного сервера DNS в BIND

---

## Определения

**Вторичный сервер (Secondary / Slave)** — авторитативный **DNS (Domain Name System)** сервер, который автоматически получает копию данных зоны с первичного (**Primary / Master**) сервера через механизм зонной передачи.

**Зонная передача (Zone Transfer)** — процесс синхронизации данных зоны между серверами. Поддерживает два режима:
- **AXFR (Authoritative Transfer)** — полная передача всех записей зоны.
- **IXFR (Incremental Zone Transfer)** — передача только измененных записей (RFC 1995), что существенно снижает нагрузку на сеть для больших зон.

**TSIG (Transaction Signature)** — механизм аутентификации (RFC 8945), использующий общие секретные ключи для проверки подлинности и целостности сообщений между DNS-серверами. Рекомендуется для защиты зонных передач.

---

## Основные концепции

### Алгоритм синхронизации данных

Процесс обновления данных на вторичном сервере следует строгому регламенту:

| Этап | Описание |
| :--- | :--- |
| 1 | Вторичный сервер запрашивает запись **SOA (Start of Authority)** у первичного сервера. |
| 2 | Сравнивает серийный номер (**Serial**) полученной записи с текущей локальной версией. |
| 3 | Если Serial на первичном сервере больше → инициируется запрос на передачу зоны (**AXFR** или **IXFR**). |
| 4 | Полученные данные сохраняются в локальный файл и применяются в памяти процесса `named`. |

### Механизмы NOTIFY и форматы файлов

*   **NOTIFY (RFC 1996):** Первичный сервер отправляет уведомление вторичным серверам сразу после перезагрузки зоны, не дожидаясь истечения таймера `Refresh`.
*   **Инкрементальный трансфер (IXFR):** Для его работы на Master-сервере должен вестись журнал изменений (файл `.jnl`).
*   **Формат файлов:** BIND 9.16+ по умолчанию использует бинарный формат (`raw`) для вторичных зон. Это ускоряет загрузку, но файл нельзя прочитать `cat`. Для сохранения в текстовом виде используйте `masterfile-format text;`.

### Параметры конфигурации вторичной зоны

BIND предоставляет директивы для управления поведением Slave-сервера:

| Директива | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `transfer-format` | Формат пакетов трансфера: `one-answer` (по одной записи) или `many-answers` (все записи в одном пакете). | `many-answers` |
| `max-transfer-time-in` | Максимальное время трансфера в секундах. По истечении — AXFR отменяется. | `120` |
| `max-transfer-idle-in` | Максимальное время простоя трансфера в секундах. | `120` |
| `transfer-source` | Источникый IP-адрес для зонных передач по IPv4. | адрес интерфейса, через который идёт маршрут до мастера |
| `transfer-source-v6` | Источникый IPv6-адрес для зонных передач. | аналогично IPv4 |
| `tcp-only` | Принудительно использовать TCP для обмена с данным мастером. | `no` |
| `ixfr-from-differences` | Вычислять IXFR-разницу локально при `rndc sync` вместо полного AXFR. | `yes` (в большинстве сборок) |
| `request-ixfr` | Запросить IXFR у мастера; если мастер не поддерживает — fallback на AXFR. | `yes` |
| `request-ixfr-from` | Список мастеров, у которых принудительно запрашивать IXFR (даже если мастер не объявил поддержку). | — |
| `masterfile-format` | Формат хранения файла зоны: `raw` (бинарный, быстрый) или `text` (текстовый, читаемый). | `raw` |
| `notify` | Разрешить ли отправлять NOTIFY на свои Slave при изменении зоны (если этот Slave становится мастером). | `yes` |
| `allow-notify` | Разрешить NOTIFY-уведомления только от указанных мастеров. | `any` |

**Пример расширенной конфигурации:**
```conf
zone "corp.local" {
    type slave;
    file "/var/lib/bind/db.corp.local.secondary";
    primaries { 192.168.10.10; };
    masterfile-format text;        // читаемый формат для отладки
    transfer-format many-answers;   // меньше пакетов, ниже overhead
    max-transfer-time-in 60;        // сек, fail-fast при медленном канале
    max-transfer-idle-in 30;
    transfer-source 192.168.10.20; // фиксированный IP источника
    tcp-only no;
    ixfr-from-differences yes;
    request-ixfr yes;
};
```

### Поведение при недоступности Master

Когда Master-сервер недоступен, Slave продолжает отдавать данные зоны из локального кэша. Ключевые параметры из SOA:

| Параметр | Роль при недоступности |
| :--- | :--- |
| `Refresh` | Интервал опроса Master. Если прошло меньше Refresh — Slave не контактирует с Master. |
| `Retry` | Интервал повторной попытки после ошибки соединения. |
| `Expire` | **Критический параметр.** Если Master недоступен дольше Expire, Slave перестаёт отдавать данные зоны (возвращает `SERVFAIL`). |
| `Minimum TTL` | Время отрицательного кэширования NXDOMAIN/NODATA. |

**Serve Stale (RFC 8767):** BIND 9.12+ поддерживает отдачу устаревших данных при недоступлении Master. Включение:
```conf
options {
    serve-stale {
        enable true;
        max-ttl 3600;      // максимум 1 час устаревания
        client-timeout 10; // секунд ожидания свежего ответа
    };
};
```

### Multi-Primary и Hidden Primary

*   **Multi-Primary:** Если у зоны несколько мастеров, BIND выбирает первый доступный из списка `primaries`. Это обеспечивает отказоустойчивость источника данных без использования HA-кластера.
*   **Hidden Primary (Скрытый мастер):** Master-сервер без публичного IP, доступный только для Slave. Все внешние запросы обрабатываются Slave. На Slave в этом случае `allow-query { any; }`, а на Master — `allow-transfer` только на IP Slave.

---

## Предварительная проверка (Pre-flight)

Перед настройкой Slave-сервера убедитесь:

| Проверка | Команда / действие |
| :--- | :--- |
| Порт 53/udp и 53/tcp открыты на Master | `nc -zv 192.168.10.10 53` |
| NTP синхронизирована | `timedatectl status` → расхождение < 5 сек |
| Директория для зон доступна | `sudo -u bind touch /var/lib/bind/.test && rm /var/lib/bind/.test` |
| DNS-резолвер работает | `dig @127.0.0.1 corp.local SOA +short` |
| SELinux/AppArmor не блокируют BIND | `sudo aa-status` или `sudo getenforce` |
| Firewall разрешает входящий 53/tcp | `sudo nft list ruleset` / `sudo firewall-cmd --list-all` |

---

## Структура директорий

| Дистрибутив | Путь конфигурации | Путь зон | Пользователь |
| :--- | :--- | :--- | :--- |
| Debian / Ubuntu | `/etc/bind/` | `/var/lib/bind/` | `bind` |
| RHEL / CentOS / Fedora | `/etc/named/` | `/var/named/` | `named` |
| Alpine Linux | `/etc/bind/` | `/var/bind/` | `bind` |

**Debian / Ubuntu:**
- `/etc/bind/named.conf` — главный include-файл
- `/etc/bind/named.conf.options` — глобальные опции
- `/etc/bind/named.conf.local` — объявление зон
- `/var/lib/bind/` — рабочая директория для Slave-зон

**RHEL-семейство:**
- `/etc/named.conf` — главный конфиг (часто включает `named.rfc1912.zones`)
- `/etc/named/` — конфигурационные файлы и зоны
- `/var/named/data/` — рабочие данные, кэш, Slave-зоны
- Служба: `systemctl enable --now named`

---

## Практические сценарии

### 1. Настройка вторичного сервера (Secondary)

В BIND 9.18+ для определения апстримов рекомендуется использовать ключевое слово `primaries` вместо устаревшего `masters`.

**Файл `/etc/bind/named.conf.local` на стороне Secondary:**

```conf
zone "corp.local" {
    type slave;                // Ключевое слово остается 'slave' для совместимости
    file "/var/lib/bind/db.corp.local.secondary"; 
    primaries { 192.168.10.10; }; // IP-адрес Master-сервера
    masterfile-format text;       // (Опционально) для удобства чтения
};
```

**Права доступа:**
Убедитесь, что пользователь `bind` имеет права на запись в рабочую директорию.
```bash
sudo chown bind:bind /var/lib/bind
# → success
```

### 2. Настройка первичного сервера (Primary)

Master должен явно разрешить передачу данных вторичному серверу.

**Файл `/etc/bind/named.conf.local` на стороне Primary:**

```conf
zone "corp.local" {
    type master;
    file "/etc/bind/zones/db.corp.local";
    allow-transfer { 192.168.10.20; }; // IP-адрес Secondary
    also-notify { 192.168.10.20; };    // Принудительное уведомление
};
```

### 3. Использование TSIG для защиты передач

1.  **Генерация ключа (на любом сервере):**
    ```bash
    tsig-keygen -a HMAC-SHA256 transfer-key > /etc/bind/transfer.key
    ```
2.  **Подключение ключа на обоих узлах:**
    В начало `named.conf.local` добавьте:
    ```conf
    include "/etc/bind/transfer.key";
    ```
3.  **Применение в конфигурации:**
    - На Primary: `allow-transfer { key "transfer-key"; };`
    - На Secondary: добавьте блок `server`:
    ```conf
    server 192.168.10.10 {
        keys { "transfer-key"; };
    };
    ```

### 4. Несколько мастеров (Multi-Primary)

Если у вас два Master-сервера (например, в разных дата-центрах), перечислите их в `primaries`:

```conf
zone "corp.local" {
    type slave;
    file "/var/lib/bind/db.corp.local.secondary";
    primaries {
        192.168.10.10;   // ДЦ1
        192.168.20.10;   // ДЦ2
    };
    also-notify { 192.168.10.10; 192.168.20.10; };
};
```

BIND попытается связаться с первым мастером; если недоступен — переключится на второго. IXFR будет запрошен у активного мастера.

### 5. IPv6 dual-stack

Если инфраструктура использует IPv6, добавьте на Secondary:

```conf
zone "corp.local" {
    type slave;
    file "/var/lib/bind/db.corp.local.secondary";
    primaries { 192.168.10.10; 2001:db8::10; };
    transfer-source-v6 2001:db8::20;
};
```

На Master добавьте IPv6-адрес Secondary в `allow-transfer` и `also-notify`.

---

## Firewall и безопасность

### nftables (Debian 12+, Ubuntu 22.04+)

```bash
sudo nft add rule inet filter input ip protocol tcp ip dport 53 accept
sudo nft add rule inet filter input ip protocol udp ip dport 53 accept
```

### firewalld (RHEL 9+, CentOS Stream)

```bash
sudo firewall-cmd --permanent --add-service=dns
sudo firewall-cmd --reload
```

### ufw (Ubuntu/Debian)

```bash
sudo ufw allow 53/tcp
sudo ufw allow 53/udp
```

### SELinux (RHEL/Fedora)

```bash
# Проверка
sudo getenforce
# → Enforcing

# Если BIND не может писать в директорию Slave-зон:
sudo semanage fcontext -a -t named_zone_t "/var/lib/bind(/.*)?"
sudo restorecon -Rv /var/lib/bind
```

### AppArmor (Ubuntu/Debian)

```bash
# Проверка статуса
sudo aa-status | grep bind

# Если профиль блокирует запись:
sudo aa-complain /usr/sbin/named
# Или добавьте правило в /etc/apparmor.d/local/usr.sbin.named
```

---

## Мониторинг и управление

### Таблица команд `rndc` для Slave

| Команда | Описание |
| :--- | :--- |
| `rndc retransfer <zone>` | Принудительный полный AXFR (сброс локальной версии). |
| `rndc sync <zone>` | Принудительная запись `.jnl` в файл зоны. |
| `rndc zonestatus <zone>` | Serial, тип зоны, адрес мастера, время последнего обновления. |
| `rndc flush` | Очистка кэша. |
| `rndc stats` | Запись статистики в `named.stats`. |

### Статистический канал

В `named.conf.options` на Secondary:
```conf
statistics-channels {
    inet 127.0.0.1 port 8053 allow { localhost; };
};
```

Затем:
```bash
curl http://127.0.0.1:8053/json/v1/zones
# → JSON со списком зон, Serial, типом, мастером
```

### Скрипт проверки здоровья (Health Check)

```bash
#!/bin/bash
# /usr/local/bin/bind-slave-check.sh
# Использование: bind-slave-check.sh corp.local 192.168.10.10

ZONE="${1:-corp.local}"
PRIMARY="${2:-192.168.10.10}"
MASTER_SERIAL=$(dig +short @"$PRIMARY" "$ZONE" SOA | awk '{print $3}')
SLAVE_SERIAL=$(dig +short @127.0.0.1 "$ZONE" SOA | awk '{print $3}')

if [ -z "$MASTER_SERIAL" ] || [ -z "$SLAVE_SERIAL" ]; then
    echo "CRITICAL: SOA недоступен (master=$MASTER_SERIAL, slave=$SLAVE_SERIAL)"
    exit 2
fi

if [ "$MASTER_SERIAL" -gt "$SLAVE_SERIAL" ]; then
    echo "WARNING: Serial drift (master=$MASTER_SERIAL, slave=$SLAVE_SERIAL)"
    exit 1
fi

echo "OK: Serial=$SLAVE_SERIAL"
exit 0
```

Интеграция с Nagios/Zabbix/cron:
```bash
# Cron (каждые 5 минут)
*/5 * * * * root /usr/local/bin/bind-slave-check.sh corp.local 192.168.10.10
```

---

## Резервное копирование

Хотя Slave получает зону с Master, резервное копирование ускоряет восстановление после сбоя — не нужно ждать AXFR.

```bash
# Резервная копия всех Slave-зон
sudo tar czf /backup/bind-slave-$(date +%Y%m%d).tar.gz \
    /var/lib/bind/*.secondary

# Проверка
sudo tar tzf /backup/bind-slave-20250912.tar.gz | head
```

**Восстановление:**
```bash
sudo systemctl stop bind9
sudo rm /var/lib/bind/db.corp.local.secondary*
sudo tar xzf /backup/bind-slave-20250912.tar.gz -C /
sudo systemctl start bind9
```

---

## Производительность и масштабирование

| Параметр | Рекомендация |
| :--- | :--- |
| Диск | SSD для Slave с частыми IXFR; HDD подходит для редких обновлений. |
| `masterfile-format` | `raw` для продакшена (быстрее загрузка), `text` для отладки. |
| `max-transfer-time-in` | Уменьшить для медленных каналов (например, `30` вместо `120`). |
| `transfer-format` | `many-answers` для минимизации overhead. |
| `max-transfer-idle-in` | Уменьшить при нестабильном соединении. |
| Количество потоков | BIND на Slave однонаправленный; несколько зон обслуживаются последовательно. |

---

## Обслуживание без простоя

### Постепенный рестарт Slave

```bash
# 1. Убедитесь, что Slave актуален
/usr/local/bin/bind-slave-check.sh corp.local 192.168.10.10
# → OK

# 2. Перезагрузите конфиг (не трогает зоны)
sudo rndc reconfig

# 3. Если меняется BIND — перезапустите службу
sudo systemctl restart bind9

# 4. Проверьте логи
sudo journalctl -u bind9 -n 20 | grep -E "transfer|error|NXDOMAIN"
```

### Ротация TSIG-ключа без простоя

```bash
# 1. Сгенерируйте новый ключ
tsig-keygen -a HMAC-SHA256 transfer-key-new > /etc/bind/transfer-new.key

# 2. Подключите на обоих серверах
echo 'include "/etc/bind/transfer-new.key";' >> /etc/bind/named.conf.local

# 3. На Primary добавьте новый ключ в allow-transfer
# allow-transfer { key "transfer-key"; key "transfer-key-new"; };

# 4. Проверка трансфера
dig @master zone AXFR -k /etc/bind/transfer-new.key

# 5. Удалите старый ключ
sudo sed -i '/transfer.key/d' /etc/bind/named.conf.local
sudo rm /etc/bind/transfer.key
```

---

## Проверка и диагностика

### Верификация синхронизации

```bash
# Проверка соответствия Serial на вторичном сервере
dig @127.0.0.1 corp.local SOA +short
# → 2025072501 (должен совпадать с Master)

# Проверка логов на факт успешной передачи
sudo journalctl -u bind9 -n 20 | grep "transfer"
# → named[1234]: transfer of 'corp.local/IN' from 192.168.10.10#53: Transfer status: success
```

### Типовые неисправности

*   **Блокировка TCP/53:** Передача зоны всегда выполняется по протоколу TCP. Проверьте firewall.
*   **Permission Denied:** В логах отображается `dumping master file: /var/lib/bind/...: permission denied`. Проверьте права на директорию или профиль **AppArmor**.
*   **Зависший Serial:** Если вы забыли увеличить Serial на мастере, Secondary не заберет изменения, даже если файл зоны был обновлен.
*   **TSIG REFUSED:** Расхождение часов > 5 минут нарушает HMAC. Проверьте `chronyc tracking`.
*   **IXFR fallback на AXFR:** Если Master не ведёт `.jnl` или IXFR не поддерживается, BIND автоматически выполняет полный трансфер. Это нормально, но увеличивает трафик.
*   **ZONEFULL:** Раздел Slave переполнен. Увеличьте `max-transfer-time-in` или проверьте дисковое пространство.
*   **Serve Stale включен:** Если Slave отдаёт устаревшие данные, проверьте `serve-stale` в `named.conf.options`.

**Ручной тест трансфера:**
```bash
dig @192.168.10.10 corp.local AXFR
# → (вывод всех записей зоны или сообщение об ошибке REFUSED)
```

---

## Дополнительная информация

*   **Версии:** Актуально для BIND 9.18+ (LTS) и 9.20+ (ESV).
*   **Спецификации:** 
    *   **RFC 1995:** Incremental Zone Transfer (IXFR).
    *   **RFC 1996:** DNS NOTIFY.
    *   **RFC 8945:** TSIG для DNS.

**Связанные разделы:**
*   **[Первичный сервер (Master)](./master_server_local_zone.md)** — настройка источника данных.
*   **[Отказоустойчивый кластер BIND9](./high-availability-cluster.md)** — полный цикл эксплуатации кластера: репликация, failover, обмен ролями.
*   **[Обратная зона](./reverse_zone_configuration.md)** — репликация PTR-записей.
*   **[Диагностика BIND](./troubleshooting.md)** — общие методы отладки.
*   **[Зоны DNS и SOA](../../../../Networking/Protocols/DNS/dns_zones.md)** — теория иерархии и метаданных.
