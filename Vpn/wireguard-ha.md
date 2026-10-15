# WireGuard: высокая доступность и масштабирование концентратора

**Актуально для:** WireGuard (wireguard-tools 1.0.x, модуль ядра Linux 5.6+) / Keepalived 2.4.x (VRRP)

## Определения

**HA-концентратор** — группа серверов WireGuard, предоставляющих единую точку входа для клиентов с автоматическим переключением при отказе. **VIP (Virtual IP)** — плавающий IP-адрес, который в каждый момент принадлежит одному активному узлу. **VRRP (Virtual Router Redundancy Protocol, RFC 5798)** — протокол выборов резервного шлюза: узлы обмениваются advertisement-пакетами, узел с наивысшим приоритетом владеет VIP, при его отказе VIP переходит к следующему по приоритету. Роли: **MASTER** (владеет VIP), **BACKUP** (ждёт), **FAULT** (узел сам объявил себя отказавшим по результату health-check). **Keepalived** — реализация VRRP для Linux с health-check'ами и notify-скриптами. **ECMP (Equal-Cost Multi-Path)** — балансировка потоков по нескольким равнозначным маршрутам. **Anycast** — публикация одного IP из нескольких точек сети с выбором ближайшей по маршрутизации. **Health-check** — механизм проверки работоспособности узла перед переключением.

## Основные концепции

### Свойства WireGuard, которые определяют схему HA

1. **У клиента статический Endpoint.** В конфигурации клиента фиксируется `Endpoint = <ip>:51820`. Чтобы клиенты переживали отказ сервера, этот адрес должен быть VIP или DNS-именем, указывающим на VIP, — иначе после падения узла туннель не восстановится.
2. **Состояние бессерверное.** WireGuard не хранит сессии вне ядра: после handshake пакеты шифруются сессионным ключом, а при переключении на другой сервер клиент просто выполняет новый handshake. Поэтому spare-узел должен иметь **тот же ключ и конфигурацию**, что и активный.
3. **Приватный ключ общий.** В Active/Passive схеме оба шлюза используют один приватный ключ (иначе клиенты не смогут подключиться к спарке). Это нормально, но означает, что ключ надо хранить и ротировать как единое целое.
4. **Нет встроенного фейловер-протокола.** WireGuard не умеет сам выбирать активный узел — HA строится внешними средствами: Keepalived/VRRP, BGP, DNS или балансировщиком.
5. **Практический предел пиров на один интерфейс.** Ядровый модуль допускает до 2^20 пиров на интерфейс, `wireguard-go` — до 2^16 (см. [Vpn/wireguard.md](./wireguard.md)). Масштаб ограничивают не эти числа, а управляемость и сегментация: большие флоты удобнее делить между несколькими интерфейсами или концентраторами.

### Схемы HA

| Схема | Механизм | Когда применять |
|-------|----------|-----------------|
| Active/Passive + VIP | Keepalived (VRRP) | До 1-2 концентраторов, remote access, максимальная простота |
| Active/Active + ECMP/BGP | Несколько серверов за разными Endpoint, маршрутизация по IP | Site-to-site на масштабе, несколько регионов/офисов |
| DNS-ротация | Несколько A-записей у имени Endpoint | Быстрая дешёвая балансировка, не защищает от отказа узла до перевыполнения handshake |
| L4-балансировка UDP | балансировщик ESP/UDP 51820 | **Не рекомендуется** для WireGuard (ломает роуминг, см. ниже) |

**Почему L4-балансировка UDP работает плохо.** WireGuard привязывает сессию к паре публичных ключей и «запоминает» Endpoint пира после первого пакета. Если трафик одного клиента раскидывается между серверами с разными приватными ключами, клиент будет постоянно терять handshake. Балансировщик UDP оправдан только как «переадресация к одному активному узлу» (DSR/VIP), а не как распределение нагрузки.

### Как Keepalived принимает решение о переключении

Понимание этих правил необходимо: без них конфигурация выглядит рабочей, но фейловер не происходит.

1. **`state` — только начальное состояние, а не роль.** После старта узлы проводят выборы: MASTER становится тот, у кого выше `priority`. Поэтому на обоих узлах можно (и современная практика рекомендует) писать `state BACKUP` — роль определится выборами, а не декларацией.
2. **Время переключения при «тихой» смерти узла** (процесс жив, advertisement не приходят): `master_down_interval = 3 × advert_int + skew`, где `skew = advert_int × (256 − priority) / 256`. При `advert_int 1` и приоритетах 150/100 — примерно 3–4 с. При health-check, переведшем узел в FAULT, keepalived отправляет advertisement с приоритетом 0, и BACKUP перехватывает VIP почти сразу (в пределах одного `advert_int`).
3. **Weight health-check'а — самая частая ловушка.** Если у `vrrp_script` не задан `weight` (т.е. `weight 0`), провал проверки переводит VRRP-инстанс в FAULT — VIP уходит гарантированно. Если `weight` задан ненулевой, при провале к `priority` прибавляется это отрицательное значение, и узел **остаётся MASTER, пока его эффективный приоритет выше, чем у BACKUP**. Пример: при `priority 150` у MASTER, `100` у BACKUP и `weight -20` провал health-check даст 130 > 100 — VIP не уедет. Безусловное переключение достигается либо отсутствием `weight` (FAULT), либо `weight` по модулю больше разрыва приоритетов (для примера — хуже −51).
4. **Preemption.** По умолчанию восстановившийся узел с более высоким приоритетом возвращает себе VIP. Опция `nopreempt` (работает только при начальном `state BACKUP`) отключает это: после ремонта роль остаётся у текущего MASTER, пока он сам не откажет. Выбор зависит от runbook'а: детерминированный возврат на «родной» узел (preempt) против отсутствия лишнего переключения (nopreempt).
5. **На L2 VIP переезжает через gratuitous ARP.** При переходе в MASTER keepalived рассылает GARP/NA-пакеты, чтобы коммутаторы и хосты сегмента обновили ARP-кеш. Клиенты WireGuard за пределами этого L2-сегмента восстанавливают сессию сами: новый handshake пойдёт на тот же VIP (см. свойства WireGuard выше).

Синтаксис конфигурации Keepalived и параметры GARP/unicast/BFD — [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md); теория VRRP — [VRRP/HSRP/GLBP](../Networking/Protocols/vrrp_hsrp_glbp.md).

### Роль `wg syncconf`

```bash
# Применить новую конфигурацию из файла, не разрывая активные сессии
sudo wg syncconf wg0 <(wg-quick strip wg0)
```

`wg syncconf` сравнивает текущее состояние интерфейса с конфигом и вносит только изменения — это безопасный способ обновлять ключи/пиры на запасном узле без простоя.

## Практические сценарии

### 1. Active/Passive WireGuard с Keepalived (рекомендуется для remote access)

**Предварительные условия:**
- Два сервера с WireGuard (установка и базовый конфиг — [Vpn/wireguard.md](./wireguard.md)).
- Один приватный ключ для обоих узлов (скопируйте `/etc/wireguard/wg0.conf` на spare).
- Keepalived установлен на обоих узлах.
- Межузловой firewall пропускает VRRP (IP-протокол 112) между обоими узлами; UDP 51820 открыт на VIP. Заблокированные advertisement'ы — классическая причина «фейловер не работает» при внешне здоровой конфигурации.

**Шаг 1. Health-check скрипт** (`/usr/local/bin/check_wg.sh`, одинаков на обоих узлах):

```bash
#!/bin/bash
# Проверка: интерфейс поднят и сервис слушает UDP 51820.
# Важно: у WireGuard интерфейсов state всегда UNKNOWN (L3-устройство),
# поэтому проверяем через фильтр up, а не по строке "state UP".
if ! ip link show up dev wg0 >/dev/null 2>&1; then
    exit 1
fi
if ! ss -H -lun 'sport = :51820' | grep -q .; then
    exit 1
fi
exit 0
```

```bash
sudo chmod +x /usr/local/bin/check_wg.sh
```

**Шаг 2. Определение health-check'а в Keepalived** (блок `vrrp_script` обязателен: `track_script` ссылается на него по имени; без определения keepalived не стартует) — добавьте в `/etc/keepalived/keepalived.conf` **до** `vrrp_instance`:

```text
vrrp_script check_wg {
    script "/usr/local/bin/check_wg.sh"
    interval 2   # период проверки, с
    fall 2       # провалов подряд для FAULT
    rise 2       # успехов подряд для восстановления
    # weight не задан: провал health-checkа переводит инстанс в FAULT
    # и VIP уходит на Backup гарантированно. См. «weight — самая частая
    # ловушка» в разделе основных концепций, если решите задать weight.
}
```

**Шаг 3. Конфигурация Keepalived на Active** (`/etc/keepalived/keepalived.conf`):

```text
vrrp_instance WG {
    state BACKUP            # начальное состояние; MASTER определяется выборами по priority
    interface eth0
    virtual_router_id 51
    priority 150
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass wireguard-ha
    }
    virtual_ipaddress {
        203.0.113.50/32 dev eth0
    }
    track_script {
        check_wg
    }
    notify_master "/usr/local/bin/notify_master_wg.sh"
    notify_backup "/usr/local/bin/notify_state_wg.sh"
    notify_fault  "/usr/local/bin/notify_state_wg.sh"
}
```

**Шаг 4. Конфигурация Keepalived на Backup** — идентична, отличается только `priority`:

```text
vrrp_instance WG {
    state BACKUP
    interface eth0
    virtual_router_id 51
    priority 100
    advert_int 1
    authentication {
        auth_type PASS
        auth_pass wireguard-ha
    }
    virtual_ipaddress {
        203.0.113.50/32 dev eth0
    }
    track_script {
        check_wg
    }
    notify_master "/usr/local/bin/notify_master_wg.sh"
    notify_backup "/usr/local/bin/notify_state_wg.sh"
    notify_fault  "/usr/local/bin/notify_state_wg.sh"
}
```

Разница приоритетов 150/100 (не менее 5–10%) исключает неопределённые выборы при равных значениях. При необходимости вернуть VIP на «родной» узел после ремонта ничего менять не нужно (preempt включён по умолчанию); чтобы роль оставалась у восстановившегося Backup, добавьте `nopreempt` в оба блока (см. концепции выше).

Если multicast на L2-сегменте не работает (частый случай на закрытых сетевых доменах), переведите обмен advertisement'ами на unicast — синтаксис `unicast_src_ip`/`unicast_peer` и примеры (включая IPv6) — в [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md).

**Шаг 5. Автоподъём интерфейса на ставшем активным узле.** В `notify_master` сценарии wg0 поднимается/переинициализируется; `notify_backup`/`notify_fault` только логируют (wg0 на spare остаётся поднятым — это позволяет применять `wg syncconf` заранее):

```bash
#!/bin/bash
# notify_master_wg.sh — keepalived запускает notify-скрипты от root, sudo не нужен
IFACE=wg0

# Пересоздать интерфейс и применить свежую конфигурацию (с возможными кейротациями)
wg-quick down "$IFACE" 2>/dev/null
wg-quick up "$IFACE"
```

```bash
#!/bin/bash
# notify_state_wg.sh — единый скрипт для notify_backup и notify_fault.
# keepalived вызывает notify-скрипты с аргументами: $1=INSTANCE, $2=имя
# инстанса, $3=состояние, $4=приоритет
logger -t keepalived-wg "state transition: $(hostname) ${2:-?} → ${3:-unknown}"
```

**Шаг 6. Порядок запуска сервисов.** Keepalived должен стартовать **после** готовности сети: при раннем старте (до поднятия eth0) узел не видит advertisement'ов живого соседа и может провозгласить себя MASTER — при включённом preempt это даёт кратковременный захват VIP при каждой загрузке. В systemd-дистрибутивах это уже обеспечивает unit keepalived (`After=network-online.target`); проверьте:

```bash
systemctl show keepalived -p After,Wants
# → After=...network-online.target...
```

**Шаг 7. Проверка и тест failover.**

```bash
# VIP принадлежит Active
ip a show eth0 | grep 203.0.113.50
# → inet 203.0.113.50/32 scope global secondary eth0

# С клиента: туннель активен
sudo wg show wg0 latest-handshakes
# → <pubkey>  1712345678

# Имитация отказа: остановить wg0 на Active
sudo systemctl stop wg-quick@wg0
# (keepalived сработает по track_script: инстанс уйдёт в FAULT,
#  VIP уедет на Backup в пределах 1-2 c)

# Проверка с клиента: через 1-5 c handshake обновится
sudo wg show wg0 latest-handshakes
# → <pubkey>  1712345679
```

Потеря пакетов при переключении обычно 0-2 (так как spare полностью синхронен). Подробности настройки Keepalived и VRRP: [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md), [VRRP/HSRP/GLBP](../Networking/Protocols/vrrp_hsrp_glbp.md). Аналогичная схема для IPsec: [IPsec HA](../Networking/Tunnels/ipsec/ipsec_ha.md).

### 2. Масштабирование: несколько концентраторов по регионам

Для флота клиентов и нескольких офисов применяйте модель «несколько независимых концентраторов»:

- В каждом офисе/дата-центре свой сервер WireGuard и своя VPN-подсеть.
- Клиенту выдаётся конфиг с Endpoint ближайшего сервера.
- Межофисная связность — через mesh (каждый концентратор — пир для остальных) или через site-to-site поверх [site-to-site сценарии](../Networking/Tunnels/wireguard_practical.md); конфигурация FRR/BGP для пары концентраторов с ECMP — [wireguard-routing.md](./wireguard-routing.md).

Если нужна единая VPN-подсеть на большой флот, а не деление по регионам, единственный предсказуемый путь — **разные интерфейсы с разными подсетями/ключами** и балансировка клиентов по ним на этапе выдачи конфига (см. [Vpn/wireguard-key-management.md](./wireguard-key-management.md)).

### 3. Anycast/ECMP (продвинутый вариант)

При наличии собственной BGP-инфраструктуры можно объявить один префикс VPN из нескольких узлов (anycast):

- Все узлы используют **один приватный ключ** и одинаковую конфигурацию интерфейса.
- Маршрутизатор отдаёт клиентам ближайший узел; при отказе одного префикс снимается.
- Клиент автоматически дотягивается до следующего узла (второй handshake после таймаута).
- Ограничение: любой перехват трафика на L3 между любым узлом и клиентом получает доступ к этому трафику (любой узел может расшифровать), поэтому необходим доверенный WAN/MPLS.

Базовая работа с BGP описана в [BGP](../Networking/Protocols/bgp.md); вариант «BGP поверх WireGuard для site-to-site с ECMP» — [wireguard-routing.md](./wireguard-routing.md).

### 4. Диагностика HA

```bash
# Где сейчас VIP
ip a show eth0 | grep "inet .*secondary"

# Актуальный маршрут клиента
ip route get 10.0.0.2

# Слушает ли сервис
ss -lun 'sport = :51820'
# → State    Recv-Q  Send-Q  Local Address:Port
# → UNCONN   0       0       0.0.0.0:51820

# Состояние VRRP: advertisement'ы идут (протокол 112)
sudo tcpdump -nn -i eth0 proto 112 -c 5
# → VRRP v2, adv 150 ...  (ожидалось каждые advert_int секунд от MASTER)

# Логи keepalived
journalctl -u keepalived -f
```

Как и в любом VPN, при проблемах применим универсальный чек-лист: [Vpn Troubleshooting](../Networking/Tunnels/vpn_troubleshooting_universal.md).

### 5. Split-brain в Active/Passive и защита от него

**Split-brain** — ситуация, когда оба узла считают себя MASTER и владеют VIP одновременно из-за разрыва связности между шлюзами (обе стороны считают себя живыми, VRRP-advertisement не доходят). Последствия: дублирование VIP в том же сегменте (порой выживает только один из-за ARP), клиенты «скачут», а при одинаковых приватных ключах оба узла отвечают на handshake.

Профилактика:

1. **Аутентификация VRRP**: пароль (`auth_pass`) должен совпадать на обоих узлах. Помните, что `auth_type PASS`/`AH` — слабая защита (только от случайного рассинхрона, не от подделки): с Keepalived 2.4.0+ для подписи advertisement'ов используйте `auth_hmac` (HMAC-SHA256), особенно в unicast-деплоях, где advertisement'ы идут через маршрутизаторы; физически узлы должны жить в L2-сегменте, недоступном посторонним. Подробнее — [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md).
2. **Кворум/физика**: узлы VRRP должны быть в одном L2-сегменте; раздельные сети управления и VIP-интерфейс.
3. **Health-check шире**: `track_script` должен проверять не только `wg0`, но и доступность внешнего шлюза (`ping` 1-2 внешних хостов), чтобы при потере uplink у узла активность перешла к живому собрату, а не к «сироте».
4. **Параметры протокола**: следите за `advert_int`/`priority` — при равных приоритетах MASTER/BACKUP поведение неопределённо; лучше разведение приоритетов на 5-10%.
5. **Детект и «демотивование»**: notify-скрипты при смене состояния должны логировать события (journald), а перед захватом VIP — фиксировать и убирать VIP старого владельца (`ip addr del`), если он «застрял».

Проверка отсутствия split-brain:

```bash
# На обоих узлах: VIP должен быть ровно на одном
for gw in 10.0.0.1 10.0.0.2; do echo "$gw:"; ssh root@$gw "ip -4 a show eth0 | grep -c 203.0.113.50"; done
# → 1 (на одном из узлов) и 0 (на другом)

# Состояние VRRP: MASTER/BACKUP согласованы (pid-файл keepalived по умолчанию)
ssh root@10.0.0.1 "cat /run/keepalived.pid" 2>/dev/null
```

### 6. Тестирование failover (в т.ч. по Chaos Engineering)

HA не существует без регулярных испытаний отказов. План теста (выполняется в регламентное окно):

```bash
# 1) Мягкий отказ: остановка wg-quick на Active
ssh root@10.0.0.1 "systemctl stop wg-quick@wg0"
# ожидание: vip уходит на Backup ≤ 3 c + handshake клиента обновляется ≤ 10 c

# 2) Жёсткий отказ: убить узел целиком (SIGKILL / отключение питания в тесте)
ssh root@10.0.0.1 "kill -9 \$(pidof keepalived)" || true
# в реальности — отключение ВМ/сети: проверяем срабатывание track_script и notify

# 3) Отказ uplink (потеря интернета у активного): track_script на внешний пинг
ssh root@10.0.0.1 "ip link set eth0 down"   # вернуть в конце теста
# ожидание: MASTER переходит к узлу с живым интернетом, а не «сироте»

# 4) С клиента: сквозное измерение потерь при переборе
ping -i 0.2 10.0.0.1 | grep -c time=   # доля успешных за окно переключения
```

Ожидаемые нормативы для Active/Passive: **потери ≤ 0-2 пакета, время переключения 1-5 c** (зависит от `advert_int` и health-check). Фиксируйте метрику в runbook и алертинг (см. [vpn-monitoring.md](./vpn-monitoring.md)).

Системный подход к подобным испытаниям («выход из строя компонента — проверка восстановления») — в разделе [Chaos Engineering](../Chaos_Engineering/chaos_engineering_overview.md) и его [практической части](../Chaos_Engineering/chaos_engineering_practical.md); метрики RTO/RPO ведите по [Chaos Engineering: метрики](../Chaos_Engineering/chaos_engineering_metrics.md).

### 7. Унификация конфигурации и ротация ключей на спарке

Оба узла должны быть конфигурационно идентичны до единой строки (включая `wg0.conf` и ключи), иначе после фейловера клиенты потеряют доступ. Прописывайте это как IaC:

- Единый источник конфига в Git (или [Vpn Automation](../Networking/Tunnels/vpn_automation.md) через Ansible), синхронизация на оба узла при каждом коммите.
- После обновления конфига применяйте `wg syncconf` (см. выше) на spare **до** переключения, чтобы spare был «горячим».
- Ротация приватного ключа пары (см. [wireguard-key-management.md](./wireguard-key-management.md)) выполняется одновременно на обоих узлах: сначала spare (`syncconf`), затем Active — окно, когда spare имеет старый, а Active новый ключ, соблюдается аккуратно, чтобы не разорвать сессии.
- Инвентарь пиров (кто подключён, какими ключами) — общий для пары; журнал всех изменений идёт в [vpn-session-audit.md](./vpn-session-audit.md).

## Устранение неисправностей

| Симптом | Причина | Диагностика и решение |
|---------|---------|----------------------|
| VIP не уходит при остановке wg-quick на Active | `weight` health-check'а по модулю меньше разрыва приоритетов: узел остаётся MASTER с пониженным, но всё же более высоким приоритетом | Убрать `weight` (FAULT-семантика) или задать \|weight\| > (priority_master − priority_backup); см. «weight — самая частая ловушка» в концепциях |
| Фейловер не происходит вообще, keepalived логирует только `VRRP_Script ... failed` | Firewall блокирует VRRP (IP proto 112) или multicast между узлами: MASTER не видит advertisement'ов и не отдаёт VIP, даже с пониженным приоритетом | `sudo tcpdump -nn -i eth0 proto 112` на обоих узлах; открыть протокол 112 или перейти на `unicast_peer` |
| keepalived не стартует | Имя в `track_script` не объявлено в `vrrp_script`; ошибка синтаксиса; дублирующийся `virtual_router_id` в соседнем сегменте | `journalctl -u keepalived -e`; проверить объявление `vrrp_script` и уникальность VRID |
| Клиенты не восстанавливают туннель после failover | Endpoint в клиентском конфиге — не VIP (старый конфиг); приватный ключ spare отличается от активного; `notify_master` не поднял wg0 | Сверить ключи пары узлов (`wg show`), проверить notify-логи (`journalctl -t keepalived-wg`), подтвердить `Endpoint = <VIP>:51820` в выданном клиентском конфиге |
| После загрузки higher-priority узла VIP кратко у него, затем уходит обратно | Keepalived стартовал до готовности сети: узел не видел advertisement'ов живого соседа и провозгласил себя MASTER | `systemctl show keepalived -p After,Wants` — должен зависеть от `network-online.target` |
| Хосты сегмента не видят VIP после переключения | Не обновился ARP-кеш: GARP-повторы слишком редкие или заблокированы | `sudo tcpdump -nn -i eth0 arp and host 203.0.113.50`; настроить `garp_master_repeat`/`garp_master_refresh` (см. [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md)) |
| Оба узла держат VIP | Split-brain при разрыве связности | См. раздел «Split-brain в Active/Passive и защита от него» |

При проблемах с самим туннелем (handshake, AllowedIPs, MTU) применим универсальный чек-лист: [Vpn Troubleshooting](../Networking/Tunnels/vpn_troubleshooting_universal.md).

## Лучшие практики

1. **Конфигурация выборов:** `state BACKUP` на обоих узлах, разведённые приоритеты (разрыв ≥ 5–10), `advert_int 1` для двухузлового Active/Passive.
2. **Health-check:** без `weight` (семантика FAULT — гарантированное переключение) либо с `weight` больше разрыва приоритетов; проверять не только wg0/UDP, но и uplink (ping 1–2 внешних хостов), иначе узел с мёртвым интернетом удержит VIP как «сирота».
3. **Быстрое обнаружение обрыва:** при необходимости субсекундного failback подключайте BFD поверх VRRP — [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md).
4. **Порядок сервисов:** keepalived — после `network-online.target`; иначе при каждой загрузке возможен кратковременный захват VIP не тем узлом.
5. **Сеть:** VRRP (proto 112) между узлами не фильтруется; с Keepalived 2.4.0+ в unicast-деплоях подписывайте advertisement'ы `auth_hmac`.
6. **«Горячий» spare:** после каждого изменения `wg0.conf` применяйте `wg syncconf` на обоих узлах; конфиги ведутся как IaC (раздел 7).
7. **Наблюдаемость:** notify-скрипты пишут переходы в journald; держатель VIP и состояние keepalived экспортируются в метрики ([vpn-monitoring.md](./vpn-monitoring.md)).
8. **Регулярность:** failover тестируется по расписанию (раздел 6), а не «когда сломается»; нормативы переключения фиксируются в runbook.
9. **Имя вместо IP:** клиентам выдавайте `Endpoint = vpn.example.com:51820` (DNS на VIP, TTL ≤ 30–60 с) — при смене адреса VIP обновление дойдёт без перевыдачи конфигов.
10. **MTU:** при VIP/anycast путь клиента не меняется, поэтому MTU-значения из [wireguard.md](./wireguard.md) остаются валидными; после фейловера не ожидайте MTU-проблем — если они появились, смотрите AllowedIPs/конфиг spare, а не сеть.

## Дополнительная информация

- **[Keepalived — обзор и настройка HA](../Networking/ServicesAndTools/keepalived_overview.md)** — VRRP, track_script, notify, BFD, unicast, auth_hmac
- **[VRRP/HSRP/GLBP](../Networking/Protocols/vrrp_hsrp_glbp.md)** — теория протокола резервирования шлюза
- **[IPsec: высокая доступность и failover](../Networking/Tunnels/ipsec/ipsec_ha.md)** — аналогичная схема Active/Passive для strongSwan
- **[Vpn/vpn-monitoring.md](./vpn-monitoring.md)** — метрики и алертинг для HA-концентратора (статус VIP, handshake)
- **[Chaos Engineering: обзор](../Chaos_Engineering/chaos_engineering_overview.md)** — испытания отказов, RTO/RPO
- **[Vpn/vpn-session-audit.md](./vpn-session-audit.md)** — журнал подключений и аудит входов на пару шлюзов