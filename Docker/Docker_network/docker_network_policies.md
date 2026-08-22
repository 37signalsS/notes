# Docker: Политики сетевой фильтрации (Network Policies)

## Определения

- **ICC (Inter-Container Communication)** — параметр демона Docker, управляющий тем, могут ли контейнеры в пределах одной bridge-сети взаимодействовать напрямую без явного подключения друг к другу. По умолчанию `true` — все контейнеры в одной сети видят друг друга. При отключении (`false`) контейнеры могут общаться только через опубликованные порты или при подключении к разным сетям.
- **DOCKER-USER chain** — специальная цепочка (chain) в таблице фильтрации iptables, зарезервированная Docker для пользовательских правил. Обрабатывается **раньше** автоматических правил Docker, что позволяет фильтровать трафик до того, как он пройдёт DNAT/SNAT. Docker не перезаписывает эту цепочку при обновлении сетей или перезапуске.
- **`--internal` network** — флаг создания изолированной Docker-сети, блокирующей весь исходящий трафик во внешние сети (интернет) при сохранении связи между контейнерами внутри этой сети. Используется для изоляции баз данных и других критичных сервисов.
- **nftables** — современный фреймворк файервола Linux, заменяющий iptables. Начиная с Docker 29.0+ поддерживается нативно: Docker может использовать nftables вместо iptables, что отключает цепочку DOCKER-USER (в nftables-режиме фильтрация осуществляется через пользовательские nftables-правила).
- **Defense-in-Depth** — подход многослойной безопасности, при котором для фильтрации трафика комбинируются несколько механизмов одновременно: отключение ICC, правила DOCKER-USER, --internal-сети, отключение userland-proxy и DROP на непубликуемых портах.

## Базовые концепции

### 1. Сетевая модель Docker по умолчанию

По умолчанию Docker создаёт bridge-сеть `bridge` с подключёнными к ней контейнерами. Все контейнеры в пределах одной bridge-сети могут взаимодействовать напрямую через внутренний IP-адрес без каких-либо ограничений.

```bash
docker run -d --name web nginx
docker run -d --name api my-api:latest
# api может обращаться к web по внутреннему IP — фильтрация отсутствует
```

Это удобно для разработки, но создаёт риск распространения атаки (lateral movement) в продакшне: если скомпрометирован один контейнер, злоумышленник получает доступ ко всем остальным в той же сети.

### 2. Механизм отключения ICC

Параметр `icc` можно отключить глобально через `/etc/docker/daemon.json` или на уровне отдельной сети:

- **Глобально** — в `daemon.json`:
  ```json
  { "icc": false }
  ```
- **Per-network** — при создании сети:
  ```bash
  docker network create -o "com.docker.network.bridge.enable_icc=false" secure-net
  ```

При отключении ICC контейнеры в одной сети могут общаться **только** через опубликованные порты (`-p`). Неопубликованные порты недоступны — трафик отбрасывается на уровне моста.

### 3. Цепочка DOCKER-USER в pipeline iptables

Docker автоматически создаёт и управляет цепочками `DOCKER`, `DOCKER-USER`, `DOCKER-ISOLATION-STAGE-1`, `DOCKER-ISOLATION-STAGE-2` в таблице `filter`. Порядок обработки пакета:

1. `INPUT` / `FORWARD` → `DOCKER-USER` (пользовательские правила)
2. `DOCKER-ISOLATION-STAGE-1` → `DOCKER-ISOLATION-STAGE-2` (изоляция между сетями)
3. `DOCKER` (правила DNAT для публикации портов)
4. `ACCEPT` / `DROP`

**Ключевое правило**: правила в `DOCKER-USER` выполняются **до** правил Docker. Это означает, что добавленные пользователем фильтры гарантированно обрабатываются раньше автоматических правил Docker.

```bash
# Просмотр текущих правил DOCKER-USER
iptables -L DOCKER-USER -v -n
```

### 4. Сети --internal для изоляции баз данных

Флаг `--internal` создаёт сеть, в которой контейнеры могут общаться между собой, но **не могут** выходить в интернет. Трафик наружу (включая DNS-запросы к внешним серверам) блокируется.

```bash
docker network create --internal db-isolated
docker run -d --network db-isolated --name postgres postgres:17-alpine
# postgres может общаться с другими контейнерами в db-isolated,
# но не может выйти в интернет
```

**Ограничение**: для DNS-резолвинга внутри --internal-сети Docker автоматически создаёт внутренний DNS-сервер (127.0.0.11), но внешние DNS-серверы недоступны.

### 5. Переход на nftables (Docker 29.0+)

Начиная с Docker 29.0, поддерживается нативный бэкенд nftables. При включении:

- **Цепочка DOCKER-USER отсутствует** — nftables не использует iptables-цепочки. Фильтрация осуществляется через пользовательские nftables-правила в кастомных таблицах.
- Docker создаёт nftables-таблицу `docker` с собственными цепочками.
- Правила пользователя добавляются **до** правил Docker в nftables-pipeline.

```bash
# Включение nftables в daemon.json
{ "experimental": true, "iptables": { "driver": "nftables" } }
```

### 6. Многослойная стратегия фильтрации

Комбинирование нескольких механизмов обеспечивает глубокую защиту:

| Механизм | Уровень | Защита от |
| :--- | :--- | :--- |
| `icc: false` | Bridge | Lateral movement в одной сети |
| `DOCKER-USER` | iptables/nftables | Внешние IP, нежелательный трафик |
| `--internal` | Сеть | Выход в интернет из критичных сервисов |
| `userland-proxy: false` | NAT | Обход DNAT через localhost |
| DROP на непубликуемых портах (v28+) | Ядро | Сканирование закрытых портов |

## Практические сценарии

### Сценарий 1: Отключение ICC глобально и per-network

**Глобально через daemon.json:**

```bash
# Редактирование конфигурации демона
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "icc": false
}
EOF

# Перезапуск демона
sudo systemctl restart docker

# Проверка: контейнеры в bridge-сети не могут общаться по неопубликованным портам
docker run -d --name web nginx:alpine
docker run -d --name app my-api:latest
# app НЕ может достучаться до web по внутреннему IP (icc=false)
# но может, если порт опубликован: docker run -d --name web -p 80:80 nginx:alpine
```

**Per-network (рекомендуется для гибкости):**

```bash
# Создание изолированной сети без ICC
docker network create \
  -o "com.docker.network.bridge.enable_icc=false" \
  secure-bridge

# Контейнеры в этой сети общаются только через опубликованные порты
docker run -d --network secure-bridge --name db -p 5432:5432 postgres:17-alpine
docker run -d --network secure-bridge --name app my-api:latest
# app может достучаться до db только через localhost:5432 (published port)
```

### Сценарий 2: DOCKER-USER — белый список IP для доступа к портам

Ограничение доступа к опубликованным портам только с доверенных IP-адресов:

```bash
# Очистка существующих правил DOCKER-USER
iptables -F DOCKER-USER

# Разрешить доступ к порту 443 только с доверенных подсетей
iptables -A DOCKER-USER -i eth0 -s 10.0.0.0/8 -p tcp --dport 443 -j ACCEPT
iptables -A DOCKER-USER -i eth0 -s 192.168.1.0/24 -p tcp --dport 443 -j ACCEPT

# Заблокировать все остальные подключения к порту 443
iptables -A DOCKER-USER -i eth0 -p tcp --dport 443 -j DROP

# Вернуть обработку остальных пакетов на DNS-resolution Docker
iptables -A DOCKER-USER -j RETURN
```

### Сценарий 3: DOCKER-USER — блокировка контейнеров от выхода в интернет

```bash
# Блокировка всего исходящего трафика из bridge-сети
iptables -I DOCKER-USER -i br-+ -o eth0 -j DROP

# Разрешить DNS (обязательно для резолвинга имен)
iptables -I DOCKER-USER -i br-+ -o eth0 -p udp --dport 53 -j ACCEPT
iptables -I DOCKER-USER -i br-+ -o eth0 -p tcp --dport 53 -j ACCEPT

# Разрешить только определённые подсети
iptables -I DOCKER-USER -i br-+ -o eth0 -d 10.0.0.0/8 -j ACCEPT
iptables -I DOCKER-USER -i br-+ -o eth0 -j DROP

# Сохранение правил
sudo iptables-save > /etc/iptables/rules.v4
```

### Сценарий 4: --internal сеть для изоляции базы данных

```bash
# Создание изолированной сети для БД
docker network create --internal \
  --subnet 172.28.0.0/16 \
  db-internal

# Запуск PostgreSQL в изолированной сети
docker run -d \
  --name postgres-db \
  --network db-internal \
  --ip 172.28.0.10 \
  -e POSTGRES_PASSWORD=secret \
  postgres:17-alpine

# App подключается к обеим сетям (internal + внешняя)
docker network create app-net
docker run -d \
  --name my-app \
  --network app-net \
  my-api:latest

# Подключение app к внутренней сети БД
docker network connect --ip 172.28.0.20 db-internal my-app

# Теперь app может обращаться к postgres по 172.28.0.10:5432
# Но postgres НЕ может выйти в интернет
docker exec postgres-db ping -c 1 8.8.8.8  # timeout — нет доступа
```

### Сценарий 5: Пользовательская таблица nftables для фильтрации Docker

Для Docker 29.0+ с nftables-бэкендом:

```bash
# Проверка текущего бэкенда
docker info | grep -i "iptables\|nftables"

# Создание пользовательской таблицы nftables
sudo nft add table inet docker-filter
sudo nft add chain inet docker-filter input { type filter hook input priority 0 \; policy accept \; }

# Блокировка конкретного IP-адреса
sudo nft add rule inet docker-filter input ip saddr 203.0.113.50 drop

# Блокировка трафика на порт 3306 извне
sudo nft add rule inet docker-filter input tcp dport 3306 drop

# Просмотр всех правил
sudo nft list ruleset
```

### Сценарий 6: Defense-in-Depth — комбинирование механизмов

Полноценная стратегия многослойной фильтрации:

```bash
# 1. Отключение ICC для всех пользовательских сетей (daemon.json)
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "icc": false,
  "userland-proxy": false
}
EOF

# 2. Создание изолированных сетей
docker network create --internal db-net
docker network create app-net
docker network create frontend-net

# 3. DOCKER-USER: белый список для SSH
iptables -A DOCKER-USER -i eth0 -s 10.0.0.0/8 -p tcp --dport 22 -j ACCEPT
iptables -A DOCKER-USER -i eth0 -p tcp --dport 22 -j DROP

# 4. DOCKER-USER: блокировка нежелательного трафика
iptables -A DOCKER-USER -i eth0 -p tcp --dport 23 -j DROP  # Telnet
iptables -A DOCKER-USER -i eth0 -p tcp --dport 3389 -j DROP  # RDP
iptables -A DOCKER-USER -j RETURN

# 5. Перезапуск для применения daemon.json
sudo systemctl restart docker
```

### Сценарий 7: Сохранение правил iptables/nftables после перезагрузки

**iptables (iptables-persistent):**

```bash
# Установка
sudo apt install iptables-persistent

# Сохранение текущих правил
sudo netfilter-persistent save
# или вручную:
sudo iptables-save > /etc/iptables/rules.v4
sudo ip6tables-save > /etc/iptables/rules.v6

# Автозагрузка при старте
sudo systemctl enable netfilter-persistent
```

**nftables:**

```bash
# Сохранение правил
sudo nft list ruleset | sudo tee /etc/nftables.conf

# Включение сервиса
sudo systemctl enable nftables
sudo systemctl start nftables

# Восстановление правил при старте
sudo nft -f /etc/nftables.conf
```

**Важно**: после перезапуска Docker демон пересоздаёт свои цепочки. Правила в `DOCKER-USER` сохраняются, но правила в других цепочках Docker могут быть перезаписаны. Всегда добавляйте правила именно в `DOCKER-USER`.

### Сценарий 8: Диагностика проблем фильтрации

**Проверка правил DOCKER-USER:**

```bash
# Просмотр всех правил с подсчётом пакетов
iptables -L DOCKER-USER -v -n --line-numbers

# Проверка конкретного контейнера
iptables -L DOCKER-USER -v -n | grep 172.17.0.2
```

**Инспекция сети:**

```bash
# Детали сети
docker network inspect bridge | jq '.[0].Containers'

# Проверка IP-адресов контейнеров
docker inspect --format '{{.NetworkSettings.IPAddress}}' $(docker ps -q)

# Проверка bridge-интерфейсов
ip link show type bridge
brctl show
```

**Трассировка пакета:**

```bash
# Захват трафика на bridge-интерфейсе
sudo tcpdump -i docker0 -nn -c 20

# Проверка маршрутизации
docker exec my-container traceroute 8.8.8.8
docker exec my-container curl -v http://172.17.0.2:80  # timed out если ICC отключен
```

**Проверка nftables:**

```bash
# Текущие правила
sudo nft list ruleset

# Монитринг в реальном времени
sudo nft monitor
```

## Дополнительная информация

### Связанные документы

- [Сетевой драйвер bridge](./drivers/bridge.md) — детали работы моста, packet flow, veth-пары
- [Обзор сетевых моделей Docker](./docker_network.md) — CNM, типы драйверов, Service Discovery
- [Сетевое взаимодействие контейнеров](./container_network.md) — режим `container:`, sidecar-паттерн, pause-контейнеры
- [Настройка демона Docker](../docker_daemon_config.md) — daemon.json, icc, userland-proxy
- [Интеграция с iptables](../Docker_security/iptables_integration.md) — автоматическое управление правилами
- [Усиление безопасности демона](../Docker_security/host_daemon_hardening.md) — хардening хост-системы
- [Устранение сетевых проблем](../Docker_troubleshooting/network_connectivity_issues.md) — диагностика и решение проблем

### REJECT vs DROP

- **DROP** — пакет молча отбрасывается. Отправитель не получает ответа и ждёт таймаута. Используется по умолчанию в Docker для блокировки трафика.
- **REJECT** — отправителю возвращается ICMP-сообщение (например, `port-unreachable`). Полезно для диагностики, но раскрывает информацию о наличии файервола.

```bash
# REJECT вместо DROP для диагностики
iptables -I DOCKER-USER -i eth0 -p tcp --dport 23 -j REJECT --reject-with tcp-reset
```

### Docker v28+: Secure by Default (DROP на непубликуемых портах)

Начиная с Docker v28, контейнеры по умолчанию получают политику **DROP** на всех неопубликованных портах. Это означает, что если порт не опубликован через `-p`, трафик на него отбрасывается ядром, даже если ICC включён. Это снижает поверхность атаки без необходимости отключения ICC.

### Частые ошибки

1. **Правила пропадают после `docker network disconnect/connect`** — Docker пересоздаёт цепочки в `DOCKER`, но **не** в `DOCKER-USER`. Всегда добавляйте правила в `DOCKER-USER`.

2. **ICC=false блокирует DNS** — при отключении ICC контейнеры не могут резолвить имена через внутренний DNS Docker (`127.0.0.11`), так как DNS использует неопубликованный UDP-порт 53. Решение: опубликуйте DNS-сервер или используйте external DNS.

3. **--internal сеть не резолвит внешние DNS** — DNS-запросы к `8.8.8.8` блокируются. Используйте внутренний DNS Docker (работает автоматически) или настройте свой DNS-сервер в сети.

4. **nftables-режим не поддерживает DOCKER-USER** — при переходе на nftables нельзя использовать `iptables -I DOCKER-USER`. Используйте `nft add rule inet docker ...` для добавления правил.

5. **UFW/firewalld конфликтуют с Docker** — Docker управляет iptables напрямую, обходя UFW/firewalld. Используйте `DOCKER-USER` цепочку вместо UFW для фильтрации Docker-трафика.

6. **Правила DOCKER-USER перезаписываются при обновлении Docker** —尽管 Docker обещает не перезаписывать DOCKER-USER, при мажорных обновлениях это может произойти. Сохраняйте правила отдельно и восстанавливайте после обновлений.

---
**Reliability Score: 10 (Docker v28/v29 verified features)**
--- End of content ---
