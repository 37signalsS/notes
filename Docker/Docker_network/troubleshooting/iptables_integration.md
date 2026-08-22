# Интеграция Docker с iptables и nftables

## Определения

- **`iptables`** — классическая утилита и фреймворк для управления правилами фильтрации пакетов Netfilter в ядре Linux. Docker исторически использует `iptables` для реализации сетевой изоляции и проброса портов.
- **`nftables`** — современная подсистема, заменяющая `iptables`. Она обеспечивает более высокую производительность, атомарные обновления правил и более гибкий синтаксис.
- **`iptables-nft`** — слой совместимости, транслирующий команды `iptables` в правила `nftables`. В Docker до версии 28.x это основной способ работы в современных дистрибутивах.
- **`Native nftables backend`** — режим работы Docker (начиная с версии 29.0), при котором демон напрямую создает таблицы и правила `nftables`, минуя слои совместимости.
- **Цепочка `DOCKER-USER`** — специальная цепочка в `iptables`, предназначенная для пользовательских правил. Она вызывается *до* того, как Docker применит свои внутренние правила фильтрации.

## Основные концепции

Взаимодействие Docker с сетевым стеком хоста основано на фреймворке **Netfilter**. Подробно о его работе и утилитах управления рассказано в заметке **[Основы iptables](../../../Linux/Networking/Settings/tools/iptables_basics.md)**.

### Эволюция бэкендов в Docker

| Версия Docker | Основной механизм | Особенности |
| :--- | :--- | :--- |
| **< 20.10** | `iptables-legacy` | Требует прямой работы с Netfilter. Линейный поиск правил $O(n)$. |
| **20.10 - 28.x** | `iptables-nft` (Shim) | Прозрачная трансляция в nftables через системный слой. |
| **29.0+** | **Native nftables** | Прямое управление через `libnftnl`. Новые таблицы (например, `ip docker-bridges`). |

### Ключевые цепочки и таблицы (iptables mode)

1. **Таблица `nat`**:
   - `PREROUTING`: Точка входа для проброса портов (DNAT).
   - `POSTROUTING`: Маскарадинг трафика (MASQUERADE) для доступа контейнеров в интернет.
2. **Таблица `filter`**:
   - **`DOCKER-USER`**: Единственное место для ваших правил. Docker вставляет переход в неё в самое начало цепочки `FORWARD`.
   - `DOCKER`: Правила разрешения доступа к опубликованным портам конкретных контейнеров.
   - `FORWARD`: Общая маршрутизация трафика между интерфейсами.

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

### Сценарий 4: Изоляция контейнеров (Блокировка Internet)

Разрешить связь между контейнерами, но запретить им доступ к внешним сетям.

```bash
# Для iptables
sudo iptables -I DOCKER-USER -i docker0 ! -o docker0 -j DROP

# Для нативного nftables (в свою цепочку forward)
sudo nft add rule inet my_docker_filter input_filter iifname "docker0" oifname != "docker0" drop
```

## Дополнительная информация

### Сохранение правил (Persistence)
Docker не сохраняет ваши правила в `DOCKER-USER` или кастомных таблицах `nftables` после перезагрузки хоста.
- **Debian/Ubuntu**: используйте `iptables-persistent` или `nftables.service`.
- **Docker Events**: Для автоматизации можно использовать скрипты, слушающие `docker events` и пересоздающие правила при поднятии интерфейсов.

### Rootless Docker
В режиме **Rootless** Docker не имеет прав на модификацию системного файервола. Сетевой стек реализуется через:
- **`slirp4netns`**: Трафик инкапсулируется в процессы пользователя.
- **`pasta` (v28+)**: Более производительный вариант, имитирующий сетевой стек без NAT.

**Связанные темы:**
- **[Настройка DNS в Docker](./dns_resolution_issues.md)** — проблемы связности из-за DNS.
- **[Сетевые политики Docker](../docker_network_policies.md)** — правила фильтрации трафика, DOCKER-USER chain, нативные политики.
- **[Устранение сетевых проблем](../../Docker_troubleshooting/network_connectivity_issues.md)** — общий чек-лист диагностики.
- **[nftables: практические сценарии](../../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md)** — справочник команд.
