# Диагностика DNS-мисконфигурации и проблем с разрешением имён

Эта заметка описывает практические сценарии (кейсы) диагностики распределённой системы при проблемах с DNS. Теоретические основы и инструменты диагностики представлены в разделах: **[Диагностика DNS](../../Linux/Diagnostics/Networking/dns/overview.md)**, **[Протокол DNS](../Protocols/DNS/dns.md)**, **[Общая методология диагностики](../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md)**, **[Порядок разрешения имён в Linux](../../Linux/Diagnostics/Networking/dns/name_resolution.md)**, **[Производительность DNS-резолвинга](../../Linux/Diagnostics/Networking/dns/dns_resolution_performance.md)**, **[Инструмент dig](../../Linux/Diagnostics/Networking/dns/dig_tool.md)**, **[DNS-клиент в Linux](../../Linux/Networking/Concepts/dns_client.md)**, **[DNS и Service Discovery в Docker](../../Docker/Docker_network/dns_and_service_discovery.md)**, **[Проблемы с DNS в Docker](../../Docker/Docker_network/troubleshooting/dns_resolution_issues.md)**.

## Определения

- **DNS-мисконфигурация (DNS Misconfiguration)** — некорректная настройка системы доменных имён **DNS (Domain Name System)**, приводящая к разрешению (resolving) имён в неверные **IP (Internet Protocol)** адреса. В данном кейсе — имя хоста базы данных разрешалось в адрес тестового сервера вместо продуктивного.
- **Ошибка 500 (HTTP 500 Internal Server Error)** — код состояния **HTTP (HyperText Transfer Protocol)**, указывающий на общую внутреннюю ошибку сервера. В данном сценарии она была вызвана логическими сбоями приложения при работе с некорректной базой данных.
- **Бэкенд (Backend)** — программно-аппаратная часть сервиса, отвечающая за логику работы и хранение данных.
- **Системный резолвер (Resolver)** — библиотека в составе **ОС (Operating System)** (обычно `glibc`), отвечающая за преобразование доменных имен в IP-адреса для прикладных программ.
- **NSS (Name Service Switch)** — механизм переключача служб имен, определяющий источники данных и последовательность их опроса для разрешения имён. Конфигурируется в `/etc/nsswitch.conf`. Подробнее: **[Порядок разрешения имён](../../Linux/Diagnostics/Networking/dns/name_resolution.md)**.
- **systemd-resolved** — современная системная служба управления DNS в Linux, предоставляющая stub-резолвер на `127.0.0.53`. Обеспечивает кэширование, DNSSEC, DoT/DoH. Подробнее: **[DNS-клиент в Linux](../../Linux/Networking/Concepts/dns_client.md)**.
- **/etc/hosts** — статический файл соответствий IP-адресов и имён хостов. Используется как локальный источник данных NSS (модуль `files`). Имеет приоритет над DNS при стандартной конфигурации `hosts: files dns`.
- **/etc/resolv.conf** — конфигурационный файл системного резолвера, определяющий DNS-серверы, домен поиска и параметры запросов (`timeout`, `attempts`, `ndots`).
- **dig (Domain Information Groper)** — утилита диагностики DNS, выполняющая прямые запросы к DNS-серверам в обход системного резолвера и NSS. Подробнее: **[Инструмент dig](../../Linux/Diagnostics/Networking/dns/dig_tool.md)**.
- **getent hosts** — системная команда, использующая NSS для разрешения имени. Показывает реальный ответ, который получит приложение (с учётом `/etc/hosts`, `systemd-resolved` и DNS).
- **Consumer Lag** — разница между последним записанным offset в партиции Kafka и текущим committed offset консьюмера. Используется в сценарии для определения того, что проблема лежит за пределами Kafka.

## Основные концепции

Система DNS является фундаментом сетевого взаимодействия в распределённых архитектурах. Приложения используют DNS для поиска ресурсов: баз данных, внешних **API (Application Programming Interface)** и микросервисов.

Ошибки в DNS-разрешении часто маскируются под сбои прикладного уровня. Если DNS возвращает IP-адрес исправного, но «не того» сервера (например, стейджинг вместо продакшена), приложение может подключаться успешно, но вести себя непредсказуемо из-за различий в схеме данных или их наполнении.

### Критический нюанс: NSS vs DNS-сервер

Не все утилиты работают одинаково. Это ключевое понимание для диагностики:
- `ping`, `getent hosts`, `curl` и большинство языков программирования (Go, Java, Python) используют системные библиотеки (`libc`), которые следуют логике `/etc/nsswitch.conf`.
- `dig` и `nslookup` являются специализированными инструментами DNS и обычно обращаются напрямую к DNS-серверам, **игнорируя** локальные файлы типа `/etc/hosts`.

**Вывод:** Если `dig` показывает правильный IP, а приложение ломается — проблема в NSS/hosts. Если `dig` тоже показывает неверный IP — проблема на DNS-сервере или в кэше.

### Цепочка разрешения имени в Linux

```
Приложение (getaddrinfo)
    ↓
NSS (/etc/nsswitch.conf)
    ├─→ files (/etc/hosts)         ← ПРОВЕРЬТЕ ПЕРВЫМ!
    ├─→ resolve (systemd-resolved)
    │       └─→ cache → upstream DNS
    └─→ dns (/etc/resolv.conf)     ← ПРОВЕРЬТЕ ВТОРЫМ!
            └─→ UDP/TCP → DNS-сервер
```

### Типичные архитектуры и точки отказа DNS

| Компонент | Типичная роль | Точки отказа |
| :--- | :--- | :--- |
| `/etc/hosts` | Статические маппинга (dev/staging) | Ручные правки, залипшие записи |
| `systemd-resolved` | Локальный кэш + DNSSEC | Некорректный кэш, баги версии |
| `/etc/resolv.conf` | Указывает DNS-серверы | Неверные серверы, symlink сломан |
| `/etc/nsswitch.conf` | Порядок источников | Неверный приоритет `files` vs `dns` |
| Внешний DNS-сервер | Рекурсивный резолвер | DDoS, сетевые задержки, кэш poisoning |
| Docker embedded DNS | Service Discovery внутри сетей | `ndots`, копирование `resolv.conf` хоста |
| Kubernetes CoreDNS | Service Discovery в кластере | Перегрузка, `ndots:5`, лимиты |

## Предварительные требования

### Необходимые инструменты

| Инструмент | Назначение | Установка / Проверка |
| :--- | :--- | :--- |
| `dig` | Прямой DNS-запрос к серверу (в обход NSS) | `apt install dnsutils` / `brew install bind` |
| `getent hosts` | Проверка разрешения имени через NSS (как видит приложение) | Встроен в glibc |
| `nslookup` | Базовая проверка DNS (устаревший, но доступен) | Встроен в большинство ОС |
| `host` | Упрощённый `dig` для быстрой проверки | `apt install dnsutils` |
| `resolvectl` | Управление и диагностика `systemd-resolved` | Встроен в systemd |
| `strace` | Отслеживание системных вызовов (какие файлы читаются) | `apt install strace` |
| `curl` | Проверка HTTP через разрешённое имя | `apt install curl` |
| `ss` / `netstat` | Проверка установленных TCP-соединений (конечный IP) | Встроены в ядро |
| `tcpdump` | Захват DNS-трафика (UDP/TCP 53) | `apt install tcpdump` |
| `kubectl` | Диагностика DNS в Kubernetes (CoreDNS) | kubectl CLI |
| `docker` | Диагностика DNS в Docker-контейнерах | Docker CLI |

### Требования к среде

- SSH-доступ к проблемному серверу или контейнеру (`docker exec` / `kubectl exec`).
- Доступ к мониторингу (Grafana) с метриками DNS-запросов и HTTP-ошибок.
- Доступ к логам приложения (ELK/Loki) или `docker logs`/`kubectl logs`.
- Права на чтение конфигурационных файлов: `/etc/hosts`, `/etc/resolv.conf`, `/etc/nsswitch.conf`.

### Права доступа

| Операция | Минимальные права |
| :--- | :--- |
| Чтение конфигурации NSS/DNS | Обычный пользователь ( файлы world-readable) |
| `strace` на процессе | `CAP_SYS_PTRACE` или root |
| `tcpdump` | `CAP_NET_RAW` или root |
| Редактирование `/etc/hosts` | root |
| Управление `systemd-resolved` | root или `CAP_SYS_ADMIN` |
| `resolvectl` | Обычный пользователь (только чтение) |

## Алгоритм диагностики

При проблемах «сервис падает, DNS подозревается» следуйте алгоритму:

1. **Определите симптом**: 500 ошибки? Таймауты? `Connection refused`? Сервис не стартует?
2. **Проверьте NSS**: `getent hosts <имя>` — что видит приложение?
3. **Проверьте DNS напрямую**: `dig <имя>` — что говорит DNS-сервер?
4. **Сравните**: Если `getent` ≠ `dig` → проблема в `/etc/hosts` или NSS.
5. **Если `dig` неверный**: Проблема на DNS-сервере или в кэше.
6. **Если всё верно, но сервис падает**: Проблема не в DNS (проверьте порты, firewall, TLS).
7. **Для Docker**: Проверьте `docker exec <container> cat /etc/resolv.conf`.
8. **Для Kubernetes**: `kubectl exec <pod> -- nslookup <service>` и логи CoreDNS.

## Практические сценарии

### Сценарий 1: Периодические 500-е ошибки из-за записи в /etc/hosts

**Проблема:** Пользователи периодически жаловались на 500-е ошибки в личном кабинете. Мониторинг показывал, что все компоненты «живы» (Healthy), но часть запросов завершалась аварийно.

**Архитектура системы:**
1. **Балансировщик нагрузки (Load Balancer)** — внешняя точка входа.
2. **Nginx Reverse Proxy** — 3 экземпляра.
3. **App Servers (Бэкенд)** — 6 экземпляров приложения на Go.
4. **DB (Database)** — PostgreSQL, общая для всех бэкендов.

#### Шаг 1: Проверка внешней связности

Проверка доступности фронтенда подтвердила корректную работу внешней DNS-записи.

```bash
ping мойкотик-бармотик.рф
# → PING мойкотик-бармотик.рф (93.184.216.34) ... 64 bytes from ...
```

**Валидация:** Внешний DNS разрешает домен корректно. Проблема не на уровне публичной DNS-зоны.

#### Шаг 2: Анализ логов прокси

Логи Nginx показали, что ошибки `500` приходят от `upstream` (бэкенда). Анализ по коду ответа выявил, что ошибки возвращает только **один конкретный сервер приложений** (app-04) из шести.

```bash
# Фильтрация логов Nginx по upstream и коду ответа
grep 'upstream.*500' /var/log/nginx/access.log | awk '{print $1}' | sort | uniq -c | sort -rn
# → 47 app-04
# →  0 app-01
# →  0 app-02
# →  0 app-03
# →  0 app-05
# →  0 app-06
```

**Валидация:** Проблема локализована на конкретный инстанс. Это исключает глобальные проблемы (DNS-сервер, БД, сеть).

#### Шаг 3: Анализ логов приложения

Логи Go-приложения на `app-04` содержали ошибки: `relation "orders" does not exist`. При этом на остальных пяти серверах таблица `orders` успешно считывалась из той же БД.

```bash
# Проверка логов проблемного сервера
docker logs app-04 --tail 20 | grep -i "error\|fatal\|relation"
# → [ERROR] pq: relation "orders" does not exist
# → [ERROR] Failed to query database: db.internal.local:5432
```

**Валидация:** Ошибка `relation "orders" does not exist` указывает на подключение к БД с другой схемой (тестовая БД без этой таблицы).

#### Шаг 4: Проверка DNS-разрешения (Решающий этап)

Сравнение разрешения имени хоста БД внутри контейнеров.

**На рабочем сервере (app-01):**
```bash
getent hosts db.internal.local
# → 10.0.1.50       db.internal.local
```

**На проблемном сервере (app-04):**
```bash
getent hosts db.internal.local
# → 10.0.99.200     db.internal.local
```

**Проверка через dig (контрольный тест):**
```bash
# На app-04:
dig db.internal.local +short
# → 10.0.1.50       ← DNS-СЕРВЕР ДАЁТ ПРАВИЛЬНЫЙ IP!

# Но getent показывает другой:
getent hosts db.internal.local
# → 10.0.99.200     ← NSS ВИДИ ДРУГОЙ IP!
```

**Валидация:** `dig` показывает `10.0.1.50` (корректный IP от DNS-сервера), а `getent hosts` показывает `10.0.99.200` (IP из `/etc/hosts`). Это однозначно подтверждает проблему в `/etc/hosts`.

**Причина:** Инженер при отладке `app-04` прописал в `/etc/hosts` IP-адрес тестовой базы данных (`10.0.99.200`) и забыл удалить запись.

**Техническое обоснование:** Библиотека `libc` (через NSS) сначала проверяет `/etc/hosts` (источник `files`), а затем DNS (источник `dns`), согласно конфигурации в `/etc/nsswitch.conf`:
```text
hosts: files dns
```
В результате приложение подключалось к тестовой БД с устаревшей схемой данных, что вызывало ошибки `500` при попытке обращения к новым таблицам. При этом `dig db.internal.local` на том же сервере показывал корректный `10.0.1.50`, что вводило в заблуждение при первичной проверке.

#### Шаг 5: Решение

```bash
# 1. Просмотр текущей записи
grep db.internal.local /etc/hosts
# → 10.0.99.200  db.internal.local

# 2. Удаление некорректной записи (выполнить на app-04)
sudo sed -i '/db.internal.local/d' /etc/hosts

# 3. Проверка восстановления
getent hosts db.internal.local
# → 10.0.1.50       db.internal.local  ← ТЕПЕРЬ КОРРЕКТНО

# 4. Перезапуск приложения для очистки кэша DNS (если есть)
docker restart app-04

# 5. Валидация: проверка логов после перезапуска
docker logs app-04 --tail 10 | grep -i "error\|fatal"
# → (пустой вывод — ошибок нет)
```

---

### Сценарий 2: Таймауты подключения из-за systemd-resolved и /etc/resolv.conf

**Проблема:** После обновления ОС (Ubuntu 22.04 → 24.04) приложение стало периодически зависать на 5 секунд при подключении к внешнему API. Логи показывали `dial tcp: lookup api.external.com: i/o timeout`.

**Архитектура:** Приложение (Go) → systemd-resolved → DNS-сервер.

#### Диагностика

```bash
# 1. Проверка resolv.conf
cat /etc/resolv.conf
# → nameserver 127.0.0.53     ← systemd-resolved stub

# 2. Проверка реальных upstream серверов
resolvectl status
# → Global
# →       DNS Servers: 10.0.0.2 10.0.0.3
# →       DNSSEC: allow-downgrade

# 3. Проверка через dig (обращается к systemd-resolved)
dig api.external.com +short
# → 104.26.10.78  (быстро, <50мс)

# 4. Проверка через getent (через NSS → systemd-resolved)
getent hosts api.external.com
# → (зависает на 5 секунд → timeout)

# 5. Сравнение: dig через конкретный upstream
dig @10.0.0.2 api.external.com +short
# → 104.26.10.78  (быстро)

# 6. Проверка кэша systemd-resolved
resolvectl query api.external.com
# → api.external.com: 104.26.10.78
# → (no cache)
```

**Причина:** `systemd-resolved` в новой версии имеет баг с обработкой AAAA-запросов для определённых доменов. Запрос IPv6 зависает на 5 секунд, затем приложение пробует IPv4.

**Решение:**

```bash
# Вариант 1: Отключить AAAA через gai.conf
echo "precedence ::ffff:0:0/96  100" | sudo tee -a /etc/gai.conf

# Вариант 2: Настроить systemd-resolved на приоритет IPv4
sudo sed -i 's/^#DNS=/DNS=10.0.0.2/' /etc/systemd/resolved.conf
sudo sed -i 's/^#DNSSEC=/DNSSEC=no/' /etc/systemd/resolved.conf
sudo systemctl restart systemd-resolved

# Вариант 3: Переключиться на прямой DNS (без systemd-resolved)
sudo ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf
```

---

### Сценарий 3: Docker-контейнер не резолвит внутренний домен

**Проблема:** Контейнер с приложением не может подключиться к `db.internal.company.com`. С хоста `nslookup` работает корректно.

#### Диагностика

```bash
# 1. Проверка resolv.conf внутри контейнера
docker exec app cat /etc/resolv.conf
# → nameserver 8.8.8.8        ← Docker скопировал публичный DNS!

# 2. Проверка с хоста
nslookup db.internal.company.com
# → 10.0.1.50  (корректно, через корпоративный DNS 10.0.0.2)

# 3. Проверка внутри контейнера
docker exec app nslookup db.internal.company.com
# → ** server can't find db.internal.company.com: NXDOMAIN

# 4. Проверка Docker-сети
docker network inspect mynet | grep DNS
# → "DNS": ["8.8.8.8"]   ← Указан публичный DNS!
```

**Причина:** Docker скопировал `resolv.conf` хоста, где был `127.0.0.53` (systemd-resolved), обнаружил loopback и подставил `8.8.8.8`. Публичный DNS не знает внутренний домен компании.

**Решение:**

```bash
# Настроить Docker на использование корпоративного DNS
# В /etc/docker/daemon.json:
{
  "dns": ["10.0.0.2", "10.0.0.3"]
}

# Или для конкретного контейнера:
docker run --dns 10.0.0.2 --dns 10.0.0.3 myapp

# Или в docker-compose.yml:
# services:
#   app:
#     dns:
#       - 10.0.0.2
#       - 10.0.0.3
```

**Валидация:**

```bash
docker exec app cat /etc/resolv.conf
# → nameserver 10.0.0.2
# → nameserver 10.0.0.3

docker exec app nslookup db.internal.company.com
# → 10.0.1.50   ← Теперь работает!
```

---

### Сценарий 4: Kubernetes CoreDNS перегружен, сервисы не резолвятся

**Проблема:** Поды в Kubernetes периодически не могут разрешить имена сервисов. Ошибки: `Could not resolve host: my-service.default.svc.cluster.local`. При этом `kubectl get svc my-service` показывает корректный ClusterIP.

#### Диагностика

```bash
# 1. Проверка CoreDNS подов
kubectl -n kube-system get pods -l k8s-app=kube-dns
# → NAME                       READY   STATUS    RESTARTS
# → coredns-abc123-x7k9f       0/1     CrashLoopBackOff  15
# → coredns-def456-q2m8n       1/1     Running            0

# 2. Логи CoreDNS
kubectl -n kube-system logs coredns-abc123-x7k9f --tail=20
# → [ERROR] plugin/errors: 2 my-service.default.svc.cluster.local. A: dial UDP 10.96.0.10:53: no route to host

# 3. Проверка количества запросов
kubectl -n kube-system logs coredns-abc123-x7k9f | grep -c "plugin/errors"
# → 45000  ← Число ошибок за последний час

# 4. Проверка ресурсов CoreDNS
kubectl -n kube-system describe pod coredns-abc123-x7k9f | grep -A5 "Limits\|Requests"
# → Limits:
# →   cpu: 100m
# →   memory: 70Mi

# 5. Проверка UDP-соединений с CoreDNS
kubectl -n kube-system exec my-app-pod -- ss -unp | grep :53
# → UNCONN  0  0  10.244.0.5:45678  10.96.0.10:53  users:(("my-app",pid=1,fd=7))
```

**Причина:** CoreDNS CrashLoopBackOff из-за нехватки памяти (70Mi Limit при высокой нагрузке). Единственный работающий под обрабатывает все запросы и перегружен.

**Решение:**

```bash
# 1. Увеличить ресурсы CoreDNS
kubectl -n kube-system edit deployment coredns
# → containers:
# →   resources:
# →     limits:
# →       cpu: 500m
# →       memory: 256Mi

# 2. Или масштабировать replicas
kubectl -n kube-system scale deployment coredns --replicas=3

# 3. Валидация
kubectl -n kube-system get pods -l k8s-app=kube-dns
# → coredns-abc123-x7k9f       1/1     Running   0
# → coredns-def456-q2m8n       1/1     Running   0
# → coredns-ghi789-r3t6y       1/1     Running   0
```

## Диагностика типичных проблем

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `dig` OK, приложение падает | Запись в `/etc/hosts` перезаписывает DNS | `getent hosts <name>` — сравнить с `dig` | Удалить запись из `/etc/hosts` |
| `getent hosts` зависает на 5 сек | systemd-resolved + IPv6 таймаут | `resolvectl query <name>`, проверка AAAA | Отключить AAAA через `gai.conf` |
| Docker-контейнер не резолвит внутренний домен | Docker скопировал `127.0.0.53`, подставил `8.8.8.8` | `docker exec cat /etc/resolv.conf` | Настроить `"dns": ["corp-dns"]` в `daemon.json` |
| `nslookup` работает, `dig` нет | `nslookup` использует NSS, `dig` — прямой DNS | Проверить `/etc/resolv.conf` | Исправить DNS-серверы в `resolv.conf` |
| CoreDNS CrashLoopBackOff в K8s | Нехватка памяти/CPU | `kubectl logs kube-dns-...`, `kubectl top pod` | Увеличить ресурсы или replicas |
| `NXDOMAIN` для внутреннего домена | DNS-сервер не знает зону | `dig @<dns-server> <domain>` | Добавить A-запись / настроить转发 |
| Ошибки 500 только на одном инстансе | Локальная запись в `/etc/hosts` на этом инстансе | `getent hosts` на каждом инстансе | Очистить `/etc/hosts` на проблемном инстансе |
| `Connection refused` к БД, DNS корректен | БД не запущена или слушает другой IP | `ss -tlnp \| grep 5432`, `pg_isready` | Запустить БД, проверить `listen_addresses` |
| Медленный DNS (>200ms p99) | Множественные nameserver, `ndots:5` | `dig` с `stats`, `resolvectl statistics` | Уменьшить `ndots`, `timeout:1`, оптимизировать `resolv.conf` |
| DNS работает на хосте, не в контейнере | Контейнерная сеть изолирована | `docker exec ping 8.8.8.8`, проверка DNS в контейнере | Настроить `--dns` или network DNS |
| Смена DNS после обновления ОС | systemd-resolved изменил конфигурацию | `resolvectl status`, сравнение `resolv.conf` до/после | Обновить конфигурацию приложения/Docker |
| `SERVFAIL` от DNS-сервера | DNSSEC-ошибка, сервер недоступен | `dig +dnssec <name>`, `resolvectl status` | Отключить DNSSEC или исправить зону |

## Граничные случаи и особенности

### Go-резолвер и /etc/hosts

Go (начиная с 1.5) использует собственный DNS-резолвер, который **не читает** `/etc/hosts` по умолчанию. Это может вводить в заблуждение: `getent hosts` показывает IP из hosts, а Go-приложение обращается напрямую к DNS.

```bash
# Проверка: Go-приложение может резолвить иначе чем getent
# Go 1.15+: GOFLAGS=-mod=mod go run main.go
# Если нужно заставить Go читать /etc/hosts:
#export GODEBUG=netdns=go+netgo  # переключить на cgo resolver
```

**Рекомендация:** Для Go-приложений проверяйте разрешение через саму программу, а не через `getent`.

### Python и собственный резолвер

Python также может использовать встроенный резолвер, игнорируя NSS. Проверяйте через `socket.getaddrinfo()`:

```python
import socket
print(socket.getaddrinfo('db.internal.local', 5432))
# Покажет реальный IP, который видит Python
```

### ndots в Kubernetes

В Kubernetes по умолчанию `ndots:5`. Имя `api.example.com` (2 точки) сначала проверяется как:
1. `api.example.com.default.svc.cluster.local`
2. `api.example.com.svc.cluster.local`
3. `api.example.com.cluster.local`
4. `api.example.com`

Это генерирует 4 лишних DNS-запроса. **Решение:** Используйте FQDN с точкой на конце (`api.example.com.`) или уменьшите `ndots`.

### Кэширование DNS и TTL

DNS-ответы кэшируются на нескольких уровнях: браузер (60 сек), systemd-resolved (зависит от TTL), рекурсивный резолвер (зависит от TTL). При смене IP-адреса DNS-записи клиенты могут подключаться к старому IP до истечения TTL.

**Рекомендация:** При плановой миграции установите TTL很低 (60 сек) за 24 часа до миграции.

### /etc/resolv.conf как symlink

В современных ОС `/etc/resolv.conf` — это символическая ссылка на файлы systemd-resolved:
```bash
ls -la /etc/resolv.conf
# → /etc/resolv.conf -> ../run/systemd/resolve/stub-resolv.conf
```

Редактирование через `echo "nameserver ..." > /etc/resolv.conf` **сломает** symlink. Используйте `resolvectl` или редактируйте `/etc/systemd/resolved.conf`.

### DNS и firewall (nf_tables / iptables)

Фаерволы могут блокировать DNS-трафик (UDP/TCP 53). При диагностике:
```bash
# Проверка правил для DNS
iptables -L -n | grep -E "53|dns"
# или
nft list ruleset | grep -E "53|dns"

# Проверка с tcpdump
tcpdump -i any port 53 -nn -c 10
```

Если `tcpdump` видит DNS-запросы, но ответов нет — проблема на стороне DNS-сервера или фаервола.

## Практические рекомендации

### По конфигурации

1. **Всегда проверяйте NSS перед DNS**: `getent hosts` — первый шаг диагностики.
2. **Не редактируйте `/etc/resolv.conf` напрямую**: Используйте `resolvectl` (systemd-resolved) или NetworkManager.
3. **Для Docker**: Настройте корпоративный DNS в `daemon.json`, не полагайтесь на автоопределение.
4. **Для Kubernetes**: Используйте FQDN с точкой или уменьшите `ndots` для внешних доменов.
5. **Для Go-приложений**: Помните о собственном резолвере; тестируйте разрешение через саму программу.

### По мониторингу

1. **DNS Success Rate**: Алерт при < 99.9% успешных запросов (см. **[Мониторинг DNS](../Protocols/DNS/dns_monitoring.md)**).
2. **DNS Latency**: Алерт при p99 > 200мс (см. **[Производительность DNS-резолвинга](../../Linux/Diagnostics/Networking/dns/dns_resolution_performance.md)**).
3. **HTTP 5xx по инстансам**: Разбивка по серверам выявит локальные DNS-проблемы.
4. **Изменение `/etc/hosts`**: Мониторинг контрольных сумм (AIDE, Tripwire).
5. **Consumer Lag в Kafka**: Рост Lag может указывать на DNS-проблемы консьюмера.

### По безопасности

1. **DNSSEC**: Настройте валидацию DNSSEC для защиты от spoofing.
2. **DNS over TLS (DoT)**: Используйте шифрованные DNS-запросы в незащищённых сетях.
3. **Ограничение доступа к `/etc/hosts`**: Только root может редактировать; мониторьте изменения.
4. **Изоляция DNS-трафика**: Выделите VLAN для DNS-серверов.
5. **Резервные DNS-серверы**: Минимум 2 независимых рекурсивных резолвера.

## Безопасность

- **DNS Spoofing / Cache Poisoning**: Подмена DNS-ответов для перенаправления трафика. Защита: DNSSEC, DNS over TLS, резервные резолверы.
- **/etc/hosts как вектор атаки**: Злоумышленник с root-доступом может перенаправить трафик через `/etc/hosts`. Мониторьте изменения: `aide --check`, `tripwire`.
- **DNS Rebinding**: Атака, при которой DNS-ответ меняется после прохождения CORS/файрвола. Защита: проверка `Host` заголовка, DNS-пиннинг.
- **Разрешение внутренних имён через публичные DNS**: Если контейнер использует `8.8.8.8`, внутренние имена (`db.internal`) не разрешатся. Всегда настраивайте корпоративный DNS.
- **DNS tunneling**: Использование DNS для передачи данных (Data Exfiltration). Мониторьте аномальные DNS-запросы (большой объём TXT-запросов, необычные домены).

## Дополнительная информация

### Рекомендации по предотвращению

1. **Запрет ручных правок:** Использование **IaC (Infrastructure as Code)** (Ansible, Terraform) для управления конфигурациями файлов `/etc/hosts` и `/etc/resolv.conf`.
2. **Динамический Service Discovery:** Переход на Consul или Kubernetes DNS, где управление именами полностью автоматизировано.
3. **Мониторинг конфигураций:** Настройка алертов на изменение контрольных сумм критических файлов системы (NSS, Hosts).
4. **Проверки при старте (Healthchecks):** Включение в процедуру запуска приложения проверки версии схемы БД, чтобы сервис не переходил в `Ready`, если база данных «не та».
5. **Валидация DNS перед деплоем:** В CI/CD pipeline добавить проверку `dig` для критичных имён перед развёртыванием.

### Инструментарий диагностики

- **`getent hosts <name>`** — лучший способ проверить разрешение имени так, как его видит приложение.
- **`dig`** — для проверки чистого ответа DNS-сервера. См. **[Инструмент dig](../../Linux/Diagnostics/Networking/dns/dig_tool.md)**.
- **`strace`** — позволяет увидеть, какой именно файл (hosts или resolv.conf) открывает приложение при попытке сетевого вызова.
- **`resolvectl`** — для систем с `systemd-resolved`.
- **`tcpdump port 53`** — для захвата DNS-трафика и проверки, что запросы доходят до сервера.
- **`resolvectl statistics`** — статистика DNS-запросов: количество, типы, ошибки.
- **`systemd-resolve --status`** — полная информация о конфигурации и статусе DNS.

### См. также

- **[Диагностика DNS в Docker](../../Docker/Docker_network/troubleshooting/dns_resolution_issues.md)**
- **[DNS и Service Discovery в Docker](../../Docker/Docker_network/dns_and_service_discovery.md)**
- **[Порядок разрешения имён в Linux](../../Linux/Diagnostics/Networking/dns/name_resolution.md)** — подробный разбор NSS и приоритетов.
- **[DNS-клиент в Linux](../../Linux/Networking/Concepts/dns_client.md)** — конфигурация и принципы работы.
- **[Производительность DNS-резолвинга](../../Linux/Diagnostics/Networking/dns/dns_resolution_performance.md)** — ndots, Happy Eyeballs, оптимизация.
- **[Анализ сокетов (ss)](../../Linux/Diagnostics/Networking/ss.md)** — для верификации конечного IP-адреса установленного соединения.
- **[Мониторинг DNS](../Protocols/DNS/dns_monitoring.md)** — SLA, метрики, алертинг.
- **[Протокол DNS](../Protocols/DNS/dns.md)** — общая теория, типы записей, иерархия.
- **[Концепции DNS](../Protocols/DNS/dns_concepts.md)** — базовые понятия DNS.
