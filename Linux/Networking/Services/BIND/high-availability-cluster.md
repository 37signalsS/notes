# Отказоустойчивый кластер BIND9 (Master-Slave)

---

## Определения

**Отказоустойчивый DNS-кластер** — схема из двух и более авторитативных серверов BIND9, в которой один узел является первичным (**Primary / Master**, эталонные файлы зон редактируются вручную), а остальные — вторичными (**Secondary / Slave**, получают копию зон через механизм зонной передачи). При выходе из строя одного узла клиенты продолжают обслуживаться вторым, так как обращаются ко всем адресам кластера по очереди.

**Зонная передача (Zone Transfer)** — синхронизация данных зоны между узлами: **AXFR** (полная передача) и **IXFR** (инкрементальная). Теория механизма: [Настройка вторичного сервера](./slave_server_configuration.md).

**Ручное переключение (Promotion)** — административная процедура перевода Slave-сервера в роль Master при окончательном выходе Primary из строя. BIND не выполняет автоматический failover авторитативных зон — это осознанное проектное решение: роль источника данных должна быть строго единственной, иначе возникает расхождение данных (два узла считают себя мастерами).

---

## Архитектура и принцип работы

### Топология стенда

| Узел | Hostname | IP-адрес | Роль |
| :--- | :--- | :--- | :--- |
| Сервер 1 | `ns1.example.com` | `10.0.8.50` | Master (эталонные зоны) |
| Сервер 2 | `ns2.example.com` | `10.0.8.51` | Slave (реплика зон) |
| Клиент | рабочая станция | любой из `10.0.8.0/24` | оба адреса в `/etc/resolv.conf` |

Параметры примера (замените на свои): домен `example.com`, обратная зона для подсети `10.0.8.0/24`.

### Цикл репликации

1. Администратор правит файл зоны **только на Master** и увеличивает Serial.
2. После `reload` Master отправляет **NOTIFY**-уведомление Slave-серверам.
3. Slave сравнивает Serial мастера со своим; если у мастера больше — запрашивает передачу (BIND сам выбирает IXFR, при невозможности — AXFR).
4. Клиент имеет **оба IP-адреса** серверов в настройках резолвера: запросы идут к первому, при его недоступности — ко второму. Отказ мастера не прерывает обслуживание.

### Почему критична синхронизация времени

Служба времени (chrony/ntp) обязательна на обоих узлах:

- **DNSSEC:** валидация криптографических подписей RRSIG опирается на временные интервалы. При сильно уехавших часах сервер может считать корректные подписи недействительными.
- **TSIG:** защищённая передача зон использует временные метки; расхождение часов ломает аутентификацию.
- **Serial по дате:** рекомендуемый формат серийного номера `ГГГГММДДНН` привязан к дате; сбитые часы генерируют странные Serial и путают репликацию.
- **Разбор инцидентов:** единое время в журналах обоих узлов необходимо для корреляции событий.

### Топологии кластеров

**Master-Slave (основная):** один эталонный узел с файлами зон, остальные получают копии через AXFR/IXFR. Простота управления: правки вносятся в одном месте.

**Скрытый мастер (Hidden Primary):** Master не имеет публичного IP и не отвечает клиентам напрямую; все внешние запросы идут на Slave, которые реплицируют зоны с Master через внутреннюю сеть. Преимущество — поверхностная защита эталонных данных от прямых атак.

**Anycast:** один и тот же IP-адрес анонсируется с нескольких узлов. Клиент обращается к ближайшему по топологии сети. Для BIND anycast реализуется на уровне маршрутизации (OSPF/BGP) или через LVS/keepalived на ядре Linux, а не через cloud-сервисы. Anycast не заменяет репликацию: каждый узел всё равно должен иметь актуальную копию зон (Slave или локальный Master).

### Журналы зон (.jnl) и непрерывность IXFR

На Master для каждого файла зоны BIND ведёт журнал изменений (`db.example.com.jnl`). Без журнала IXFR невозможен — Slave получит AXFR. Журнал хранится рядом с файлом зоны и автоматически применяется к файлу при `rndc sync` или `rndc reload`. При ручном редактировании файла зоны журнал сбрасывается: BIND считает, что базовая версия обновлена, и IXFR продолжится с нового Serial.

### Ротация TSIG-ключей

Общий секрет TSIG имеет рекомендованный срок жизни (обычно 30–90 дней). В кластере ротация выполняется на обоих узлах одновременно:

1. Генерация нового ключа: `tsig-keygen -a HMAC-SHA256 new-transfer-key > /etc/bind/transfer.key.new`
2. Распространение нового ключа на оба узла (scp/ansible/etc.)
3. Переключение конфигурации на новый ключ (оба узла)
4. `rndc reconfig` на Master и Slave
5. Проверка: `dig @master zone AXFR` — трансфер проходит с новым ключом
6. Удаление старого ключа после успешной проверки

Старый ключ не удаляйте сразу: оставьте его в конфиге 1–2 цикла репликации, чтобы Slave успел обновиться при перезагрузке мастера.

### Обнаружение дрейфа Serial

При асинхронных правках или сбое репликации Serial на Slave может отстать. Автоматическая проверка (cron + скрипт):

```bash
#!/bin/bash
MASTER=10.0.8.50
SLAVE=10.0.8.51
ZONE=example.com
EXPECTED=$(dig @$MASTER $ZONE SOA +short | awk '{print $3}')
ACTUAL=$(dig @$SLAVE $ZONE SOA +short | awk '{print $3}')
if [ "$EXPECTED" != "$ACTUAL" ]; then
    echo "ALERT: Serial drift on $SLAVE: expected=$EXPECTED actual=$ACTUAL"
    # rndc retransfer $ZONE на Slave принудит AXFR
fi
```

Скрипт должен выполняться на внешнем мониторе или на самом Slave; на Slave он обнаруживает собственную отсталость.

---

## Подготовка окружения

Выполняется на обоих серверах, если не указано иное. Пример для Astra Linux и других Debian-подобных дистрибутивов (в RHEL-семействе пакеты называются `bind`/`bind-utils`, служба — `named`).

### Имена хостов и разрешение между узлами

```bash
sudo hostnamectl set-hostname ns1.example.com   # на первом сервере
sudo hostnamectl set-hostname ns2.example.com   # на втором
```

Добавьте записи в `/etc/hosts` на обоих узлах, чтобы узлы resolving друг друга без DNS (важно на этапе первоначальной настройки):

```bash
sudo tee -a /etc/hosts > /dev/null <<EOF
10.0.8.50  ns1.example.com  ns1
10.0.8.51  ns2.example.com  ns2
EOF
cat /etc/hosts   # → строки добавлены в конец файла
```

### Установка пакетов

```bash
sudo apt update && sudo apt install -y bind9 bind9utils dnsutils chrony
# → success
```

| Пакет | Назначение |
| :--- | :--- |
| `bind9` | демон `named`, утилита управления `rndc`, `named-checkconf`, `named-checkzone`, `named-compilezone` |
| `dnsutils` | клиентские утилиты диагностики: `dig`, `nslookup`, `host` |
| `chrony` | демон и клиент синхронизации времени |

Подробности установки и конфликтов с `systemd-resolved`: [Установка BIND](./installation.md).

### Проверка времени

```bash
timedatectl
# → NTP service: active; время на обоих узлах совпадает
chronyc sources -v   # → список источников синхронизации
```

### Межсетевой экран (опционально)

Если используется iptables, разрешите DNS-трафик: `53/udp` — обычные запросы, `53/tcp` — усечённые ответы и трансфер зон. Паттерн «проверить и добавить» идемпотентен — повторный запуск не создаст дубликат правила:

```bash
sudo apt install -y iptables iptables-persistent

# -C проверяет наличие правила (код 0 — есть, 1 — нет); 2>/dev/null глушит сообщение об ошибке
iptables -C INPUT -p udp --dport 53 -s 10.0.8.0/24 -j ACCEPT 2>/dev/null || \
iptables -I INPUT -p udp --dport 53 -s 10.0.8.0/24 -j ACCEPT

iptables -C INPUT -p tcp --dport 53 -s 10.0.8.0/24 -j ACCEPT 2>/dev/null || \
iptables -I INPUT -p tcp --dport 53 -s 10.0.8.0/24 -j ACCEPT

sudo netfilter-persistent save   # сохраняет правила IPv4 и IPv6 для автозагрузки
sudo iptables -L -n              # → правила ACCEPT dpt:domain присутствуют
```

Расшифровка ключей: `-I` — insert (вставка в начало цепочки INPUT); `-s 10.0.8.0/24` — ограничение источника внутренней подсетью. Для публичной зоны уберите `-s <подсеть>` — сервер должен отвечать любым клиентам.

#### nftables (Debian 12+, Ubuntu 22.04+)

На современных дистрибутивах nftables заменяет iptables. Правила аналогичны:

```bash
sudo apt install -y nftables

sudo nft add rule inet filter input ip saddr 10.0.8.0/24 udp dport 53 accept
sudo nft add rule inet filter input ip saddr 10.0.8.0/24 tcp dport 53 accept

sudo nft list ruleset   # → правила присутствуют
sudo systemctl enable --now nftables
```

#### firewalld (RHEL 9+, CentOS Stream)

```bash
sudo firewall-cmd --permanent --add-service=dns
sudo firewall-cmd --permanent --add-source=10.0.8.0/24
sudo firewall-cmd --reload
sudo firewall-cmd --list-all   # → services: dns, sources: 10.0.8.0/24
```

### SELinux и AppArmor

Оба механизма ограничивают права демона `named`. По умолчанию в Debian/Ubitus активен AppArmor, в RHEL — SELinux (enforcing).

Проверка статуса:

```bash
# AppArmor
sudo aa-status | grep named
# → /usr/sbin/named (enforced)

# SELinux
getenforce
# → Enforcing
```

Если BIND не может записать файлы зон или открыть порты, проверяйте логи:

```bash
sudo journalctl -u named -n 50 | grep -i "apparmor\|denied\|avc"
```

Для временного отключения AppArmor (только для диагностики!):

```bash
sudo aa-complain /usr/sbin/named
# → верните в enforced после решения проблемы: sudo aa-enforce /usr/sbin/named
```

Для SELinux — создание политики или установка правильных контекстов:

```bash
sudo restorecon -Rv /etc/bind /var/cache/bind /var/lib/bind
sudo chcon -t named_zone_t /etc/bind/zones/db.example.com
```

### IPv6 (опционально)

Если инфраструктура использует IPv6, добавьте адреса в `named.conf.options`:

```conf
listen-on-v6 { any; };    // вместо { none; }
allow-transfer { localhost; dns-cluster; ::1; };   // добавьте IPv6 адреса кластера
```

Клиенты с IPv6 будут обращаться к серверам по AAAA-записям. Убедитесь, что firewall разрешает `53/udp` и `53/tcp` для IPv6-подсети.

---

## Базовая конфигурация (оба сервера)

### Резервная копия исходных конфигураций

```bash
sudo cp -a /etc/bind /etc/bind.backup.$(date +%F)
ls -d /etc/bind.backup.*
# → /etc/bind.backup.2026-08-21
```

**RHEL-семейство:** замените `/etc/bind` → `/etc/named` (пакет `bind`, служба `named`).

### Глобальные настройки: `/etc/bind/named.conf.options`

Замените содержимое файла на следующее (пояснения ниже):

```conf
// /etc/bind/named.conf.options — одинаково на ns1 и ns2

acl "trusted" {
    127.0.0.0/8;        // локальная петля
    10.0.8.0/24;        // внутренняя подсеть
};

acl "dns-cluster" {
    10.0.8.50;          // ns1
    10.0.8.51;          // ns2
};

options {
    directory "/var/cache/bind";

    listen-on port 53 { any; };     // слушать на всех интерфейсах
    listen-on-v6 { none; };         // IPv6 отключен

    // Кто может задавать DNS-запросы этому серверу
    allow-query { trusted; };

    // Кто может копировать зоны (трансфер): сам сервер и узлы кластера
    allow-transfer { localhost; dns-cluster; };

    // От кого принимать NOTIFY об изменении зон (защита от поддельных уведомлений)
    allow-notify { dns-cluster; };

    // Динамические обновления запрещены: зоны правятся вручную на мастере
    allow-update { none; };

    recursion no;               // только авторитативные ответы по своим зонам
    dnssec-validation auto;     // автоматическая проверка DNSSEC-подписей
    auth-nxdomain no;           // соответствие RFC1035 для NXDOMAIN

    // Статистический канал для мониторинга (только localhost)
    statistics-channels {
        inet 127.0.0.1 port 8053 allow { localhost; };
    };
};
```

Пояснение ключевых решений:

- **ACL (списки контроля доступа)** `trusted` и `dns-cluster` — именованные группы адресов. Использование групп вместо перечисления IP в каждом правиле упрощает сопровождение: изменение подсети вносится в одном месте.
- **`allow-query { trusted; }`** — запросы с чужих адресов отклоняются кодом `REFUSED`: сервер не отвечает случайным сканерам из интернета. Для публичной зоны замените на `allow-query { any; };`.
- **`allow-transfer`** — открытый трансфер `any` недопустим: любой желающий выкачает полную карту вашей сети (все имена и адреса зоны командой `dig ... AXFR`).
- **`allow-notify`** — Slave принимает уведомления об изменениях только от известных узлов кластера. Фальшивый NOTIFY от злоумышленника будет проигнорирован.
- **`recursion no`** — сервер отвечает исключительно по зонам, за которые авторитетен. Вариант «авторитативный + рекурсивный для своей сети»:

```conf
    recursion yes;
    allow-recursion { trusted; };
    forwarders { 8.8.8.8; 1.1.1.1; };   // upstream для остальных имён
```

Проверка синтаксиса (пустой вывод — ошибки нет):

```bash
sudo named-checkconf
# → (нет вывода — конфигурация корректна)
```

---

## Настройка первичного сервера (ns1)

### Каталог зон и права

```bash
sudo mkdir -p /etc/bind/zones
sudo chown root:bind /etc/bind/zones
sudo chmod 750 /etc/bind/zones
# владелец root: чтение/запись/исполнение; группа bind: чтение/исполнение; остальные: нет доступа
```

Файлы зон принадлежат `root:bind` с правами `640`: демон `named` работает от пользователя `bind` и должен только **читать** эталонные зоны. Право на запись мастеру не нужно — это защита от случайной модификации.

### Объявление зон: `/etc/bind/named.conf.local`

```conf
// /etc/bind/named.conf.local — только на ns1 (Master)

zone "example.com" {
    type master;
    file "/etc/bind/zones/db.example.com";  // текстовый файл зоны
    allow-transfer { 10.0.8.51; };          // кому разрешено копировать зону
    also-notify { 10.0.8.51; };             // куда слать NOTIFY после каждого изменения
};

zone "8.0.10.in-addr.arpa" {
    type master;
    file "/etc/bind/zones/db.10.0.8";
    allow-transfer { 10.0.8.51; };
    also-notify { 10.0.8.51; };
};
```

Имя обратной зоны строится переворотом сетевой части адреса: `10.0.8.0/24` → `8.0.10.in-addr.arpa`. Она отвечает за PTR-записи (IP → имя), проверяется командой `dig -x`.

### Файл прямой зоны: `/etc/bind/zones/db.example.com`

```dns
; /etc/bind/zones/db.example.com
$TTL    300     ; время жизни записей в кэше по умолчанию (5 минут)
$ORIGIN example.com.   ; база для коротких имён без точки на конце

@   IN  SOA ns1.example.com. admin.example.com. (
            2026082100  ; Serial: ГГГГММДДНН (НН — номер правки за день)
            3600        ; Refresh: интервал опроса мастера Slave-ом (1 час)
            900         ; Retry: повтор при неудачном опросе (15 минут)
            1209600     ; Expire: срок жизни данных Slave при недоступном мастере (14 дней)
            300 )       ; Negative TTL: кэширование ответов «имя не существует» (5 минут)

; Авторитативные серверы зоны
@       IN  NS  ns1.example.com.
@       IN  NS  ns2.example.com.

; Glue-записи: адреса самих NS-серверов
ns1     IN  A   10.0.8.50
ns2     IN  A   10.0.8.51

; Тестовая запись инфраструктуры
server01 IN A   10.0.8.10
```

Разбор механики:

- **`$TTL 300`** — короткое значение ускоряет распространение изменений: через 5 минут после получения ответа резолверы забудут запись и спросят снова.
- **`$ORIGIN`** — любое имя в файле без точки на конце дополняется этим суффиксом: `ns1` превращается в `ns1.example.com.`.
- **`@`** — сокращение для имени самой зоны (`example.com.`); запись относится к домену целиком, а не к подузлу.
- **`IN`** — класс записи (Internet), присутствует в каждой строке.
- **SOA** — «паспорт» зоны: первичный сервер, e-mail администратора (`admin.example.com.` = `admin@example.com`), таймеры репликации. Скобки позволяют разбить одну запись на несколько строк.
- **Serial обязателен к увеличению при каждой правке** — иначе Slave не узнает об изменениях (сравнивает номера, а не содержимое).
- **NS и glue-A работают в паре**: без A-записей резолвер не смог бы найти адреса серверов, перечисленных в NS.
- Текст после `;` — комментарий, BIND его игнорирует.

### Файл обратной зоны: `/etc/bind/zones/db.10.0.8`

```dns
; /etc/bind/zones/db.10.0.8
$TTL    300
$ORIGIN 8.0.10.in-addr.arpa.

@   IN  SOA ns1.example.com. admin.example.com. (
            2026082100
            3600
            900
            1209600
            300 )

@       IN  NS  ns1.example.com.
@       IN  NS  ns2.example.com.

; PTR: число слева — последний октет адреса
50      IN  PTR ns1.example.com.
51      IN  PTR ns2.example.com.
10      IN  PTR server01.example.com.
```

Имена в PTR записываются **полным FQDN с точкой на конце**: без точки `$ORIGIN` допишет суффикс зоны, и получится `ns1.example.com.8.0.10.in-addr.arpa.` — ошибочная запись.

### Права на файлы зон

```bash
sudo chown root:bind /etc/bind/zones/db.example.com /etc/bind/zones/db.10.0.8
sudo chmod 640 /etc/bind/zones/db.example.com /etc/bind/zones/db.10.0.8
ls -l /etc/bind/zones/
# → -rw-r----- 1 root bind ... db.10.0.8
# → -rw-r----- 1 root bind ... db.example.com
```

### Валидация и запуск

```bash
sudo named-checkconf
# → (пусто — синтаксис конфигурации верен)

sudo named-checkzone example.com /etc/bind/zones/db.example.com
# → zone example.com/IN: loaded serial 2026082100; OK

sudo named-checkzone 8.0.10.in-addr.arpa /etc/bind/zones/db.10.0.8
# → zone 8.0.10.in-addr.arpa/IN: loaded serial 2026082100; OK

sudo systemctl enable --now bind9
systemctl status bind9 --no-pager
# → Active: active (running)
```

Serial в выводе обеих проверок должен совпадать с указанным в файлах.

---

## Настройка вторичного сервера (ns2)

Slave **не создаёт файлы зон** — они будут получены с мастера. Настраивается только объявление зон.

### `/etc/bind/named.conf.local`

```conf
// /etc/bind/named.conf.local — только на ns2 (Slave)

zone "example.com" {
    type slave;
    file "/var/cache/bind/db.example.com";  // сюда BIND сохранит полученную зону
    primaries { 10.0.8.50; };               // адрес мастера (устаревший синоним: masters)
    masterfile-format text;                 // хранить файл зоны в текстовом виде, не в бинарном raw
    allow-notify { 10.0.8.50; };            // принимать NOTIFY только от мастера
};

zone "8.0.10.in-addr.arpa" {
    type slave;
    file "/var/cache/bind/db.10.0.8";
    primaries { 10.0.8.50; };
    masterfile-format text;
    allow-notify { 10.0.8.50; };
};
```

Пояснения:

- **`type slave`** — зона поддерживается только через трансфер; локальное редактирование невозможно и не нужно.
- **Файл в `/var/cache/bind`**, а не в `/etc/bind/zones`: каталог кэша доступен пользователю `bind` на запись — именно туда демон сохраняет полученные с мастера данные.
- **`primaries`** — актуальное имя директивы в BIND 9.18+; старое `masters` продолжает работать для совместимости, но в новых конфигурациях используйте `primaries`.
- **`masterfile-format text`** — начиная с BIND 9.16 вторичные зоны по умолчанию хранятся в бинарном формате `raw` (быстрее загрузка, но файл не читается `cat`). Текстовый формат удобнее для диагностики.

### Запуск и контроль трансфера

```bash
sudo named-checkconf && sudo systemctl enable --now bind9

# Через несколько секунд после старта:
ls -l /var/cache/bind/
# → -rw-r--r-- 1 bind bind ... db.10.0.8
# → -rw-r--r-- 1 bind bind ... db.example.com

journalctl -u bind9 -n 50 --no-pager | grep -i transfer
# → transfer of 'example.com/IN' from 10.0.8.50#53: Transfer status: success
# → transferred serial 2026082100
```

Если файлы зон не появились сразу — это нормальное поведение в моменте: дождитесь NOTIFY/Refresh либо перезапустите службу на обоих узлах (`systemctl restart bind9`). Если файлы не появляются после рестарта — ищите ошибку в журнале (см. раздел неполадок).

---

## Проверка репликации

Все команды — с любого узла или клиента.

```bash
# 1. Serial на обоих серверах должен совпадать
dig @10.0.8.50 example.com SOA +short
# → ns1.example.com. admin.example.com. 2026082100 3600 900 1209600 300
dig @10.0.8.51 example.com SOA +short
# → ns1.example.com. admin.example.com. 2026082100 3600 900 1209600 300

# 2. Прямые A-записи (+short — компактный вывод, только значения)
dig @10.0.8.50 example.com A +short
dig @10.0.8.51 ns1.example.com A +short
# → 10.0.8.50

# 3. Обратная зона (PTR)
dig @10.0.8.51 -x 10.0.8.50 +short
# → ns1.example.com.

# 4. Ручной тест трансфера: полный список записей зоны
dig @10.0.8.50 example.com AXFR
# → перечислены все записи зоны и 'XFR size: N records'
```

Совпадение Serial в ответах обоих серверов — главный признак консистентности кластера.

### Мониторинг состояния кластера

#### Статистический канал BIND

Статистический канал, настроенный в `named.conf.options`, позволяет получать метрики в формате XML/JSON без риска для конфигурации. Проверка на обоих узлах:

```bash
curl -s http://127.0.0.1:8053/json/v1/server
# → {"json_version":"1.5","name":"ns1.example.com","version":"9.18.18","current_time":"...","boot_time":"...","config_time":"...","uptime":12345,"opcodes":{"QUERY":42,...},"rcodes":{"NOERROR":38,...},"nsstats":...}
```

Ключевые метрики для кластера:
- `opcodes.QUERY` — общее количество запросов
- `rcodes.NOERROR` / `rcodes.SERVFAIL` — соотношение успешных и ошибочных ответов
- `nsstats.Success` / `nsstats.Failure` — успешные/неуспешные трансферы зон
- `zone.ExampleCom.serial` — текущий Serial конкретной зоны

#### Скрипт health-check для мониторинга

Скрипт для Nagios/Zabbix/cron, проверяет консистентность и доступность обоих узлов:

```bash
#!/bin/bash
# /usr/local/bin/bind-cluster-check.sh
MASTER=10.0.8.50
SLAVE=10.0.8.51
ZONE=example.com
MASTER_SERIAL=$(dig @$MASTER $ZONE SOA +short 2>/dev/null | awk '{print $3}')
SLAVE_SERIAL=$(dig @$SLAVE $ZONE SOA +short 2>/dev/null | awk '{print $3}')

if [ -z "$MASTER_SERIAL" ] || [ -z "$SLAVE_SERIAL" ]; then
    echo "CRITICAL: Unable to reach one or both servers"
    exit 2
fi

if [ "$MASTER_SERIAL" != "$SLAVE_SERIAL" ]; then
    echo "WARNING: Serial drift - master=$MASTER_SERIAL slave=$SLAVE_SERIAL"
    exit 1
fi

echo "OK: Cluster consistent, serial=$MASTER_SERIAL"
exit 0
```

Добавление в cron (каждые 5 минут):

```bash
*/5 * * * * root /usr/local/bin/bind-cluster-check.sh > /dev/null 2>&1
```

#### Проверка через rndc на обоих узлах

```bash
# Статус сервера
sudo rndc status
# → BIND 9.18.18 (Development Release) <id:...> running on ns1.example.com
# → DNS configured: yes; DNS enabled: yes; recursion: no

# Статус конкретной зоны
sudo rndc zonestatus example.com
# → zone example.com/IN: loaded serial 2026082100; type master; files: /etc/bind/zones/db.example.com

# Принудительный трансфер (если Serial совпадает, но данные устарели)
sudo rndc retransfer example.com
# → zone retransfer queued

# Синхронизация journal с файлом зоны
sudo rndc sync example.com
```

---

## Настройка клиентов

Клиенту указываются **оба** адреса серверов. Пример для NetworkManager (Astra Linux, десктоп):

```bash
nmcli con mod "Проводное соединение 1" ipv4.dns "10.0.8.50 10.0.8.51"
nmcli con mod "Проводное соединение 1" ipv4.dns-search "example.com"
nmcli con up "Проводное соединение 1"

cat /etc/resolv.conf
# → nameserver 10.0.8.50
# → nameserver 10.0.8.51
# → search example.com
```

- `ipv4.dns` — оба сервера; резолвер опрашивает их сверху вниз, при таймауте первого автоматически переходит ко второму.
- `ipv4.dns-search` — позволяет обращаться по коротким именам: `ping ns1` вместо `ping ns1.example.com`.
- Порядок адресов определяет приоритет: первым опрашивается верхний `nameserver`. Поменяйте порядок, если хотите сместить нагрузку на другой узел.

Проверка работы и отказоустойчивости:

```bash
ping ns1.example.com
# → PING ns1.example.com (10.0.8.50) — имя разрешилось в адрес

ping server01.example.com
# → имя разрешается в 10.0.8.10; если хост выключен — 'Destination Host Unreachable',
#   но само разрешение имени работает: DNS исправен

# Полное выключение ns1 — запросы автоматически уходят на ns2:
dig @10.0.8.51 printer.example.com   # ответ приходит, чуть медленнее (таймаут первого сервера)
```

---

## Внесение изменений в зону

Регламент правки (только на текущем мастере):

1. Отредактируйте файл зоны, например добавьте запись:

```dns
printer  IN  A   10.0.8.20
```

2. **Обязательно увеличьте Serial** (например, `2026082100` → `2026082101`). Без этого Slave сочтёт свою копию актуальной и изменения не распространятся.
3. Примените и проверьте:

```bash
sudo named-checkzone example.com /etc/bind/zones/db.example.com
# → zone example.com/IN: loaded serial 2026082101; OK
sudo rndc reload example.com
# → zone reload queued

# На Slave (через пару секунд):
dig @10.0.8.51 printer.example.com A +short
# → 10.0.8.20
dig @10.0.8.51 example.com SOA +short | awk '{print $3}'
# → 2026082101  (совпадает с мастером)
```

NOTIFY доставляет уведомление за секунды; если Slave не получил его, он сам опросит мастера по таймеру Refresh (в примере — до часа).

### Ротация TSIG-ключей в кластере

Ключи, используемые для защиты трансферов, имеют рекомендованный срок жизни (30–90 дней). Ротация выполняется на обоих узлах одновременно:

1. Генерация нового ключа (на любом узле):
   ```bash
   sudo tsig-keygen -a HMAC-SHA256 transfer-key-new > /etc/bind/transfer.key.new
   ```
2. Распространение нового ключа на оба узла (ansible/scp).
3. Подключение в конфиг: `include "/etc/bind/transfer.key.new";` на Master и Slave.
4. Замена `allow-transfer { key "transfer-key"; }` на `key "transfer-key-new"`.
5. `sudo rndc reconfig` на обоих узлах.
6. Проверка трансфера: `dig @master zone AXFR` — проходит с новым ключом.
7. Удаление старого ключа после 1–2 успешных циклов репликации.

---

## Процедура ручного переключения при отказе мастера

### Когда требуется

Мастер окончательно вышел из строя. Slave продолжает авторитативно отвечать из памяти, но **только до истечения таймера Expire** (в примере — 14 дней): после этого он считает данные устаревшими и перестаёт отвечать по зоне. Кроме того, без мастера невозможно вносить новые записи. Решение — повысить Slave до Master.

Исходная ситуация: `ns2` (10.0.8.51) — действующий Slave с актуальными данными; `ns1` — выключен.

### Шаг 1. Перенос файлов зон в постоянный каталог

```bash
# на ns2
sudo mkdir -p /etc/bind/zones
sudo cp /var/cache/bind/db.example.com /etc/bind/zones/
sudo cp /var/cache/bind/db.10.0.8 /etc/bind/zones/
sudo chown root:bind /etc/bind/zones/db.*
sudo chmod 640 /etc/bind/zones/db.*
```

Файлы **копируются, а не создаются заново** — в них уже есть все актуальные записи.

### Шаг 2. Смена типа зон на master

Замените содержимое `/etc/bind/named.conf.local` на ns2:

```conf
zone "example.com" {
    type master;
    file "/etc/bind/zones/db.example.com";
    allow-transfer { 10.0.8.50; };   // бывший мастер станет Slave — ему нужен трансфер
    also-notify { 10.0.8.50; };
};

zone "8.0.10.in-addr.arpa" {
    type master;
    file "/etc/bind/zones/db.10.0.8";
    allow-transfer { 10.0.8.50; };
    also-notify { 10.0.8.50; };
};
```

### Шаг 3. Увеличение Serial в обеих зонах

Конфигурация изменилась — зафиксируйте новую версию зоны (например, `2026082100` → `2026082102`) в файлах `db.example.com` и `db.10.0.8`.

### Шаг 4. Валидация и перезапуск

```bash
sudo named-checkconf
sudo named-checkzone example.com /etc/bind/zones/db.example.com
# → zone example.com/IN: loaded serial 2026082102; OK
sudo named-checkzone 8.0.10.in-addr.arpa /etc/bind/zones/db.10.0.8
# → OK, serial 2026082102

sudo systemctl restart bind9
systemctl status bind9 --no-pager   # → active (running)

dig @127.0.0.1 example.com SOA +short
# → ... 2026082102 ...
```

Клиентам ничего менять не нужно: у них прописаны оба адреса, и теперь авторитативно отвечает второй.

### Автоматический failover (скрипт)

Для сред, где допустима минимальная автоматизация, можно реализовать автоматическое повышение Slave при недоступном Master. Скрипт выполняется на Slave (ns2) через cron каждую минуту:

```bash
#!/bin/bash
# /usr/local/bin/bind-auto-failover.sh
MASTER=10.0.8.50
SLAVE=10.0.8.51
ZONES=("example.com" "8.0.10.in-addr.arpa")
CURRENT_TYPE=$(grep -h 'type master' /etc/bind/named.conf.local 2>/dev/null | wc -l)

# Если уже мастер — выходим
if [ "$CURRENT_TYPE" -gt 0 ]; then
    exit 0
fi

# Проверка доступности мастера (2 попытки, таймаут 2 секунды)
if ! ping -c 2 -W 2 $MASTER > /dev/null 2>&1; then
    # Дополнительная проверка: порт 53/TCP
    if ! nc -z -w 2 $MASTER 53 > /dev/null 2>&1; then
        echo "$(date): Master unreachable, promoting self to master"
        # Шаг 1: каталог зон
        sudo mkdir -p /etc/bind/zones
        # Шаг 2: копирование зон из кэша
        for zone in "${ZONES[@]}"; do
            file=$(echo $zone | sed 's/\./\\./g' | sed 's/^/db./')
            if [ -f "/var/cache/bind/$file" ]; then
                sudo cp "/var/cache/bind/$file" "/etc/bind/zones/"
                sudo chown root:bind "/etc/bind/zones/$file"
                sudo chmod 640 "/etc/bind/zones/$file"
            fi
        done
        # Шаг 3: смена типа зон на master
        sudo tee /etc/bind/named.conf.local > /dev/null <<'EOF'
zone "example.com" {
    type master;
    file "/etc/bind/zones/db.example.com";
    allow-transfer { 10.0.8.50; };
    also-notify { 10.0.8.50; };
};

zone "8.0.10.in-addr.arpa" {
    type master;
    file "/etc/bind/zones/db.10.0.8";
    allow-transfer { 10.0.8.50; };
    also-notify { 10.0.8.50; };
};
EOF
        # Шаг 4: увеличение Serial (опционально: +1 в каждом файле)
        # ...
        # Шаг 5: перезапуск
        sudo named-checkconf && sudo systemctl restart bind9
        echo "$(date): Promotion complete, now master"
    fi
fi
```

Добавление в cron:

```bash
* * * * * root /usr/local/bin/bind-auto-failover.sh > /var/log/bind-failover.log 2>&1
```

**Предупреждение:** автоматический failover увеличивает риск split-brain. Используйте только при отсутствии альтернатив и настройте `notify`/`allow-notify` строго по IP.

---

## Восстановление старого мастера и обмен ролями

После ремонта прежнего мастера (`ns1`) **рекомендуется не возвращать роли обратно, а закрепить новые**: `ns2` остаётся мастером, восстановленный `ns1` переводится в Slave. Это исключает ситуацию «два мастера», когда администратор по привычке правит зоны на старом узле, и изменения не попадают в кластер.

### На новом мастере (ns2) ничего менять не нужно — `allow-transfer`/`also-notify` уже указывают на 10.0.8.50.

### На восстановленном узле (ns1)

Старые эталонные зоны больше не актуальны — уберите их в архив:

```bash
sudo mkdir -p /etc/bind/zones.old
sudo mv /etc/bind/zones/db.* /etc/bind/zones.old/
```

Переведите узел в роль Slave (файл `/etc/bind/named.conf.local`):

```conf
zone "example.com" {
    type slave;
    file "/var/cache/bind/db.example.com";
    primaries { 10.0.8.51; };       // новый мастер
    masterfile-format text;
    allow-notify { 10.0.8.51; };
};

zone "8.0.10.in-addr.arpa" {
    type slave;
    file "/var/cache/bind/db.10.0.8";
    primaries { 10.0.8.51; };
    masterfile-format text;
    allow-notify { 10.0.8.51; };
};
```

Применение и проверка:

```bash
sudo named-checkconf && sudo systemctl restart bind9
ls -l /var/cache/bind/
# → db.10.0.8, db.example.com — зоны скачаны с нового мастера

dig @10.0.8.50 example.com SOA +short | awk '{print $3}'
dig @10.0.8.51 example.com SOA +short | awk '{print $3}'
# → 2026082102 (одинаково на обоих узлах — кластер консистентен)
```

Клиенты продолжают работать без изменений: оба адреса в `resolv.conf` остаются валидными при любой комбинации ролей.

### Rolling restart без простоя

При обновлении BIND или изменении глобальных параметров (например, добавление нового ACL) перезапускайте узлы последовательно:

1. `sudo systemctl restart bind9` на Slave (ns2) — клиенты продолжают ходить на Master.
2. Проверка: `dig @10.0.8.51 example.com SOA +short` — Slave отвечает.
3. `sudo systemctl restart bind9` на Master (ns1) — Slave продолжает обслуживать клиенты во время перезапуска.
4. Проверка: `dig @10.0.8.50 example.com SOA +short`.

Общая downtime = 0, если рестарты выполняются последовательно, а не одновременно.

### Предотвращение split-brain

Split-brain возникает, когда оба узла считают себя мастерами и принимают независимые правки. Меры предотвращения:

- **Никогда не редактируйте файлы зон на Slave** — они перезаписываются трансфером.
- **Фиксируйте роль в конфиге:** добавьте комментарий `// ROLE: SLAVE` или `// ROLE: MASTER` в начало `named.conf.local`.
- **Ограничьте доступ к конфигам:** толькоroot может править `/etc/bind/named.conf.local`.
- **Мониторинг Serial:** если Serial на Slave больше, чем на Master, — это признак двойного мастерства. Немедленно исправьте.
- **TSIG для NOTIFY:** без ключа Slave игнорирует чужой NOTIFY, но Master продолжает слать. Консистентность полагается на административный контроль.

---

## Типовые неисправности

| Симптом | Причина | Диагностика и решение |
| :--- | :--- | :--- |
| Файлы зон не появляются в `/var/cache/bind` на Slave | NOTIFY ещё не дошёл / службы стартовали вразнобой | Подождать Refresh или `systemctl restart bind9` на обоих узлах; проверить `journalctl -u bind9 \| grep -i transfer` |
| `transfer of '...' failed: connection refused/time out` | Закрыт TCP/53 между узлами | Трансфер всегда идёт по TCP — проверить firewall (см. раздел подготовки) |
| `dumping master file ... permission denied` | Нет прав на запись в каталог файла Slave-зоны | `chown bind:bind /var/cache/bind`; проверить профиль AppArmor (`/etc/apparmor.d/usr.sbin.named`) |
| Slave не видит изменения после правки зоны | Не увеличен Serial на мастере | Сравнить `dig ... SOA +short` на обоих узлах; увеличить Serial, `rndc reload` |
| Клиент получает `REFUSED` | Источник вне ACL `trusted` | Добавить подсеть клиента в ACL в `named.conf.options` |
| Ответы приходят с задержкой после отказа одного узла | Таймаут ожидания первого nameserver | Нормальное поведение; убедиться, что второй адрес прописан в `resolv.conf` |
| Зона перестала отвечать на Slave спустя время | Истёк таймер Expire при недоступном мастере | Выполнить процедуру повышения Slave до Master или восстановить мастера |

Общая диагностика BIND: [Диагностика и troubleshooting](./troubleshooting.md).

---

## Лучшие практики и откат изменений

- **Защищайте трансфер ключами TSIG** — ограничение по IP надёжно дополняется криптографической аутентификацией: [DNS-безопасность](../../../../Networking/Protocols/DNS/dns_security.md).
- **Никогда не редактируйте файлы зон на Slave** — они перезаписываются при следующем трансфере.
- **Более двух узлов:** добавление второго Slave — та же конфигурация `type slave` плюс его IP в `allow-transfer`/`also-notify` мастера.
- **Контроль консистентности:** периодически сравнивайте Serial всех узлов мониторингом (`dig @узел zone SOA +short`).
- **Откат настроек:** восстановите каталог из резервной копии и перезапустите службу:
  ```bash
  sudo systemctl stop bind9
  sudo rm -rf /etc/bind && sudo cp -a /etc/bind.backup.2026-08-21 /etc/bind
  sudo systemctl start bind9
  ```
- **Разделяйте роли для отказоустойчивости:** держите Master и Slave в разных rack/блоке питания. Одинаковая подсеть допустима, но единая точка отказа в инфраструктуре (свитч, шлюз) всё равно снижает доступность.
- **Тестируйте отказ:** периодически отключайте Master и проверяйте, что Slave отвечает и клиенты переключаются. Автоматизируйте это через мониторинг.
- **Журналирование:** включите `querylog` на обоих узлах при расследовании инцидентов: `rndc querylog on` (не оставляйте включённым постоянно — логи растут быстро).
- **Размер зон и ресурсы:** для зон >100K записей увеличьте `max-journal-size` на Master (например, `max-journal-size "500M";`) и используйте SSD для `/var/cache/bind` на Slave — частые IXFR создают нагрузку на диск.
- **Резервное копирование Slave:** хотя Slave получает зону с Master, бэкап `/var/cache/bind` ускоряет восстановление — не нужно ждать AXFR.
- **Кадровый резерв:** имейте второго администратора, знакомого с процедурой промоушена. Failover в 3 часа ночи — не лучшее время для изучения документации.

### Контейнеризация BIND в кластере

BIND можно запускать в Docker/Podman для изоляции и упрощения развертывания. Пример `docker-compose.yml` для двухузлового кластера (запускается на каждом узле локально, не как cloud-сервис):

```yaml
services:
  bind:
    image: internetsystemsconsortium/bind9:9.18
    container_name: bind-master
    restart: unless-stopped
    ports:
      - "53:53/tcp"
      - "53:53/udp"
    volumes:
      - /etc/bind:/etc/bind
      - /var/cache/bind:/var/cache/bind
    cap_add:
      - NET_ADMIN  # для привязки к порту 53
    environment:
      - TZ=UTC
    command: ["-g"]  # foreground для systemd/docker
```

На Slave — тот же манифест, но с переменной окружения `ROLE=slave` и перемонтированием томов. Ключевые моменты:

- Тома `/etc/bind` и `/var/cache/bind` монтируются из хоста — это позволяет использовать привычные пути и инструменты (`named-checkconf`, `rndc`).
- `restart: unless-stopped` обеспечивает автозапуск после перезагрузки хоста.
- Для связи между контейнерами используйте пользовательскую сеть Docker (`--network bind-cluster`), а не `host` — это упрощает firewall и мониторинг.
- На хосте должны быть открыты порты `53/tcp` и `53/udp`; внутри контейнера BIND слушает на всех интерфейсах.

### IPv6 dual-stack в HA

Если инфраструктура использует IPv6, добавьте в `named.conf.options` на обоих узлах:

```conf
listen-on-v6 { any; };
allow-transfer { localhost; dns-cluster; ::1; 2001:db8::10; 2001:db8::11; };
allow-notify { dns-cluster; ::1; 2001:db8::10; 2001:db8::11; };
```

Клиенты с IPv6 будут обращаться к серверам по AAAA-записям NS. Убедитесь, что:

- Firewall разрешает `53/udp` и `53/tcp` для IPv6-подсети.
- Обратная зона для IPv6 (`ip6.arpa`) настроена аналогично IPv4.
- SLAAC/DHCPv6 раздаёт клиентам оба IPv6-адреса серверов в `resolv.conf` или через RA.

---

## Дополнительная информация

*   **Версии:** сценарий проверен на BIND 9.18+ (LTS) на базе Debian/Astra Linux; для RHEL-семейства меняются имена пакетов и службы (`bind`, `named`).
*   **Спецификации:** RFC 1995 (IXFR), RFC 1996 (NOTIFY), RFC 8945 (TSIG).

**Связанные разделы:**

*   [Первичный сервер (Master)](./master_server_local_zone.md) — детальная работа с SOA, glue-записями и типами записей.
*   [Вторичный сервер (Slave)](./slave_server_configuration.md) — теория зонных передач и TSIG.
*   [Обратная зона](./reverse_zone_configuration.md) — форматы in-addr.arpa/ip6.arpa и RFC 2317.
*   [Продвинутые возможности](./advanced_topics.md) — Views, RPZ, CatZ, статистический канал.
*   [Диагностика BIND](./troubleshooting.md) — методы отладки кластера и диагностика трансферов.
*   [Обзор BIND](./overview.md) — архитектура, AXFR/IXFR, роли серверов.
