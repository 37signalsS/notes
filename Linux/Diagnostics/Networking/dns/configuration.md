# Конфигурация DNS-клиента: диагностика и проверка

## Определения

**Конфигурация DNS-клиента** — иерархический набор настроек ОС, библиотек (glibc/musl) и системных служб, определяющий процесс преобразования доменных имен в IP-адреса.

**Системный резолвер** — программный интерфейс (API), через который приложения запрашивают данные у DNS. В Linux реализация резолвера встроена в системные библиотеки. Поведение резолвера динамически изменяется в зависимости от активных сетевых менеджеров и конфигурационных файлов. Теоретические основы представлены в разделе [DNS-клиент в Linux: концепции](../../../Networking/Concepts/dns_client.md).

## Базовые концепции

### Иерархия источников (NSS)

Разрешение имен в Linux начинается не с DNS, а с механизма **NSS (Name Service Switch)**. Файл `/etc/nsswitch.conf` определяет приоритеты:
1.  **files**: Локальный файл `/etc/hosts`.
2.  **resolve**: Служба `systemd-resolved`.
3.  **dns**: Традиционный опрос через `/etc/resolv.conf`.
4.  **myhostname**: Встроенный механизм разрешения локального имени хоста.

### Библиотеки реализации: glibc против musl

Поведение резолвера зависит от используемой библиотеки (актуально для контейнеров):
-   **glibc (Ubuntu, Debian, CentOS)**: Поддерживает все опции `resolv.conf`, выполняет запросы последовательно (по умолчанию), чувствителен к порядку в `nameserver`.
-   **musl (Alpine Linux)**: Выполняет запросы ко всем серверам **параллельно**, использует первый пришедший ответ. Не поддерживает некоторые опции (например, `rotate`) и имеет жесткие лимиты на количество серверов и доменов поиска.

### Управляющие службы

1.  **systemd-resolved**: Современный стандарт. Создает «заглушку» на `127.0.0.53`. Основной конфиг — `/etc/systemd/resolved.conf`.
2.  **NetworkManager**: Автоматизирует получение DNS по DHCP. Может работать в режимах:
    -   `default`: Пишет напрямую в `resolv.conf`.
    -   `systemd-resolved`: Передает данные службе через D-Bus.
    -   `none`: Не трогает настройки DNS (ручное управление).

### Файл /etc/resolv.conf: структура и опции

Классический текстовый файл, который читают традиционные резолверы. В современных ОС часто является символической ссылкой:
- `/run/systemd/resolve/stub-resolv.conf` — заглушка на `127.0.0.53` (systemd-resolved)
- `/run/NetworkManager/resolv.conf` — управляется NetworkManager
- `/run/resolvconf/resolv.conf` — управляется resolvconf

**Основные директивы:**
| Директива | Назначение |
| :--- | :--- |
| `nameserver` | IP-адрес DNS-сервера. До 3 штук. Первый — основной. |
| `domain` | Локальный домен поиска (устаревает в пользу `search`). |
| `search` | Список доменов, добавляемых к неполным именам. |
| `options timeout:N` | Время ожидания ответа (по умолчанию 5 секунд). |
| `options attempts:N` | Количество попыток на каждый сервер (по умолчанию 2). |
| `options rotate` | Циклическое распределение запросов между всеми nameserver. |
| `options ndots:N` | Количество точек, при котором имя считается абсолютным (FQDN). |

### DHCP и автоматическое получение DNS

При получении адреса по DHCP клиент получает от сервера опцию `domain-name-servers`. Инструменты:
- **dhclient** (Debian/Ubuntu/RHEL): пишет в `/etc/resolv.conf` или вызывает hook-скрипты.
- **systemd-networkd** (modern RHEL/Ubuntu Server): передает DNS в `systemd-resolved` или пишет в `resolv.conf` через `systemd-resolved.service`.
- **NetworkManager**: вызывает `dhclient` или внутренний DHCP-клиент, затем интегрирует результат с `resolv.conf` или `systemd-resolved`.

### Типичные ошибки конфигурации

| Ошибка | Причина | Влияние |
| :--- | :--- | :--- |
| `resolv.conf` — симлинк на systemd-resolved, но служба не запущена | Обновление или сбой | Все локальные запросы DNS падают с timeout |
| Указание `127.0.0.53` в `resolv.conf` без systemd-resolved | Неправильная миграция или ручное редактирование | DNS недоступен |
| Неверный порядок `nameserver` в `resolv.conf` | Ручная ошибка | Запросы идут на внутренний DNS, хотя нужен внешний |
| Отсутствие `options timeout:1` при медленном upstream | Стандартные 5 секунд на каждый сервер | Задержки в p99 до 10–15 секунд |
| `search` содержит слишком много доменов | Наследие больших корпоративных окружений | Каскад из 5–10 лишних запросов на каждое имя |

### Формат и применение /etc/hosts

Локальный файл имеет приоритет над DNS при стандартной конфигурации NSS (`hosts: files dns`).
```
# Поля: IP-адрес, каноническое_имя, псевдонимы
127.0.0.1       localhost.localdomain localhost
10.0.1.50       db.internal.local
```

**Правила:**
- IP и имя разделяются пробелами или табуляцией.
- Комментарии начинаются с `#`.
- Для имен с суффиксом поиска (search domain) используйте FQDN с точкой: `db.internal.local.` — это предотвратит добавление суффикса.

## Практические сценарии

### Сценарий 1: Проверка цепочки разрешения имен

Первичная диагностика: «Почему система видит не тот IP, который отдает DNS?».

```bash
# 1. Проверка порядка источников
grep '^hosts:' /etc/nsswitch.conf

# 2. Проверка локальных переопределений
grep "example.com" /etc/hosts

# 3. Анализ типа resolv.conf
ls -l /etc/resolv.conf
# Ссылка на /run/systemd/resolve/stub-resolv.conf -> управляется systemd-resolved
# Ссылка на /run/NetworkManager/resolv.conf -> управляется NetworkManager
```

### Сценарий 2: Диагностика systemd-resolved

Если служба активна, классического чтения `resolv.conf` недостаточно.

```bash
# Просмотр глобальных настроек и серверов на интерфейсах
resolvectl status

# Проверка конфигурационного файла (статические настройки)
cat /etc/systemd/resolved.conf
# Параметр DNSStubListener=no отключает заглушку на 127.0.0.53

# Проверка того, какой именно сервер ответил на конкретный запрос
resolvectl query example.com
```

### Сценарий 3: Диагностика специфики Alpine (musl)

В контейнерах Alpine DNS часто ведет себя иначе из-за параллельных запросов.

**Проблема**: Периодические ошибки разрешения при использовании медленных DNS-серверов.
**Причина**: musl отправляет запросы всем серверам сразу. Если один сервер (например, внутренний) медленный, а второй (публичный) быстрый, но не знает внутренних имен — запрос может завершиться ошибкой NXDOMAIN.

**Проверка**:
```bash
# В Alpine только прямая проверка resolv.conf
cat /etc/resolv.conf
```

### Сценарий 4: Link-specific DNS (VPN и несколько интерфейсов)

Ситуация, когда корпоративные домены должны разрешаться через туннель, а остальные — через провайдера.

```bash
# Проверка привязки доменов к интерфейсам
resolvectl domain
# Ожидается: tun0 -> corporate.local (~corporate.local - тильда означает только поиск)

# Если домен не привязан к интерфейсу VPN, запросы пойдут на DNS провайдера
```

### Сценарий 5: Режим "Ручное управление" в NetworkManager

Если NetworkManager перезаписывает ваши настройки в `/etc/resolv.conf`.

**Решение**:
1. Создать конфиг `/etc/NetworkManager/conf.d/99-dns.conf`:
```ini
[main]
dns=none
```
2. Перезапустить службу: `systemctl reload NetworkManager`.
3. Удалить симлинк и создать статический `/etc/resolv.conf`.

### Сценарий 6: Оптимизация параметров резолвера (options)

Диагностика медленного разрешения из-за таймаутов.

```bash
# Проверка опций в resolv.conf
# timeout:N — время ожидания ответа (по умолчанию 5с в glibc)
# attempts:N — количество попыток (по умолчанию 2)
# rotate — распределение нагрузки между всеми nameserver
options timeout:1 attempts:3 rotate
```

### Сценарий 7: Проверка /etc/hosts

Ошибки вручную добавленных записей — частая причина неверного разрешения.

```bash
# 1. Поиск конкретного домена
grep -E '^[^#]' /etc/hosts | grep example.com

# 2. Проверка синтаксиса: строки не должны начинаться с пробела,
#    комментарии только в начале строки
cat /etc/hosts

# 3. Верификация: сравниваем с результатом getent
getent hosts example.com
```

**Типичные ошибки:**
- Лишние пробелы перед IP (hosts допускает, ноNagios/скрипты могут падать).
- Использование локального имени без точки при наличии `search` домена (раскрывается в неверное FQDN).
- Устаревшие IP после миграции сервисов.

### Сценарий 8: Аудит параметров resolv.conf

Полная проверка файла на корректность и соответствие политикам.

```bash
# 1. Определяем тип файла
file /etc/resolv.conf
# /etc/resolv.conf: symbolic link to ../run/systemd/resolve/stub-resolv.conf

# 2. Содержимое
cat /etc/resolv.conf

# 3. Проверяем, не отключен ли DNSStubListener
grep DNSStubListener /etc/systemd/resolved.conf
# DNSStubListener=no означает, что 127.0.0.53 не слушается — resolv.conf должен указывать на реальные серверы

# 4. Сравниваем с активными серверами systemd-resolved
resolvectl status | grep 'DNS Servers'
```

### Сценарий 9: DHCP vs статический DNS

Определение, откуда система получает настройки DNS.

```bash
# 1. Проверка истории DHCP (dhclient)
cat /var/lib/dhcp/dhclient.leases | grep 'domain-name-servers'
# domain-name-servers 10.0.0.2, 10.0.0.3;

# 2. Проверка systemd-networkd (RHEL/CentOS/AlmaLinux)
networkctl status eth0 | grep DNS

# 3. Проверка NetworkManager
nmcli device show eth0 | grep DNS

# 4. Если настройки меняются после перезагрузки — это DHCP
#    Если остаются статическими — ручная конфигурация
```

### Сценарий 10: Отключение systemd-resolved (при необходимости)

В редких случаях (например, совместимость с старым ПО, требующим прямого доступа к `resolv.conf`) службу приходится отключать.

```bash
# 1. Отключаем и останавливаем службу
sudo systemctl disable --now systemd-resolved

# 2. Удаляем симлинк и создаем обычный файл
sudo rm /etc/resolv.conf
sudo ln -s /run/systemd/resolve/resolv.conf /etc/resolv.conf
# ИЛИ для статического файла:
# sudo tee /etc/resolv.conf <<EOF
# nameserver 8.8.8.8
# nameserver 1.1.1.1
# options timeout:1 attempts:2
# EOF

# 3. Верификация: getent должен работать
getent hosts google.com

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

### Сценарий 11: Поиск конфликтов NetworkManager и systemd-resolved

Диагностика ситуации, когда NM и resolved «borrow» настройки друг у друга.

```bash
# 1. Режим работы NM
grep '^dns=' /etc/NetworkManager/NetworkManager.conf
# dns=systemd-resolved (правильно)
# dns=default (пишет в resolv.conf напрямую)

# 2. Симлинк resolv.conf
ls -la /etc/resolv.conf
# Должен указывать на stub-resolv.conf при dns=systemd-resolved

# 3. Статус resolved
resolvectl status
# Должен показывать DNS-серверы, полученные через NM/DHCP

# 4. Проверка, не включен ли в NM плагин dnsmasq
grep '\[main\]' /etc/NetworkManager/conf.d/*.conf
# plugins=ifupdown,keyfile,dnsmasq  ← если dnsmasq есть, возможен конфликт портов
```

**Решение конфликта dnsmasq + systemd-resolved:**
Оба службы пытаются слушать порт 53. Отключите один из плагинов.

```bash
# Вариант A: Отключить dnsmasq в NM
sudo tee /etc/NetworkManager/conf.d/99-no-dnsmasq.conf <<EOF
[main]
plugins=ifupdown,keyfile
EOF
sudo systemctl restart NetworkManager

# Вариант B: Переключить NM на режим none и использовать только resolved
sudo tee /etc/NetworkManager/conf.d/99-dns-none.conf <<EOF
[main]
dns=none
EOF
sudo systemctl restart NetworkManager
```

### Сценарий 12: Проверка доменов поиска (search) и параметра ndots

Некорректные `search` или `ndots` — причина лишних запросов и задержек.

```bash
# 1. Просмотр search доменов
grep '^search' /etc/resolv.conf
# search corp.local example.com

# 2. Просмотр ndots
grep '^options' /etc/resolv.conf
# options timeout:1 attempts:2 ndots:5

# 3. Проверка в Kubernetes (если применимо)
kubectl get pod <pod> -o jsonpath='{.spec.dnsConfig}'
# dnsConfig:
#   options:
#   - name: ndots
#     value: "5"

# 4. Тест: разрешение короткого имени
dig +stats api
# → Будет искать как api.corp.local, api.example.com, api и т.д.

# 5. Тест: разрешение FQDN
dig +stats api.example.com.
# → С одним dot и точкой в конце запрос уходит напрямую
```

**Рекомендации:**
- Для хостов с преимущественно внешними доменами: `ndots:1` или `ndots:2`.
- Для внутренних корпоративных сред: `ndots:3`–`ndots:4` если короткие имена используются часто.
- Избегайте более 2–3 доменов в `search`.

### Сценарий 13: Верификация DNS-конфигурации (скелетный скрипт)

Комплексная проверка состояния конфигурации для включения в runbook или мониторинг.

```bash
#!/bin/bash
# dns_config_audit.sh — аудит конфигурации DNS-клиента

echo "=== NSS ==="
grep '^hosts:' /etc/nsswitch.conf

echo -e "\n=== /etc/hosts (пользовательские записи) ==="
grep -vE '^(#|$)' /etc/hosts | grep -v '^127.0.0.1' | grep -v '::1'

echo -e "\n=== resolv.conf ==="
ls -l /etc/resolv.conf
cat /etc/resolv.conf

echo -e "\n=== systemd-resolved.conf ==="
if [ -f /etc/systemd/resolved.conf ]; then
    cat /etc/systemd/resolved.conf
else
    echo "Файл отсутствует"
fi

echo -e "\n=== Active DNS (resolvectl) ==="
resolvectl status 2>/dev/null || echo "systemd-resolved неактивен"

echo -e "\n=== NetworkManager DNS mode ==="
grep '^dns=' /etc/NetworkManager/NetworkManager.conf 2>/dev/null || echo "NM конфиг не найден"

echo -e "\n=== Resolver check (getent vs dig) ==="
getent hosts google.com
dig google.com +short +timeout=2
```

## Дополнительная информация

- [DNS-клиент в Linux: концепции](../../../Networking/Concepts/dns_client.md) — архитектура, NSS и подробное описание файлов.
- [Базовая диагностика DNS](./basic_diagnostics.md) — пошаговый алгоритм поиска неисправностей.
- [Порядок разрешения имён](./name_resolution.md) — детальный разбор цепочки разрешения.
- [Производительность DNS](./dns_resolution_performance.md) — диагностика задержек и оптимизация параметров (ndots, timeout).
- [Инструмент dig](./dig_tool.md) — выполнение прямых запросов в обход системной конфигурации.
- [Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md) — диагностика и настройка DoH/DoT.
