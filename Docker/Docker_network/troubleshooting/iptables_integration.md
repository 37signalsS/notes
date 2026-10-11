**Актуально для:** Docker Engine 29.x

# Интеграция Docker с iptables и nftables

## Определения

- **`iptables`** — классическая утилита и фреймворк для управления правилами фильтрации пакетов Netfilter в ядре Linux. Docker исторически использует `iptables` для реализации сетевой изоляции и проброса портов.
- **`nftables`** — современная подсистема, заменяющая `iptables`. Она обеспечивает более высокую производительность, атомарные обновления правил и более гибкий синтаксис.
- **`iptables-nft`** — слой совместимости, транслирующий команды `iptables` в правила `nftables`. В Docker до версии 28.x это основной способ работы в современных дистрибутивах.
- **Native nftables backend** — режим работы Docker (начиная с версии 29.0), при котором демон напрямую создает таблицы и правила `nftables`, минуя слои совместимости.
- **Цепочка `DOCKER-USER`** — специальная цепочка в `iptables`, предназначенная для пользовательских правил. Она вызывается *до* того, как Docker применит свои внутренние правила фильтрации.
- **`conntrack` (`nf_conntrack`)** — подсистема ядра Linux для отслеживания состояний сетевых соединений. Docker использует её для разрешения возвратного трафика (`ESTABLISHED,RELATED`) и корректной работы NAT.
- **`MASQUERADE`** — динамический вариант SNAT, автоматически подставляющий IP-адрес исходящего интерфейса. Используется Docker для выхода контейнеров в интернет через `docker0`.
- **`userland-proxy`** — userspace-прокси Docker для опубликованных портов. В production отключается (`false`) в пользу DNAT через ядро, чтобы избежать обхода правил файревола через `127.0.0.1`.
- **`bridge-nf-call-iptables`** — параметр ядра (`net.bridge.bridge-nf-call-iptables`), определяющий, передавать ли bridge-трафик в Netfilter для фильтрации. Docker требует значение `1` для корректной работы правил `FORWARD`.

## Основные концепции

Взаимодействие Docker с сетевым стеком хоста основано на фреймворке **Netfilter**. Подробно о его работе и утилитах управления рассказано в заметке **[Основы iptables](../../../Linux/Networking/Settings/tools/iptables_basics.md)**.

### Архитектура обработки пакетов

```
Входящий пакет на интерфейс хоста
  → PREROUTING (DNAT: проброс портов хоста → контейнер)
  → FORWARD
    → DOCKER-USER (пользовательские правила, выполняются первыми)
    → DOCKER-ISOLATION-STAGE-1/2 (изоляция между Docker-сетями)
    → DOCKER (разрешение доступа к опубликованным портам)
  → POSTROUTING (SNAT/MASQUERADE: выход контейнеров в интернет)
```

В режиме **Native nftables** (Docker 29.0+) тот же pipeline реализован через таблицы `ip docker-bridges` и `ip6 docker-bridges`. Пользовательские правила добавляются в собственную таблицу с приоритетом `hook forward priority -10`.

> **Важно:** поддержка nftables в Docker 29.x считается экспериментальной (per upstream docs). Поведение и конфигурационные опции могут меняться в будущих релизах. Overlay-сети (Swarm) с nftables-бэкендом не поддерживаются.

### Эволюция бэкендов в Docker

| Версия Docker | Основной механизм | Особенности | Статус |
| :--- | :--- | :--- | :--- |
| **< 20.10** | `iptables-legacy` | Прямая работа с Netfilter. Линейный поиск правил $O(n)$. | Устарел |
| **20.10 - 28.x** | `iptables-nft` (Shim) | Трансляция команд iptables в nftables через системный слой. | EOL (28.x завершил поддержку в мае 2026) |
| **29.0+** | **Native nftables** | Прямое управление через `libnftnl`. Таблицы `ip docker-bridges`, `ip6 docker-bridges`. | Актуальная стабильная ветка (29.8.2 на сентябрь 2026) |

### Ключевые цепочки и таблицы (iptables mode)

1. **Таблица `nat`**:
    - `PREROUTING`: Точка входа для проброса портов (DNAT).
    - `POSTROUTING`: Маскарадинг трафика (MASQUERADE) для доступа контейнеров в интернет.
2. **Таблица `filter`**:
    - **`DOCKER-USER`**: Единственное место для ваших правил. Docker вставляет переход в неё в самое начало цепочки `FORWARD`.
    - `DOCKER`: Правила разрешения доступа к опубликованным портам конкретных контейнеров.
    - `FORWARD`: Общая маршрутизация трафика между интерфейсами.

### Приоритеты цепочек в nftables-режиме

| Компонент | Приоритет | Описание |
| :--- | :--- | :--- |
| Пользовательская таблица | `-10` (рекомендуется) | Обрабатывается раньше правил Docker |
| `docker-bridges` (forward) | `0` | Стандартная фильтрация Docker |
| `docker-bridges` (nat) | `-100` (prerouting) / `100` (postrouting) | NAT-трансляции |

**Правило:** создавайте свою таблицу с `hook forward priority -10`, чтобы фильтрация работала раньше цепочек Docker в `filter`. Учтите, что `nat` PREROUTING с приоритетом ниже выполняется раньше, поэтому к моменту обработки `forward` DNAT уже подставил адрес и порт контейнера — сопоставляйте внутренние значения либо используйте `ct original` (`--ctorigdst`, `--ctorigdstport`).

### Определение активного бэкенда

```bash
# Проверка текущего бэкенда Docker
docker info | grep -i "iptables\|nftables\|firewall"
# → Firewall Backend: nftables
# или
# → iptables: true

# Просмотр созданных Docker таблиц (nftables-режим)
sudo nft list ruleset | grep -E "table (ip|ip6) docker"
# → table ip docker-bridges { ... }
# → table ip6 docker-bridges { ... }
```

## Практические сценарии

### Сценарий 1: Ограничение доступа к порту контейнера (iptables)

**Задача:** Вы запустили контейнер с `-p 8080:80`, но хотите, чтобы доступ к нему был разрешен только с IP `1.2.3.4`.

**Проблема:** Правила в цепочке `INPUT` игнорируются, так как трафик проходит через `FORWARD`.

**Решение:**
```bash
# 1. Разрешить доступ доверенному IP
sudo iptables -I DOCKER-USER -s 1.2.3.4 -p tcp --dport 8080 -j ACCEPT

# 2. Запретить всё остальное к этому порту
sudo iptables -A DOCKER-USER -p tcp --dport 8080 -j DROP

# 3. Обязательно разрешить возвратный трафик (если не настроено глобально)
sudo iptables -I DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```

**Валидация:**
```bash
# Проверка правил DOCKER-USER
sudo iptables -L DOCKER-USER -v -n --line-numbers

# Тест доступа с доверенного IP
curl -s http://1.2.3.4:8080
# → Connection succeeded

# Тест доступа с недоверенного IP
curl -s --max-time 3 http://<host-ip>:8080
# → Connection timed out
```

### Сценарий 2: Переход на Native nftables (Docker 29.0+)

**Задача:** Включить современный бэкенд для избавления от legacy-зависимостей.

**Решение:** Отредактируйте `/etc/docker/daemon.json`:
```json
{
  "firewall-backend": "nftables"
}
```

После перезапуска (`systemctl restart docker`) Docker создаст структуру таблиц:
```bash
sudo nft list ruleset
# → table ip docker-bridges { ... }
# → table ip6 docker-bridges { ... }
```

**Важно:** В этом режиме цепочка `DOCKER-USER` **отсутствует**. Для фильтрации трафика вы должны создать свою таблицу `nftables` с цепочкой, имеющей **приоритет выше (меньшее число)**, чем у таблиц Docker.

**Валидация:**
```bash
# Проверка, что DOCKER-USER отсутствует
iptables -L DOCKER-USER -v -n 2>&1
# → iptables: No chain/target/match by that name.

# Проверка nftables-таблиц
sudo nft list tables
# → table ip docker-bridges
# → table ip6 docker-bridges
```

### Сценарий 3: Пользовательская фильтрация в режиме nftables

Если `firewall-backend: nftables` включен, используйте нативный синтаксис для блокировки.

```bash
# Создание своей таблицы для фильтрации трафика Docker
sudo nft add table inet my_docker_filter
sudo nft add chain inet my_docker_filter input_filter { type filter hook forward priority -10; policy accept; }

# Блокировка доступа к порту 8080 для всех, кроме 1.2.3.4
sudo nft add rule inet my_docker_filter input_filter ip saddr != 1.2.3.4 tcp dport 8080 drop
```
*За счет приоритета `-10` это правило сработает до того, как пакет попадет в таблицы Docker.*

**Сохранение для персистентности:**
```bash
sudo nft list ruleset | sudo tee /etc/nftables.conf
sudo systemctl enable --now nftables
```

### Сценарий 4: Изоляция контейнеров (Блокировка Internet)

Разрешить связь между контейнерами, но запретить им доступ к внешним сетям.

```bash
# Для iptables
sudo iptables -I DOCKER-USER -i docker0 ! -o docker0 -j DROP

# Для нативного nftables (в свою цепочку forward)
sudo nft add rule inet my_docker_filter input_filter iifname "docker0" oifname != "docker0" drop
```

**Валидация:**
```bash
# Контейнер не должен достучаться до внешнего IP
docker exec <container> ping -c 1 -W 2 8.8.8.8
# → ping: sendmsg: Operation not permitted (или timeout)

# Контейнер может общаться с другим контейнером в той же сети
docker exec <container1> ping -c 1 <container2-ip>
# → 64 bytes from ... icmp_seq=1 ttl=64 time=0.089 ms
```

## Устранение неполадок

### Правила DOCKER-USER исчезают после перезагрузки

Docker не сохраняет пользовательские правила в `DOCKER-USER` после перезагрузки хоста.

**Диагностика:**
```bash
# После перезагрузки проверьте цепочку
sudo iptables -L DOCKER-USER -v -n
# Если пуста — правила не были сохранены
```

**Решение:**
- **Debian/Ubuntu**: установите `iptables-persistent` и выполните `sudo netfilter-persistent save`
- **RHEL/CentOS/Fedora**: используйте `service iptables save` или `nftables.service` для nftables
- **Автоматизация**: слушайте `docker events` и восстанавливайте правила при поднятии интерфейсов

### DOCKER-USER отсутствует после включения nftables

При использовании `firewall-backend: nftables` цепочка `DOCKER-USER` не создаётся.

**Диагностика:**
```bash
iptables -L DOCKER-USER -v -n 2>&1
# → iptables: No chain/target/match by that name.
```

**Решение:** Создайте собственную таблицу `nftables` с приоритетом выше Docker:
```bash
sudo nft add table inet my_docker_filter
sudo nft add chain inet my_docker_filter input_filter { type filter hook forward priority -10; policy accept; }
```

### UFW/firewalld конфликтует с Docker

Docker управляет `iptables` напрямую, обходя UFW/firewalld.

**Диагностика:**
```bash
# Проверка правил UFW
sudo ufw status verbose

# Проверка, есть ли конфликтующие правила
sudo iptables -L -v -n | grep -i "ufw\|firewalld"
```

**Решение:** Используйте цепочку `DOCKER-USER` (или нативные таблицы `nftables`) для фильтрации Docker-трафика вместо UFW. Если UFW необходим для других сервисов, добавьте в `/etc/ufw/after.rules`:

```bash
# BEGIN UFW AND DOCKER
*filter
:DOCKER-USER - [0:0]
-A DOCKER-USER -s 1.2.3.4 -j RETURN
-A DOCKER-USER -j DROP
COMMIT
# END UFW AND DOCKER
```

### Rootless Docker не может управлять файреволом

В режиме **Rootless** Docker не имеет прав на модификацию системного файревола.

**Диагностика:**
```bash
# В rootless-режиме iptables/nftables не управляются демоном
sudo iptables -L DOCKER-USER
# → цепочка может отсутствовать или быть пустой
```

**Решение:** Сетевой стек реализуется через:
- **`slirp4netns`**: трафик инкапсулируется в процессы пользователя
- **`gvisor-tap-vsock`** (дефолт с 29.5, moby/moby#52319): сетевой драйвер на базе gVisor
- **`pasta`**: экспериментальный вариант, требует Docker Engine 25.0+

Официальная таблица throughput относит все перечисленные драйверы к **низкой** пропускной способности сети; высокая доступна только у экспериментальных `lxc-user-nic` и `bypass4netns`. Полная таблица и порядок выбора — в разделе «[Rootless: сетевой сток](../docker_network.md#rootless-сетевой-стек)».

Фильтрация трафика в rootless-режиме должна выполняться на уровне хостового файревола администратором.

### Conntrack переполнен

При большом количестве соединений таблица `nf_conntrack` может переполниться.

**Диагностика:**
```bash
# Проверка количества записей
sudo conntrack -S | grep drop
# → drop=12345 (если есть дропы — таблица переполнена)

# Проверка лимита
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_max = 65536
```

**Решение:**
```bash
# Увеличение лимита
sudo sysctl -w net.netfilter.nf_conntrack_max=262144

# Перманентное изменение
echo "net.netfilter.nf_conntrack_max=262144" | sudo tee -a /etc/sysctl.d/99-conntrack.conf
```

### Правила Docker перезаписываются при обновлении сети

Docker пересоздаёт цепочки в `DOCKER` при `docker network create/disconnect`, но **не** в `DOCKER-USER`.

**Диагностика:**
```bash
# Мониторинг событий Docker
docker events --filter 'type=network'
```

**Решение:** Всегда добавляйте пользовательские правила в `DOCKER-USER` (iptables) или в собственную таблицу `nftables` с приоритетом `-10`.

## Рекомендации

1. **Используйте native nftables на Docker 29+** — отключайте зависимость от iptables и получайте $O(1)$ поиск правил через хэш-таблицы. Учитывайте, что функция всё ещё экспериментальна в версии 29.x.
2. **Отключайте ICC** (`"icc": false`) в production — основа микросегментации контейнеров. Детали: [Сетевые политики Docker](../docker_network_policies.md).
3. **Создавайте пользовательскую таблицу nftables с приоритетом `-10`** вместо `DOCKER-USER` — это совместимо с iptables и нативным nftables.
4. **Используйте `--internal` сети** для баз данных и критичных сервисов — двойная изоляция на уровне моста и файревола.
5. **Сохраняйте правила в `/etc/nftables.conf`** и включайте `nftables.service` — Docker не персистит пользовательские правила после перезагрузки.
6. **Отключайте `userland-proxy`** (`"userland-proxy": false`) в production — демон не должен обходить DNAT через userspace, иначе правила iptables/nftables могут не применяться к трафику через `127.0.0.1`.
7. **Тестируйте изоляцию** — после применения правил проверяйте доступность портов с доверенных и недоверенных хостов, а также связность между контейнерами.
8. **Версионируйте конфигурации** — храните nftables/iptables-правила для Docker в Git вместе с конфигурацией демона.
9. **Мониторьте conntrack** — нагруженные продакшен-хосты требуют увеличения `nf_conntrack_max` и отслеживания дропов через `conntrack -S`.
10. **Не полагайтесь на Docker Events для персистентности** — события ненадёжны при массовом поднятии контейнеров. Используйте системные сервисы (`iptables-persistent`, `nftables`).
11. **Версионируйте конфигурации** — храните `daemon.json` и правила файревола в Git. После обновления Docker 28.x → 29.x проверяйте, что правила `DOCKER-USER` мигрировали в нативные таблицы `nftables`.
12. **Аудит правил регулярно** — используйте `iptables-save` / `nft list ruleset` для сравнения эталонного состояния с фактическим. Встраивайте проверки в CI/CD пайплайны инфраструктуры.

## Дополнительная информация

### Сохранение правил (Persistence)
Docker не сохраняет ваши правила в `DOCKER-USER` или кастомных таблицах `nftables` после перезагрузки хоста.
- **Debian/Ubuntu**: используйте `iptables-persistent` или `nftables.service`.
- **RHEL/CentOS/Fedora**: для iptables — `service iptables save`; для nftables — `nftables.service`.
- **Docker Events**: Для автоматизации можно использовать скрипты, слушающие `docker events` и пересоздающие правила при поднятии интерфейсов.

### Rootless Docker
В режиме **Rootless** Docker не имеет прав на модификацию системного файревола. Сетевой стек реализуется через:
- **`slirp4netns`**: Трафик инкапсулируется в процессы пользователя.
- **`gvisor-tap-vsock`**: Новый дефолтный драйвер начиная с Docker Engine 29.5 (moby/moby#52319); `slirp4netns` больше не устанавливается пакетами Docker.
- **`pasta`**: Экспериментальный вариант, требует Docker Engine 25.0+.

### Overlay-сети и nftables
Overlay-сети (Swarm, Kubernetes) инкапсулируют трафик в UDP (VXLAN, порт 4789). На момент Docker 29.x nftables-бэкенд **не поддерживает overlay-сети**. При использовании Swarm оставайтесь на iptables-бэкенде.

### Связанные темы:
- **[Настройка DNS в Docker](./dns_resolution_issues.md)** — проблемы связности из-за DNS.
- **[Сетевые политики Docker](../docker_network_policies.md)** — ICC, DOCKER-USER, --internal сети, Defense-in-Depth.
- **[Устранение сетевых проблем](../../Docker_troubleshooting/network_connectivity_issues.md)** — общий чек-лист диагностики.
- **[nftables: интеграция с Docker](../../../Linux/Networking/Settings/tools/nftables/docker_integration.md)** — нативный nftables-бэкенд, приоритеты цепочек, микросегментация.
- **[nftables: практические сценарии](../../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md)** — справочник команд.
- **[Пакетная фильтрация и файерволы (Docker docs)](https://docs.docker.com/engine/network/packet-filtering-firewalls/)** — официальная документация по бэкендам.
- **[Docker with nftables](https://docs.docker.com/engine/network/firewall-nftables/)** — руководство по миграции.
