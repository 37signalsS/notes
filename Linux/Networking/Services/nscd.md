# nscd (Name Service Cache Daemon)

## Определения

**`nscd` (Name Service Cache Daemon)** — устаревший (Legacy) системный демон в Linux, предназначенный для кэширования запросов к службам имен через Name Service Switch (NSS). В 2024–2026 годах считается **устаревшим** и заменен на более современные инструменты (SSSD, systemd-resolved).

**NSS (Name Service Switch)** — механизм библиотек Си (glibc, musl), определяющий источники данных и последовательность их опроса для разрешения системных сущностей (хосты, пользователи, группы). Конфигурируется в файле `/etc/nsswitch.conf`.

**NSS-модули** — динамические библиотеки (`libnss_*.so.2`), реализующие логику опроса конкретного источника (например, `libnss_files` для `/etc/hosts`, `libnss_sss` для SSSD, `libnss_resolve` для `systemd-resolved`).

**Кэшируемые базы данных:**
- `passwd` — учетные записи пользователей.
- `group` — группы пользователей.
- `hosts` — разрешение имен (DNS).
- `services` — информация о сетевых службах.
- `netgroup` — сетевые группы.

**Shared memory cache** — сегмент разделяемой памяти, используемый `nscd` для хранения кэшированных записей, доступный всем процессам через интерфейс NSS. Коррупция сегмента приводит к возврату неверных данных без явных ошибок в логах.

**Cache hit / Cache miss** — метрики эффективности кэширования. Hit означает, что запрос был обработан из кэша; miss — пришлось обращаться к upstream-источнику (файл, DNS, LDAP).

**Negative caching** — сохранение отрицательных ответов (`NXDOMAIN`, `NOTFOUND`) в кэше на время `negative-time-to-live`. При превышении этого времени демон повторяет запрос к источнику.

**Paranoia mode** — режим `paranoia yes` в `/etc/nscd.conf`. Включает периодическую проверку контрольных сумм записей кэша и автоматический сброс при обнаружении рассогласований.

**TTL (Time To Live)** — время жизни записи в кэше. В `nscd` TTL задается в конфигурации и **не привязан** к TTL DNS-записи, что является основным источником проблем с устаревшими данными.

**Инвалидация (Invalidation)** — процесс принудительной очистки кэша конкретной базы данных без перезапуска демона. Выполняется сигналом `SIGUSR1` с аргументом базы.

**nslcd** — демон LDAP-клиента (пакет `nslcd`), выполняющий функцию кэширования и преобразования запросов NSS в LDAP-запросы. Предшествовал SSSD и в настоящее время также считается устаревшим.

**SSSD (System Security Services Daemon)** — современный демон, заменяющий `nscd` и `nslcd`. Обеспечивает кэширование данных пользователей/групп с поддержкой LDAP, AD, Kerberos и автоматической инвалидацией через D-Bus.

**Статус на 2025 год:**
- **RHEL 10 / Fedora 36+:** Удален из репозиториев.
- **Debian 13 / Ubuntu 24.04+:** Доступен в репозиториях, но не установлен по умолчанию.
- **Современные дистрибутивы:** Заменен на `sssd` (для пользователей/групп) и `systemd-resolved` (для DNS).

## Базовые концепции

### Архитектура NSS и место nscd в стеке

```
Приложение (getpwnam, getgrnam, gethostbyname, getaddrinfo)
    │
    ▼
glibc (NSS-интерфейс)
    │
    ▼
/etc/nsswitch.conf (порядок источников)
    │
    ├──► files (/etc/passwd, /etc/group, /etc/hosts)
    │
    ├──► nscd (Name Service Cache Daemon)
    │       │
    │       ├── shared memory cache (/var/run/nscd/socket)
    │       └── IPC socket (/var/run/nscd)
    │
    ├──► sssd (современный кэширующий демон)
    │       │
    │       └── D-Bus,LDAP, Kerberos
    │
    ├──► systemd-resolved (DNS-кэш)
    │       │
    │       └── D-Bus, stub-resolv.conf (127.0.0.53)
    │
    └──► nslcd (устаревший LDAP-клиент)
            │
            └── LDAP-сервер
```

`nscd` позиционируется между glibc и источниками данных (файлы, DNS, LDAP). Он перехватывает NSS-запросы, кэширует результат в разделяемой памяти и возвращает его при повторных запросах без обращения к upstream.

### Архитектура процесса nscd

Демон `nscd` работает в модели **one-process-many-threads**:

- **Главный поток (Main thread)** — принимает входящие соединения на Unix-domain сокете `/var/run/nscd/socket`, распределяет запросы по рабочим потокам.
- **Рабочие потоки (Worker threads)** — количество задается параметром `threads` в `/etc/nscd.conf`. Каждый поток обслуживает запросы к конкретной базе данных.
- **Слежение за файлами (Check-files thread)** — для баз `passwd`, `group`, `hosts` отслеживает изменения в соответствующих файлах (`/etc/passwd`, `/etc/group`, `/etc/hosts`) через `inotify`. При изменении файла кэш автоматически инвалидируется.
- **Мониторинг (Per-database threads)** — для каждой кэшируемой базы запущен отдельный поток, управляющий TTL и удалением устаревших записей.

**Разделяемая память:** Записи кэша хранятся в сегменте разделяемой памяти, доступном всем процессам через NSS-интерфейс glibc. Это означает, что при аварийном завершении `nscd` или повреждении сегмента кэша все процессы могут получить некорректные данные.

### Механизм кэширования по базам данных

Каждая база данных (`passwd`, `group`, `hosts`, `services`, `netgroup`) кэшируется независимо со своими параметрами TTL:

| Параметр | Назначение | Типичное значение |
| :--- | :--- | :--- |
| `enable-cache` | Включить/выключить кэширование базы | `yes` |
| `positive-time-to-live` | TTL успешного ответа (сек) | 3600 |
| `negative-time-to-live` | TTL отрицательного ответа (сек) | 20 |
| `suggested-size` | Начальный размер хеш-таблицы | 211 |
| `check-files` | Следить за изменениями в локальных файлах | `yes` |
| `shared` | Разрешить клиентам читать кэш напрямую из памяти | `yes` |

**Важно:** Для базы `hosts` параметр `check-files` отслеживает `/etc/hosts`. Для `passwd`/`group` — `/etc/passwd` и `/etc/group`. Если файл изменяется, кэш сбрасывается автоматически. Это не касается DNS-записей: `nscd` не отслеживает изменения на DNS-сервере и зависит только от собственного TTL.

### TTL и автоматическая инвалидация

`nscd` использует два независимых таймера на каждую запись:

1. **Positive TTL** — время хранения успешного ответа. По истечении этого времени запись удаляется, и следующий запрос вызывает обращение к upstream.
2. **Negative TTL** — время хранения отрицательного ответа (`NOTFOUND`, `UNAVAIL`). Предотвращает повторные запросы к недоступному источнику, но может блокировать доступ к недавно созданным записям.

**Проблема:** В отличие от `systemd-resolved`, `nscd` игнорирует TTL, установленный в DNS-записи. Это приводит к возврату устаревших IP-адресов, если DNS-запись была изменена, но TTL `nscd` еще не истек.

### Безопасность: paranoia, poisoned cache и permissions

**Paranoia mode (`paranoia yes`):**
- Включает проверку контрольных сумм записей кэша при каждом доступе.
- При обнаружении рассогласований (возможная коррупция памяти или атака) запись автоматически удаляется, и выполняется обращение к upstream.
- Значительное снижение производительности (до 30% на высоконагруженных системах), поэтому по умолчанию отключено.

**Права доступа:**
- Сокет `/var/run/nscd/socket` должен принадлежать `root:root` с правами `0660` или `0600`. Доступ посторонних пользователей к сокету позволяет сбрасывать кэш и получать статистику.
- Файл `/etc/nscd.conf` — `root:root`, права `0644`.
- База данных `secrets.tdb` (если используется) — `root:root`, права `0600`.

**Cache poisoning:**
- Удаленный злоумышленник, имеющий доступ к сети, не может напрямую отравить кэш `nscd`, так как демон получает данные только от доверенных источников (файлы, DNS-серверы из `/etc/resolv.conf`).
- Основной риск — локальный пользователь с доступом к сокету может выполнить `nscd -i hosts` для сброса кэша, что может использоваться в DoS-атаках.

### Сравнение с современными аналогами

| Характеристика | nscd | sssd | systemd-resolved | nslcd |
| :--- | :--- | :--- | :--- | :--- |
| **Статус** | Legacy | Активный | Активный | Legacy |
| **Кэширование DNS** | Да (без TTL) | Через resolve | Да (с TTL) | Нет |
| **Кэширование passwd/group** | Да | Да | Нет | Да (LDAP) |
| **LDAP/AD поддержка** | Нет | Да | Нет | Да |
| **Kerberos** | Нет | Да | Нет | Нет |
| **D-Bus API** | Нет | Да | Да | Нет |
| **Автоинвалидация** | Только check-files | Полная | Полная | Нет |
| **Настройка TLS** | Нет | Да (StartTLS, LDAPS) | Да (DoT, DoH) | Нет |
| **Удален из RHEL 10** | Да | Нет | Нет | Нет |

**Вывод:** Для новых систем используйте `systemd-resolved` (DNS) и `sssd` (пользователи/группы/LDAP). `nscd` актуален только для поддержки устаревших систем, не требующих LDAP-интеграции.

## Практические сценарии

### Сценарий 1: Установка и управление сервисом

Несмотря на статус legacy, `nscd` может потребоваться для поддержки старых систем или специфических сценариев.

```bash
# Установка (Debian/Ubuntu)
sudo apt update && sudo apt install nscd

# Установка (RHEL/CentOS/Rocky/Alma)
sudo dnf install nscd

# Включение и запуск
sudo systemctl enable --now nscd

# Проверка статуса
sudo systemctl status nscd
# → Active: active (running) since ...

# Отключение сервиса
sudo systemctl disable --now nscd
```

### Сценарий 2: Полная конфигурация баз данных

Файл `/etc/nscd.conf` содержит секции для каждой базы данных. Ниже приведен полный пример конфигурации для mixed-среды (локальные файлы + DNS-кэш):

```conf
# /etc/nscd.conf

# === Глобальные параметры ===
logfile             /var/log/nscd.log
threads             4
debug-level         0
paranoia            no
restart-interval    3600

# === База данных: passwd ===
enable-cache        passwd   yes
positive-time-to-live passwd  600
negative-time-to-live passwd  20
suggested-size      passwd   211
check-files         passwd   yes
shared              passwd   yes

# === База данных: group ===
enable-cache        group    yes
positive-time-to-live group   600
negative-time-to-live group   20
suggested-size      group   211
check-files         group   yes
shared              group   yes

# === База данных: hosts ===
enable-cache        hosts   yes
positive-time-to-live hosts  3600
negative-time-to-live hosts  20
suggested-size      hosts   211
check-files         hosts   yes
shared              hosts   yes

# === База данных: services ===
enable-cache        services yes
positive-time-to-live services 28800
negative-time-to-live services 20
suggested-size      services  211
check-files         services yes
shared              services yes

# === База данных: netgroup ===
enable-cache        netgroup yes
positive-time-to-live netgroup 28800
negative-time-to-live netgroup 20
suggested-size      netgroup  211
check-files         netgroup yes
shared              netgroup yes
```

**Пояснение параметров:**
- `positive-time-to-live passwd 600` — пользовательские записи кэшируются на 10 минут. Это компромисс между производительностью и актуальностью при локальной среде без LDAP.
- `positive-time-to-live hosts 3600` — DNS-записи кэшируются на 1 час. Увеличьте до 86400 (сутки), если DNS-инфраструктура статична.
- `negative-time-to-live 20` — отрицательные ответы кэшируются на 20 секунд. Достаточно для предотвращения флуда запросов при недоступности источника.

### Сценарий 3: Диагностика и статистика кэша

Команда `nscd -g` выводит полную статистику по всем базам данных:

```bash
sudo nscd -g
```

**Пример вывода:**
```
----- cache status -----
cache hosts:
  hits 12457, misses 342, cache hit rate: 97.31%
  cache data not valid for 342 queries
  cache not valid for 0 queries
  ...
```

**Ключевые показатели:**
- **hits / misses** — соотношение успешных нахождений к промахам. Hit rate >95% считается хорошим для DNS; для passwd/group зависит от размера кэша и частоты смены пользователей.
- **negative hits / misses** — статистика по «отрицательным» ответам. Высокий negative miss rate указывает на проблемы с источником (например, недоступный LDAP).
- **check-files** — статус мониторинга изменений в локальных файлах. Если `no`, изменения в `/etc/passwd` не приводят к сбросу кэша.
- **shared** — если `yes`, процессы читают кэш напрямую из памяти, минуя системные вызовы. Это повышает производительность, но требует осторожности с правами доступа.

### Сценарий 4: Принудительная очистка (Invalidation)

Если система отдает неверные данные, необходимо сбросить кэш конкретной базы:

```bash
# Сброс кэша DNS (хостов)
sudo nscd -i hosts

# Сброс кэша пользователей
sudo nscd -i passwd

# Сброс кэша групп
sudo nscd -i group

# Сброс всех баз
sudo nscd -i all
```

**Важно:** Сброс кэша `hosts` не влияет на кэш DNS-сервера (например, `systemd-resolved` или локальный кэш в приложении). При сбросе `nscd` может потребоваться сброс и других уровней:

```bash
# Полный сброс кэша имен на хосте
sudo nscd -i all
sudo resolvectl flush-caches  # если запущен systemd-resolved
```

### Сценарий 5: Анализ логов и отладка

Файл логов: `/var/log/nscd.log`. Уровень детализации задается параметром `debug-level` (0–10).

```bash
# Изменение уровня отладки без перезапуска
sudo nscd -d  # переключает в foreground с debug=10
sudo systemctl restart nscd  # вернуть в background

# Просмотр логов в реальном времени
sudo tail -f /var/log/nscd.log | grep -E "nscd|NSS|cache"

# Поиск ошибок доступа
sudo grep -E "permission|denied|EACCES" /var/log/nscd.log

# Поиск повреждений кэша
sudo grep -E "paranoia|corrupt|checksum" /var/log/nscd.log
```

**Типичные сообщения в логах:**
- `nscd: getpwnam_r failed for user ...` — источник (файл/LDAP) недоступен или вернул ошибку.
- `nscd: parse_hosts() failed` — ошибка парсинга `/etc/hosts`.
- `nscd: cannot stat() ...` — файл конфигурации или кэша не найден.

### Сценарий 6: Troubleshooting типичных проблем

**Проблема 1: Устаревшие DNS-записи (Stale data)**
```bash
# Диагностика
getent hosts example.com
dig +short example.com

# Если getent возвращает старый IP, а dig — новый:
sudo nscd -i hosts

# Постоянное решение: уменьшить positive-time-to-live hosts
# или перейти на systemd-resolved
```

**Проблема 2: Отрицательное кэширование блокирует новый домен**
```bash
# Симптом: домен существует, но getent возвращает "not found"
dig +short example.com  # работает
getent hosts example.com  # NOTFOUND

# Причина: nscd кэшировал NXDOMAIN на negative-time-to-live (20 сек по умолчанию)
# Решение: подождать 20 секунд или сбросить кэш
sudo nscd -i hosts
```

**Проблема 3: Конфликт с sssd**
```bash
# Симптом: пользователи не видны, или видны дубликаты
# Причина: оба демона кэшируют passwd/group
# Решение: остановить и отключить nscd
sudo systemctl disable --now nscd
```

**Проблема 4: Коррупция разделяемой памяти**
```bash
# Симптом: случайные ошибки разрешения, падение приложений
# Решение: включить paranoia mode или перезапустить nscd
sudo systemctl restart nscd
```

**Проблема 5: Нет доступа к сокету**
```bash
# Симптом: nscd -g возвращает "Connection refused"
# Проверка прав на сокет
ls -la /var/run/nscd/socket
# → srw-rw---- 1 root root ... socket

# Если права нарушены:
sudo chown root:root /var/run/nscd/socket
sudo chmod 660 /var/run/nscd/socket
```

### Сценарий 7: Интеграция с LDAP/AD (через nslcd)

`nscd` не поддерживает напрямую LDAP, но может использоваться совместно с `nslcd` для кэширования результатов LDAP-запросов:

```bash
# Установка (Debian/Ubuntu)
sudo apt install nslcd libnss-ldap libpam-ldap

# Установка (RHEL/CentOS/Rocky)
sudo dnf install nslcd nss-pam-ldapd

# Настройка /etc/nslcd.conf
cat > /etc/nslcd.conf <<EOF
uid nslcd
gid nslcd
ldap_uri ldaps://ldap.example.com:636
ldap_base dc=example,dc=com
ldap_bind_dn cn=nslcd,ou=services,dc=example,dc=com
ldap_bind_credw password
ldap_tls_cacertfile /etc/ssl/certs/ca-certificates.crt
EOF

# Настройка /etc/nsswitch.conf
# passwd:         files ldap
# group:          files ldap
# shadow:         files ldap

# Включение nscd для кэширования результатов nslcd
sudo systemctl enable --now nslcd nscd
```

**Важно:** При использовании `nslcd` параметр `check-files` для `passwd` и `group` должен быть отключен (`no`), так как данные поступают из LDAP, а не из локальных файлов.

### Сценарий 8: Миграция на современные аналоги

#### Миграция DNS-кэширования с nscd на systemd-resolved

```bash
# 1. Остановка и отключение nscd
sudo systemctl disable --now nscd

# 2. Проверка статуса systemd-resolved
sudo systemctl enable --now systemd-resolved
sudo resolvectl status

# 3. Проверка symlink /etc/resolv.conf
ls -l /etc/resolv.conf
# → /etc/resolv.conf -> /run/systemd/resolve/stub-resolv.conf

# 4. Очистка старого кэша (необязательно)
sudo rm -f /var/run/nscd/*

# 5. Валидация: сравнение getent и dig
getent hosts example.com
dig +short example.com
# Оба должны возвращать одинаковый результат
```

#### Миграция пользовательских/групповых кэшей с nscd на sssd

```bash
# 1. Установка sssd
sudo apt install sssd sssd-ldap sssd-tools libnss-sssd libpam-sssd
# или
sudo dnf install sssd sssd-ldap sssd-tools

# 2. Создание /etc/sssd/sssd.conf
cat > /etc/sssd/sssd.conf <<EOF
[sssd]
services = nss, pam
config_file_version = 2
domains = local

[nss]
filter_users = root,daemon,bin,sys,sync

[pam]

[domain/local]
id_provider = files
EOF

# Права доступа: критично для sssd
sudo chown root:root /etc/sssd/sssd.conf
sudo chmod 600 /etc/sssd/sssd.conf

# 3. Настройка /etc/nsswitch.conf
# passwd:         files sss
# group:          files sss

# 4. Остановка и отключение nscd
sudo systemctl disable --now nscd

# 5. Запуск sssd
sudo systemctl enable --now sssd

# 6. Валидация
getent passwd root
getent group root
id testuser
```

### Сценарий 9: Автоматизация с Ansible

```yaml
# tasks/nscd.yml
- name: Установка nscd
  package:
    name: nscd
    state: present

- name: Развертывание конфигурации nscd
  copy:
    src: files/nscd.conf
    dest: /etc/nscd.conf
    owner: root
    group: root
    mode: '0644'
  notify: restart nscd

- name: Включение сервиса nscd
  service:
    name: nscd
    state: started
    enabled: yes

- name: Миграция с nscd на systemd-resolved
  service:
    name: nscd
    state: stopped
    enabled: no
  when: nscd_migration | default(false)

- name: Включение systemd-resolved
  service:
    name: systemd-resolved
    state: started
    enabled: yes
  when: nscd_migration | default(false)
```

### Сценарий 10: Мониторинг и алертинг

```bash
# Проверка hit rate (порог: <90% — warning, <80% — critical)
HIT_RATE=$(sudo nscd -g | grep "cache hit rate" | awk '{print $NF}' | sed 's/%//')
if (( $(echo "$HIT_RATE < 90" | bc -l) )); then
  echo "WARNING: nscd cache hit rate low: ${HIT_RATE}%"
fi

# Проверка размера лога (порог: >100MB)
LOG_SIZE=$(du -sm /var/log/nscd.log | awk '{print $1}')
if [ "$LOG_SIZE" -gt 100 ]; then
  echo "WARNING: nscd log size: ${LOG_SIZE}MB"
fi

# Проверка статуса сервиса
if ! systemctl is-active --quiet nscd; then
  echo "CRITICAL: nscd service is not running"
fi
```

**Prometheus-экспортер (textfile collector):**
```bash
# /etc/nscd/prometheus.prom
nscd_cache_hit_ratio{db="hosts"} 0.9731
nscd_cache_hit_ratio{db="passwd"} 0.9854
nscd_cache_hit_ratio{db="group"} 0.9821
```

### Сценарий 11: Аварийное восстановление

```bash
# Полная остановка nscd
sudo systemctl stop nscd

# Удаление кэша и логов
sudo rm -f /var/run/nscd/*
sudo rm -f /var/log/nscd.log

# Перезапуск с чистым кэшем
sudo systemctl start nscd

# Проверка статистики (должна показывать нулевые hits/misses)
sudo nscd -g
```

## Конфигурация

Основной файл настроек: `/etc/nscd.conf`.

### Глобальные параметры

```conf
logfile             /var/log/nscd.log
threads             4
debug-level         0
paranoia            no
restart-interval    3600
```

### База данных: passwd

```conf
enable-cache        passwd   yes
positive-time-to-live passwd  600
negative-time-to-live passwd  20
suggested-size      passwd   211
check-files         passwd   yes
shared              passwd   yes
```

### База данных: group

```conf
enable-cache        group   yes
positive-time-to-live group   600
negative-time-to-live group   20
suggested-size      group   211
check-files         group   yes
shared              group   yes
```

### База данных: hosts

```conf
enable-cache        hosts   yes
positive-time-to-live hosts  3600
negative-time-to-live hosts  20
suggested-size      hosts   211
check-files         hosts   yes
shared              hosts   yes
```

### База данных: services

```conf
enable-cache        services yes
positive-time-to-live services 28800
negative-time-to-live services 20
suggested-size      services  211
check-files         services yes
shared              services yes
```

### База данных: netgroup

```conf
enable-cache        netgroup yes
positive-time-to-live netgroup 28800
negative-time-to-live netgroup 20
suggested-size      netgroup  211
check-files         netgroup yes
shared              netgroup yes
```

## Дополнительная информация

### См. также
- **[Порядок разрешения имён: диагностика](../../../Linux/Diagnostics/Networking/dns/name_resolution.md)** — архитектура NSS и glibc, взаимодействие с `systemd-resolved`.
- **[Производительность DNS-резолвинга](../../../Linux/Diagnostics/Networking/dns/dns_resolution_performance.md)** — сравнение кэширующих демонов и методы диагностики.
- **[Установка и настройка LDAP и SSSD](../../../Linux/SystemAdministration/Users/LDAP_SSSD/configuration.md)** — современная замена `nscd`+`nslcd` для централизованной идентификации.
