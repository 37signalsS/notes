# Порядок разрешения имён в Linux: диагностика

## Определения

**NSS (Name Service Switch)** — механизм библиотек Си (glibc, musl), определяющий источники данных и последовательность их опроса для разрешения системных сущностей (хосты, пользователи, группы). Конфигурируется в файле `/etc/nsswitch.conf`.

**Системный резолвер** — компонент библиотеки **glibc**, реализующий функции `getaddrinfo()` и `gethostbyname()`. Он выступает посредником между приложением и источниками данных (файлы, DNS, mDNS), следуя правилам NSS.

**NSS-модули** — динамические библиотеки (`libnss_*.so.2`), реализующие логику опроса конкретного источника (например, `libnss_files` для `/etc/hosts` или `libnss_resolve` для `systemd-resolved`).

**`getaddrinfo()`** — современная потокобезопасная функция разрешения имён, поддерживающая IPv4/IPv6 и возвращающая список адресов с приоритетами (RFC 6724). Рекомендуется для всех новых приложений.

**`gethostbyname()`** — устаревшая функция разрешения имён (только IPv4, не потокобезопасная). Сохраняется в некоторых legacy-приложениях и обёртках.

**Stub-резолвер** — локальная служба, принимающая DNS-запросы от приложений и пересылающая их upstream-серверам. В современных системах — `systemd-resolved` на `127.0.0.53:53`.

**LLMNR (Link-Local Multicast Name Resolution)** — протокол Microsoft для разрешения имён в локальном сегменте сети без DNS-сервера (multicast 224.0.0.252, UDP 5355). В Linux реализован в `systemd-resolved`; может создавать конфликты с mDNS.

**DNS64 (RFC 6147)** — механизм синтеза AAAA-записей из A-записей на рекурсивном резолвере при отсутствии原生 AAAA. В паре с NAT64 позволяет IPv6-only клиентам обращаться к IPv4-ресурсам.

## Базовые концепции

### Логика работы /etc/nsswitch.conf

Строка `hosts:` в этом файле является списком источников с возможными условиями перехода.
Пример: `hosts: files [NOTFOUND=return] dns`

#### Статусы ответа источника:
- **SUCCESS**: Имя найдено, результат возвращен приложению.
- **NOTFOUND**: Источник опрошен, но имя не найдено.
- **UNAVAIL**: Источник недоступен (например, служба выключена или файл отсутствует).
- **TRYAGAIN**: Временная ошибка (например, таймаут).

#### Действия (Actions):
- **return**: Немедленно вернуть результат (или ошибку) приложению.
- **continue**: Перейти к следующему источнику в списке.

**Важно:** По умолчанию при статусе `SUCCESS` выполняется `return`, во всех остальных случаях — `continue`.

### Модули разрешения имен

| Модуль | Описание |
| :--- | :--- |
| **files** | Опрос локального файла `/etc/hosts`. |
| **myhostname** | Встроенное разрешение имени `localhost` и текущего `hostname`. Предотвращает ошибки, если хост не прописан в `/etc/hosts`. |
| **resolve** | Передача запроса в `systemd-resolved` через D-Bus. Рекомендуемый модуль для современных систем. |
| **dns** | Классический опрос DNS-серверов из `/etc/resolv.conf`. |
| **mdns_minimal** | Разрешение имен `.local` через mDNS (Avahi). |

### Механизм загрузки NSS-модулей

При запуске приложения glibc загружает `libnss_*.so.2` через `dlopen()` в порядке, указанном в `nsswitch.conf`. Кэширует дескрипторы библиотек внутри процесса, поэтому изменение файлов NSS на лету не влияет на уже запущенные приложения — требуется их перезапуск.

### Поведение системного резолвера: glibc против musl

| Аспект | Glibc | Musl (Alpine) |
| :--- | :--- | :--- |
| **NSS** | Поддерживается (`/etc/nsswitch.conf`) | Не поддерживается (игнорируется) |
| **Порядок запросов** | Последовательный (A, затем AAAA) | Параллельный (A и AAAA одновременно) |
| **Поддержка `rotate`** | Да | Нет |
| **Максимум nameserver** | 3 | Ограничен |
| **Обработка таймаутов** | 5 секунд по умолчанию на сервер | Параллельная отправка, первый ответ побеждает |

### Stub-резолвер: systemd-resolved

`systemd-resolved` принимает запросы на `127.0.0.53:53`, кэширует ответы и пересылает их upstream-серверам через UDP/TCP, DoT или DoH. Взаимодействие с NSS-модулем `resolve` происходит через D-Bus, что позволяет `getent` возвращать кэшированные данные без сетевых запросов.

### DNS64/NAT64 и локальное разрешение

При включенном DNS64 рекурсивный резолвер синтезирует AAAA-записи (префикс `64:ff9b::/96`) для доменов, имеющих только A-записи. Для приложения процесс прозрачен: `getaddrinfo()` возвращает синтезированный IPv6-адрес, который маршрутизируется через NAT64-шлюз. Диагностика: `dig AAAA ipv4only.arpa` — ожидается синтезированный адрес, если DNS64 активен.

### Выбор адреса (gai.conf и RFC 6724)

Функция `getaddrinfo()` сортирует возвращаемые адреса по правилам RFC 6724. Файл `/etc/gai.conf` позволяет переопределить приоритеты:
- `precedence ::ffff:0:0/96 100` — IPv4 over IPv6
- `label 2001:db8::/32 10` — кастомные метки для политик

### Happy Eyeballs (RFC 8305)

При наличии как A, так и AAAA записей glibc параллельно отправляет запросы на оба адреса (с задержкой 50–250 мс для IPv6) и использует первый установившийся TCP-соединение. В musl параллелизм реализован на уровне DNS-запросов, что может создавать дополнительную нагрузку.

### Диагностические уровни

| Уровень | Объект проверки | Ключевые файлы/инструменты |
| :--- | :--- | :--- |
| **Приложение** | Вызов `getaddrinfo()` или `gethostbyname()` | `strace -e trace=network,openat` |
| **NSS** | Чтение `nsswitch.conf`, загрузка `libnss_*.so.2` | `/etc/nsswitch.conf`, `ldd`, `strace` |
| **Локальный кэш** | `systemd-resolved`, `nscd` | `resolvectl statistics`, `nscd -g` |
| **Транспорт** | Отправка пакетов DNS (UDP/TCP 53), D-Bus | `tcpdump port 53`, `resolvectl query` |
| **Upstream** | Рекурсивные/авторитетные DNS-серверы | `dig +trace`, `dig @<server>` |

## Практические сценарии

### Сценарий 1: Глубокая проверка через getent ahosts

В отличие от `getent hosts`, команда `ahosts` показывает все адреса (IPv4 и IPv6) и учитывает настройки приоритетов из `/etc/gai.conf`.

```bash
getent ahosts google.com
# → 142.250.185.110 STREAM google.com
# → 142.250.185.110 DGRAM
# → 2a00:1450:4010:c0f::66 STREAM google.com
```

### Сценарий 2: Трассировка системных вызовов (strace)

Если вы подозреваете, что приложение игнорирует `nsswitch.conf` или читает не тот файл, используйте `strace`.

```bash
# Проверка, какие библиотеки NSS подгружает процесс
strace -e open,openat getent hosts example.com 2>&1 | grep libnss

# Проверка, читает ли приложение /etc/hosts напрямую
strace -e open,openat curl -s http://example.com 2>&1 | grep hosts
```

### Сценарий 3: Диагностика "зависшего" резолвинга (Таймауты)

Если разрешение имен занимает ровно 5 или 10 секунд, проблема часто кроется в попытке опроса нерабочего модуля.

**Чек-лист:**
1.  Проверьте наличие модуля `mdns` или `mdns_minimal` в `nsswitch.conf` при отсутствии запущенной службы `avahi-daemon`.
2.  Проверьте работоспособность `systemd-resolved`, если указан модуль `resolve`.
3.  Убедитесь, что после `mdns_minimal` стоит условие `[NOTFOUND=return]`, чтобы обычные запросы не уходили в мультикаст.

### Сценарий 4: Очистка кэша на разных уровнях

В Linux кэширование может происходить в нескольких местах:

```bash
# 1. systemd-resolved (самый частый случай)
resolvectl flush-caches

# 2. [nscd (Name Service Cache Daemon)](../../../Linux/Networking/Services/nscd.md) — если установлен
sudo nscd -i hosts

# 3. Браузеры (Chrome/Firefox)
# Введите в адресной строке: chrome://net-internals/#dns
```

### Сценарий 5: Специфика Alpine Linux (musl)

Библиотека `musl` **не поддерживает NSS**. В Alpine Linux:
- `/etc/nsswitch.conf` игнорируется.
- `/etc/hosts` проверяется всегда перед DNS.
- Порядок опроса серверов в `resolv.conf` может быть параллельным.

**Диагностика в Alpine:**
Используйте `getent hosts` (реализован как обертка), но помните, что он не отражает логику NSS.

### Сценарий 6: Верификация источника разрешения (NSS)

Когда `getent hosts` и `dig` возвращают разные результаты, проблема в NSS или `/etc/hosts`. Чтобы понять, какой модуль сработал:

```bash
# 1. strace показывает, какие libnss-библиотеки загружены
strace -e open,openat getent hosts example.com 2>&1 | grep libnss

# 2. Проверка, читает ли приложение /etc/hosts напрямую
strace -e open,openat curl -s http://example.com 2>&1 | grep hosts

# 3. Изоляция: временно переименовать /etc/hosts и проверить
sudo mv /etc/hosts /etc/hosts.bak
getent hosts example.com
sudo mv /etc/hosts.bak /etc/hosts
```

**Интерпретация:** Если после удаления `/etc/hosts` результат изменился — источником был файл. Если `dig @8.8.8.8 example.com` и `getent hosts example.com` совпадают, а `getent` без `/etc/hosts` не работает — проблема в DNS/NSS-цепочке.

### Сценарий 7: Взаимодействие nscd и systemd-resolved

Оба сервиса кэшируют результаты NSS. Если `resolvectl flush-caches` не помогает, а `getent` возвращает устаревший IP — проверьте `nscd`:

```bash
# 1. Проверка статуса nscd
systemctl status nscd

# 2. Просмотр статистики кэша
sudo nscd -g

# 3. Очистка кэша хостов
sudo nscd -i hosts

# 4. Перезапуск nscd (если кэш corrupted)
sudo systemctl restart nscd
```

**Важно:** `nscd` кэширует на уровне NSS и может игнорировать TTL DNS. В современных системах предпочтительнее `systemd-resolved` без `nscd`.

### Сценарий 8: Разрешение имен в chroot/jail

В изолированных окружениях (chroot, jail) может отсутствовать `/etc/resolv.conf`, `/etc/nsswitch.conf` или NSS-модули. Диагностика:

```bash
# 1. Проверка наличия конфигурационных файлов внутри chroot
sudo chroot /path/to/chroot ls -la /etc/resolv.conf /etc/nsswitch.conf /etc/hosts

# 2. Проверка resolv.conf
sudo chroot /path/to/chroot cat /etc/resolv.conf

# 3. Проверка NSS-модулей
sudo chroot /path/to/chroot ls -la /lib/x86_64-linux-gnu/libnss_*.so.2

# 4. Тест разрешения изнутри chroot
sudo chroot /path/to/chroot getent hosts example.com
```

**Решение:** Скопируйте или смонтируйте необходимые файлы:
```bash
sudo mount --bind /etc/resolv.conf /path/to/chroot/etc/resolv.conf
sudo mount --bind /etc/nsswitch.conf /path/to/chroot/etc/nsswitch.conf
```

### Сценарий 9: Обратное разрешение (PTR) в практике sysadmin

Обратное разрешение (IP → имя) используется в SSH, SMTP, логах. Отличие от прямого: PTR-записи управляются владельцем IP-подсети, а не вашим DNS-администратором.

```bash
# 1. Быстрая проверка
host 93.184.216.34
# → 93.184.216.34.in-addr.arpa domain name pointer example.com.

# 2. Детальная проверка через dig
dig -x 93.184.216.34
dig 34.216.184.93.in-addr.arpa PTR +short

# 3. Проверка через NSS (как видит система)
getent hosts 93.184.216.34
# Если PTR не настроен — вернет только IP

# 4. Проверка в SSH-логах (бanner)
ssh -v user@192.0.2.1 2>&1 | grep "Ping"
# → peer IP 192.0.2.1, resolved to myhost.example.com

# 5. SMTP-проверка (PTR обязателен для многих почтовых серверов)
dig -x 192.0.2.1 PTR +short
```

**Типичная проблема:** PTR-запись указывает на `host.example.com`, но обратное разрешение возвращает `host`. Разница в суффиксе поиска (`search`) может вызывать ошибки валидации в почтовых системах.

### Сценарий 10: DNS при миграции ОС

После обновления ОС (например, Ubuntu 22.04 → 24.04) `systemd-resolved` может изменить способ управления DNS, что ломает legacy-сервисы.

```bash
# 1. Проверка версии systemd-resolved
systemd-resolve --version
resolvectl --version

# 2. Проверка конфигурации
cat /etc/systemd/resolved.conf
# Обратите внимание на DNSStubListener, DNSOverTLS, LLMNR

# 3. Проверка symlink resolv.conf
ls -l /etc/resolv.conf
# Может измениться с stub-resolv.conf на resolv.conf

# 4. Проверка NetworkManager
grep '^dns=' /etc/NetworkManager/NetworkManager.conf

# 5. Верификация: getent и dig
getent hosts example.com
dig @127.0.0.53 example.com +short
dig @8.8.8.8 example.com +short
```

**Типичные проблемы после миграции:**
- `systemd-resolved` по умолчанию включает LLMNR, что создает лишний multicast-трафик.
- `DNSStubListener` может быть отключен, и `resolv.conf` нужно перенастроить.
- `NetworkManager` переключается с `dns=default` на `dns=systemd-resolved`, ломая старые конфигурации.

### Сценарий 11: Валидация синтаксиса /etc/hosts

Ошибки вручную добавленных записей — частая причина неверного разрешения:

```bash
# 1. Проверка синтаксиса: строки не должны начинаться с пробела
cat -A /etc/hosts | grep -E '^[^#]'
# ^I = tab (допустимо), пробел в начале = ошибка

# 2. Проверка FQDN с точкой (предотвращает добавление search domain)
grep -E 'db\.internal\.local$' /etc/hosts
# → db.internal.local. (точка в конце — правильно)
# → db.internal.local (без точки — при наличии search домена раскроется неверно)

# 3. Проверка дубликатов IP
awk '{print $1}' /etc/hosts | sort | uniq -d
# → 10.0.1.50 (если повторяется — возможно, ошибка)

# 4. Проверка резолвинга через NSS
getent hosts db.internal.local
```

## Дополнительная информация

- [DNS-клиент в Linux: концепции](../../../Linux/Networking/Concepts/dns_client.md) — детальная архитектура glibc и резолвера.
- [Конфигурация DNS-клиента](./configuration.md) — файлы `resolv.conf` и `nsswitch.conf`.
- [Обзор диагностики DNS](./overview.md) — общие принципы и уровни проверки.
- [Диагностика IPv6 и DNS64](../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md) — влияние `/etc/gai.conf`, NAT64/DNS64 и Dual Stack на разрешение имён.
- [Производительность DNS](./dns_resolution_performance.md) — измерение задержек в цепочке разрешения.
