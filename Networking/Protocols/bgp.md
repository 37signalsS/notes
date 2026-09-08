# BGP — протокол граничного шлюза

## Определения

**BGP (Border Gateway Protocol)** — протокол маршрутизации между автономными системами (EGP — Exterior Gateway Protocol), используемый для построения таблиц маршрутизации в сети Интернет. BGP отвечает за обмен информацией о доступности префиксов между автономными системами.

**Автономная система (AS)** — группа IP-сетей под единым административным управлением с общей политикой маршрутизации. Каждая AS имеет уникальный номер **ASN (Autonomous System Number)**.

**Ключевая особенность:** BGP — это **path-vector протокол**, который выбирает маршруты на основе политик (Policy-based routing), а не только технических метрик. Это делает его протоколом достижения консенсуса в глобальном масштабе.

## Основные концепции

### Состояния BGP-сессии

Для установления соседства (peering) маршрутизатор проходит через несколько состояний:

1. **Idle:** Начальное состояние. Маршрутизатор ищет маршрут к соседу и ожидает события Start.
2. **Connect:** Ожидание завершения трехэтапного рукопожатия TCP.
3. **Active:** Попытка инициализации TCP-соединения (если Connect не удался).
4. **OpenSent:** TCP установлено, отправлено сообщение **OPEN**.
5. **OpenConfirm:** Получено сообщение **OPEN** от соседа, ожидание **Keepalive**.
6. **Established:** Сессия установлена, начинается обмен маршрутами (**UPDATE**).

### Типы сообщений BGP

| Сообщение | Описание |
| :--- | :--- |
| **OPEN** | Используется для установления сессии (ASN, Hold Time, BGP ID). |
| **UPDATE** | Основное сообщение: анонс новых маршрутов или отзыв (Withdraw) старых. |
| **KEEPALIVE** | Подтверждение активности сессии (по умолчанию каждые 60с). |
| **NOTIFICATION** | Сообщение об ошибке, после которого сессия закрывается. |
| **ROUTE-REFRESH** | Запрос на повторную отправку всей таблицы маршрутов от соседа. |

### Типы BGP (eBGP и iBGP)

| Тип | Описание | Особенности |
|-----|----------|-------------|
| **eBGP (external BGP)** | Между различными AS | **TTL** = 1 по умолчанию. Используется для связи с провайдерами и IXP. |
| **iBGP (internal BGP)** | Внутри одной AS | Не меняет AS Path. Требует full-mesh или Route Reflector. |

### Атрибуты BGP

Атрибуты делятся на четыре категории:
1. **Well-known Mandatory:** Должны присутствовать в каждом UPDATE (AS_PATH, NEXT_HOP, ORIGIN).
2. **Well-known Discretionary:** Распознаются всеми, но могут отсутствовать (LOCAL_PREF, ATOMIC_AGGREGATE).
3. **Optional Transitive:** Могут не распознаваться, но должны передаваться дальше (COMMUNITY, AGGREGATOR).
4. **Optional Non-transitive:** Могут игнорироваться и не передаваться (MED, Originator ID).

#### Алгоритм выбора наилучшего пути (Best Path Selection)

BGP сравнивает маршруты по очереди до первого отличия (атрибут выше имеет более высокий приоритет, чем атрибут ниже):

| Порядок | Атрибут | Cisco | Juniper | Arista / Huawei |
| :--- | :--- | :--- | :--- | :--- |
| 1 | **Weight** | Локальное значение (0–65535). Больше = лучше. | *Нет* | *Нет* |
| 2 | **LOCAL_PREF** | Приоритет внутри AS. Больше = лучше (дефолт 100). | Аналог Weight | Да, больше = лучше |
| 3 | **Locally Originated** | Маршруты, созданные на этом роутере (network/aggregate). | Аналогично | Аналогично |
| 4 | **AS_PATH** | Длина пути в AS. Короче = лучше. | Аналогично | Аналогично |
| 5 | **ORIGIN** | IGP < EGP < Incomplete. | Аналогично | Аналогично |
| 6 | **MED** | Меньше = лучше (дефолт 0). | Аналогично | Аналогично |
| 7 | **eBGP over iBGP** | Внешние маршруты предпочтительнее внутренних. | Аналогично | Аналогично |
| 8 | **IGP Metric** | Стоимость пути до Next Hop. Меньше = лучше. | Аналогично | Аналогично |
| 9 | **Router ID** | Tie-breaker: меньший ID. | Аналогично | Аналогично |
| 10 | **Neighbor IP** | Если ID одинаковы — меньший IP соседа. | Аналогично | Аналогично |

#### Почему BGP может выбрать более длинный путь

Алгоритм выбора лучшего пути в BGP — это не просто «наименьшее количество AS в пути». BGP проходит по атрибутам **последовательно** и останавливается на **первом отличии**. Поскольку `AS_PATH length` стоит на 4-й позиции (после Weight, LOCAL_PREF и Locally Originated), более длинный путь может быть выбран, если более высокоприоритетный атрибут определил иной победителя.

**Пример:**

Маршрутизатор получил маршрут `10.10.10.0/24` от двух пирей:

| Peer | AS_PATH | LOCAL_PREF |
| :--- | :--- | :--- |
| A | `64501 64502` (2 AS) | 100 |
| B | `64503 64504 64505` (3 AS) | 200 |

На первый взгляд кажется, что BGP выберет peer A (короткий AS_PATH). Однако на этапе сравнения `LOCAL_PREF` (позиция 2) маршрут B уже победил: `200 > 100`. Атрибут `AS_PATH` на позиции 4 даже не рассматривается — алгоритм остановился на первом отличии.

```
A:  LOCAL_PREF 100 → AS_PATH 2   ←  BGP выбирает B
B:  LOCAL_PREF 200 → AS_PATH 3
```

**Вывод:** добавление ещё одного AS в путь не обязательно перенаправит трафик на другого провайдера. Сначала нужно понять, какой атрибут на более ранней позиции сделал маршрут предпочтительнее.

**Диагностика выбора конкретного маршрута:**

```bash
# Cisco: детальная информация о выбранном best path для префикса
show bgp ipv4 unicast 10.10.10.0/24

# FRRouting: просмотр выбранного best path и анализ победившего маршрута
vtysh -c "show bgp ipv4 unicast 10.10.10.0/24"

# Просмотр всех кандидатных маршрутов (не только выбранного)
# Cisco:
show ip bgp <prefix>
# FRRouting:
vtysh -c "show bgp ipv4 unicast <prefix>"
```

Команда `show bgp ... <prefix>` выводит все рассмотренные пути с отметкой выбранного (обычно `>*` или `best`). Это позволяет увидеть, какой именно атрибут стал решающим — например, `Localpref 200` против `Localpref 100` — даже если AS_PATH у победителя длиннее.

#### Сообщества BGP (Communities)

Метки для группировки префиксов и управления политиками:
- **Standard Community:** 32-битное число (обычно `ASN:Value`).
- **Well-known Communities:**
  - `NO_EXPORT` (0xFFFFFF01): Не передавать за пределы AS (или конфедерации).
  - `NO_ADVERTISE` (0xFFFFFF02): Не передавать никому (даже iBGP-пирам).
  - `LOCAL_AS` (0xFFFFFF03): Не передавать за пределы локальной AS (используется в конфедерациях).
  - `BLACKHOLE`: Сигнализирует о необходимости отбросить трафик (DDoS-защита).
- **Large Community (RFC 8092):** 96-битное число, необходимое для 4-байтовых ASN (формат `ASN:Function:Value`).
- **Extended Community:** Используются в MPLS VPN для передачи Route Targets и Route Origin.

#### Механизмы устойчивости (Resiliency)

1. **Graceful Restart (GR, RFC 4724):** Позволяет маршрутизатору сохранять таблицу форвардинга (Forwarding State) при перезагрузке процесса BGP, если сосед поддерживает GR. Это предотвращает прерывание трафика во время коротких сбоев управления.
2. **Long-Lived Graceful Restart (LLGR):** Расширение для сохранения маршрутов на длительный период (часы/дни) в состоянии "stale".
3. **BFD (Bidirectional Forwarding Detection):** Используется для мгновенного (миллисекунды) обнаружения падения линка, что позволяет BGP переключиться быстрее, не дожидаясь истечения Hold Time (обычно 180с).

### Безопасность BGP: RPKI, ROA и ASPA

**Проблема:** BGP изначально строился на доверии, что позволяет совершать **BGP hijacking** (объявление чужих префиксов) или **Route Leaks** (ошибочное перенаправление транзитного трафика).

**Решения:**

1. **RPKI (Resource Public Key Infrastructure):**
   - **ROA (Route Origin Authorization):** Подпись, подтверждающая право AS анонсировать префикс.
   - **ROV (Route Origin Validation):** Проверка анонсов. Статусы: `Valid`, `Invalid` (отбрасывать), `NotFound`.

2. **ASPA (AS Provider Authorization, RFC 9601):**
   - Стандарт, расширяющий RPKI (опубликован в 2024 году).
   - Позволяет AS подписать список своих легитимных провайдеров (Upstreams).
   - Защищает от **Route Leaks**, проверяя всю цепочку AS_PATH на легитимность отношений клиент-провайдер.

3. **BGPsec (RFC 8205):** Криптографическая подпись всего AS_PATH. Из-за высокой нагрузки на CPU внедряется крайне медленно.

4. **BGP FlowSpec (RFC 5575 / RFC 8955):**
   - Позволяет передавать правила фильтрации трафика (L3/L4) через BGP.
   - Используется для динамической блокировки DDoS-атак на пограничных маршрутизаторах (Drop, Rate-limit, Redirect to VRF).

**Актуальность и риски (2024-2026):**

- Более **60%** IPv4/IPv6 маршрутов покрыты RPKI ROA.
- Крупные провайдеры (Cloudflare, Google, Akamai, NTT) жестко отклоняют `Invalid` маршруты.
- **Кейс Cloudflare (27 июня 2024):** Бразильский провайдер по ошибке анонсировал адрес `1.1.1.1` с маской `/32`. Этот анонс перебил штатный анонс Cloudflare (`/24`) по всему миру. Несмотря на наличие RPKI-подписи у Cloudflare, один из магистральных провайдеров Tier-1 принял поддельный маршрут без проверки и разнёс его дальше. Итог: глобальный сбой сервиса в 70 странах.
- Рекомендуется включать RPKI validation и использовать ASPA (где поддерживается) на всех пограничных роутерах.

### Anycast и BGP

Anycast эксплуатирует фундаментальный механизм BGP — выбор кратчайшего пути (AS Path).

* **Механизм:** Разные дата-центры в разных частях мира одновременно анонсируют один и тот же IP-префикс.
* **Результат:** Запрос пользователя автоматически уезжает в географически ближайшую копию, так как для сетевых маршрутизаторов это выглядит как кратчайший путь (меньше "прыжков" между AS).
* **Надёжность:** Anycast обеспечивает автоматическое переключение (failover): если узел падает, он перестаёт анонсировать префикс, и BGP перенаправляет трафик на следующую ближайшую точку.

**Пример настройки RPKI в FRRouting:**

```bash
router bgp 65001
  bgp rpki server tcp rpki.example.com 323
  address-family ipv4 unicast
    bgp rpki source cache
  exit-address-family
```

### BGP Route Reflector (Отражатель маршрутов)

В больших AS прямое соединение между всеми iBGP-пирами требует `n(n-1)/2` сессий, что плохо масштабируется. **Route Reflector (RR)** решает эту проблему: маршрутизатор принимает маршруты от iBGP-пиров и рассылает их другим пирам внутри AS.

**Терминология:**

| Термин | Описание |
| :--- | :--- |
| **Route Reflector** | Маршрутизатор, пересылающий iBGP-маршруты между пирами |
| **Route Reflector Client** | Пир, получающий отражённые маршруты от RR |
| **Non-Client** | iBGP-пир, не являющийся клиентом (требует full-mesh с RR) |

**Ограничения:**
- RR может стать точкой отказа (нужна избыточность)
- Используется `cluster-id` для предотвращения петель
- RR не генерирует маршруты самостоятельно

**Конфигурация на Cisco:**

```cisco
! На Route Reflector
router bgp 65000
  neighbor 10.0.12.1 remote-as 65000
  neighbor 10.0.12.1 route-reflector-client
  neighbor 10.0.12.2 remote-as 65000
  neighbor 10.0.12.2 route-reflector-client

! На клиентах R1 и R2
router bgp 65000
  neighbor 10.0.12.254 remote-as 65000  ! IP маршрутизатора RR
```

**Конфигурация на FRRouting:**

```bash
# На Route Reflector
vtysh -c "configure terminal" \
  -c "router bgp 65000" \
  -c "neighbor 10.0.12.1 remote-as 65000" \
  -c "neighbor 10.0.12.1 route-reflector-client" \
  -c "neighbor 10.0.12.2 remote-as 65000" \
  -c "neighbor 10.0.12.2 route-reflector-client"

# На клиентах R1 и R2
vtysh -c "configure terminal" \
  -c "router bgp 65000" \
  -c "neighbor 10.0.12.254 remote-as 65000"
```

**Диагностика и проверка:**

| Команда (Cisco/FRR) | Описание |
| :--- | :--- |
| `show ip bgp summary` | Общий статус сессий, ASN, аптайм и количество префиксов. |
| `show ip bgp neighbors <IP>` | Детальная информация о соседе (Capabilities, Hold Time, Errors). |
| `show ip bgp neighbors <IP> advertised-routes` | Маршруты, которые мы анонсируем этому соседу. |
| `show ip bgp neighbors <IP> received-routes` | Все маршруты, полученные от соседа (требует `soft-reconfiguration inbound`). |
| `show ip bgp neighbors <IP> routes` | Принятые маршруты от соседа после фильтрации. |
| `show ip bgp <prefix>` | Детальный анализ конкретного маршрута (AS Path, Communities, причины выбора). |
| `clear ip bgp <IP> soft` | Мягкая перезагрузка сессии (применение политик без разрыва TCP). |

### Мониторинг BGP

Для обеспечения надежности в 2024-2026 годах используются следующие методы:

1. **BGP Monitoring Protocol (BMP, RFC 7854):** Позволяет маршрутизатору передавать копию всех BGP-сообщений (включая отвергнутые маршруты) на центральный коллектор без нагрузки на CPU роутера.
2. **OpenConfig / gNMI:** Современный подход к управлению и мониторингу через gRPC и структурированные данные (YANG модели).
3. **Внешний мониторинг:**
   - **RIPE RIS / RouteViews:** Глобальные коллекторы для проверки видимости ваших префиксов извне.
   - **BGPStream:** Анализ аномалий и утечек маршрутов в реальном времени.
   - **SNMP MIBs:** Классический мониторинг состояния сессий (Up/Down).

## Транзит и пиринг (Transit vs Peering)

В контексте BGP существует два основных способа обеспечения глобальной связности: покупка транзита и организация пиринга.

### IP Transit (Транзит)

Провайдер анонсирует клиенту полную таблицу маршрутов (**Full Routing Table**) или маршрут по умолчанию, а взамен принимает префиксы клиента и распространяет их своим апстримам и пирам.

- **Отношения:** Клиент — Провайдер.
- **Экономика:** Клиент платит за трафик (за каждый мегабит/порт).
- **Маршруты:** Провайдер отдает клиенту все известные ему маршруты.

**Пример конфигурации (Cisco):**
```cisco
router bgp 65001
 neighbor 198.51.100.1 remote-as 1299
 neighbor 198.51.100.1 description Telia-Transit
 neighbor 198.51.100.1 route-map TRANSIT-IN in
 neighbor 198.51.100.1 route-map TRANSIT-OUT out
```

### Peering (Пиринг)

Два оператора договариваются обмениваться трафиком бесплатно, но только своим собственным трафиком и трафиком своих клиентов. Транзитный трафик третьих AS через пиринг не передается.

- **Отношения:** Партнер — Партнер.
- **Экономика:** Обычно бесплатно (**Settlement-Free**).
- **Логика:** Взаимная экономия на транзите и снижение задержек.

**Ограничение анонсов (OWN-PREFIXES):**
```cisco
route-map PEER-OUT permit 10
 match ip address prefix-list OWN-PREFIXES
```

### Технические различия и политики

#### Приоритезация (LOCAL_PREF)

Стандартная политика оператора для управления трафиком:
1. **Customer (Клиент)** — `Local Pref 200` (нам платят).
2. **Peer (Пиринг)** — `Local Pref 150` (бесплатно).
3. **Upstream (Транзит)** — `Local Pref 100` (мы платим).

#### Границы распространения маршрутов (Valley-Free Routing)

Это ключевое техническое отличие, определяющее пиринговую модель:
- Маршруты, полученные от **Пира**, анонсируются только своим **Клиентам**. Они не передаются другим Пирам или Апстримам.
- Маршруты, полученные от **Клиента**, анонсируются всем: Пирам, Апстримам и другим Клиентам.

**Платный пиринг (Paid Peering):** Промежуточный вариант, когда один участник платит другому из-за сильной асимметрии трафика (например, Netflix платит крупным ISP).

### MP-BGP (Multiprotocol BGP)

Современные сети используют расширение **MP-BGP (RFC 4760)**, которое позволяет передавать маршрутную информацию для разных семейств адресов (**AFI/SAFI**):
- **IPv6 Unicast:** Для маршрутизации IPv6 трафика.
- **VPNv4/VPNv6:** Для построения [MPLS L3VPN](../Tunnels/mpls.md).
- **EVPN:** Для построения современных дата-центров (VXLAN Overlay).

### Предотвращение петель (Loop Prevention)

1. **eBGP:** Если маршрутизатор видит собственный ASN в атрибуте **AS_PATH**, он отбрасывает такой UPDATE.
2. **iBGP:** Маршрутизатор не пересылает маршруты, полученные от одного iBGP-пира, другому iBGP-пиру (правило iBGP Split Horizon). Для обхода этого правила используются **Route Reflectors** или **Confederations**.

---

## Практические сценарии

### Платформы для BGP

#### Аппаратные решения

- **Cisco (IOS-XE, IOS-XR, NX-OS)** — enterprise и carrier-grade
- **Juniper (Junos OS)** — дата-центры и ISP
- **Arista (EOS)** — high-performance DC
- **Huawei (VRP)** — Азия и enterprise

#### Программные решения (Soft-router)

- **FRRouting (FRR)** — полноценный routing suite (BGP, OSPF, IS-IS)
- **BIRD** — легковесный, популярен на **IXP (Internet Exchange Point)**
- **GoBGP** — Go-implementation с API
- **VyOS** — роутер на базе Linux
- **MikroTik (RouterOS)** — **SMB** (Small and Medium Business) сегмент

### Базовая конфигурация BGP

#### Cisco IOS-XE

```cisco
! Базовая настройка BGP
router bgp 65001
 bgp router-id 1.1.1.1
 bgp log-neighbor-changes
 !
 ! eBGP-сосед (провайдер)
 neighbor 198.51.100.1 remote-as 1299
 neighbor 198.51.100.1 description Telia-Transit
 neighbor 198.51.100.1 password MySecret123
 neighbor 198.51.100.1 timers 10 30
 !
 ! iBGP-сосед (internal)
 neighbor 10.0.0.2 remote-as 65001
 neighbor 10.0.0.2 route-reflector-client
 !
 ! Address families
 address-family ipv4 unicast
  network 10.0.0.0/8
  neighbor 198.51.100.1 activate
  neighbor 198.51.100.1 route-map TRANSIT-IN in
  neighbor 198.51.100.1 route-map TRANSIT-OUT out
  neighbor 198.51.100.1 prefix-list OWN-PREFIXES out
  maximum-paths 2
 exit-address-family
 !
 address-family ipv4 multicast
  neighbor 10.0.0.2 activate
 exit-address-family
```

#### FRRouting

```bash
# Базовая настройка BGP
vtysh -c "configure terminal" \
  -c "router bgp 65001" \
  -c "bgp router-id 1.1.1.1" \
  -c "bgp log-neighbor-changes" \
  -c "neighbor 198.51.100.1 remote-as 1299" \
  -c "neighbor 198.51.100.1 description Telia-Transit" \
  -c "neighbor 198.51.100.1 password MySecret123" \
  -c "neighbor 198.51.100.1 timers 10 30" \
  -c "neighbor 10.0.0.2 remote-as 65001" \
  -c "neighbor 10.0.0.2 route-reflector-client" \
  -c "address-family ipv4 unicast" \
  -c "network 10.0.0.0/8" \
  -c "neighbor 198.51.100.1 activate" \
  -c "neighbor 198.51.100.1 route-map TRANSIT-IN in" \
  -c "neighbor 198.51.100.1 route-map TRANSIT-OUT out" \
  -c "neighbor 198.51.100.1 prefix-list OWN-PREFIXES out" \
  -c "maximum-paths 2" \
  -c "exit-address-family"

# Сохранение конфигурации
vtysh -c "write memory"
```

#### Juniper Junos

```juniper
set protocols bgp group EXTERNAL type external
set protocols bgp group EXTERNAL neighbor 198.51.100.1 remote-as 1299
set protocols bgp group EXTERNAL neighbor 198.51.100.1 description Telia-Transit
set protocols bgp group EXTERNAL neighbor 198.51.100.1 authentication-key MySecret123
set protocols bgp group EXTERNAL family inet unicast
set protocols bgp group EXTERNAL import TRANSIT-IN
set protocols bgp group EXTERNAL export TRANSIT-OUT

set protocols bgp group INTERNAL type internal
set protocols bgp group INTERNAL neighbor 10.0.0.2
set protocols bgp group INTERNAL neighbor 10.0.0.2 route-reflector-client
set protocols bgp group INTERNAL family inet unicast
```

### Сценарий: Multi-homed подключение к интернету

**Задача:** Обеспечить отказоустойчивость при подключении к двум провайдерам.

**Конфигурация:**

```
                    AS 64500 (Your Network)
                   /                       \
              eBGP /                         \ eBGP
                  /                           \
         AS 1234 (Provider A)           AS 5678 (Provider B)
```

**Рекомендации:**

1. Получите собственный ASN и префикс у **LIR (Local Internet Registry)** / **RIR (Regional Internet Registry)**
2. Настройте BGP с обоими провайдерами
3. Используйте Local Preference для выбора основного провайдера
4. Настройте RPKI validation для защиты от hijacking
5. Используйте BFD (Bidirectional Forwarding Detection) для быстрого обнаружения сбоев

### Сценарий: BGP в дата-центре

**Использование:** BGP для underlay сети в Clos/fat-tree топологиях.

**Преимущества:**

- ECMP (Equal-Cost Multi-Path) для балансировки
- Быстрая конвергенция с BFD
- Масштабируемость для больших DC

**Популярная практика:** eBGP между всеми уровнями (leaf-spine) с уникальным ASN на каждом устройстве.

### Типичные ошибки и их решение

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| BGP-сессия не устанавливается | Firewall блокирует TCP/179 | `telnet 10.0.0.2 179` + `tcpdump port 179` |
| | Несовпадение ASN | Проверить `remote-as` на обоих роутерах |
| | Неверный IP-адрес соседа | Проверить `show ip bgp summary` |
| | Проблемы с TCP | Проверить MTU, MSS, stateful firewall |
| Сессия устанавливается, но маршруты не приходят | Filter block | Проверить `show ip bgp neighbors <IP> received-routes` |
| | Prefix-list отбрасывает маршруты | Проверить `show ip bgp neighbors <IP> adj-rib-in` |
| | Soft-reconfiguration не включена | `neighbor <IP> soft-reconfiguration inbound` |
| Маршруты есть в RIB, но нет в FIB | Проблема с next-hop resolution | `show ip cef <prefix>` |
| | TCAM переполнен | Проверить `show platform hardware capacity` |
| | Синхронизация RIB/FIB | `clear ip bgp * soft` |
| Конвергенция медленная | Hold Time слишком велик | Уменьшить Hold Time, включить BFD |
| | MRAI-таймер не оптимизирован | `neighbor <IP> advertisement-interval 5` |
| | Route Reflector не отражает | Проверить `show ip bgp neighbors <IP> routes` |
| Маршруты флапают | Проблемы с линком | `show interface`, `ethtool`, проверить кабель |
| | DDoS-атака | Включить RTBH, BGP Flowspec |
| | CPU перегружен | `show processes cpu`, проверить BGP logging |
| Ложные срабатывания RPKI | ROA устарел | Обновить ROA в реестре RIR |
| | ASPA не настроена | Проверить `show ip bgp rpki` |

## Дополнительная информация

### Порты и протоколы

- **Порт:** 179/TCP
- **Протокол:** **TCP (Transmission Control Protocol)** — гарантирует надёжную доставку обновлений.

### Таймеры BGP

| Таймер | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **Hold Time** | 180 сек | Максимальное время ожидания Keepalive перед разрывом сессии |
| **Keepalive** | 60 сек | Интервал отправки Keepalive (обычно 1/3 от Hold Time) |
| **Connect Retry** | 120 сек | Интервал между попытками установления TCP-соединения |
| **MRAI (Minimum Route Advertisement Interval)** | 30 сек (eBGP), 0 сек (iBGP) | Минимальный интервал между UPDATE для одного префикса |

**Оптимизация таймеров для быстрой конвергенции:**
```cisco
! Cisco: уменьшение таймеров для быстрого обнаружения сбоев
router bgp 65001
 neighbor 10.0.0.2 timers 10 30
 ! 10 сек Keepalive, 30 сек Hold Time
```

```bash
# FRRouting: аналогичная настройка
vtysh -c "configure terminal" \
  -c "router bgp 65001" \
  -c "neighbor 10.0.0.2 timers 10 30"
```

### Graceful Shutdown (BGP Graceful Restart)

Механизм для контролируемого завершения работы BGP-сессии без потери трафика:

```cisco
! Cisco: включение Graceful Restart
router bgp 65001
 bgp graceful-restart
 bgp graceful-restart restart-time 120
 bgp graceful-restart stalepath-time 360
```

```bash
# FRRouting: включение Graceful Restart
vtysh -c "configure terminal" \
  -c "router bgp 65001" \
  -c "bgp graceful-restart" \
  -c "bgp graceful-restart restart-time 120" \
  -c "bgp graceful-restart stalepath-time 360"
```

**Процедура Graceful Shutdown:**
1. Включить Graceful Restart на обоих соседях
2. Установить `maximum-paths` для ECMP (если используется)
3. Выполнить `clear ip bgp * soft` для применения настроек
4. При перезагрузке маршрутизатор отправит NOTIFICATION с кодом Restart
5. Сосед сохранит маршруты в状态 "stale" на время `restart-time`
6. После восстановления сессии маршруты обновляются без разрыва трафика

### BGP Dampening (Подавление флапа)

Механизм для предотвращения распространения нестабильных маршрутов:

```cisco
! Cisco: настройка Dampening
router bgp 65001
 bgp dampening 15 750 2000 60
 ! half-life = 15 мин, reuse = 750, suppress = 2000, max-suppress = 60 мин
```

```bash
# FRRouting: настройка Dampening
vtysh -c "configure terminal" \
  -c "router bgp 65001" \
  -c "bgp dampening 15 750 2000 60"
```

**Параметры:**
- **half-life:** Время для уменьшения штрафа на 50% (по умолчанию 15 мин)
- **reuse:** Порог штрафа для восстановления маршрута (по умолчанию 750)
- **suppress:** Порог штрафа для подавления маршрута (по умолчанию 2000)
- **max-suppress:** Максимальное время подавления (по умолчанию 60 мин)

### RTBH (Remotely Triggered Black Hole)

Механизм для динамической блокировки трафика на уровне сети:

```cisco
! Cisco: настройка RTBH
ip prefix-list BLACKHOLE seq 5 permit 192.0.2.1/32
!
route-map RTBH permit 10
 match ip address prefix-list BLACKHOLE
 set ip next-hop 192.0.2.1
 set community no-export
!
router bgp 65001
 neighbor 198.51.100.1 send-community
 neighbor 198.51.100.1 route-map RTBH out
```

```bash
# FRRouting: настройка RTBH
vtysh -c "configure terminal" \
  -c "ip prefix-list BLACKHOLE seq 5 permit 192.0.2.1/32" \
  -c "route-map RTBH permit 10" \
  -c "match ip address prefix-list BLACKHOLE" \
  -c "set ip next-hop 192.0.2.1" \
  -c "set community no-export" \
  -c "router bgp 65001" \
  -c "neighbor 198.51.100.1 send-community" \
  -c "neighbor 198.51.100.1 route-map RTBH out"
```

### BGP в Linux и Kubernetes

#### FRRouting на Linux

```bash
# Установка FRRouting
sudo apt install frr frr-pythontools

# Включение BGP
sudo sed -i 's/bgpd=no/bgpd=yes/' /etc/daemons
sudo systemctl restart frr

# Настройка BGP через vtysh
sudo vtysh -c "configure terminal" \
  -c "router bgp 65001" \
  -c "bgp router-id 1.1.1.1" \
  -c "neighbor 10.0.0.2 remote-as 65002" \
  -c "address-family ipv4 unicast" \
  -c "network 10.0.0.0/24" \
  -c "exit-address-family"

# Сохранение конфигурации
sudo vtysh -c "write memory"
```

#### BGP в Kubernetes (Calico)

```yaml
# Calico BGP Configuration
apiVersion: projectcalico.org/v3
kind: BGPConfiguration
metadata:
  name: default
spec:
  logSeverityScreen: Info
  nodeToNodeMeshEnabled: true
  asNumber: 65001
  serviceClusterIPs:
    - cidr: 10.96.0.0/12
  serviceExternalIPs: []
  peerings: []
```

```bash
# Проверка BGP-сессий в Calico
calicoctl node status

# Настройка BGP-пира
calicoctl create -f - <<EOF
apiVersion: projectcalico.org/v3
kind: BGPPeer
metadata:
  name: peer-to-rr
spec:
  peerIP: 10.0.0.254
  asNumber: 65000
  nodeSelector: all()
EOF
```

#### GoBGP в Kubernetes

```yaml
# GoBGP Configuration
apiVersion: gobgp.io/v1alpha1
kind: BGPPolicy
metadata:
  name: default
spec:
  neighbors:
    - config:
        neighborAddress: 10.0.0.2
        peerAs: 65002
      afiSafis:
        - config:
            afi: AFI_IP
            safi: SAFI_UNICAST
```

### BGP FlowSpec

Механизм для динамической фильтрации трафика через BGP:

```cisco
! Cisco: настройка FlowSpec
router bgp 65001
 address-family ipv4 flowspec
  neighbor 10.0.0.2 activate
 exit-address-family

! Создание правила фильтрации
flow spec
 match destination 192.0.2.0/24
 match protocol tcp
 match destination-port 80
 action drop
```

```bash
# FRRouting: настройка FlowSpec
vtysh -c "configure terminal" \
  -c "router bgp 65001" \
  -c "address-family ipv4 flowspec" \
  -c "neighbor 10.0.0.2 activate" \
  -c "exit-address-family"
```

### BGP-LS (Link State)

Расширение BGP для передачи топологической информации:

```cisco
! Cisco: включение BGP-LS
router bgp 65001
 address-family link-state
  bgp additional-paths select all
  bgp additional-paths receive
  bgp additional-paths send select
 exit-address-family
```

### Связанные документы и RFC

- [Сетевой уровень](../OSI_TCP_IP_Model/Network_layer/Concepts/network_layer_overview.md) — основы маршрутизации.
- [Протоколы и оборудование](../OSI_TCP_IP_Model/Network_layer/routing_protocols_equipment.md) — обзор маршрутизации.
- [RFC 4271](https://datatracker.ietf.org/doc/html/rfc4271) — спецификация BGP-4.
- [RFC 4760](https://datatracker.ietf.org/doc/html/rfc4760) — MP-BGP (Multiprotocol BGP).
- [RFC 4724](https://datatracker.ietf.org/doc/html/rfc4724) — Graceful Restart.
- [RFC 5575](https://datatracker.ietf.org/doc/html/rfc5575) — BGP FlowSpec.
- [RFC 7854](https://datatracker.ietf.org/doc/html/rfc7854) — BGP Monitoring Protocol (BMP).
- [RFC 8092](https://datatracker.ietf.org/doc/html/rfc8092) — Large Communities.
- [RFC 8205](https://datatracker.ietf.org/doc/html/rfc8205) — BGPsec.
- [RFC 8955](https://datatracker.ietf.org/doc/html/rfc8955) — Dissemination of Flow Specification Rules.
- [RFC 9601](https://datatracker.ietf.org/doc/html/rfc9601) — ASPA (AS Provider Authorization).

**Примечание:** Для изучения безопасности рекомендуется документация по [RPKI и ROV](https://rpki.readthedocs.io/).
