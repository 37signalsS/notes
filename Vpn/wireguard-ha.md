# WireGuard: высокая доступность и масштабирование концентратора

## Определения

**HA-концентратор** — группа серверов WireGuard, предоставляющих единую точку входа для клиентов с автоматическим переключением при отказе. **VIP (Virtual IP)** — плавающий IP-адрес, который в каждый момент принадлежит одному активному узлу. **ECMP (Equal-Cost Multi-Path)** — балансировка потоков по нескольким равнозначным маршрутам. **Anycast** — публикация одного IP из нескольких точек сети с выбором ближайшей по маршрутизации. **Health-check** — механизм проверки работоспособности узла перед переключением.

## Основные концепции

### Свойства WireGuard, которые определяют схему HA

1. **У клиента статический Endpoint.** В конфигурации клиента фиксируется `Endpoint = <ip>:51820`. Чтобы клиенты переживали отказ сервера, этот адрес должен быть VIP или DNS-именем, указывающим на VIP, — иначе после падения узла туннель не восстановится.
2. **Состояние бессерверное.** WireGuard не хранит сессии вне ядра: после handshake пакеты шифруются сессионным ключом, а при переключении на другой сервер клиент просто выполняет новый handshake. Поэтому spare-узел должен иметь **тот же ключ и конфигурацию**, что и активный.
3. **Приватный ключ общий.** В Active/Passive схеме оба шлюза используют один приватный ключ (иначе клиенты не смогут подключиться к спарке). Это нормально, но означает, что ключ надо хранить и ротировать как единое целое.
4. **Нет встроенного фейловер-протокола.** WireGuard не умеет сам выбирать активный узел — HA строится внешними средствами: Keepalived/VRRP, BGP, DNS или балансировщиком.
5. **Практический предел пиров на один интерфейс.** В [Vpn/wireguard.md](./wireguard.md) отмечен лимит порядка 256 пиров на интерфейс. Для больших флотов нужны несколько интерфейсов или несколько концентраторов.

### Схемы HA

| Схема | Механизм | Когда применять |
|-------|----------|-----------------|
| Active/Passive + VIP | Keepalived (VRRP) | До 1-2 концентраторов, remote access, максимальная простота |
| Active/Active + ECMP/BGP | Несколько серверов за разными Endpoint, маршрутизация по IP | Site-to-site на масштабе, несколько регионов/офисов |
| DNS-ротация | Несколько A-записей у имени Endpoint | Быстрая дешёвая балансировка, не защищает от отказа узла до перевыполнения handshake |
| L4-балансировка UDP | балансировщик ESP/UDP 51820 | **Не рекомендуется** для WireGuard (ломает роуминг, см. ниже) |

**Почему L4-балансировка UDP работает плохо.** WireGuard привязывает сессию к паре публичных ключей и «запоминает» Endpoint пира после первого пакета. Если трафик одного клиента раскидывается между серверами с разными приватными ключами, клиент будет постоянно терять handshake. Балансировщик UDP оправдан только как «переадресация к одному активному узлу» (DSR/VIP), а не как распределение нагрузки.

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

**Шаг 1. Конфигурация Keepalived на Active** (`/etc/keepalived/keepalived.conf`):

```text
vrrp_instance WG {
    state MASTER
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
}
```

**Шаг 2. Health-check скрипт** (`/usr/local/bin/check_wg.sh`):

```bash
#!/bin/bash
# Проверка: интерфейс поднят и сервис слушает UDP 51820
if ! ip link show wg0 up >/dev/null 2>&1; then
    exit 1
fi
if ! ss -lun | grep -q ':51820'; then
    exit 1
fi
exit 0
```

```text
chmod +x /usr/local/bin/check_wg.sh
```

**Шаг 3. Конфигурация Keepalived на Backup** (`/etc/keepalived/keepalived.conf`):

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
}
```

**Шаг 4. Автоподъём интерфейса на ставшем активным узле.** В `notify` сценарий, вызываемый при переходе в MASTER, поднимает/переинициализирует wg0:

```bash
#!/bin/bash
# notify_master_wg.sh
IFACE=wg0
CONF=/etc/wireguard/${IFACE}.conf

# Пересоздать интерфейс и применить свежую конфигурацию (с возможными кейротациями)
sudo wg-quick down "$IFACE" 2>/dev/null
sudo wg-quick up "$IFACE"
```

Укажите его в `vrrp_instance`:

```text
notify_master "/usr/local/bin/notify_master_wg.sh"
```

**Шаг 5. Проверка и тест failover.**

```bash
# VIP принадлежит Active
ip a show eth0 | grep 203.0.113.50
# → inet 203.0.113.50/32 scope global eth0

# С клиента: туннель активен
sudo wg show wg0 latest-handshakes
# → <pubkey>  1712345678

# Имитация отказа: остановить wg0 на Active
sudo systemctl stop wg-quick@wg0
# (keepalived сработает по track_script: VIP уедет на Backup в течение 1-3 c)

# Проверка с клиента: через 1-5 c handshake обновится
sudo wg show wg0 latest-handshakes
# → <pubkey>  1712345679
```

Потеря пакетов при переключении обычно 0-2 (так как spare полностью синхронен). Подробности настройки Keepalived и VRRP: [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md), [VRRP/HSRP/GLBP](../Networking/Protocols/vrrp_hsrp_glbp.md). Аналогичная схема для IPsec: [IPsec HA](../Networking/Tunnels/ipsec/ipsec_ha.md).

### 2. Масштабирование: несколько концентраторов по регионам

Для флота клиентов и нескольких офисов применяйте модель «несколько независимых концентраторов»:

- В каждом офисе/дата-центре свой сервер WireGuard и своя VPN-подсеть.
- Клиенту выдаётся конфиг с Endpoint ближайшего сервера.
- Межофисная связность — через mesh (каждый концентратор — пир для остальных) или через site-to-site поверх [site-to-site сценарии](../Networking/Tunnels/wireguard_practical.md).

Если нужна единая VPN-подсеть на большой флот, а не деление по регионам, единственный предсказуемый путь — **разные интерфейсы с разными подсетями/ключами** и балансировка клиентов по ним на этапе выдачи конфига (см. [Vpn/wireguard-key-management.md](./wireguard-key-management.md)).

### 3. Anycast/ECMP (продвинутый вариант)

При наличии собственной BGP-инфраструктуры можно объявить один префикс VPN из нескольких узлов (anycast):

- Все узлы используют **один приватный ключ** и одинаковую конфигурацию интерфейса.
- Маршрутизатор отдаёт клиентам ближайший узел; при отказе одного префикс снимается.
- Клиент автоматически дотягивается до следующего узла (второй handshake после таймаута).
- Ограничение: любой перехват трафика на L3 между любым узлом и клиентом получает доступ к этому трафику (любой узел может расшифровать), поэтому необходим доверенный WAN/MPLS.

Базовая работа с BGP описана в [BGP](../Networking/Protocols/bgp.md).

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

# Состояние VRRP
ip -s -d addr show eth0 | grep -i vrrp

# Логи keepalived
journalctl -u keepalived -f
```

Как и в любом VPN, при проблемах применим универсальный чек-лист: [Vpn Troubleshooting](../Networking/Tunnels/vpn_troubleshooting_universal.md).

### 5. Split-brain в Active/Passive и защита от него

**Split-brain** — ситуация, когда оба узла считают себя MASTER и владеют VIP одновременно из-за разрыва связности между шлюзами (обе стороны считают себя живыми, VRRP-advertisement не доходят). Последствия: дублирование VIP в том же сегменте (порой выживает только один из-за ARP), клиенты «скачут», а при одинаковых приватных ключах оба узла отвечают на handshake.

Профилактика:

1. **Аутентификация VRRP**: пароль должен совпадать на обоих узлах; при VRRPv3 желателен переход с `auth_type PASS` на AH/HMAC, а физически узлы должны жить в L2-сегменте, недоступном посторонним.
2. **Кворум/физика**: узлы VRRP должны быть в одном L2-сегменте; раздельные сети управления и VIP-интерфейс.
3. **Health-check шире**: `track_script` должен проверять не только `wg0`, но и доступность внешнего шлюза (`ping` 1-2 внешних хостов), чтобы при потере uplink у узла активность перешла к живому собрату, а не к «сироте».
4. **Параметры протокола**: следите за `advert_int`/`priority` — при равных приоритетах MASTER/BACKUP поведение неопределённо; лучше разведение приоритетов на 5-10%.
5. **Детект и «демотивование»**: notify-скрипты при смене состояния должны логировать события (journald), а перед захватом VIP — фиксировать и убирать VIP старого владельца (`ip addr del`), если он «застрял».

Проверка отсутствия split-brain:

```bash
# На обоих узлах: VIP должен быть ровно на одном
for gw in 10.0.0.1 10.0.0.2; do echo "$gw:"; ssh root@$gw "ip -4 a show eth0 | grep -c 203.0.113.50"; done
# → 1 (на одном из узлов) и 0 (на другом)

# Состояние VRRP: MASTER/BACKUP согласованы
ssh root@10.0.0.1 "cat /proc/keepalived/keepalived.pid" 2>/dev/null
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

## Дополнительная информация

- **[Keepalived — обзор и настройка HA](../Networking/ServicesAndTools/keepalived_overview.md)** — VRRP, track_script, notify, BFD
- **[IPsec: высокая доступность и failover](../Networking/Tunnels/ipsec/ipsec_ha.md)** — аналогичная схема Active/Passive для strongSwan
- **[Vpn/vpn-monitoring.md](./vpn-monitoring.md)** — метрики и алертинг для HA-концентратора (статус VIP, handshake)
- **[Chaos Engineering: обзор](../Chaos_Engineering/chaos_engineering_overview.md)** — испытания отказов, RTO/RPO
- **[Vpn/vpn-session-audit.md](./vpn-session-audit.md)** — журнал подключений и аудит входов на пару шлюзов