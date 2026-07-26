# Сценарии Policy-Based Routing (PBR)

## Определения

**Сценарии PBR** — практические примеры применения Policy-Based Routing для решения задач разделения трафика, балансировки нагрузки и устранения сетевых аномалий.

Подробное теоретическое описание механизмов PBR приведено в [главном разделе](./index.md).

---

## Основные концепции

### Принципы реализации сценариев

Любой практический сценарий PBR базируется на взаимодействии трех уровней:

1.  **Таблицы маршрутизации**: создание независимых наборов маршрутов в `/etc/iproute2/rt_tables`.
2.  **Правила маршрутизации (`ip rule`)**: логика выбора таблицы на основе селекторов (адрес источника, метка пакета, входящий интерфейс).
3.  **Маркировка трафика**: классификация пакетов средствами `iptables` или `nftables` для последующей обработки правилами PBR.

---

## Практические сценарии

### Сценарий 1: Разделение трафика по приложениям (VPN для браузера)

Задача: направлять трафик веб-браузера через VPN, а SSH-соединения — через основной канал провайдера.

**Исходные данные:**
- `eth0`: основной интерфейс (шлюз `192.168.1.1`).
- `tun0`: VPN-интерфейс (шлюз `10.8.0.1`).

#### 1. Подготовка таблиц маршрутизации
```bash
# Добавление таблиц, если они отсутствуют
sudo grep -qxF '100 vpn_table' /etc/iproute2/rt_tables || echo "100 vpn_table" | sudo tee -a /etc/iproute2/rt_tables
sudo grep -qxF '200 direct_table' /etc/iproute2/rt_tables || echo "200 direct_table" | sudo tee -a /etc/iproute2/rt_tables
```

#### 2. Наполнение таблиц маршрутами
```bash
# Маршрут для прямого подключения
sudo ip route add default via 192.168.1.1 dev eth0 table direct_table

# Маршрут для VPN
sudo ip route add default via 10.8.0.1 dev tun0 table vpn_table
```

#### 3. Классификация и маркировка трафика

**Используя iptables:**
```bash
# Маркировка трафика конкретного пользователя (browseruser)
sudo iptables -t mangle -A OUTPUT -m owner --uid-owner browseruser -j MARK --set-mark 1

# Маркировка SSH-трафика (порт 22)
sudo iptables -t mangle -A OUTPUT -p tcp --dport 22 -j MARK --set-mark 2
```

**Используя nftables:**
```bash
# Маркировка трафика пользователя browseruser
nft add rule inet filter output skuid browseruser meta mark set 0x1

# Маркировка SSH
nft add rule inet filter output tcp dport 22 meta mark set 0x2
```

#### 4. Применение правил PBR
```bash
# Пакеты с меткой 1 -> в VPN
sudo ip rule add fwmark 1 table vpn_table

# Пакеты с меткой 2 -> напрямую
sudo ip rule add fwmark 2 table direct_table
```

---

### Сценарий 2: Решение проблемы асимметричной маршрутизации

Проблема возникает на серверах с несколькими интерфейсами, когда пакет приходит на один IP, а ответ уходит через шлюз по умолчанию другого интерфейса. Это приводит к блокировкам со стороны `rp_filter` или фаерволов.

**Решение:** принудительная маршрутизация ответа через тот же интерфейс, на который пришел запрос, на основе IP-адреса источника (Source IP).

#### 1. Настройка таблицы и маршрута
```bash
# Добавление таблицы управления
echo "200 mgmt_table" | sudo tee -a /etc/iproute2/rt_tables

# Добавление маршрута в таблицу
sudo ip route add default via 10.0.5.1 dev ens5 table mgmt_table
```

#### 2. Создание правила по адресу источника
```bash
# Если Source IP пакета 10.0.5.101 — использовать mgmt_table
sudo ip rule add from 10.0.5.101 table mgmt_table priority 1000
```

---

### Сценарий 3: Балансировка трафика между аплинками (ECMP)

Использование нескольких провайдеров одновременно через механизмы ECMP (Equal-Cost Multi-Path).

```bash
# Распределение нагрузки с равными весами
sudo ip route replace default scope global \
    nexthop via 11.22.33.1 dev eth0 weight 1 \
    nexthop via 55.66.77.1 dev eth1 weight 1
```

**Особенности:**
- Балансировка происходит на уровне сессий (L4), а не отдельных пакетов.
- В современных ядрах (4.19+) распределение происходит более динамично благодаря удалению кэша маршрутов IPv4.

---

### Сценарий 4: Сохранение меток через CONNMARK

Модуль `CONNMARK` позволяет "запоминать" метку для всего соединения, что критично для корректной маршрутизации входящих запросов на серверах с несколькими интерфейсами.

```bash
# Маркировка входящих соединений по интерфейсам
iptables -t mangle -A PREROUTING -i eth0 -j CONNMARK --set-mark 0x2
iptables -t mangle -A PREROUTING -i eth1 -j CONNMARK --set-mark 0x4

# Восстановление метки для всех исходящих пакетов в рамках сессии
iptables -t mangle -A OUTPUT -j CONNMARK --restore-mark
```

**Связка с PBR:** После восстановления метки в цепочке `OUTPUT`, пакет подпадает под действие правила `ip rule add fwmark ...`.

---

## Дополнительная информация

- **[ip rule & PBR](../Tools/iproute2/ip_rule_pbr.md)** — синтаксис и селекторы правил.
- **[Администрирование PBR](./administration.md)** — отладка и сохранение конфигурации.
- **[ip route](../Tools/iproute2/ip_route.md)** — управление таблицами маршрутизации.
