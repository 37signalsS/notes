# Политики сетевой фильтрации Docker (Network Policies)

**Актуально для:** Docker Engine 28.x / 29.x (проверено на 29.8.1, бэкенд `iptables`)

Docker не имеет механизма сетевых политик уровня Kubernetes: нет объекта «политика», нет
селекторов, нет автоматического применения к контейнерам. Политика сетевой фильтрации на
хосте с Docker собирается вручную из четырёх независимых механизмов. Этот файл — о том, что
каждый из них **реально** блокирует, где в цепочке обработки он срабатывает и как доказать,
что он сработал.

## Определения

- **Бэкенд файрвола** (`firewall-backend`) — реализация, которой Docker управляет
  собственными правилами: `iptables` (по умолчанию) или экспериментальный `nftables`
  (с Docker 29.0). Определяется в `daemon.json` или флагом `dockerd`. Активный бэкенд
  виден в `docker info` в поле `Firewall Backend`.
- **ICC** (Inter-Container Communication) — возможность контейнеров одной bridge-сети
  обращаться друг к другу напрямую, минуя публикацию портов. Управляется опцией сети
  `com.docker.network.bridge.enable_icc` (по умолчанию `true`). Для сети `bridge` по
  умолчанию — параметром демона `icc` / `--icc`.
- **`DOCKER-USER`** — цепочка в таблице `filter`, зарезервированная Docker для
  пользовательских правил. Единственная цепочка, которую Docker не перезаписывает и в
  которую можно добавлять правила без риска конфликта.
- **Direct routing** — обращение к контейнеру напрямую по его IP-адресу, в обход
  опубликованных портов хоста. Возможно только при наличии маршрута к подсети сети.
- **Gateway mode** (`com.docker.network.bridge.gateway_mode_ipv4/ipv6`) — режим внешней
  связности сети: `nat` (по умолчанию), `nat-unprotected`, `routed`, `isolated`.
- **`raw` PREROUTING** — хук, который выполняется **до** таблицы `filter`. Именно там
  Docker 28.2+ блокирует direct routing, поэтому правило в `DOCKER-USER` не может его
  отменить.
- **DNAT** — подстановка адреса и порта назначения. К моменту, когда пакет попадает в
  `DOCKER-USER`, DNAT уже выполнен: сопоставлять можно только внутренние адреса и порты
  контейнеров.

## Как устроена фильтрация

### Модель доступа по умолчанию

Docker реализует сегментацию не политиками, а структурой сетей и цепочками iptables.
Поведение bridge-сети без дополнительных настроек:

| Источник трафика | К опубликованному порту | К неопубликованному порту контейнера |
| :--- | :--- | :--- |
| Хост Docker | разрешено | разрешено |
| Контейнер в той же сети | разрешено | разрешено |
| Контейнер в другой сети этого же хоста | разрешено через адрес хоста | запрещено |
| Удалённый хост (прямой маршрут к IP контейнера) | запрещено | запрещено |
| Удалённый хост (адрес опубликованного порта) | разрешено | — |

Обратите внимание на строку 3 и строку 2: «разрешено через адрес хоста» означает, что
контейнер должен знать IP хоста и опубликованный порт. Прямого маршрута между разными
bridge-сетями нет.

### Порядок обхода цепочек

Реальный вывод `iptables -S` на хосте с Docker Engine 29.8.1 (сокращённо):

```bash
sudo iptables -S | grep -E '^-A FORWARD|^-N DOCKER'
# → -N DOCKER
# → -N DOCKER-BRIDGE
# → -N DOCKER-CT
# → -N DOCKER-FORWARD
# → -N DOCKER-INTERNAL
# → -N DOCKER-USER
# → -A FORWARD -j DOCKER-USER
# → -A FORWARD -j DOCKER-FORWARD
```

Внутри `DOCKER-FORWARD` порядок фиксирован:

```bash
sudo iptables -L DOCKER-FORWARD -v -n --line-numbers
# → num   pkts bytes target         prot opt in              out
# → 1    64321  271M DOCKER-CT      all  --  *               *
# → 2    64290  271M DOCKER-INTERNAL all  --  *               *
# → 3    64290  271M DOCKER-BRIDGE   all  --  *               *
# → 4    35044  262M ACCEPT         all  --  docker0         *
# → 5        0     0 DROP           all  --  br-d35cae11c229 br-d35cae11c229
# → 6        5   355 ACCEPT         all  --  br-d35cae11c229 !br-d35cae11c229
```

Полный путь пакета:

```text
FORWARD
  └─ DOCKER-USER          ← единственное место для пользовательских правил
  └─ DOCKER-FORWARD
       ├─ DOCKER-CT       established/related для каждого моста
       ├─ DOCKER-INTERNAL изоляция сетей, созданных с --internal
       ├─ DOCKER-BRIDGE   → DOCKER: правила по опубликованным портам
       ├─ DOCKER          ACCEPT по опубликованным портам, иначе DROP
       └─ ACCEPT / DROP   по интерфейсам мостов, безусловные
```

Цепочек `DOCKER-ISOLATION-STAGE-1` и `DOCKER-ISOLATION-STAGE-2`, встречающихся в старой
документации и ответах в интернете, в Docker 28/29 **нет**. Их роль распределена между
`DOCKER-BRIDGE` (разрешение по опубликованным портам), `DOCKER-INTERNAL` (`--internal`) и
`DOCKER-CT` (connection tracking). Диагностика, построенная на поиске `DOCKER-ISOLATION`,
в современных версиях бесполезна.

### Что попадает в `DOCKER-USER`, а что нет

Это главное ограничение, которое ломает большинство правил. К моменту входа пакета в
`DOCKER-USER`:

- **уже выполнен DNAT** — `--dport` совпадает с портом *внутри контейнера*, а не с
  опубликованным портом хоста;
- пакет уже прошёл `raw` PREROUTING, то есть direct routing отфильтрован без возможности
  вмешательства;
- цепочка вызывается только из `FORWARD`, то есть видит только межсетевой трафик. Трафик
  самого демона к контейнеру (`OUTPUT`, `docker-proxy`, `dockerd`) в неё не попадает.

Практический вывод: правило `-p tcp --dport 443` в `DOCKER-USER` не означает «порт 443 на
хосте». Оно означает «порт 443 такого-то контейнера».

Если нужно сопоставление по исходному адресу и порту запроса, Docker Docs предлагают
расширение `conntrack`:

```bash
sudo iptables -A DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -A DOCKER-USER -m conntrack --ctorigdst 192.0.2.10 --ctorigdstport 443 -j ACCEPT
```

Официальная документация предупреждает: расширение `conntrack` может снизить
производительность. Для правил с ограничением по источнику используйте `-s`/`--src-range`,
для ограничения по опубликованным интерфейсам — `com.docker.network.bridge.host_binding_ipv4`.

### Слепая зона: direct routing

Docker 28.0 перестал полагаться на политику `FORWARD` хоста и добавил блокировку
неопубликованных портов в цепочку `DOCKER`. Docker 28.2 перенёс эту блокировку в
`raw` PREROUTING — по одному правилу на контейнер, без указания порта и протокола.

```bash
sudo iptables -t raw -S PREROUTING
# → -A PREROUTING ! -i docker0 * -d 172.18.0.2 -j DROP
```

Следствия, которые важно понимать до написания правил:

- `DROP` в `raw` — окончательное решение. Правило `ACCEPT` в `DOCKER-USER` его **не**
  переопределит.
- Отключить блокировку можно только штатными средствами: `allow-direct-routing`
  (все опубликованные порты), `com.docker.network.bridge.trusted_host_interfaces`
  (конкретные интерфейсы хоста и конкретная сеть) либо gateway mode `nat-unprotected`
  (для совместимости со старым поведением доступны все порты).
- «Неопубликованные порты защищены по умолчанию» означает защиту **от обращений извне
  хоста**. Внутри сети между контейнерами все порты по-прежнему открыты — см. ниже.

### Почему UFW и firewalld не защищают опубликованные порты

Docker выполняет DNAT в таблице `nat`, которая обрабатывается до `filter`. Пакет,
адресованный опубликованному порту, перенаправляется на порт контейнера и уже не
пересекает цепочки `INPUT`/`OUTPUT`, которыми управляет ufw. Правило
`ufw deny 443` не влияет на `docker run -p 443:443`.

Практические следствия для администратора:

- фильтрацию Docker-трафика ведут в `DOCKER-USER`, а не в ufw;
- при включённом firewalld Docker дополнительно создаёт зону `docker` с target `ACCEPT` и
  политику `docker-forwarding`; интерфейсы мостов помещаются в эту зону, поэтому
  правила firewalld на них не применяются;
- `ip-forward-no-drop: true` в `daemon.json` возвращает глобальную политику `FORWARD` в
  `ACCEPT`, но **не** отключает блокировку неопубликованных портов — она реализована
  отдельными правилами.

Полная интеграция с UFW (включая инструмент `ufw-docker`) и пошаговая диагностика конфликтов Docker с ufw/firewalld — в [UFW — интеграция с Docker](../../Linux/Networking/Settings/tools/ufw.md) и [Диагностика Docker + ufw/firewalld](../../Linux/Diagnostics/Networking/firewall_troubleshooting.md).

## Механизмы фильтрации

### 1. ICC: отключение межконтейнерного взаимодействия

Два способа задать значение, и они **не равнозначны по области действия**:

| Способ | К какой сети относится |
| :--- | :--- |
| `"icc": false` в `daemon.json` / `dockerd --icc=false` | только сеть `bridge` по умолчанию (`docker0`) |
| `-o com.docker.network.bridge.enable_icc=false` при `docker network create` | только что созданная сеть |

Опция демона не влияет на пользовательские сети, созданные ранее или позже: у них
собственный дефолт `enable_icc=true`. Аудит сводится к проверке опции у каждой сети:

```bash
docker network inspect <сеть> --format '{{.Name}} internal={{.Internal}} {{json .Options}}'
# → secure-net internal=false {"com.docker.network.bridge.enable_icc":"false",...}
```

Что именно блокируется при `enable_icc=false` — установлено экспериментально на
Docker 29.8.1:

```bash
docker network create -o com.docker.network.bridge.enable_icc=false icc-off
docker run -d --name a --network icc-off nginx:alpine
docker run -d --name b --network icc-off alpine:3.22 sleep 300
A=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' a)

docker exec b wget -qO- --timeout=4 "http://$A/"
# → (пусто, таймаут)  — трафик отброшен

docker exec b nslookup a
# → Name:	a
# → Address: 172.21.0.3     — DNS работает

docker exec b nslookup example.com
# → Address: 172.66.147.243 — внешний DNS работает

docker exec b wget -qO- --timeout=5 http://example.com/
# → <!doctype html>...      — выход в интернет работает
```

Механизм — два безусловных правила в `DOCKER-FORWARD`, а не правило в `DOCKER`:

```bash
sudo iptables -S DOCKER-FORWARD | grep -- '-o br-'
# → -A DOCKER-FORWARD -i br-d35cae11c229 -o br-d35cae11c229 -j DROP
# → -A DOCKER-FORWARD -i br-d35cae11c229 ! -o br-d35cae11c229 -j ACCEPT
```

Следствия, которые ломают ожидания:

- Блокируется **весь** трафик внутри сети, включая обращение к опубликованному порту через
  адрес хоста: пакет возвращается в тот же мост и попадает под то же правило.
- DNS **не** блокируется. Распространённое утверждение обратного — миф; встроенный
  резолвер `127.0.0.11` слушает в netns контейнера и не проходит через `FORWARD`.
- Выход в интернет **не** блокируется: второе правило явно разрешает трафик наружу.
- Сравните с обычной сетью (`enable_icc` не задан) — там в `DOCKER-FORWARD` есть только
  `-i br-… -j ACCEPT`, и неопубликованные порты доступны:

```bash
docker exec b wget -qO- --timeout=4 "http://$A/"
# → <!DOCTYPE html>        — общение напрямую по IP, публикация не требуется
```

Поэтому `enable_icc=false` — не инструмент микросегментации «разрешить приложению БД, но
запретить всё остальное». Это инструмент полного замыкания сети, в котором исключены даже
те приложения, которым вы хотите разрешить связь. Для разграничения по парам контейнеров
используйте отдельные сети, а для фильтрации по признакам — `DOCKER-USER`.

### 2. Сеть `--internal`

Флаг `--internal` реализуется двумя правилами в цепочке `DOCKER-INTERNAL`:

```bash
docker network create --internal --subnet 172.30.5.0/24 int-net
docker run -d --name db --network int-net postgres:17-alpine
docker run -d --name app --network int-net alpine:3.22 sleep 300

sudo iptables -S DOCKER-INTERNAL
# → -A DOCKER-INTERNAL ! -s 172.30.5.0/24 -o br-0a532e992162 -j DROP
# → -A DOCKER-INTERNAL ! -d 172.30.5.0/24 -i br-0a532e992162 -j DROP
```

Проверка поведения:

```bash
docker exec app nslookup db
# → Name:	db
# → Address: 172.30.5.3                       — имена внутри сети работают

docker exec app nslookup example.com
# → ** server can't find example.com: SERVFAIL — внешний DNS не резолвится

docker exec app ip route
# → 172.30.5.0/24 dev eth0 scope link src 172.30.5.2
#   (маршрута по умолчанию нет вообще)

docker exec app wget -qO- --timeout=4 http://1.1.1.1/
# → wget: can't connect to remote host (1.1.1.1): Network unreachable
```

Практические следствия для эксплуатации:

- Внутренние имена резолвятся, внешние — нет (`SERVFAIL`, а не `NXDOMAIN`: резолвер
  работает, но его запрос к апстрим-серверу отбрасывается). Если контейнеру нужен внешний
  DNS — передайте `--dns` и обеспечьте маршрут до него отдельно.
- Публикация порта контейнера из `--internal`-сети бессмысленна для контейнеров внутри:
  они обращаются к адресу моста и получают отказ. Для внешнего доступа контейнер должен
  быть подключён как минимум к двум сетям — внутренней и сетевой с выходом.
- `docker run --network <internal> <образ>` **работает**: образ вытягивается до
  создания контейнера, ограничение сети на загрузку не распространяется. Локального
  реестра с образами в `--internal`-сети, наоборот, недостичь нельзя — это рабочий
  приём для изолированных контуров.
- Образование gateway mode `isolated` допустимо только вместе с `--internal`; в этом
  режиме адрес моста не назначается вовсе.

### 3. `DOCKER-USER`: правила на хосте

Цепочка обрабатывается первой в `FORWARD` и принадлежит администратору. Два рабочих
шаблона.

> **Порядок правил.** Много-правиловые примеры ниже используют `-A` (append):
> порядок в листинге совпадает с порядком в цепочке. `-I` вставляет правило в
> начало — при нескольких `-I` подряд итоговый порядок обратный, и `DROP`
> окажется выше `RELATED,ESTABLISHED`, разрывая установленные соединения.
> Одинокие правила добавляйте через `-I`, если они должны иметь приоритет
> над правилами, добавленными позже.

**Шаблон «белый список по источнику».** Предпочтительнее, чем `ACCEPT` + `DROP` в конце:
правило выражает намерение напрямую, не зависит от порядка и не требует отдельной строки
для обратного трафика.

```bash
# Обратный трафик по уже установленным соединениям — обязательно перед DROP
# Правила добавляются через -A (append): порядок в листинге = порядок в цепочке
sudo iptables -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

# Опубликованные порты доступны только с доверенной подсети
sudo iptables -A DOCKER-USER -i eth0 -s 192.0.2.0/24 -j ACCEPT
sudo iptables -A DOCKER-USER -i eth0 -s 198.51.100.0/24 -j ACCEPT
sudo iptables -A DOCKER-USER -i eth0 -j DROP
```

Ограничение `-i eth0` привязывает правило к одному внешнему интерфейсу и распространяет
фильтрацию только на трафик Docker. Чтобы правило действовало на любую внешнюю сеть
независимо от режима gateway, опустите `-i` и ограничьте источник:

```bash
sudo iptables -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
sudo iptables -A DOCKER-USER -s 192.0.2.0/24 -j ACCEPT
sudo iptables -A DOCKER-USER -j DROP
```

Осторожно с `-i` и в обратную сторону: правило `-o eth0` без ограничения источника
заблокирует исходящий трафик всех контейнеров, включая ответы на уже установленные
соединения, если правило `RELATED,ESTABLISHED` не стоит выше.

**Шаблон «разрешить диапазон адресов».** Для точечных исключений:

```bash
sudo iptables -I DOCKER-USER -m iprange -i eth0 ! --src-range 192.0.2.1-192.0.2.3 -j DROP
```

**Шаблон «заблокировать egress контейнеру».** Идентифицируйте контейнер по адресу, а не по
интерфейсу: адрес меняется при пересоздании, интерфейс назначается сетью.

```bash
sudo iptables -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
sudo iptables -A DOCKER-USER -s 172.30.5.0/24 ! -d 172.30.5.0/24 -j DROP
```

Правило выбрасывает трафик из подсети наружу, сохраняя связь внутри сети. Оно не мешает
публикации портов, потому что входящий опубликованный трафик идёт с адреса *хоста*,
а не из подсети.

### 4. Бэкенд `nftables` (экспериментально, Docker 29.0+)

Ключ конфигурации — `firewall-backend`, а не `iptables.driver`:

```json
{
  "firewall-backend": "nftables"
}
```

Здесь важна только семантика фильтрации; порядок перехода и команды миграции разобраны в
[Интеграции Docker с iptables и nftables](./troubleshooting/iptables_integration.md) и
[nftables — интеграция с Docker](../../Linux/Networking/Settings/tools/nftables/docker_integration.md).

Ограничения бэкенда, влияющие на политику:

- поддержка экспериментальная — ключ, поведение и реализация могут измениться;
- правила overlay-сетей не мигрированы, поэтому **включить нельзя при работающем Swarm**;
- Docker больше не включает IP forwarding сам и не создаёт политику `drop` по умолчанию.

Семантические отличия, из-за которых правило из `DOCKER-USER` не переносится дословно:

| Свойство | `iptables` / `DOCKER-USER` | `nftables` |
| :--- | :--- | :--- |
| Окончательность `ACCEPT` | окончателен в рамках `FORWARD` | завершает только свою базовую цепочку; другие цепочки того же хука продолжают обработку и могут отбросить пакет |
| Порядок выполнения | порядком правил в цепочке | приоритетом базовой цепочки: меньше — раньше |
| Отмена `DROP` Docker | правилом `ACCEPT` | только пометкой fwmark (`--bridge-accept-fwmark`) с приоритетом не выше `filter - 1` |
| Блокировка direct routing | недоступна: `DROP` в `raw` до `filter` | недоступна по той же причине; fwmark на неё не действует |

Вместо `DOCKER-USER` создаётся собственная таблица с базовой цепочкой на хуке `forward`,
приоритет которой ниже dockerовской:

```bash
sudo nft add table inet docker-filter
sudo nft add chain inet docker-filter forward \
  '{ type filter hook forward priority filter - 1 ; policy accept ; }'
sudo nft add rule inet docker-filter forward ct state established,related accept
sudo nft add rule inet docker-filter forward iifname "eth0" ip saddr != 192.0.2.0/24 drop
```

Два обязательных шага миграции, которые легко пропустить: политика `FORWARD` в iptables,
оставшаяся в `DROP` от прежнего режима, продолжит отбрасывать трафик, принятый правилами
Docker в nftables (лечится `iptables -P FORWARD ACCEPT`); переход
`FORWARD → DOCKER-USER` при старте с nftables демон не создаёт, поэтому старые правила
молча перестают работать — счётчики остаются нулевыми.

## Практические сценарии

### Сценарий 1: baseline перед изменением правил

Снимок исходного состояния — обязательный первый шаг: без него откат невозможен.

```bash
STAMP=$(date +%Y%m%d-%H%M)
sudo mkdir -p /var/backups/docker-netfilter/$STAMP
sudo iptables-save  > /var/backups/docker-netfilter/$STAMP/iptables.v4
sudo ip6tables-save > /var/backups/docker-netfilter/$STAMP/iptables.v6
sudo nft list ruleset > /var/backups/docker-netfilter/$STAMP/nftables.ruleset
docker info --format 'backend={{.FirewallBackend.Driver}}' \
  | sudo tee /var/backups/docker-netfilter/$STAMP/backend.txt
# → backend=iptables
```

Полезно сохранить и перечень сетей с их опциями — это «политика» в терминах Docker:

```bash
docker network ls -q | xargs -I{} \
  docker network inspect {} \
  --format '{{.Name}} driver={{.Driver}} internal={{.Internal}} {{json .Options}}' \
  | sudo tee /var/backups/docker-netfilter/$STAMP/networks.txt
```

### Сценарий 2: ограничение внешнего доступа к опубликованным портам

**Задача:** к опубликованным портам 8080 и 9090 допускаются только две доверенные подсети.
Остальной внешний трафик отбрасывается. Публикация на loopback и правила для Swarm не
затрагиваются.

```bash
# 1. Обратный трафик по установленным соединениям — первым
sudo iptables -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

# 2. Доверенные источники. -s без -i: работает при любом режиме gateway
sudo iptables -A DOCKER-USER -s 192.0.2.0/24 -j ACCEPT
sudo iptables -A DOCKER-USER -s 198.51.100.0/24 -j ACCEPT

# 3. Остальное — отброс
sudo iptables -A DOCKER-USER -j DROP
```

**Проверка:**

```bash
sudo iptables -L DOCKER-USER -v -n --line-numbers
# → num   pkts bytes target     prot opt in  out source     destination
# → 1     1842  132K ACCEPT     all  --  *   *   0.0.0.0/0  0.0.0.0/0   ctstate RELATED,ESTABLISHED
# → 2      311  21984 ACCEPT    all  --  *   *   192.0.2.0/24  0.0.0.0/0
# → 3       12    812 DROP      all  --  *   *   0.0.0.0/0  0.0.0.0/0
```

Ненулевые счётчики в строке 3 подтверждают, что правило действительно срабатывает, а не
просто присутствует в цепочке.

### Сценарий 3: запрет egress для контейнера, кроме своей подсети

**Задача:** контейнер в `172.30.5.0/24` не должен обращаться во внешние сети.

```bash
sudo iptables -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
sudo iptables -A DOCKER-USER -s 172.30.5.0/24 ! -d 172.30.5.0/24 -j DROP
```

**Проверка изнутри контейнера:**

```bash
docker exec app ping -c 2 172.30.5.3
# → 2 packets transmitted, 2 received, 0% packet loss

docker exec app ping -c 2 1.1.1.1
# → ping: sendmsg: Network is unreachable
```

Обратите внимание на порядок правил. Правила добавляются через `-A` (append): порядок
в листинге совпадает с порядком в цепочке. `-I` вставляет каждое правило в начало —
при нескольких `-I` подряд итоговый порядок обратный, `DROP` окажется выше
`RELATED,ESTABLISHED`, и весь трафик, включая ответы на уже установленные
соединения, будет отброшен. Проверить фактический порядок:
`sudo iptables -L DOCKER-USER -v -n --line-numbers`.

### Сценарий 4: разделение инфраструктуры по назначению

**Задача:** БД без выхода наружу; приложение — в отдельной сети с выходом; доступ к БД
только с адреса приложения.

```bash
docker network create --internal --subnet 172.30.5.0/24 db-net
docker network create --subnet 172.30.6.0/24 app-net

docker run -d --name postgres-db --network db-net postgres:17-alpine

docker run -d --name my-app --network app-net my-api:latest
docker network connect db-net my-app

APP_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' my-app)

sudo iptables -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
sudo iptables -A DOCKER-USER -d 172.30.5.0/24 ! -s "$APP_IP" -j DROP
```

Сеть `db-net` уже изолирует БД от интернета на уровне маршрутизации. Последнее правило
закрывает оставшийся вектор — прямой доступ к контейнерам `db-net` из других сетей хоста,
который иначе проходит через цепочку `DOCKER-BRIDGE`.

### Сценарий 5: персистентность правил без сохранения правил Docker

Правила, введённые через `iptables` вручную, живут только в памяти ядра. Сохранение
`iptables-save` целиком — ловушка: в файл попадут динамические правила Docker, которые
при следующем старте демона будут конфликтовать с его собственными.

Правильный способ — сервис, который применяет только `DOCKER-USER` после запуска Docker:

```bash
sudo tee /etc/systemd/system/docker-netfilter.service <<'EOF'
[Unit]
Description=Apply operator rules to the Docker DOCKER-USER chain
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/docker-netfilter-apply
ExecStop=/usr/local/sbin/docker-netfilter-clear

[Install]
WantedBy=multi-user.target
EOF

sudo tee /usr/local/sbin/docker-netfilter-apply <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

RULES=(
  "-m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"
  "-s 192.0.2.0/24 -j ACCEPT"
  "-s 198.51.100.0/24 -j ACCEPT"
  "-j DROP"
)

sudo iptables -N DOCKER-USER 2>/dev/null || true
sudo iptables -F DOCKER-USER

for rule in "${RULES[@]}"; do
  # shellcheck disable=SC2086
  sudo iptables -A DOCKER-USER $rule
done
EOF

sudo tee /usr/local/sbin/docker-netfilter-clear <<'EOF'
#!/usr/bin/env bash
sudo iptables -F DOCKER-USER 2>/dev/null || true
EOF

sudo chmod +x /usr/local/sbin/docker-netfilter-{apply,clear}
sudo systemctl daemon-reload
sudo systemctl enable --now docker-netfilter.service
```

Для nftables роль этого сервиса выполняет `nftables.service` с `/etc/nftables.conf`,
куда в `include "/etc/nftables.d/*.nft"` помещается таблица `docker-filter`.

Проверка после перезагрузки:

```bash
systemctl is-enabled docker-netfilter.service
# → enabled
sudo iptables -S DOCKER-USER | wc -l
# → 4
```

### Сценарий 6: переход на бэкенд `nftables`

Порядок обязателен — иначе после перезапуска демона не будет ни маршрутизации, ни
фильтрации. Полная процедура с командами приведена в
[Интеграции Docker с iptables и nftables](./troubleshooting/iptables_integration.md);
здесь зафиксированы только контрольные точки, специфичные для политики.

```bash
# Контрольная точка 1: Swarm не активен — с ним бэкенд несовместим
docker info --format '{{.Swarm.LocalNodeState}}'
# → inactive

# Контрольная точка 2: снимок правил для откката
sudo iptables-save > /root/iptables-before-nftables.v4

# Контрольная точка 3: forwarding поднимается вручную, демон этого больше не делает
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1

# Контрольная точка 4: политика FORWARD не должна остаться в DROP
sudo iptables -P FORWARD ACCEPT

# Контрольная точка 5: после перезапуска с новым бэкендом
docker info --format '{{.FirewallBackend.Driver}}'
# → nftables
sudo iptables -S DOCKER-USER
# → iptables: No chain/target/match by that name.
```

Откат: вернуть предыдущий `daemon.json`, выполнить
`iptables-restore < /root/iptables-before-nftables.v4`, перезапустить демон.

## Диагностика и валидация

### Определить, какое правило сработало

Счётчики пакетов — единственный надёжный способ отличить «правило не сработало» от
«правило не применено». Обнулите счётчики, воспроизведите проблему, посмотрите прирост:

```bash
sudo iptables -Z DOCKER-FORWARD
# воспроизвести неудачное соединение
sudo iptables -L DOCKER-FORWARD -v -n --line-numbers
# → 5        0     0 DROP  all  --  br-d35cae11c229 br-d35cae11c229
# → 6       14   840 ACCEPT all -- br-d35cae11c229 !br-d35cae11c229
```

Ненулевой счётчик у `DROP` на строке 5 при нулевом у `ACCEPT` на строке 6 доказывает, что
трафик шёл внутри одного моста и был отброшен именно правилом изоляции сети. Для
`DOCKER-USER` процедура такая же: обнулите цепочку, повторите попытку подключения,
сравните прирост по строкам.

### Проверить изоляцию сети

```bash
docker network inspect <сеть> --format '{{json .Options}}'
# → {"com.docker.network.bridge.enable_icc":"false",...}

sudo iptables -S DOCKER-FORWARD | grep -- "-o br-"
# пусто — изоляция внутри сети не настроена
```

### Проверить, работает ли политика вообще

```bash
# Активный бэкенд
docker info --format '{{.FirewallBackend.Driver}}'
# → iptables

# Цепочка существует и не пуста
sudo iptables -S DOCKER-USER
# -N DOCKER-USER
# -A DOCKER-USER -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

# IP forwarding
sysctl net.ipv4.ip_forward
# → net.ipv4.ip_forward = 1

# Мосты и их адреса — входные данные для правил
ip -o -4 addr show type bridge
# → 16: docker0    inet 172.17.0.1/16 brd ...
# → 85: br-1ac0...  inet 172.18.0.1/16 brd ...
```

### Типовые симптомы

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Правило в `DOCKER-USER` есть, счётчик нулевой | правило не в пути пакета: трафик не идёт через `FORWARD` (обращение с самого хоста, через `docker-proxy`) | `ip route get <ip:port>`, `iptables -L OUTPUT -v -n` | фильтруйте на маршруте или в `OUTPUT`, а не в `DOCKER-USER` |
| Правило `--dport 443` не срабатывает при `-p 8443:443` | в `DOCKER-USER` уже выполнен DNAT, `--dport` — это порт контейнера | `iptables -t nat -L DOCKER -v -n` | указывайте порт контейнера либо используйте `--ctorigdstport` |
| Удалённый хост не может попасть на неопубликованный порт вопреки `-s trusted -j ACCEPT` | `DROP` в `raw` PREROUTING срабатывает раньше `filter` и окончателен | `iptables -t raw -S PREROUTING` | `allow-direct-routing`, `trusted_host_interfaces` или `nat-unprotected` |
| После `docker network disconnect/connect` поведение изменилось, правила целы | Docker пересоздал правила цепочки `DOCKER`/`DOCKER-FORWARD` под новую конфигурацию сети | `iptables -S DOCKER-FORWARD` | правьте по фактическим правилам, не по памяти |
| Правила `DOCKER-USER` пропали после перезапуска демона | они были только в памяти ядра | `systemctl status docker-netfilter.service` | оформите сервис из сценария 5 |
| Правила `DOCKER-USER` пропали после перехода на nftables | демон не создаёт переход `FORWARD → DOCKER-USER` | `iptables -S FORWARD` | перенесите правила в собственную таблицу nftables |
| Работало до перехода на nftables, теперь не публикуются порты | политика `FORWARD` осталась `DROP` от iptables-режима | `iptables -L FORWARD` → `Chain FORWARD (policy DROP)` | `iptables -P FORWARD ACCEPT` |
| В `--internal` сети `nslookup` даёт `SERVFAIL` | встроенный резолвер есть, запрос к апстриму отброшен `DOCKER-INTERNAL` | `docker exec <c> ip route` — нет маршрута по умолчанию | `--internal` несовместим с внешним DNS без отдельного маршрута |
| После `icc=false` контейнер не видит соседа, но видит интернет | так и задумано: правило `-i br -o br -j DROP` | `iptables -S DOCKER-FORWARD \| grep -- '-o br-'` | разделяйте сервисы по сетям вместо отключения ICC |

## Рекомендации

- **Фильтруйте источник, а не интерфейс.** Правило с `-s` работает при любом режиме
  gateway и любом интерфейсе; правило с `-i eth0` молча перестаёт действовать при смене
  сетевого интерфейса хоста.
- **Первым правилом всегда ставьте `RELATED,ESTABLISHED`.** Без него `DROP` разрывает
  уже установленные соединения и ломает не только доступ, но и возврат ответов.
- **Не сохраняйте `iptables-save` целиком.** В файл попадут правила Docker, которые
  конфликтуют с демоном. Сохраняйте только содержимое `DOCKER-USER` и применяйте его
  сервисом после старта Docker.
- **Не используйте `enable_icc=false` как микросегментацию.** Механизм не различает
  приложения внутри сети. Разделяйте стек на несколько сетей.
- **Проверяйте политику счётчиками, а не наличием строки.** Правило без прироста
  счётчика после проверки не работает.
- **Держите `daemon.json` под контролем версий.** `icc`, `firewall-backend`,
  `allow-direct-routing`, `ip-forward-no-drop`, `userland-proxy` меняют поведение
  существующих сетей; после изменения нужен перезапуск демона и сверка `docker network ls`
  и `iptables -S`.
- **Включайте `firewall-backend: nftables` только после проверки отсутствия Swarm.** Это
  необратимое изменение правил на хосте, и откат требует ручного восстановления.
- **Не правьте таблицы `docker-bridges` в nftables.** Docker считает их своими и
  перезаписывает при любом изменении сетей.

## Очистка и откат

```bash
# 1. Вернуть счётчики и убрать пользовательские правила
sudo iptables -F DOCKER-USER

# 2. Отключить сервис персистентности, иначе он вернёт правила при следующем старте
sudo systemctl disable --now docker-netfilter.service
sudo rm -f /usr/local/sbin/docker-netfilter-{apply,clear}
sudo rm -f /etc/systemd/system/docker-netfilter.service
sudo systemctl daemon-reload

# 3. Вернуть nftables-конфигурацию к iptables, если выполнялся сценарий 6
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "firewall-backend": "iptables"
}
EOF
sudo systemctl restart docker

# 4. Восстановить исходное состояние из baseline
sudo iptables-restore < /var/backups/docker-netfilter/<STAMP>/iptables.v4

# 5. Удалить сети, созданные под изоляцию
docker network disconnect db-net my-app
docker network rm db-net app-net

# 6. Убедиться, что цепочка пуста и вернулось штатное поведение
sudo iptables -S DOCKER-USER
# -N DOCKER-USER
docker info --format '{{.FirewallBackend.Driver}}'
# → iptables
```

## Ограничения

- Измерения выполнены на Docker Engine 29.8.1 в LinuxKit VM (Docker Desktop для macOS).
  В этой среде `raw`-таблица пуста и политика `FORWARD` имеет значение `ACCEPT`, поэтому
  правила direct routing и `FORWARD DROP` **не воспроизводились локально** — они описаны
  по официальной документации Docker и примечаниям к выпуску.
- Поведение `enable_icc` подтверждено для пользовательской bridge-сети. Для сети `bridge`
  по умолчанию, где действует параметр демона `--icc`, отдельная проверка не выполнялась.
- Работа `nftables`-бэкенда, `--bridge-accept-fwmark`, `com.docker.network.bridge.trusted_host_interfaces`
  и gateway modes `routed`/`nat-unprotected`/`isolated` описана по документации; включение
  бэкенда в этой среде не проверялось.
- Правила для IPv6 (`ip6tables`) не приводились: в проверках IPv6-forwarding на хосте был
  выключен. При двусторонней публикации портов правила должны быть продублированы для
  `ip6tables`, иначе IPv6-доступ останется открытым.
- Символические адреса в примерах (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`)
  взяты из документационных диапазонов RFC 5737. Фактические адреса и имена хостов
  подставляются при внедрении.

## Дополнительная информация

### Смежные темы

- [Интеграция Docker с iptables и nftables](./troubleshooting/iptables_integration.md) —
  механика управления правилами, `bridge-nf-call-iptables`, conntrack, rootless.
- [Сетевой драйвер bridge](./drivers/bridge.md) — veth-пары, маршрутизация, опции драйвера.
- [Публикация портов](./drivers/bridge.md) и [настройка демона](../docker_daemon_config.md) —
  поведение `-p`, `daemon.json`.
- [Режим сети `container:`](./container_network.md) — общий netns и его следствия для фильтрации.
- [Диагностика сетевых проблем](../Docker_troubleshooting/network_connectivity_issues.md) —
  симптомы и методы поиска неисправностей.
- [Защита хоста и демона](../Docker_security/host_daemon_hardening.md) — sysctl, доступ
  к сокету демона, изоляция хоста.
- [iptables: основы и практические сценарии](../../Linux/Networking/Settings/tools/iptables_basics.md) —
  синтаксис правил, цепочки, таблицы.
- [nftables: архитектура и основные принципы](../../Linux/Networking/Settings/tools/nftables/architecture_and_concepts.md) —
  базовые цепочки, приоритеты, отличия от iptables.

### Официальные источники

- [Packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
- [Docker with iptables](https://docs.docker.com/engine/network/firewall-iptables/)
- [Docker with nftables](https://docs.docker.com/engine/network/firewall-nftables/)
- [Port publishing and mapping](https://docs.docker.com/engine/network/port-publishing/)
- [Bridge network driver](https://docs.docker.com/engine/network/drivers/bridge/)
- Docker Engine release notes 28.x, 29.x
