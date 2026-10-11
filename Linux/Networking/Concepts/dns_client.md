# DNS-клиент в Linux: конфигурация и принципы работы

## Определения

**DNS-клиент (Domain Name System — система доменных имен)** — системный компонент или прикладное ПО, ответственное за преобразование доменных имен в IP-адреса и обратно. В Linux этот процесс реализуется через библиотеки системного уровня (glibc/musl) и специализированные службы (systemd-resolved, nscd).

**Системный резолвер (glibc resolver)** — набор функций в стандартной библиотеке C (GNU C Library), которые приложения вызывают для разрешения имен (преимущественно `getaddrinfo`). Его поведение определяется конфигурационными файлами NSS и параметрами резолвера.

**NSS (Name Service Switch — переключатель служб имен)** — модульный механизм, позволяющий выбирать источники данных для системных баз. Для имен хостов источники настраиваются в `/etc/nsswitch.conf` (строка `hosts:`).

**Stub-резолвер (заглушка)** — локальная служба (обычно `systemd-resolved` на `127.0.0.53`), которая принимает запросы от приложений и пересылает их внешним (upstream) серверам. Обеспечивает кэширование, валидацию DNSSEC и поддержку шифрованных протоколов.

**FQDN (Fully Qualified Domain Name — полностью определенное доменное имя)** — имя хоста, включающее все уровни иерархии DNS и заканчивающееся точкой (например, `example.com.`). Точка указывает на корень иерархии и предотвращает применение суффиксов поиска (`search`).

## Основные концепции

### Многоуровневая цепочка разрешения имени

Процесс разрешения имени в Linux не ограничивается только DNS-запросами и следует строгому алгоритму:

1.  **Прикладной уровень:** Приложение вызывает `getaddrinfo()`.
    *   **Glibc:** Использует NSS для определения источников.
    *   **Musl (Alpine):** Игнорирует NSS, читает `/etc/resolv.conf` напрямую (параллельные запросы IPv4/IPv6).
    *   **Go/Java:** Могут иметь собственные реализации резолверов (например, нативный Go-резолвер игнорирует `/etc/hosts` при определенных условиях).
2.  **Уровень NSS (`/etc/nsswitch.conf`):** Опрашиваются модули в порядке их перечисления:
    *   `files` → Читает `/etc/hosts`.
    *   `resolve` → Направляет запрос в `systemd-resolved` через D-Bus API (рекомендуется для современных систем).
    *   `dns` → Читает `/etc/resolv.conf` и выполняет классические UDP/TCP запросы.
    *   `myhostname` → Гарантирует разрешение локального имени хоста.
3.  **Уровень резолвера (`/etc/resolv.conf`):** Определяет параметры связи с DNS-серверами.

### Ключевые конфигурационные файлы

| Файл | Роль и влияние |
| :--- | :--- |
| `/etc/nsswitch.conf` | Стратегия поиска. Ошибки здесь могут сделать DNS недоступным, даже если сервера пингуются. |
| `/etc/hosts` | Статическое переопределение. Полезно для локальной разработки и блокировки рекламы. |
| `/etc/resolv.conf` | Транспортный слой. В современных ОС — симлинк на файлы `systemd-resolved`. |
| `/etc/gai.conf` | Настройка приоритетов `getaddrinfo`. Позволяет, например, предпочитать IPv4 над IPv6. |
| `/etc/systemd/resolved.conf` | Глобальные настройки кэширования, DoT, DoH и DNSSEC. |

### Параметры /etc/resolv.conf

Классический текстовый файл, который читают традиционные резолверы. В современных ОС часто является символической ссылкой:

| Директива | Назначение |
| :--- | :--- |
| `nameserver` | IP-адрес DNS-сервера. До 3 штук. Первый — основной. |
| `domain` | Локальный домен поиска (устаревает в favor `search`). |
| `search` | Список доменов, добавляемых к неполным именам. |
| `options timeout:N` | Время ожидания ответа (по умолчанию 5 секунд). |
| `options attempts:N` | Количество попыток на каждый сервер (по умолчанию 2). |
| `options rotate` | Циклическое распределение запросов между всеми nameserver. |
| `options ndots:N` | Количество точек, при котором имя считается абсолютным (FQDN). |
| `options single-request-reopen` | Переоткрытие сокета для каждого запроса при параллельных A/AAAA запросах (только glibc; musl/Alpine игнорирует опцию). |
| `options single-request` | Отправлять A и AAAA запросы последовательно, а не параллельно. |
| `options use-vc` | Принудительное использование TCP для всех запросов (устраняет проблемы с UDP-фрагментацией). |
| `options trust-ad` | Доверять флагу аутентичности DNSSEC от резолвера. |

### Механизмы кэширования и производительности

Для снижения нагрузки на сеть и уменьшения задержек используются два основных подхода:

*   **systemd-resolved:** Современный стандарт. Поддерживает Split DNS (разные сервера для разных интерфейсов/VPN) и кэширование с учетом TTL.
*   **[nscd (Name Service Cache Daemon)](../Services/nscd.md):** Устаревший (Legacy) демон кэширования. В современных дистрибутивах заменён на `systemd-resolved` и `sssd`. **Внимание:** часто становится причиной отдачи старых данных из-за игнорирования DNS TTL и отсутствия поддержки современных протоколов.

## Предусловия

Для работы с DNS-клиентом на Linux необходимы следующие инструменты:

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y dnsutils bind-utils

# RHEL/CentOS/Rocky/AlmaLinux
sudo dnf install -y bind-utils

# Alpine Linux
apk add bind-utils

# Проверка наличия утилит
dig -v
# → DiG 9.18.18-0ubuntu0.22.04.2-Ubuntu

resolvectl --version
# → systemd 252 (252.3-1)

getent hosts example.com
# → 93.184.216.34    example.com
```

## Конфигурация systemd-resolved

### Глобальные параметры /etc/systemd/resolved.conf

```ini
[Resolve]
# Upstream DNS-серверы (можно указать несколько)
DNS=1.1.1.1 8.8.8.8 2606:4700:4700::1111

# DNS over TLS (DoT)
DNSOverTLS=yes

# DNS over QUIC (DoQ) — поддержка в современных реализациях (v255+)
# DNS=quic://dns.adguard-dns.com

# Валидация DNSSEC
DNSSEC=yes

# Локальный домен поиска (по умолчанию)
Domains=~corp.internal ~.

# Разрешить LLMNR (Link-Local Multicast Name Resolution)
LLMNR=yes

# Разрешить mDNS (multicast DNS)
MulticastDNS=yes

# Статус заглушки на 127.0.0.53
# yes — заглушка активна (по умолчанию)
# no — заглушка отключена, resolv.conf должен содержать реальные серверы
DNSStubListener=yes

# Кэширование
Cache=yes
CacheFromLocalhost=yes
```

### Применение конфигурации

```bash
# Проверка синтаксиса
sudo systemd-analyze cat-config systemd/resolved.conf

# Перезапуск службы
sudo systemctl restart systemd-resolved

# Проверка статуса
resolvectl status
# → Global
# →          Protocols: +LLMNR +mDNS -DNSOverTLS DNSSEC=no/unsupported
# → resolv.conf mode: stub
```

### Per-link конфигурация

```bash
# Назначение DNS-серверов конкретному интерфейсу
sudo resolvectl dns eth0 10.0.0.2 10.0.0.3
sudo resolvectl dns tun0 100.64.0.2

# Назначение доменов поиска интерфейсу
sudo resolvectl domain eth0 "~corp.internal"
sudo resolvectl domain tun0 "~corp.internal"

# Отключение DNS для интерфейса
sudo resolvectl revert eth0

# Просмотр текущей конфигурации
resolvectl status
```

## Практические сценарии

### 1. Диагностика через resolvectl и getent

Различайте системное разрешение и прямой опрос DNS:

```bash
# Что видит система (учитывает NSS и /etc/hosts)
getent ahosts google.com
# → 142.250.185.110 STREAM google.com
# → 2a00:1450:4010:c0f::66 STREAM google.com

# Что видит служба systemd-resolved (учитывает кэш)
resolvectl query google.com
# → google.com: 142.250.185.110
# → (cache miss)

# Прямой опрос сервера (игнорирует NSS и локальный кэш)
dig @8.8.8.8 google.com
```

### 2. Оптимизация параметров ndots и search

В контейнерных и высоконагруженных средах параметр `ndots` часто является причиной задержек:

*   **Проблема:** При `ndots:5` имя `google.com` (1 точка) будет последовательно дополняться всеми суффиксами из `search`, вызывая до 4-х лишних (и неудачных) запросов перед попыткой разрешения оригинала.
*   **Решение:** Установка `ndots:1` или использование FQDN (с точкой в конце) в конфигурациях приложений.

```bash
# Проверка текущих опций
grep options /etc/resolv.conf
# Ожидаемый вывод: options timeout:1 attempts:2 ndots:1

# Проверка в контейнере (Docker/Podman)
cat /etc/resolv.conf | grep -E 'nameserver|options|search'

# Проверка в Kubernetes
kubectl get pod <pod> -o jsonpath='{.spec.dnsConfig}'
```

### 3. Настройка шифрованного DNS (DoT/DoH/DoQ)

Стандартом безопасности является шифрование DNS-трафика (DoT/DoH/DoQ) для предотвращения MITM-атак.

```ini
# /etc/systemd/resolved.conf
[Resolve]
# DNS over TLS (DoT)
DNS=1.1.1.1#cloudflare-dns.com
DNSOverTLS=yes

# DNS over QUIC (DoQ) — поддержка в современных реализациях (v255+)
# DNS=quic://dns.adguard-dns.com

# DNS over HTTPS (DoH) — настраивается через внешний форвардер (например, nginx или cloudflared)
# Если используется cloudflared как локальный DoH-прокси:
# DNS=127.0.0.1#localhost
```

```bash
# Включение DoT после изменения конфигурации
sudo systemctl restart systemd-resolved

# Проверка статуса
resolvectl status | grep -A5 "DNS Servers"
# → DNS Servers: 1.1.1.1 (cloudflare-dns.com)

# Включение временного режима отладки
sudo resolvectl log-level debug
# После завершения: sudo resolvectl log-level info
```

### 4. Управление приоритетами IPv4/IPv6 через gai.conf

Если система пытается соединиться по IPv6 (который работает медленно или не настроен), можно изменить приоритет:

```bash
# /etc/gai.conf
# Предпочитать IPv4 над IPv6
precedence ::ffff:0:0/96  100

# Или отключить IPv6 для новых соединений
# precedence ::/0  40
```

### 5. Особенности Split DNS в многоинтерфейсных системах

`systemd-resolved` позволяет назначать DNS-сервера конкретным линкам (например, `eth0` и `tun0`).

*   **Route-only domains:** Если интерфейс имеет домен `~corp.internal`, запросы к нему пойдут только через этот интерфейс.
*   **Default route:** Интерфейс с доменом `~.` принимает все запросы, если нет более специфичного совпадения.

```bash
# Просмотр привязки доменов к интерфейсам
resolvectl domain
# → tun0: ~corp.internal (~corp.internal - тильда означает только поиск)
# → eth0: ~. (принимает все остальные запросы)

# Настройка статической привязки
sudo resolvectl domain eth0 "~."
sudo resolvectl dns eth0 8.8.8.8 8.8.4.4
```

### 6. Отключение systemd-resolved и переход на традиционный режим

В редких случаях (например, совместимость с старым ПО, требующим прямого доступа к `resolv.conf`) службу приходится отключать.

```bash
# 1. Отключаем и останавливаем службу
sudo systemctl disable --now systemd-resolved

# 2. Удаляем симлинк и создаем обычный файл
sudo rm /etc/resolv.conf
sudo tee /etc/resolv.conf <<EOF
nameserver 8.8.8.8
nameserver 1.1.1.1
options timeout:1 attempts:2 rotate
EOF

# 3. Верификация: getent должен работать
getent hosts google.com
# → 142.250.185.110    google.com

# 4. Проверка, что systemd-resolved не слушает 127.0.0.53
ss -ulnp | grep 53
# → Должен показать либо пустой результат, либо только dnsmasq/другой резолвер
```

**Обратное включение:**
```bash
sudo systemctl enable --now systemd-resolved
sudo rm /etc/resolv.conf
sudo ln -s /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
```

### 7. Локальные переопределения через /etc/hosts

Для sysadmin часто требуется обеспечить разрешение имен локальных служб без DNS:

```bash
# 1. Добавление записи
echo "10.0.1.50    db.internal.local" | sudo tee -a /etc/hosts

# 2. Проверка синтаксиса: строки не должны начинаться с пробела
cat -A /etc/hosts | grep -E '^[^#]'
# ^I = tab (допустимо), пробел в начале = ошибка

# 3. Проверка FQDN с точкой (предотвращает добавление search domain)
echo "10.0.1.50    db.internal.local." | sudo tee -a /etc/hosts

# 4. Проверка резолвинга через NSS
getent hosts db.internal.local
# → 10.0.1.50    db.internal.local

# 5. Проверка дубликатов IP
awk '{print $1}' /etc/hosts | sort | uniq -d
# → 10.0.1.50 (если повторяется — возможно, ошибка)
```

### 8. Запуск локального кэширующего резолвера (unbound)

Для снижения задержек и изоляции от внешних проблем можно запустить локальный кэширующий резолвер:

```bash
# Debian/Ubuntu
sudo apt install unbound

# RHEL/CentOS/Rocky
sudo dnf install unbound

# Настройка /etc/unbound/unbound.conf
sudo tee /etc/unbound/unbound.conf <<EOF
server:
    interface: 127.0.0.1
    port: 53
    do-ip4: yes
    do-ip6: no
    do-udp: yes
    do-tcp: yes
    access-control: 127.0.0.0/8 allow
    access-control: 0.0.0.0/0 refuse
    cache-max-ttl: 3600
    cache-min-ttl: 60
    num-threads: 2
    msg-cache-slabs: 4
    rrset-cache-slabs: 4
    infra-cache-slabs: 4
    key-cache-slabs: 4
EOF

# Запуск и добавление в systemd-resolved
sudo systemctl enable --now unbound
sudo resolvectl dns lo 127.0.0.1
sudo resolvectl domain lo "~."

# Проверка
dig @127.0.0.1 google.com +short
# → 142.250.185.110
```

### 9. Отладка резолвинга через strace

Если приложение игнорирует `nsswitch.conf` или читает не тот файл, используйте `strace`:

```bash
# Проверка, какие библиотеки NSS подгружает процесс
strace -e open,openat getent hosts example.com 2>&1 | grep libnss
# → openat(AT_FDCWD, "/lib/x86_64-linux-gnu/libnss_files.so.2", O_RDONLY|O_CLOEXEC) = 3

# Проверка, читает ли приложение /etc/hosts напрямую
strace -e open,openat curl -s http://example.com 2>&1 | grep hosts

# Изоляция: временно переименовать /etc/hosts и проверить
sudo mv /etc/hosts /etc/hosts.bak
getent hosts example.com
sudo mv /etc/hosts.bak /etc/hosts
```

### 10. DNS в chroot и jail окружениях

В изолированных окружениях может отсутствовать `/etc/resolv.conf`, `/etc/nsswitch.conf` или NSS-модули:

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

### 11. Предотвращение DNS-утечек при использовании VPN

На клиентской стороне VPN необходимо убедиться, что DNS-запросы не утекают за пределы туннеля:

```bash
# 1. Проверка DNS-серверов на VPN-интерфейсе
resolvectl status tun0
# → DNS Servers: 100.64.0.2 (должен быть VPN-сервер)

# 2. Настройка Split DNS для VPN-доменов
sudo resolvectl domain tun0 "~corp.internal"
sudo resolvectl dns tun0 100.64.0.2

# 3. Проверка, что запросы к внешним доменам не утекают
dig @100.64.0.2 google.com +short
# Должен вернуть IP или таймаут (в зависимости от конфигурации VPN)

# 4. Проверка через traceroute
traceroute -n 8.8.8.8
# Должен проходить через tun0, а не eth0
```

## Типичные ошибки и их решение

### DNS не работает после смены сети (VPN / новый интерфейс)

**Симптом:** После подключения VPN или изменения сетевого интерфейса DNS перестает работать.

**Диагностика:**
```bash
# 1. Проверьте, какой интерфейс активен
ip route get 8.8.8.8

# 2. Проверьте DNS-серверы на интерфейсе
resolvectl status

# 3. Проверьте search домены
grep search /etc/resolv.conf

# 4. Проверьте, не перезаписал ли NetworkManager настройки
nmcli device show eth0 | grep DNS
```

**Решение:** Если `systemd-resolved` не получил новые DNS от DHCP, перезапустите службу или настройте статические домены для интерфейса:
```bash
resolvectl domain eth0 '~corp.local'
resolvectl dns eth0 10.0.0.2
```

**Валидация:** `resolvectl query internal.corp.local` должен возвращаться через правильный интерфейс.

### DoT/DoH не работает после включения шифрования

**Симптом:** После включения DoT/DoH в `systemd-resolved`, все DNS-запросы завершаются таймаутом.

**Причины и решение:**
1.  **Блокировка порта 853** файрволом (для DoT).
2.  **Проблема с сертификатом** резолвера (для DoT).
3.  **Блокировка HTTPS** прокси (для DoH).

```bash
# 1. Проверка связности с DoT-сервером
openssl s_client -connect 1.1.1.1:853
# → Должен показать успешное TLS-соединение

# 2. Проверка логов systemd-resolved
journalctl -u systemd-resolved -n 50 | grep -i "tls\|error\|fail"

# 3. Проверка связности по HTTPS (для DoH)
curl -I https://dns.google/dns-query
# → HTTP/2 200
```

### DNS возвращает устаревшие данные

**Симптом:** `dig @8.8.8.8` возвращает свежий IP, а `getent` — старый.

**Диагностика:**
```bash
# 1. Проверка кэша systemd-resolved
resolvectl statistics
# → Cache Statistics: 1234 hits, 567 misses

# 2. Очистка кэша
resolvectl flush-caches

# 3. Проверка nscd (если установлен)
systemctl status nscd
sudo nscd -g
sudo nscd -i hosts
```

**Решение:** Если `nscd` установлен, отключите его или увеличьте TTL для hosts-базы в `/etc/nscd.conf`.

### Конфликт systemd-resolved и BIND/Unbound

**Симптом:** BIND/Unbound не может запуститься, так как порт 53 занят.

**Решение:**
```bash
# 1. Остановить и отключить systemd-resolved
sudo systemctl stop systemd-resolved
sudo systemctl disable systemd-resolved

# 2. Настроить /etc/resolv.conf на указание самого себя или внешних DNS
echo "nameserver 127.0.0.1" | sudo tee /etc/resolv.conf

# 3. Запустить BIND/Unbound
sudo systemctl start named
# ИЛИ
sudo systemctl start unbound
```

### DNS не разрешает локальные имена в /etc/hosts

**Симптом:** Имена из `/etc/hosts` игнорируются, `getent hosts` возвращает DNS-результат.

**Диагностика:**
```bash
# 1. Проверка порядка источников в nsswitch.conf
grep '^hosts:' /etc/nsswitch.conf
# → hosts: files dns

# 2. Проверка синтаксиса /etc/hosts
cat -A /etc/hosts | grep -E '^[^#]'
# Строки не должны начинаться с пробела

# 3. Проверка, загружен ли модуль files
ldd /lib/x86_64-linux-gnu/libnss_files.so.2
```

**Решение:** Убедитесь, что модуль `files` стоит перед `dns` в `nsswitch.conf`. Перезапустите приложение после изменения конфигурации.

## Лучшие практики и очистка

### Лучшие практики

*   **Используйте FQDN с точкой** при работе с DNS-инструментами (`dig`, `nslookup`), чтобы исключить влияние локальных суффиксов поиска.
*   **Проверяйте разрешение через `getent hosts`** вместо `dig` при диагностике приложений — `getent` учитывает NSS и `/etc/hosts`, как это делает само приложение.
*   **Очищайте кэш** при подозрении на устаревшие записи: `resolvectl flush-caches` (systemd-resolved), `sudo nscd -i hosts` (nscd).
*   **Не опускайте TTL ниже 60 секунд** без крайней необходимости — это создает экстремальную нагрузку на DNS-серверы.
*   **Для контейнерных сред:** используйте `ndots:1` и FQDN с точкой (`example.com.`) для внешних доменов, чтобы избежать задержек.
*   **В Alpine Linux (musl):** тюните поддерживаемые опции (`options timeout:2 attempts:1`); `single-request-reopen` musl не поддерживает — при «зависании» параллельных A/AAAA исправляйте IPv6 или используйте DNS-прокси.
*   **`getaddrinfo()` блокирует поток:** Стандартный glibc-резолвер является блокирующим. Для асинхронного резолвинга используйте `c-ares` (C/C++), `Go net.Resolver` (Go), или `dns` модуль (Node.js).
*   **glibc vs musl:** glibc учитывает `/etc/nsswitch.conf` и поддерживает NSS, musl (Alpine) игнорирует NSS и читает только `/etc/resolv.conf`. В Alpine-контейнерах `getent hosts` может не работать для кастомных NSS-источников.
*   **Не смешивайте nscd и systemd-resolved:** одновременный запуск приводит к двойному кэшированию и конфликтам.

### Очистка и откат изменений

```bash
# 1. Восстановление стандартного resolv.conf для systemd-resolved
sudo ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf

# 2. Очистка кэшей
resolvectl flush-caches
sudo nscd -i hosts 2>/dev/null || true

# 3. Откат /etc/systemd/resolved.conf
sudo cp /etc/systemd/resolved.conf.bak /etc/systemd/resolved.conf 2>/dev/null || true
sudo systemctl restart systemd-resolved

# 4. Откат /etc/gai.conf
sudo cp /etc/gai.conf.bak /etc/gai.conf 2>/dev/null || true

# 5. Проверка, что система разрешает имена
getent hosts google.com
dig google.com +short
```

### Резервное копирование конфигурации

```bash
# Создание бэкапа перед изменениями
sudo cp /etc/resolv.conf /etc/resolv.conf.bak.$(date +%Y%m%d)
sudo cp /etc/systemd/resolved.conf /etc/systemd/resolved.conf.bak.$(date +%Y%m%d)
sudo cp /etc/nsswitch.conf /etc/nsswitch.conf.bak.$(date +%Y%m%d)
sudo cp /etc/gai.conf /etc/gai.conf.bak.$(date +%Y%m%d)
```

## Крайние случаи

### musl (Alpine Linux) и параллельные запросы

Библиотека `musl` **не поддерживает NSS**. В Alpine Linux:
*   `/etc/nsswitch.conf` игнорируется.
*   `/etc/hosts` проверяется всегда перед DNS.
*   Порядок опроса серверов в `resolv.conf` может быть параллельным.

**Проблема:** Если один из DNS-серверов медленный, а второй быстрый, но не знает внутренних имен, запрос может завершиться ошибкой NXDOMAIN.

**Решение:** Добавьте `options timeout:2 attempts:1` в `/etc/resolv.conf` или настройте `dnsConfig` в Docker/Kubernetes (опция `single-request-reopen` musl не поддерживает; для glibc-образов она дополнительно переоткрывает сокет).

### DNS64/NAT64 и локальное разрешение

При включенном DNS64 рекурсивный резолвер синтезирует AAAA-записи (префикс `64:ff9b::/96`) для доменов, имеющих только A-записи. Для приложения процесс прозрачен: `getaddrinfo()` возвращает синтезированный IPv6-адрес, который маршрутизируется через NAT64-шлюз.

**Диагностика:**
```bash
# Проверка работы DNS64
dig AAAA ipv4only.arpa
# → Ожидается синтезированный адрес, если DNS64 активен
```

### DNS в контейнерах (Docker/Podman)

В контейнерах DNS может работать иначе из-за изоляции сетевого пространства имен:

```bash
# 1. Проверка текущих настроек резолвера в контейнере
docker exec <container_id> cat /etc/resolv.conf
# Ожидаемый результат для user-defined network: nameserver 127.0.0.11

# 2. Проверка разрешения через встроенный DNS Docker
docker exec <container_id> nslookup <target_container_name>
# → Server: 127.0.0.11, Address: 127.0.0.11#53

# 3. Явное указание DNS в docker run
docker run --dns 8.8.8.8 --dns 1.1.1.1 alpine cat /etc/resolv.conf

# 4. Проверка на хосте: убедитесь, что systemd-resolved не конфликтует с Docker
resolvectl status
ss -ulnp | grep ':53'
```

### Обратное разрешение (PTR) в практике sysadmin

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

# 4. Проверка в SSH-логах (banner)
ssh -v user@192.0.2.1 2>&1 | grep "Ping"
# → peer IP 192.0.2.1, resolved to myhost.example.com

# 5. SMTP-проверка (PTR обязателен для многих почтовых серверов)
dig -x 192.0.2.1 PTR +short
```

**Типичная проблема:** PTR-запись указывает на `host.example.com`, но обратное разрешение возвращает `host`. Разница в суффиксе поиска (`search`) может вызывать ошибки валидации в почтовых системах.

### Сосуществование нескольких активных VPN

При наличии нескольких VPN-туннелей с собственными DNS-серверами:

```bash
# 1. Проверка всех активных интерфейсов
ip -br link show up

# 2. Проверка DNS-серверов на каждом интерфейсе
resolvectl status | grep -A10 "Link"

# 3. Проверка маршрутов
ip route show
ip -6 route show

# 4. Проверка, что DNS-запросы идут через правильный интерфейс
sudo tcpdump -i any port 53 -nn -c 10
```

**Решение:** Явно назначьте домены для каждого интерфейса:
```bash
sudo resolvectl domain tun0 "~vpn-a.corp.local"
sudo resolvectl dns tun0 10.0.0.2
sudo resolvectl domain tun1 "~vpn-b.corp.local"
sudo resolvectl dns tun1 10.1.0.2
```

## Дополнительная информация

### Конфликты сетевых менеджеров

При использовании **NetworkManager** убедитесь в корректной интеграции с резолвером. В `/etc/NetworkManager/NetworkManager.conf` должно быть:
```ini
[main]
dns=systemd-resolved
```
Если вы хотите управлять DNS вручную, удалите симлинк `/etc/resolv.conf` и создайте обычный файл, предварительно отключив запись в него в настройках NM.

### Новые типы записей (SVCB и HTTPS)

Современные клиенты (браузеры, curl) при запросе `example.com` запрашивают также записи типа `HTTPS` или `SVCB`. Это позволяет DNS-серверу сразу сообщить параметры TLS, поддержку HTTP/3 (QUIC) и альтернативные порты, исключая лишние редиректы с HTTP на HTTPS.

### См. также
* [Протокол DNS](../../../Networking/Protocols/DNS/dns.md) — теория, типы записей и иерархия.
* [Диагностика DNS: Обзор](../../Diagnostics/Networking/dns/overview.md) — подробный разбор архитектуры и уровней диагностики.
* [Безопасность DNS](../../../Networking/Protocols/DNS/dns_security.md) — детали DNSSEC и защиты от атак.
* [Порядок разрешения имен](../../Diagnostics/Networking/dns/name_resolution.md) — детальный разбор цепочки разрешения и NSS.
* [Конфигурация DNS-клиента](../../Diagnostics/Networking/dns/configuration.md) — диагностика и проверка конфигурационных файлов.
* [Производительность DNS-резолвинга](../../Diagnostics/Networking/dns/dns_resolution_performance.md) — оптимизация задержек, conntrack race, ndots.
