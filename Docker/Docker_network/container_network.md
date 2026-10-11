# Режим сети `container`: общий сетевой namespace

**Актуально для:** Docker Engine 29.x

## Определения

- **`--network container:<имя|id>`** — режим подключения, при котором контейнер не получает собственный сетевой stack, а присоединяется к сетевому пространству имён (netns) уже работающего контейнера, который в этой базе знаний называется **целевым**.
- **Sandbox (sandbox-контейнер)** — изолированный сетевой stack одного контейнера: netns, veth-пара, адреса, правила firewall и встроенный DNS-резолвер. Sandbox принадлежит целевому контейнеру; у контейнера в режиме `container:` своего sandbox нет.
- **Endpoint (эндпоинт)** — запись о подключении контейнера к сети в `NetworkSettings.Networks`. У контейнера в режиме `container:` эндпоинтов нет вообще — поле пустое.
- **Sidecar (коляска)** — вспомогательный контейнер, разделяющий сетевой namespace с основным: реверс-прокси, агент доставки логов, сетевой наблюдатель.
- **Pause-контейнер** — минимальный контейнер, единственная задача которого — удерживать sandbox, пока в него присоединяются остальные. Образ `pause` взят из состава Kubernetes и перенесён в Docker для этого паттерна.
- **netns inode** — значение вида `net:[4026532831]`, возвращаемое `readlink /proc/self/ns/net`. Одинаковый inode означает, что два процесса находятся в одном сетевом пространстве имён.

## Как это работает

Docker не создаёт для контейнера в режиме `container:` ни sandbox, ни endpoint, ни пару veth-интерфейсов. Вместо этого процесс нового контейнера при старте вызывает системный вызов `setns(2)` и переводит себя в сетевое пространство имён целевого контейнера. Дальше всё происходит в чужом netns: сокеты, маршруты, DNS и правила firewall принадлежат целевому контейнеру.

```
Хост
└── Sandbox целевого контейнера  (владеет всем ниже)
    ├── netns  net:[4026532831]
    │   ├── eth0  172.18.0.2   ← veth, одна на весь sandbox
    │   ├── lo
    │   ├── таблица маршрутизации, шлюз 172.18.0.1
    │   ├── правила iptables/nftables этого sandbox
    │   └── встроенный DNS-резолвер 127.0.0.11
    │
    ├── PID 1  — процесс целевого контейнера
    ├── PID 57 — процесс контейнера в режиме container:   ┐
    └── PID 88 — ещё один такой же контейнер              ┘
                  все три видят eth0, lo, маршруты и 127.0.0.11
```

Проверка идентичности пространства имён:

```bash
docker network create demo-net

docker run -d --name target --network demo-net nginx:alpine

docker run -d --name sidecar --network container:target \
  alpine:3.22 sleep 3600

# Оба процесса должны показать одинаковый inode
docker exec target  readlink /proc/self/ns/net
# → net:[4026532831]
docker exec sidecar readlink /proc/self/ns/net
# → net:[4026532831]

# Интерфейс тоже один и тот же — вплоть до индекса ядра (eth0@if86)
docker exec target  ip -o link show eth0 | cut -c1-60
# → 11: eth0@if86: <BROADCAST,MULTICAST,UP,LOWER_UP,M-DOWN> mtu 1500
docker exec sidecar ip -o link show eth0 | cut -c1-60
# → 11: eth0@if86: <BROADCAST,MULTICAST,UP,LOWER_UP,M-DOWN> mtu 1500
```

Цепочки разрешены: контейнер в режиме `container:` может сам быть целью для третьего. Все три окажутся в одном netns.

## Что разделяется, а что нет

Разделяется только сеть. Остальные подсистемы контейнеризации изолированы, и это важно не путать — hostname, PID и IPC требуют отдельных флагов.

| Ресурс | Разделяется? | Как проверено |
| :--- | :--- | :--- |
| Сетевой namespace | **да** | одинаковый `net:[...]` в `/proc/self/ns/net` |
| Интерфейсы, IP, MAC, шлюз, MTU | **да** | `ip -o link show eth0` идентичен |
| `/etc/hosts` | **да**, общий bind-mount | запись в целевом контейнере видна в sidecar |
| `/etc/resolv.conf` | **да**, общий bind-mount | одинаковый inode `stat -c %i` в обоих |
| Значение имени хоста | **да** | `uname -n` в sidecar возвращает имя целевого |
| UTS namespace | нет | inode `uts:[...]` различается |
| PID namespace | нет | `ps` в sidecar показывает только свои процессы |
| IPC namespace | нет | нужен отдельный `--ipc container:<имя>` |
| Mount namespace | нет | `mnt:[...]` различается |
| Файловая система | нет | только через `--volumes-from` или тома |

### Общие `/etc/hosts` и `/etc/resolv.conf`

Это не копия, а один и тот же файл: изменение, сделанное в любом из контейнеров, немедленно видно во втором.

```bash
docker exec target sh -c 'echo "10.0.0.5 legacy-db" >> /etc/hosts'
docker exec sidecar tail -1 /etc/hosts
# → 10.0.0.5 legacy-db
```

Практические следствия:

- **Можно** централизованно дописывать статические записи из одного контейнера, и sidecar увидит их сразу — без перезапуска.
- **Нельзя** считать `/etc/hosts` и `/etc/resolv.conf` изолированными: любой процесс в обоих контейнерах, запущенный от root, переписывает их для обоих. У sidecar-агента, работающего с правами root, это вектор неожиданной правки сетевых настроек основного приложения.
- Имя хоста наследуется, но задать его нельзя: флаг `--hostname` в этом режиме запрещён (см. ниже), а UTS namespace при этом остаётся собственным.

## Ограничения, которые накладывает daemon

### Отклоняемые параметры

Проверено на Docker Engine 29.8.1. Ошибка возвращается на этапе создания контейнера, до запуска.

| Параметр | Ошибка демона |
| :--- | :--- |
| `-p`, `--publish` | `conflicting options: port publishing and the container type network mode` |
| `-P`, `--publish-all` | `conflicting options: port publishing and the container type network mode` |
| `--expose` | `conflicting options: port exposing and the container type network mode` |
| `--hostname` | `conflicting options: hostname and the network mode` |
| `--add-host` | `conflicting options: custom host-to-IP mapping and the network mode` |
| `--dns` | `conflicting options: dns and the network mode` |
| `--link` | `conflicting options: container type network can't be used with links. This would result in undefined behavior` |
| `--network-alias` | `network-scoped aliases are only supported for user-defined networks` |
| `--ip`, `--ip6` | `invalid config for network container:<id>: invalid endpoint settings: user-specified IP address is supported on user-defined networks only` |

Причина у `--ip` и `--network-alias` одна: демон не создаёт для такого контейнера эндпоинт, а сеть вида `container:<id>` не проходит проверку «это пользовательская сеть». Алиас и адрес задавать некуда — их некуда записать.

### Параметры, которые принимаются, но ничего не делают

Расхождение между документацией и поведением демона. Docker Docs перечисляют `--mac-address`, `--dns-search` и `--dns-option` в списке неподдерживаемых, но Engine 29.8.1 их принимает без ошибки и молча игнорирует.

| Параметр | Фактическое поведение в 29.8.1 |
| :--- | :--- |
| `--mac-address` | принят, MAC-адрес не меняется — остаётся адрес целевого |
| `--dns-search` | принят, строка `search` в `/etc/resolv.conf` не появляется |
| `--dns-option` | принят, в `/etc/resolv.conf` остаются опции целевого контейнера |

```bash
# --mac-address «применяется», но не имеет эффекта
docker run --rm --mac-address 02:42:ac:1c:00:77 --network container:target \
  alpine:3.22 sh -c 'ip -o link show eth0' | grep -o 'ether [0-9a-f:]*'
# → ether da:8a:6c:53:f0:d2   (тот же, что у целевого, а не 02:42:ac:1c:00:77)
```

Практический вывод: опираться на эти три флага нельзя — они создают иллюзию настройки. Если требуется изменить DNS-конфигурацию, её нужно задавать целевому контейнеру.

### Подключение к другим сетям невозможно

```bash
docker network connect demo-net sidecar
# → Error response from daemon: container sharing network namespace with
#   another container or host cannot be connected to any other network
```

Архитектурно это верно: у контейнера нет собственного эндпоинта, который можно было бы добавить в сеть. Следствие для автоматизации: `NetworkSettings.Networks` у такого контейнера — пустой объект, и `docker ps` не показывает для него ни одной сети и ни одного порта. Инвентаризация, опирающаяся на это поле, «не увидит» sidecar.

```bash
docker inspect -f '{{json .NetworkSettings.Networks}}' sidecar
# → {}
docker inspect -f '{{json .HostConfig.PortBindings}}' sidecar
# → {}
docker inspect -f '{{.HostConfig.NetworkMode}}' sidecar
# → container:30ab24892d797fe3196cfcbe34c094c8af4cb2bfd2eaf89f56c509ec4d73ba26
```

## Публикация портов: правило общего netns

Правила DNAT привязаны к адресу в сети, а не к процессу. Поэтому **порт, опубликованный на целевом контейнере, обслуживает любой процесс, слушающий этот порт в общем netns** — включая процесс из sidecar. Обратное тоже верно: если целевой контейнер не слушает опубликованный порт, его обслужит sidecar.

```bash
# Целевой контейнер публикует порт, но сам ничего не слушает
docker run -d --name target --network demo-net -p 18090:90 \
  alpine:3.22 sleep 3600

# Слушатель живёт только в sidecar
docker run -d --name sidecar --network container:target \
  alpine:3.22 sh -c 'while true; do \
    printf "HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\nSIDECAR" | nc -l -p 90; done'

curl -s http://127.0.0.1:18090/
# → SIDECAR
```

Это свойство делает паттерн с pause-контейнером рабочим, и именно на нём держится любая схема, где публикация портов должна пережить перезапуск приложения.

## Жизненный цикл и отказоустойчивость

Самое важное свойство режима: **контейнер в режиме `container:` не падает вместе с целевым и не переподключается к нему**. Он продолжает работать в netns, который больше никем не обслуживается.

| Событие | Состояние sidecar | Сеть | DNS |
| :--- | :--- | :--- | :--- |
| Целевой работает | `running` | работает | работает |
| `docker stop target` | `running` | маршрута нет | не резолвится |
| `docker start target` | `running` | маршрута по-прежнему нет | не резолвится |
| Целевой пересоздан | `running` | требуется пересоздать sidecar | — |

При остановке целевого его sandbox освобождается: veth-пара и встроенный DNS-резолвер исчезают вместе с ним. Sidecar продолжает находиться в освободившемся netns, в котором не осталось ни интерфейса `eth0`, ни маршрута по умолчанию.

```bash
# Пока целевой жив
docker exec sidecar sh -c 'getent hosts target; wget -qO- -T2 http://127.0.0.1:80/ | head -c 20'
# → 172.20.0.2        target
# → <!DOCTYPE html>

docker stop target

# Через несколько секунд — целевой процесс пропал, сеть деградировала
docker inspect -f '{{.State.Status}}' sidecar
# → running                      ← контейнер жив, проблема не видна в docker ps
docker exec sidecar sh -c 'getent hosts target || echo NO_DNS'
# → NO_DNS
docker exec sidecar ping -c1 -W2 172.20.0.1 2>&1 | tail -1
# → ping: sendto: Network unreachable
```

Перезапуск целевого не восстанавливает связь: контейнер получает **новый** sandbox с новым netns и, как правило, новым IP, а sidecar остаётся в старом.

```bash
docker start target
docker exec target  readlink /proc/self/ns/net
# → net:[4026533962]              ← новый
docker exec sidecar readlink /proc/self/ns/net
# → net:[4026534084]              ← старый, осиротевший
```

**Правило: перезапуск целевого контейнера требует пересоздания всех контейнеров, работающих в его netns.** Пересоздание (а не перезапуск) — обязательное условие.

### Swarm

Режим `container:` недоступен для сервисов Swarm: демон трактует значение как имя сети.

```bash
docker service create --name svc --network container:target alpine:3.22 sleep 60
# → Error response from daemon: network container:target not found
```

Схемы с sidecar, разделяющим сеть, — это local mode и Docker Compose. В Swarm задача решается на уровне overlay-сетей и VIP, а не разделением netns; см. раздел про routing mesh в [обзоре сетевой модели](./docker_network.md#swarm-routing-mesh).

### Docker Compose

Compose знает о зависимости и стартует сервис-цель раньше зависимого, а `restart` распространяется на зависимые сервисы (в развёрнутом конфиге это `depends_on: {app: {condition: service_started, restart: true}}`):

```bash
docker compose restart app
# → Container app-1        Restarting / Started
# → Container sidecar-1    Restarting / Started   ← Compose перезапустил и его
```

Прямой вызов `docker restart` в обход Compose этого не делает и оставляет тихую поломку:

```bash
docker restart ctest-app-1
docker compose exec -T sidecar sh -c 'getent hosts app || echo NO_DNS'
# → NO_DNS
```

Практическое правило: если в проекте есть сервисы с `network_mode: "service:..."`, любые операции с жизненным циклом целевого сервиса выполняйте через `docker compose`, а не через `docker restart` / `docker stop` напрямую.

### Прочие проверенные границы

- **Целевой контейнер в режиме `host`** — допустимо. Sidecar получает сетевой namespace хоста целиком, вместе со всеми интерфейсами. Это не «изоляция», а полный доступ к сети хоста.
- **Присоединение к приостановленному контейнеру** — допустимо: `docker pause` на целевом не мешает присоединиться к его netns.
- **Restart policy** на целевом (`--restart=always`) разрушительнее, чем кажется: демон пересоздаст sandbox, а sidecar останется в старом netns. Для схем с sidecar политика перезапуска должна быть на обоих контейнерах синхронной, а не только на целевом.

## Практические сценарии

### Сценарий 1: диагностика приложения без оболочки

Основное назначение режима в SRE-практике. Контейнер с утилитами запускается в чужом netns и видит то же состояние сети, что и приложение.

```bash
# 1. Запустить приложение на пользовательской сети
docker network create diag-net
docker run -d --name app-backend --network diag-net -p 18080:80 nginx:alpine

# 2. Открыть его сетевое пространство имён
docker run --rm -it --network container:app-backend nicolaka/netshoot
```

Внутри — состояние сети приложения. Сокеты `127.0.0.11` в выводе — это встроенный DNS-резолвер, живущий в том же sandbox:

```text
Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process
udp   UNCONN 0      0         127.0.0.11:60977      0.0.0.0:*
tcp   LISTEN 0      511          0.0.0.0:80         0.0.0.0:*
tcp   LISTEN 0      4096      127.0.0.11:43589      0.0.0.0:*
tcp   LISTEN 0      511             [::]:80            [::]:*

$ nslookup app-backend
Server:		127.0.0.11
Address:	127.0.0.11#53

Non-authoritative answer:
Name:	app-backend
Address: 172.20.0.2

$ curl -s http://127.0.0.1/ | head -c 30
<!DOCTYPE html>
```

Обратите внимание на пустую колонку `Process`. `ss -p` не показывает, кто именно слушает порт, потому что PID namespace не разделяется: отладочный контейнер просто не видит процессов приложения. Чтобы получить имена процессов, добавьте `--pid container:`:

```bash
docker run --rm --network container:app-backend --pid container:app-backend \
  --cap-add SYS_PTRACE --security-opt seccomp=unconfined \
  nicolaka/netshoot ss -tulpn
# → tcp   LISTEN 0  511  0.0.0.0:80  0.0.0.0:*
#          users:(("nginx",pid=39,fd=6),("nginx",pid=38,fd=6),...,("nginx",pid=1,fd=6))
```

Это самая частая причина недоразумённой диагностики: сеть видна, порты видны, а «владелец» порта не определяется.

Отдельно про DNS: `nslookup` работает, только если целевой контейнер запущен на пользовательской сети. На дефолтной сети `bridge` встроенного резолвера нет, `nameserver` в `resolv.conf` указывает на хост, и имя не разрешится:

```text
$ nslookup app-df
** server can't find app-df: NXDOMAIN
```

Тот же приём применяется для захвата трафика: `tcpdump -i eth0 -nn port 80` из netshoot видит те же пакеты, что и процесс приложения, потому что интерфейс у них один. Подробнее — в материалах по [диагностике сетевых проблем](../Docker_troubleshooting/network_connectivity_issues.md) и [отладке distroless-контейнеров](../Docker_troubleshooting/debugging_distroless.md).

### Сценарий 2: pause-контейнер как владелец netns

Позволяет перезапускать приложение, не теряя опубликованные порты и не пересоздавая sidecar-контейнеры.

```bash
# 1. Pause-контейнер владеет sandbox и публикацией портов
docker run -d --name net-holder -p 18095:80 registry.k8s.io/pause:3.10

# 2. Приложение и sidecar присоединяются к его netns
docker run -d --name app       --network container:net-holder nginx:alpine
docker run -d --name sidecar   --network container:net-holder \
  alpine:3.22 sleep 3600

# 3. Публикация работает — слушает приложение
curl -s http://127.0.0.1:18095/ | head -c 30
# → <!DOCTYPE html>
```

Теперь приложение можно пересоздать, не трогая `net-holder`:

```bash
docker rm -f app
docker run -d --name app --network container:net-holder nginx:alpine
curl -s http://127.0.0.1:18095/ | head -c 30
# → <!DOCTYPE html>          ← порт и IP те же, sidecar не затронут
```

Ограничения паттерна:

- Образ берётся из `registry.k8s.io/pause:3.10`; `pause:3.11` и выше не существуют. Прежний путь `mirror.gcr.io/google_containers/pause` больше не отдаёт теги — запрос списка возвращает пустой массив, и pull падает.
- Несколько контейнеров присоединяются к одному net-holder параллельно: ограничения на число присоединённых нет, ограничение — конфликты портов и общие `/etc/hosts`.
- Pause-контейнер — это держатель, а не прокси. Он не пересылает трафик и не участвует в обработке запросов; его роль — удерживать sandbox.

### Сценарий 3: sidecar с доступом к процессам приложения

Сетевой namespace не даёт доступа к процессам. Для `strace`, `gdb` и разбора поведения приложения нужен отдельный флаг `--pid container:<имя>`, а для общей памяти — `--ipc container:<имя>`.

```bash
# Целевой контейнер с долгоживущим процессом
docker run -d --name app-backend --network demo-net nginx:alpine

# Подключение к его PID namespace
docker run --rm -it \
  --pid container:app-backend \
  --cap-add SYS_PTRACE \
  --security-opt seccomp=unconfined \
  alpine:3.22 sh

# Внутри
apk add strace
ps -o pid,args          # видны процессы целевого контейнера, а не свои
strace -p 1
# → strace: Process 1 attached
```

Форма с `--cap-add SYS_PTRACE --security-opt seccomp=unconfined` — рекомендуемая переносимая: она требуется там, где ptrace ограничивают LSM-политики (AppArmor, SELinux) или где цель не является dumpable. На стоковом хосте с Docker Engine 29.8.1 и ядром по умолчанию `strace -p 1` подключается и без этих флагов — целевой процесс dumpable, а ptrace внутри одного user namespace ядро разрешает по умолчанию. Полагаться на это в production-диагностике не стоит.

Флаг `--ipc container:<имя>` работает иначе: он даёт общий `/dev/shm` и разделяемые сегменты SysV/POSIX. Это отдельный канал обмена данными, минующий сетевой стек:

```yaml
services:
  app:
    image: my-app:latest
    ipc: "shareable"        # донор общего IPC namespace

  worker:
    image: my-worker:latest
    ipc: "service:app"      # присоединяется к IPC донору
    depends_on:
      - app
```

Механизмы namespaces разобраны в [пространствах имён Linux](../../Linux/Core/namespaces.md); общая память и IPC — в [IPC Linux](../../Linux/Core/processes/ipc.md).

### Сценарий 4: Compose с `network_mode: service:`

```yaml
services:
  app:
    image: nginx:alpine
    ports:
      - "18110:80"            # публикация только здесь
    volumes:
      - app-logs:/var/log/app

  sidecar-proxy:
    image: nginx:alpine
    network_mode: "service:app"
    volumes:
      - ./sidecar-nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - app-logs:/var/log/app:ro

  sidecar-logger:
    image: fluent/fluent-bit:latest
    network_mode: "service:app"
    volumes:
      - app-logs:/var/log/app:ro

volumes:
  app-logs:
```

Ключевые правила:

- `ports:` указываются **только** на сервисе-владельце. Compose не отвергает `ports:` у зависимого сервиса на этапе валидации, но падает при запуске, и ошибка атрибутируется зависимому сервису:
  ```text
  service:sidecar:1 Error response from daemon: conflicting options:
  port publishing and the container type network mode
  ```
- Compose выводит зависимость по `network_mode: "service:X"` автоматически — в развёрнутом `docker compose config` она выглядит так, и отдельный `depends_on` не обязателен (но не повредит для читаемости):
  ```yaml
  sidecar:
    depends_on:
      app:
        condition: service_started
        restart: true
        required: true
    network_mode: "service:app"
  ```
  Флаг `restart: true` — это и есть механизм распространения `docker compose restart` на зависимые сервисы.
- Сервис с `network_mode: "service:X"` нельзя подключить к дополнительным сетям: Compose отвергает это сам, до обращения к демону — `service sidecar declares mutually exclusive network_mode and networks: invalid compose project`.
- Пересоздание сервиса-владельца (`docker compose up -d --force-recreate`) восстанавливает сеть для всех зависимых сервисов; `docker compose restart` делает это тоже, а прямой `docker restart` — нет.

Проверка результата:

```bash
docker compose up -d
docker compose exec -T sidecar-logger sh -c 'getent hosts app; wget -qO- -T2 http://127.0.0.1:80/ | head -c 20'
# → 172.20.0.2        app
# → <!DOCTYPE html>
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:18110/
# → HTTP 200
```

Справочник по Compose — в [примерах docker compose](../Docker_compose/docker_compose_file_example.md) и [продвинутых темах Compose](../Docker_compose/docker_compose_advanced_topics.md).

## Устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `joining network namespace of container: No such container: <id>` | целевого контейнера нет | `docker ps -a --filter name=<id>` | создать целевой контейнер или исправить имя |
| `cannot join network namespace of a non running container: container <id> is created` | целевой контейнер создан, но не запущен | `docker ps -a --filter name=<id>` | `docker start <id>` |
| `conflicting options: port publishing and the container type network mode` | указан `-p` или `-P`; в Compose — `ports:` у сервиса с `network_mode: "service:..."` | `docker compose config` ошибку не покажет, проверяйте при `up` | убрать флаги; публиковать порт на целевом контейнере |
| `conflicting options: port exposing and the container type network mode` | указан `--expose` | — | убрать флаг; `EXPOSE` целевого образа действует и на sidecar |
| `conflicting options: hostname and the network mode` | указан `--hostname` | — | убрать флаг; имя наследуется от целевого |
| `conflicting options: dns and the network mode` | указан `--dns` | `docker exec <target> cat /etc/resolv.conf` | убрать флаг; настроить DNS на целевом контейнере |
| `network-scoped aliases are only supported for user-defined networks` | указан `--network-alias` | — | убрать флаг; алиасов у sidecar не бывает |
| `service sidecar declares mutually exclusive network_mode and networks` | у сервиса с `network_mode: "service:..."` задан `networks:` | `docker compose config` | убрать `networks:`; сеть задаётся владельцу |
| `container sharing network namespace with another container or host cannot be connected to any other network` | попытка `docker network connect` для контейнера в этом режиме | `docker inspect -f '{{json .NetworkSettings.Networks}}' <sidecar>` → `{}` | сеть задаётся только целевому контейнеру |
| `ss -p` из контейнера в режиме `container:` не показывает процесс, слушающий порт | PID namespace не разделяется | `docker exec <target> readlink /proc/self/ns/pid` и то же для sidecar — inode различаются | добавить `--pid container:<имя>` (плюс `--cap-add SYS_PTRACE --security-opt seccomp=unconfined`) |
| `bind: Address in use` / `nginx: [emerg] still could not bind()` | два процесса в одном netns слушают один порт | `docker exec <target> ss -tulpn` | освободить порт в одном из контейнеров либо развести на разные порты |
| Sidecar `running`, но `NO_DNS` и `Network unreachable` | целевой остановлен или перезапущен | `docker exec <a> readlink /proc/self/ns/net` и то же для `b` — inode разошлись | пересоздать sidecar: `docker restart` целевого недостаточно |
| `docker ps` не показывает у sidecar ни сети, ни портов | ожидаемо: у него нет эндпоинтов | `docker inspect -f '{{json .NetworkSettings.Networks}}' <sidecar>` → `{}` | проверять конфигурацию по целевому контейнеру |
| Sidecar не может разрешить имя целевого, хотя сеть пользовательская | проверяется не тот контейнер либо целевой пересоздан | `docker exec <target> cat /etc/resolv.conf` | смотреть резолвер целевого; при расхождении inode — пересоздать sidecar |

Диагностическая команда, которая сразу показывает проблему с netns:

```bash
for c in target sidecar; do
  printf '%-10s state=%s netns=%s\n' "$c" \
    "$(docker inspect -f '{{.State.Status}}' $c)" \
    "$(docker exec $c readlink /proc/self/ns/net)"
done
# → target     state=running netns=net:[4026533962]
# → sidecar    state=running netns=net:[4026534084]   ← расхождение: sidecar осиротел
```

Альтернативный способ зайти в чужой netns без запуска контейнера — `nsenter` по пути `/var/run/docker/netns/<id>`; он разобран в [диагностике ядра и сети Linux](../../Linux/Diagnostics/Kernel/dmesg/network-stack.md) и в [nsenter](../../Linux/Diagnostics/Processes/nsenter.md). Учтите, что на Docker Desktop для macOS и Windows путь недоступен из хостовой файловой системы — сеть живёт в виртуальной машине, и нужен либо `docker exec`, либо `vpnkit`, либо режим `container:`.

## Рекомендации

- **Используйте `container:` для диагностики, а не как основную схему развёртывания.** Режим лишает контейнер эндпоинта, делает невозможной изоляцию и создаёт скрытую связь между жизненным циклом двух контейнеров. Для постоянной схемы применяйте общие тома, общий PID namespace или отдельный сетевой интерфейс.
- **Держите число присоединённых контейнеров минимальным.** Каждый из них делит один IP и портовое пространство с целевым; конфликт портов и неожиданная перезапись `/etc/hosts` — прямое следствие.
- **Всегда задавайте целевому контейнеру `--name`.** Ссылка `container:<имя>` переживает пересоздание контейнера, тогда как `container:<id>` ломается после `docker rm` + `docker run`.
- **Не задавайте sidecar `--restart=always` в одиночку.** Перезапуск целевого не восстановит сеть sidecar; без пересоздания он продолжит работать в мёртвом netns и выглядеть исправным.
- **Режим в Compose безопаснее, чем вручную:** Compose перезапускает зависимые сервисы вместе с владельцем. Не обходите `docker compose` прямыми вызовами `docker restart` / `docker stop`, если в проекте есть `network_mode: "service:..."`.
- **Не полагайтесь на `--mac-address`, `--dns-search`, `--dns-option`** — они принимаются, но не применяются. Проверяйте фактическую конфигурацию в целевом контейнере.
- **Sidecar, пишущий в общий `/etc/hosts` или `/etc/resolv.conf`, должен работать не от root.** Файлы общие, и запись, сделанная агентом, немедленно изменяет сетевые настройки основного приложения.
- **Для аудита используйте `docker inspect`, а не `docker ps`:** у sidecar пустые `NetworkSettings.Networks` и `PortBindings`, и инвентаризация по выводу `docker ps` их пропустит.

### Очистка и откат

Режим не меняет состояние хоста, поэтому откат — это удаление присоединённых контейнеров. Побочных артефактов (правил firewall, сетей, томов) режим не создаёт, откатывать нечего.

```bash
# 1. Удалить присоединённые контейнеры
docker rm -f sidecar

# 2. Вернуть sidecar на обычную сеть
docker run -d --name sidecar --network demo-net <image>

# 3. Удалить сеть и держатель netns, если они больше не нужны
docker network rm demo-net
docker rm -f net-holder
```

Порядок важен: сначала sidecar, потом net-holder. Удаление целевого первым оставит sidecar в осиротевшем netns, и диагностика следующего инцидента станет сложнее.

## Ограничения, о которых нужно знать заранее

- Режим недоступен в Swarm: `docker service create --network container:<id>` завершается ошибкой поиска сети.
- Контейнер в этом режиме нельзя подключить к дополнительным сетям — эндпоинта не существует.
- `docker restart` целевого **не** восстанавливает сеть sidecar и **не** приводит к его остановке: нужен `docker compose up -d --force-recreate` или явное пересоздание.
- Публиковать порты и задавать имя хоста, DNS, алиасы, адреса в режиме `container:` нельзя — только на целевом контейнере.
- Порт занят, если два процесса в общем netns слушают один адрес; ошибка возникает у второго процесса, а не у демона.
- Конфликт портов диагностируется только изнутри общего netns: `docker ps` покажет один и тот же порт у нескольких контейнеров только как «неизвестный источник», и по нему источник не определить.
- Docker Desktop для macOS и Windows реализует сеть в виртуальной машине, поэтому проверки через `/var/run/docker/netns/` и `nsenter` с хоста там недоступны.

## Дополнительная информация

### Смежные темы

- [Обзор сетевой модели Docker](./docker_network.md) — архитектура CNM, sandbox и endpoint, драйверы, Swarm routing mesh.
- [Драйвер `host`](./drivers/host.md) — предельный случай: полное разделение сетевого namespace с хостом.
- [Драйвер `none`](./drivers/none.md) — противоположный полюс: контейнер без сети.
- [Проблемы разрешения имён DNS](./troubleshooting/dns_resolution_issues.md) — встроенный резолвер `127.0.0.11`, отладка из чужого netns.
- [Взаимодействие с iptables и nftables](./troubleshooting/iptables_integration.md) — где физически живут правила sandbox и почему sidecar меняет их вместе с целевым.
- [Docker Exec и отладка в контейнерах](../Docker_troubleshooting/docker_debug.md) — штатная альтернатива режиму `container:`.
- [EXPOSE, -p и -P](../Dockerfile/Instructions/networking_ports.md) — семантика публикации портов на уровне образа и CLI.

### Смежные технологии

- [Пространства имён в Linux](../../Linux/Core/namespaces.md) и [ip netns](../../Linux/Networking/Tools/iproute2/ip_netns.md) — механизм, лежащий в основе режима.
- [Агенты доставки логов: Vector](../../Vector/vector_overview.md) и [Fluent Bit](../../ELK_Stack/filebeat_overview.md) — типичные sidecar-роли, реализуемые поверх этого режима.
- [Podman Pods](../../Podman/podman_pods.md) — близкая по смыслу модель общего netns в альтернативном runtime.
