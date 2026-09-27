# Продвинутый Firewall в Proxmox VE

## Определения

**PVE Firewall** -- встроенный межсетевой экран Proxmox, работающий на уровне netfilter (iptables/nftables) с правилами на уровнях датацентра, узла и VM/LXC. Предоставляет графический интерфейс в веб-панели и CLI-утилиты.

**Netfilter** -- фреймворк ядра Linux для пакетной фильтрации, трансляции адресов (NAT) и манипулирования пакетами. Proxmox использует как iptables (legacy), так и nftables (новые установки).

**ipset** -- набор IP-адресов, CIDR-блоков и других сетевых объектов, используемых в правилах firewall для группировки и эффективной фильтрации. Заменяет устаревший `ipset` в iptables.

**Conntrack (Connection Tracking)** -- подсистема ядра Linux для отслеживания состояний сетевых соединений (NEW, ESTABLISHED, RELATED, INVALID). В Proxmox используется для stateful firewall и NAT.

**Macros** -- именованные наборы правил в Proxmox firewall, определяющие стандартные сервисы (SSH, HTTP, HTTPS). Упрощают управление правилами.

**Security Groups** -- именованные группы правил, применяемые к нескольким VM/LXC одновременно. Упрощают управление одинаковыми правилами для разных гостей.

**Alias** -- именованный сетевой объект (CIDR или IP), используемый в правилах firewall для упрощения адресации. В Proxmox alias создается на уровне дата-центра и доступен на всех нодах кластера.

## Что такое firewall в Proxmox

Firewall в Proxmox — распределенная система фильтрации сетевого трафика, объединяющая в себе графический веб-интерфейс и backend на основе iptables/nftables. Управление может осуществляться через веб-панель (Datacenter → Firewall) или через конфигурационные файлы (`/etc/pve/firewall/*.fw`).

Ключевые возможности:
- централизованное управление правилами через веб-интерфейс;
- задание правил на уровне кластера, узла и отдельной VM/LXC;
- использование Macros и Security Groups для масштабирования;
- интеграция с netfilter — не требует отдельной настройки firewall внутри каждой гостевой ОС.

## Плюсы и минусы

### Плюсы

1. **Централизованное управление** — правила настраиваются один раз для кластера и применяются ко всем нодам и гостям.
2. **Гибкие уровни применения** — глобальные правила на дата-центре, отдельные политики для узлов и гостей.
3. **Графический интерфейс** — не требуется знание iptables/nftables для базовых сценариев.
4. **Security Groups и Alias** — удобные абстракции для переиспользования политик.

### Минусы

1. **Зависимость от веб-интерфейса** — ошибки в правилах могут заблокировать доступ к Proxmox (порт 8006). Рекомендуется тестировать правила пошагово.
2. **Ограниченный мониторинг** — по сравнению с внешними решениями (pfSense, OPNsense) возможности аудита и отчетности скромнее.
3. **Не заменяет perimeter firewall** — для продакшн-окружений Proxmox firewall дополняет, но не заменяет внешние средства защиты.
4. **Сложность отладки** — при конфликтах с Corosync, Ceph или SDN требуется понимание netfilter и conntrack.

## Теоретический блок

### Архитектура PVE Firewall

```
┌──────────────────────────────────────────────────┐
│  5. VM/LXC Firewall (ct/<ctid>.fw / vm/<vmid>.fw)│
│     Правила для конкретного контейнера/VM         │
├──────────────────────────────────────────────────┤
│  4. Node Firewall (nodes/<node>/host.fw)          │
│     Правила для узла: SSH, Corosync, API          │
├──────────────────────────────────────────────────┤
│  3. Datacenter Firewall (firewall/cluster.fw)     │
│     Глобальные правила, макросы, группы           │
├──────────────────────────────────────────────────┤
│  2. IPSET (firewall/ipset.conf)                   │
│     Группы IP-адресов для использования в правилах│
├──────────────────────────────────────────────────┤
│  1. Netfilter (iptables/nftables)                 │
│     Низкоуровневая фильтрация пакетов            │
└──────────────────────────────────────────────────┘
```

### Приоритет правил

1. **Datacenter-level**: Глобальные правила, макросы, группы.
2. **Host-level**: Правила для узла.
3. **VM/CT-level**: Правила для гостя.

Правила обрабатываются сверху вниз. Первое совпадение определяет действие (ACCEPT, DROP, REJECT).

### Формат правил

```
# Формат:
<direction> <source/destination> <proto> <dport> <action>

# Примеры:
IN ACCEPT --p tcp --dport 22 -s 10.0.0.0/8      # SSH из локальной сети
IN DROP --p tcp --dport 22                        # SSH отовсюду
OUT ACCEPT --p tcp --dport 80 --destination 10.0.0.1  # HTTP на конкретный IP
```

### Directions (Направления)

| Direction | Описание | Пример |
| :--- | :--- | :--- |
| `IN` | Входящий трафик на интерфейс | `IN ACCEPT --p tcp --dport 22` |
| `OUT` | Исходящий трафик с интерфейса | `OUT ACCEPT --p tcp --dport 80` |
| `GROUP` | Группа правил (macro/security group) | `GROUP SSH` |

### Типы действий

| Действие | Описание |
| :--- | :--- |
| `ACCEPT` | Разрешить пакет |
| `DROP` | Молча отбросить пакет |
| `REJECT` | Отклонить пакет с ICMP-ответом |

## Практические сценарии

### 1. Базовая конфигурация firewall

```bash
# Включение firewall на дата-центре
pve-firewall set options --enable 1

# Конфигурация (/etc/pve/firewall/cluster.fw)
[OPTIONS]
enable: 1
log_level_in: info
log_level_out: info
log_level_fw: warning
smurf_protection: 1
no_hw_tso: 0

[RULES]
# SSH только с доверенных сетей
IN SSH ACCEPT -source 10.0.0.0/8
IN SSH ACCEPT -source 192.168.0.0/16
IN SSH DROP

# HTTP/HTTPS отовсюду
IN HTTP ACCEPT
IN HTTPS ACCEPT

# ICMP ping
IN ACCEPT -p icmp

# Исходящий трафик
OUT ACCEPT -p icmp
OUT ACCEPT -d 10.0.0.0/8
OUT DROP
```

#### Три обязательных правила для начала работы

Если firewall включен на дата-центре, но не настроены базовые правила, трафик между узлами и гостями по умолчанию запрещен. Для начала работы добавьте минимум три правила:

1. **Веб-интерфейс Proxmox** — доступ к порту 8006:
   ```
   Action: ACCEPT
   Direction: IN
   Interface: vmbr0
   Protocol: tcp
   Destination Port: 8006
   Comment: Allow WebGUI
   ```

2. **DHCP** — запросы от гостей:
   ```
   Action: ACCEPT
   Direction: IN
   Macro: DHCPfwd
   Comment: Allow DHCP
   ```

3. **DNS** — разрешение имен:
   ```
   Action: ACCEPT
   Direction: IN
   Macro: DNS
   Comment: Allow DNS
   ```

Порядок правил важен: правило для веб-интерфейса должно идти первым, затем DHCP и DNS. Правила обрабатываются сверху вниз, первое совпадение определяет действие.

### 2. Настройка Aliases

Alias — именованный сетевой объект (CIDR или отдельный IP), используемый в правилах firewall для упрощения адресации. Alias создается на уровне дата-центра и автоматически доступен на всех нодах кластера.

```bash
# Примеры alias через веб-интерфейс:
# Datacenter → Firewall → Alias → Add

# Локальная сеть
Name: local-network
IP/CIDR: 192.168.1.0/24

# Виртуальная сеть (SDN VNET)
Name: virt-network
IP/CIDR: 11.11.11.0/24

# Шлюз локальной сети
Name: gateway
IP/CIDR: 192.168.1.1
```

Alias можно использовать в правилах через `-source +local-network` или `-destination +gateway`.

### 3. Настройка IPSet

```bash
# Конфигурация IPSet (/etc/pve/firewall/ipset.conf)
[trusted_networks]
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16

[blocked_hosts]
203.0.113.50
198.51.100.0/24

# Использование IPSet в правилах
# В cluster.fw или host.fw:
[RULES]
IN SSH ACCEPT -source +trusted_networks
IN DROP -source +blocked_hosts
```

### 4. Security Groups

```bash
# Создание Security Group через веб-интерфейс
# Datacenter -> Firewall -> Security Groups -> Add

# Или через конфигурацию (/etc/pve/firewall/cluster.fw)
[GROUP web_servers]
IN HTTP ACCEPT
IN HTTPS ACCEPT
IN SSH ACCEPT -source 10.0.0.0/8

[GROUP db_servers]
IN ACCEPT -p tcp -dport 5432 -source 10.0.0.0/8
IN ACCEPT -p tcp -dport 3306 -source 10.0.0.0/8

# Применение группы к VM
# В vm/<vmid>.fw:
[OPTIONS]
group: web_servers
```

### 4. Продвинутые правила для узла

```bash
# Конфигурация узла (/etc/pve/nodes/node1/host.fw)
[OPTIONS]
enable: 1
log_level_in: info
log_level_out: info

[RULES]
# SSH только из management сети
IN SSH ACCEPT -source 10.0.0.0/24
IN SSH DROP

# Corosync (knet: UDP 5405-5412)
IN ACCEPT -p udp -dport 5405:5412 -source 10.0.0.0/24
OUT ACCEPT -p udp -sport 5405:5412 -destination 10.0.0.0/24

# QDevice (TCP 5403)
IN ACCEPT -p tcp -dport 5403 -source 10.0.0.50

# Proxmox API (TCP 8006)
IN ACCEPT -p tcp -dport 8006 -source 10.0.0.0/24

# Ceph (TCP 6800-7300)
IN ACCEPT -p tcp -dport 6800:7300 -source 10.0.0.0/24

# Live Migration (TCP 60000-60050)
IN ACCEPT -p tcp -dport 60000:60050 -source 10.0.0.0/24
```

### 5. Firewall для VM/LXC

```bash
# Конфигурация VM (/etc/pve/firewall/100.fw)
[OPTIONS]
enable: 1
log_level_in: info
log_level_fw: warning

[RULES]
# Входящий трафик
IN ACCEPT -p tcp -dport 80
IN ACCEPT -p tcp -dport 443
IN SSH ACCEPT -source 10.0.0.0/8
IN ACCEPT -p icmp

# Исходящий трафик
OUT ACCEPT -p tcp -dport 80
OUT ACCEPT -p tcp -dport 443
OUT ACCEPT -p tcp -dport 53
OUT ACCEPT -p udp -dport 53
OUT ACCEPT -p icmp
OUT DROP
```

### 6. Мониторинг и диагностика

```bash
# Статус firewall
pve-firewall status

# Просмотр правил
iptables -L -v -n
nft list ruleset

# Мониторинг в реальном времени
tail -f /var/log/pve/pvefirewall.log

# Статистика по правилам
iptables -L -v -n | grep -E "DROP|REJECT"
conntrack -L | wc -l

# Проверка conntrack
cat /proc/sys/net/netfilter/nf_conntrack_count   # текущее количество
cat /proc/sys/net/netfilter/nf_conntrack_max     # максимум
```

### 7. Настройка conntrack

```bash
# Увеличение лимита conntrack (для высоконагруженных узлов)
echo "net.netfilter.nf_conntrack_max=1048576" >> /etc/sysctl.d/99-conntrack.conf
echo "net.netfilter.nf_conntrack_buckets=262144" >> /etc/sysctl.d/99-conntrack.conf
sysctl -p /etc/sysctl.d/99-conntrack.conf

# Уменьшение таймаутов
echo "net.netfilter.nf_conntrack_tcp_timeout_established=3600" >> /etc/sysctl.d/99-conntrack.conf
echo "net.netfilter.nf_conntrack_tcp_timeout_time_wait=30" >> /etc/sysctl.d/99-conntrack.conf
sysctl -p /etc/sysctl.d/99-conntrack.conf

# Исключение трафика из conntrack (для балансировщиков)
# В raw таблице:
iptables -t raw -A PREROUTING -p tcp --dport 80 -j NOTRACK
iptables -t raw -A OUTPUT -p tcp --sport 80 -j NOTRACK
```

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Пакеты блокируются | Приоритет правил | Проверьте порядок правил: `iptables -L -v -n` |
| Conntrack переполнен | Высокая нагрузка | Увеличьте `nf_conntrack_max` |
| SSH недоступен после включения firewall | Нет правила IN SSH | Добавьте `IN SSH ACCEPT -source <trusted>` |
| VM не видна извне | Нет DNAT/Masquerade | Настройте port forwarding в firewall |
| Логи firewall пусты | log_level = none | Установите `log_level_in: info` |
| Проблемы с Live Migration | Firewall блокирует порты | Откройте TCP 60000-60050 |

## Лучшие практики

1. **Начинайте с ALLOW правил**: Сначала разрешайте необходимый трафик, затем переходите к блокировке. Ошибочное правило DROP может заблокировать доступ к самому Proxmox.
2. **Whitelist по умолчанию**: Разрешайте только необходимый трафик, всё остальное блокируйте.
3. **Используйте IPSet и Alias**: Группируйте IP-адреса и сети в именованные объекты для удобства управления.
4. **Security Groups**: Для одинаковых правил на разных VM используйте группы.
5. **Разделяйте уровни**: Datacenter для глобальных правил, Node для хоста, VM для гостя.
6. **Логирование**: Включайте логирование для диагностики, но не для каждого правила (performance).
7. **Conntrack tuning**: Для высоконагруженных узлов увеличивайте лимиты conntrack.
8. **Регулярные аудиты**: Проверяйте правила и удаляйте неиспользуемые.
9. **Внешний firewall**: Для продакшн-окружений используйте Proxmox firewall вместе с perimeter firewall (pfSense, OPNsense, iptables на роутере).
10. **Тестирование**: Проверяйте правила пошагово после каждого изменения, чтобы не потерять доступ к управляющему интерфейсу.
11. **Alias для сетей**: Используйте Alias для локальных, виртуальных сетей и шлюзов — это упрощает поддержку правил при изменении адресации.

## Граничные случаи

- **Привилегированные контейнеры**: У контейнеров с `privileged: 0` может быть собственный firewall, конфликтующий с правилами хоста.
- **Одновременно iptables и nftables**: Proxmox поддерживает оба, но смешивание может вызвать конфликты. Используйте один фреймворк.
- **Движок firewall**: В новых установках Proxmox 8+ по умолчанию используется nftables. Проверьте: `update-alternatives --display iptables`.
- **Влияние на производительность**: Каждое правило добавляет оверхед. Для высоконагруженных VM используйте fewer rules + ipset.

## Дополнительная информация

### Связанные темы

- [Сетевые технологии Proxmox](./proxmox_networking.md)
- [Безопасность и Hardening Proxmox VE](./proxmox_security.md)
- [iptables basics -- SSoT](../Linux/Networking/Settings/tools/iptables_basics.md)
- [nftables architecture -- SSoT](../Linux/Networking/Settings/tools/nftables/architecture_and_concepts.md)
- [Conntrack Production Tuning -- SSoT](../Linux/Networking/Concepts/conntrack_production_tuning.md)
