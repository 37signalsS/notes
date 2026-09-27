# Настройка первичного DNS-сервера (Master) для локальной зоны

---

## Определения

**DNS (Domain Name System)** — распределённая система для хранения и получения информации о доменах, обеспечивающая сопоставление символьных имен с сетевыми адресами (IP).

**Master-сервер (Primary)** — авторитативный сервер, являющийся единственным источником эталонных данных зоны. Изменения вносятся администратором вручную в текстовые файлы базы данных зоны именно на этом сервере.

**FQDN (Fully Qualified Domain Name)** — полностью определённое доменное имя, включающее все уровни иерархии и завершающееся точкой (например, `web.corp.local.`). Точка сигнализирует BIND о завершении имени, предотвращая автоматическое добавление суффикса текущей зоны.

**Zone File (файл зоны)** — текстовый файл в формате RFC 1035, содержащий все ресурсные записи (RR) для конкретной зоны. На Master-сервере файлы зон хранятся в текстовом формате и редактируются администратором.

**Journal File (файл журнала)** — файл с расширением `.jnl`, который BIND создаёт рядом с файлом зоны при включённых динамических обновлениях или IXFR. Журнал фиксирует изменения и необходим для инкрементальных трансферов.

**ACL (Access Control List)** — именованный список IP-адресов, используемый для ограничения доступа к рекурсии, трансферу зон, динамическим обновлениям или NOTIFY-уведомлениям.

---

## Основные концепции

### Структура и директивы файла зоны

Корректная работа Master-сервера зависит от правильного оформления файла зоны. BIND распознаёт специальные директивы:

- **`$ORIGIN`**: определяет базовый домен, который будет автоматически подставляться ко всем относительным именам (не заканчивающимся точкой).
- **`$TTL` (Time To Live)**: время жизни записей в кэше сторонних резолверов по умолчанию.
- **`$GENERATE`**: позволяет автоматически создавать серию записей по шаблону. Полезно для больших подсетей (PTR-записи, диапазоны A-записей).
- **`$INCLUDE`**: включает содержимое внешнего файла в текущий. Удобно для разделения больших зон на логические части или подключения стандартных записей.
- **`@`**: сокращение для имени самой зоны (Apex). Эквивалент записи `$ORIGIN` без изменения.
- **`;`**: начало комментария. BIND игнорирует всё до конца строки.

### Запись SOA и серийный номер

**SOA (Start of Authority)** — запись о начале полномочий, содержащая метаданные управления зоной:
- **Serial**: целое число, которое **обязательно** должно увеличиваться при каждом редактировании файла. Без этого вторичные (Slave) серверы не узнают об изменениях. Рекомендуемый формат: `ГГГГММДДНН`.
- **Refresh**: интервал, через который Slave-сервер опрашивает Master на предмет изменений.
- **Retry**: интервал повторной попытки трансфера при неудаче.
- **Expire**: срок, в течение которого Slave считает данные актуальными при недоступном Master. После истечения этот срок Slave прекращает отвечать по зоне.
- **Minimum TTL / Negative Cache TTL**: время кэширования ответов «имя не существует» (NXDOMAIN) резолверами.

### Приклеенные записи (Glue Records)

Если серверы имен (NS) находятся внутри самой зоны (например, `ns1.corp.local` для зоны `corp.local`), необходимо создать **Glue Records** — явные A-записи с их IP-адресами. Это позволяет резолверам найти сервер, отвечающий за зону, до того как они смогут разрешить его имя. Без glue-записей запрос к такой зоне может завершиться `SERVFAIL`.

### Журналирование и файл .jnl

При использовании динамических обновлений (RFC 2136) или IXFR BIND создаёт файл `.jnl` рядом с файлом зоны. Этот журнал:
- Фиксирует все изменения, внесённые динамически.
- Необходим Slave-серверам для выполнения IXFR (инкрементальной передачи).
- Автоматически сбрасывается в файл зоны при выполнении `rndc sync` или `rndc reload`.
- Должен храниться в директории, доступной пользователю `bind` на запись.

### Разделение горизонта (Split-horizon / Views)

В среде с внутренней и внешней сетью один Master-сервер может обслуживать разные версии одной зоны через механизм **Views** (Представления). Внутренние клиенты получают внутренние IP-адреса, внешние — публичные. Теория и практика Views описаны в разделе [Продвинутые возможности](./advanced_topics.md).

### Подпись зоны (DNSSEC)

Для защиты от подмены данных зона может быть подписана с использованием DNSSEC. На Master-сервере генерируются ключи (ZSK и KSK), зона подписывается, а DS-запись передаётся в родительскую зону. Подробная процедура описана в разделе [Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md).

---

## Подготовка окружения

### Предварительные проверки

Перед установкой и конфигурацией убедитесь, что окружение готово:

```bash
# 1. Порты 53/UDP и 53/TCP свободны
sudo ss -ulnp | grep ':53'
sudo ss -tlnp | grep ':53'
# → (пусто или только named/bind9)

# 2. Служба времени активна (критично для TSIG и DNSSEC)
timedatectl
# → NTP service: active
chronyc sources -v   # → источники синхронизации

# 3. Firewall разрешает DNS
sudo iptables -C INPUT -p udp --dport 53 -j ACCEPT 2>/dev/null || \
sudo iptables -I INPUT -p udp --dport 53 -j ACCEPT
sudo iptables -C INPUT -p tcp --dport 53 -j ACCEPT 2>/dev/null || \
sudo iptables -I INPUT -p tcp --dport 53 -j ACCEPT

# 4. Резервная копия существующей конфигурации
sudo cp -a /etc/bind /etc/bind.backup.$(date +%F)
ls -d /etc/bind.backup.*
# → /etc/bind.backup.2026-09-12
```

### Структура директорий и файлов

#### Debian / Ubuntu

| Путь | Назначение |
| :--- | :--- |
| `/etc/bind/named.conf` | Главный файл (корневой include). |
| `/etc/bind/named.conf.options` | Глобальные опции: ACL, форвардеры, параметры безопасности. |
| `/etc/bind/named.conf.local` | Объявление пользовательских зон (Master/Slave) и Views. |
| `/etc/bind/named.conf.default-zones` | Стандартные зоны (root-серверы, localhost). |
| `/etc/bind/zones/` | Стандартная директория для файлов описания зон. |
| `/var/cache/bind/` | Кэш, статистика, рабочие файлы Slave-зон. |
| `/var/log/bind/` | Логи (если настроены). |

#### RHEL / CentOS / Fedora

| Путь | Назначение |
| :--- | :--- |
| `/etc/named.conf` | Главный файл конфигурации (объединённый). |
| `/etc/named.rfc1912.zones` | Стандартные зоны. |
| `/var/named/` | Директория для файлов зон (Master/Slave). |
| `/var/named/data/` | Сессии, кэш, статистика, рабочие файлы. |
| `/var/named/dynamic/` | Динамически обновляемые зоны и журналы (.jnl). |

#### Alpine Linux

| Путь | Назначение |
| :--- | :--- |
| `/etc/bind/` | Конфигурация. |
| `/var/bind/` | Файлы зон. |

### Пользователь и группа

Демон `named` работает от пользователя `bind` (в RHEL-family может быть `named`). На Master-сервере файлы зон должны принадлежать `root:bind` с правами `640` — демону достаточно прав на чтение, запись только пользователю `root` для предотвращения случайной модификации через уязвимости в BIND.

```bash
sudo mkdir -p /etc/bind/zones
sudo chown root:bind /etc/bind/zones
sudo chmod 750 /etc/bind/zones
sudo chown root:bind /etc/bind/zones/db.*
sudo chmod 640 /etc/bind/zones/db.*
```

---

## Практические сценарии

### 1. Объявление зоны в `named.conf.local`

Для Master-сервера необходимо указать тип зоны, путь к файлу и настройки безопасности.

```conf
// /etc/bind/named.conf.local

zone "corp.local" {
    type master;
    file "/etc/bind/zones/db.corp.local";
    
    // Ограничение: кто может запрашивать записи этой зоны
    allow-query { any; }; 
    
    // Безопасность: трансфер только на доверенный Slave-сервер
    allow-transfer { 192.168.10.20; }; 
    
    // Уведомление Slave-серверов об изменениях
    notify yes;                        
};
```

Директивы `allow-transfer` и `also-notify` могут быть опущены, если зона используется только локально и не реплицируется. В этом случае BIND по умолчанию запрещает AXFR для всех.

### 2. Создание файла базы данных зоны

**Шаг 1: Подготовка директории**
```bash
sudo mkdir -p /etc/bind/zones
sudo chown bind:bind /etc/bind/zones
# → success
```

**Шаг 2: Наполнение файла `db.corp.local`**
```dns
; /etc/bind/zones/db.corp.local
$ORIGIN corp.local.
$TTL    86400  ; 1 день
@       IN      SOA     ns1.corp.local. admin.corp.local. (
                             2025072501     ; Serial
                             3600           ; Refresh (1ч)
                             600            ; Retry (10м)
                             1209600        ; Expire (2н)
                             3600 )         ; Negative Cache TTL (1ч)

; Серверы имен (NS)
@       IN      NS      ns1.corp.local.
@       IN      NS      ns2.corp.local.

; Glue Records (IP-адреса для NS)
ns1     IN      A       192.168.10.10
ns2     IN      A       192.168.10.20

; Инфраструктура
web     IN      A       192.168.10.50
db      IN      CNAME   web            ; Алиас (без точки, добавится $ORIGIN)

; Почта и верификация
@       IN      MX  10  mail.corp.local.
mail    IN      A       192.168.10.60
@       IN      TXT     "v=spf1 ip4:192.168.10.60 -all" ; SPF-запись

; Сервисные записи (SRV) для обнаружения служб
_ldap._tcp IN   SRV 0 5 389 ldap.corp.local.
```

**Шаг 3: Права и резервная копия**
```bash
sudo chown root:bind /etc/bind/zones/db.corp.local
sudo chmod 640 /etc/bind/zones/db.corp.local
```

### 3. Расширенные сценарии конфигурации

#### Сценарий 3.1: Зона с директивой $GENERATE

Для автоматического создания последовательных записей (например, PTR для подсети):

```dns
; /etc/bind/zones/db.10.0.8
$TTL    300
$ORIGIN 8.0.10.in-addr.arpa.

@   IN  SOA ns1.corp.local. admin.corp.local. (
         2025072501 3600 900 1209600 300 )
@   IN  NS  ns1.corp.local.
@   IN  NS  ns2.corp.local.

; Автоматическое создание PTR для 50-70 хостов
$GENERATE 50-70 $ IN PTR host$.corp.local.
```

#### Сценарий 3.2: Зона с директивой $INCLUDE

Для разделения большой зоны на логические части:

```dns
; /etc/bind/zones/db.corp.local
$ORIGIN corp.local.
$TTL 86400
@ IN SOA ns1.corp.local. admin.corp.local. ( ... )
@ IN NS ns1.corp.local.

; Подключение записей инфраструктуры из отдельного файла
$INCLUDE /etc/bind/zones/db.corp.local.hosts

; Подключение SRV-записей
$INCLUDE /etc/bind/zones/db.corp.local.srv
```

#### Сценарий 3.3: Динамические обновления с TSIG

Настройка Master для приёма защищённых динамических обновлений:

```conf
// /etc/bind/named.conf.local
include "/etc/bind/tsig.keys";

zone "corp.local" {
    type master;
    file "/etc/bind/zones/db.corp.local";
    allow-update { key "update-key"; };
    also-notify { 192.168.10.20; };
};
```

```bash
# Генерация ключа
sudo tsig-keygen -a HMAC-SHA256 update-key > /etc/bind/tsig.keys

# Применение динамического обновления
nsupdate -k /etc/bind/tsig.keys
> server 127.0.0.1
> zone corp.local
> update add newhost.corp.local 3600 A 192.168.10.70
> send
> quit

# Проверка
dig @127.0.0.1 newhost.corp.local A +short
# → 192.168.10.70
```

#### Сценарий 3.4: Локальная зона в View (Split-horizon)

Для отдачи разных наборов записей в зависимости от источника запроса:

```conf
acl "internal_clients" {
    192.168.0.0/24;
    127.0.0.1;
};

view "internal" {
    match-clients { internal_clients; };
    recursion yes;

    zone "corp.local" {
        type master;
        file "/etc/bind/zones/db.corp.local.internal";
    };
};

view "external" {
    match-clients { any; };
    recursion no;

    zone "corp.local" {
        type master;
        file "/etc/bind/zones/db.corp.local.external";
    };
};
```

При использовании View **все** зоны должны быть объявлены внутри блоков представлений. Теория Views: [Продвинутые возможности](./advanced_topics.md).

### 4. Валидация и применение

**Проверка синтаксиса:**
```bash
# Проверка named.conf
sudo named-checkconf
# → (нет вывода при успехе)

# Проверка файла зоны
sudo named-checkzone corp.local /etc/bind/zones/db.corp.local
# → zone corp.local/IN: loaded serial 2025072501
# → OK
```

**Перезагрузка зоны:**
```bash
sudo rndc reload corp.local
# → zone reload queued
```

**Принудительный повторный трансфер (для отладки):**
```bash
sudo rndc retransfer corp.local
# → zone retransfer queued
```

### 5. Верификация разрешения имен

Проверьте наличие флага авторитетности (**aa**) в ответе.

```bash
dig @127.0.0.1 web.corp.local
# → ;; flags: qr aa rd ra; QUERY: 1, ANSWER: 1, ...
# → ;; ANSWER SECTION:
# → web.corp.local. 86400 IN A 192.168.10.50
```

---

## Управление зонами через rndc

| Команда | Описание |
| :--- | :--- |
| `rndc reload` | Перезагрузка всех зон и конфигурации. |
| `rndc reload <zone>` | Перезагрузка конкретной зоны. |
| `rndc retransfer <zone>` | Принудительный полный трансфер зоны (AXFR) с Master на Slave. |
| `rndc flush` | Очистка всего кэша резолвера. |
| `rndc flushname <name>` | Очистка кэша для конкретного имени. |
| `rndc flushtree <name>` | Очистка кэша для поддерева имён. |
| `rndc freeze <zone>` | Приостановка динамических обновлений (для резервного копирования). |
| `rndc thaw <zone>` | Возобновление динамических обновлений. |
| `rndc sync <zone>` | Принудительная запись изменений из .jnl в файл зоны. |
| `rndc notify <zone>` | Принудительная отправка NOTIFY-уведомлений Slave-серверам. |
| `rndc status` | Вывод статистики и времени работы сервера. |
| `rndc querylog` | Включение/выключение логирования всех входящих запросов. |
| `rndc dumpdb` | Дамп текущего кэша в файл. |
| `rndc stats` | Запись статистики в канал (если statistics-channel включён). |

---

## Резервное копирование и откат

### Экспорт конфигурации

```bash
# Остановка динамических обновлений (если зоны динамические)
sudo rndc freeze corp.local

# Резервное копирование
sudo tar czf /backup/bind-master-$(date +%Y%m%d).tar.gz \
    /etc/bind/ \
    /var/lib/bind/ \
    /var/cache/bind/

# Возобновление обновлений
sudo rndc thaw corp.local
```

### Восстановление

```bash
sudo systemctl stop bind9
sudo rm -rf /etc/bind && sudo cp -a /etc/bind.backup.2026-09-12 /etc/bind
sudo systemctl start bind9
```

---

## Мониторинг

### Statistics Channel

```conf
// /etc/bind/named.conf.options
statistics-channels {
    inet 127.0.0.1 port 8053 allow { 127.0.0.1; };
};
```

```bash
curl http://127.0.0.1:8053/  # → JSON со статистикой
curl http://127.0.0.1:8053/json  # → расширенная статистика
```

### Проверка состояния зон

```bash
# Список всех зон и их статус
sudo rndc status
# → версия, uptime, количество зон

# Проверка конкретной зоны
dig @127.0.0.1 corp.local SOA +multiline
# → серийный номер, таймеры

# Проверка журнала динамических обновлений
ls -l /var/cache/bind/db.corp.local.jnl
# → файл присутствует, размер соответствует активности
```

---

## Производительность

### Основные параметры в `options`

```conf
options {
    directory "/var/cache/bind";

    tcp-clients 100;
    udp-receive-buffer 4m;

    max-cache-size 512m;
    max-cache-ttl 3600;
    max-ncache-ttl 600;

    prefetch 2 90;
    stale-cache-enable yes;
    stale-answer-ttl 30;
};
```

### Параметры для Master-сервера

```conf
zone "corp.local" {
    type master;
    file "/etc/bind/zones/db.corp.local";
    masterfile-format raw;  // ускоряет загрузку Slave-серверами
    journal-file "/var/cache/bind/db.corp.local.jnl";
    max-journal-size 50m;   // ограничение размера .jnl
};
```

### Рекомендации по ресурсам

- **RAM:** 1 GB минимум; +1 GB на каждые 1 млн записей в зонах.
- **CPU:** BIND преимущественно однопоточный на запрос; пиковые нагрузки требуют быстрых ядер.
- **Disk:** SSD для Master-серверов с динамическими обновлениями и большими `.jnl`; HDD подходит для статических зон.

---

## Безопасность

### Меры защиты Master-сервера

1. **Ограничьте `allow-transfer`:** передача зоны только доверенным Slave-серверам по IP. Для критичных сред используйте TSIG.
2. **Ограничьте `allow-query`:** если зона внутренняя, разрешайте запросы только из внутренней подсети.
3. **Версия `none`:** скройте версию BIND от внешних сканеров.
   ```conf
   version "none";
   ```
4. **Запретите динамические обновления без аутентификации:** `allow-update { none; };`.
5. **AppArmor / SELinux:** убедитесь, что профиль безопасности не блокирует чтение файлов зон.
6. **TSIG для NOTIFY и Dynamic Update:** защита от поддельных уведомлений и изменений.
7. **DNSSEC:** подпишите зоны для защиты от подмены ответов.

### Конфигурация TSIG для защиты трансферов

```bash
# Генерация ключа
sudo tsig-keygen -a HMAC-SHA256 transfer-key > /etc/bind/transfer.key
```

```conf
// /etc/bind/named.conf.local — на Master
include "/etc/bind/transfer.key";

zone "corp.local" {
    type master;
    file "/etc/bind/zones/db.corp.local";
    allow-transfer { key "transfer-key"; };
    also-notify { 192.168.10.20; };
};
```

---

## Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **SERVFAIL при запросе зоны** | Ошибка синтаксиса в файле зоны, невалидный Serial. | `named-checkzone`, проверка `journalctl -u bind9`. |
| **Slave не получает зону** | `allow-transfer` не настроен, закрыт TCP/53, расхождение часов при TSIG. | `dig @master zone AXFR`, проверка firewall, `chronyc tracking`. |
| **Зона не обновляется после правки** | Serial не увеличен. | Увеличить Serial, `rndc reload`. |
| **NOTIFY не доставляется** | UDP-пакет потерян, `allow-notify` не настроен на Slave. | `rndc notify zone`, проверка конфигурации Slave. |
| **`dumping master file ... permission denied`** | Нет прав на запись в каталог Slave-зоны или AppArmor блокирует. | `chown bind:bind`, проверка `/etc/apparmor.d/usr.sbin.named`. |
| **Ключ rndc не работает** | Ключ не сгенерирован или не подключён в конфиге. | `rndc-confgen -a`, проверка `include "/etc/bind/rndc.key"`. |
| **Высокое потребление памяти** | Неограниченный кэш, большие зоны в памяти. | `max-cache-size`, переключение на `masterfile-format raw`. |
| **Динамическое обновление не применяется** | Файл .jnl не синхронизирован с файлом зоны. | `rndc sync zone`, проверка прав на .jnl. |

---

## Health-check скрипт

Скрипт для мониторинга состояния Master-сервера через cron или систему мониторинга:

```bash
#!/bin/bash
# /usr/local/bin/bind-master-healthcheck.sh

ZONES=("corp.local" "10.0.8.in-addr.arpa")
EXPECTED_SERIAL=("2025072501" "2025072501")
MASTER_IP="127.0.0.1"
ALERT_EMAIL="admin@corp.local"

for i in "${!ZONES[@]}"; do
    zone="${ZONES[$i]}"
    expected="${EXPECTED_SERIAL[$i]}"
    current=$(dig @"$MASTER_IP" "$zone" SOA +short 2>/dev/null | awk '{print $3}')

    if [ -z "$current" ]; then
        echo "CRITICAL: Zone $zone is not responding" | mail -s "BIND Alert: $zone down" "$ALERT_EMAIL"
        continue
    fi

    if [ "$current" != "$expected" ]; then
        echo "WARNING: Zone $zone serial mismatch: expected=$expected, actual=$current" | mail -s "BIND Alert: $zone serial drift" "$ALERT_EMAIL"
    fi
done

# Проверка службы
if ! systemctl is-active --quiet bind9; then
    echo "CRITICAL: bind9 service is down" | mail -s "BIND Alert: service down" "$ALERT_EMAIL"
fi
```

```bash
sudo chmod +x /usr/local/bin/bind-master-healthcheck.sh

# Тестовый запуск
sudo /usr/local/bin/bind-master-healthcheck.sh
# → (нет вывода при нормальной работе)

# Добавление в cron (каждые 5 минут)
sudo crontab -e
# → */5 * * * * /usr/local/bin/bind-master-healthcheck.sh
```

---

## Дополнительная информация

*   **Версии:** Актуально для BIND 9.18+ (LTS) и 9.20+ (ESV).
*   **RFC:** RFC 1035 (зоны), RFC 1995 (IXFR), RFC 1996 (NOTIFY), RFC 2136 (Dynamic Update), RFC 8945 (TSIG).
*   **Связанные разделы:**
    *   **[Зоны DNS и SOA-запись](../../../../Networking/Protocols/DNS/dns_zones.md)** — глубокая теория метаданных.
    *   **[Вторичный сервер (Slave)](./slave_server_configuration.md)** — настройка репликации.
    *   **[Отказоустойчивый кластер BIND9](./high-availability-cluster.md)** — сквозной сценарий Master-Slave с ручным переключением ролей.
    *   **[Обратная зона (Reverse)](./reverse_zone_configuration.md)** — настройка PTR-записей.
    *   **[Ресурсные записи DNS](../../../../Networking/Protocols/DNS/dns_records.md)** — детали форматов MX, TXT, SRV.
    *   **[Диагностика BIND](./troubleshooting.md)** — поиск и устранение ошибок.
    *   **[Перенаправляющий сервер](./forwarding_server.md)** — работа с внешними запросами.
