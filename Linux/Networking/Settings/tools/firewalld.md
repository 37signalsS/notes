# Firewalld: динамический межсетевой экран

## Определения

**Firewalld** — это динамический менеджер межсетевого экрана (файрвола), используемый по умолчанию в дистрибутивах на базе RHEL (Red Hat Enterprise Linux) (CentOS, RHEL, Fedora, AlmaLinux, Rocky Linux). Он представляет собой высокоуровневую надстройку над подсистемами `nftables` (в современных версиях) или `iptables` (в устаревших системах).

**Ключевые особенности:**

- **Динамичность:** Изменение правил "на лету" без разрыва существующих соединений и полной перезагрузки правил.
- **Зонирование:** Использование концепции **зон** (zones) для управления уровнем доверия к сетевым интерфейсам и источникам трафика.
- **Сервисно-ориентированность:** Управление доступом через именованные **сервисы** (services), объединяющие порты и протоколы.
- **Rich Rules:** Поддержка сложных условий фильтрации (ограничение по IP, логирование, лимиты подключений).

См. также:

- **[Основы работы межсетевых экранов](../../../../Networking/Concepts/firewall_concepts.md)** — теоретические основы (Netfilter, L3/L4/L7).
- **[Сетевые зоны безопасности](../../../../Networking/Concepts/network_security_zones.md)** — концептуальный разбор уровней доверия и зон.

## Основные концепции

### Зоны и сервисы

**Сервисы** — это предопределенные шаблоны, описывающие порты и протоколы для конкретных приложений. Например:

- `ssh` (**SSH (Secure Shell)**, порт 22/**TCP (Transmission Control Protocol)**)
- `http` (**HTTP (HyperText Transfer Protocol)**, порт 80/TCP), `https` (порт 443/TCP)
- `dns` (**DNS (Domain Name System)**, порт 53/**UDP (User Datagram Protocol)**, 53/TCP)

**Зоны** — это наборы правил, которые применяются к сетевым интерфейсам или конкретным IP (Internet Protocol)-адресам отправителей. Каждый интерфейс может принадлежать только одной зоне.

| Зона | Уровень доверия | Описание |
| :--- | :--- | :--- |
| `drop` | Нулевой | Весь входящий трафик отбрасывается без ответа (`DROP`). Исходящий разрешен. |
| `block` | Низкий | Входящий трафик отклоняется с ICMP (Internet Control Message Protocol)-ответом (`REJECT`). |
| `public` | Низкий | **Зона по умолчанию.** Для использования в публичных сетях. Доверяются только выбранные сервисы. |
| `dmz` | Средний | Для серверов в демилитаризованной зоне (Demilitarized Zone) с ограниченным доступом к внутренней сети. |
| `external` | Средний | Для внешних сетей с включенным **Masquerading (NAT)**. Обычно используется на роутерах. |
| `internal` | Высокий | Для внутренних сетей. Доверяются почти все типичные сервисы. |
| `trusted` | Максимальный | Разрешен весь сетевой трафик. |

### Постоянные и временные изменения

Firewalld различает два режима конфигурации:

1. **Runtime (в процессе работы):** Правила применяются немедленно, но теряются после перезагрузки службы или системы. Используется для тестирования.
2. **Permanent (постоянный):** Правила сохраняются в конфигурационных файлах, но вступают в силу только после перезагрузки (`--reload`).

## Практические сценарии

### 1. Базовое управление (firewall-cmd)

```bash
# Проверка текущего статуса и зоны по умолчанию
firewall-cmd --state
firewall-cmd --get-default-zone

# Просмотр всех правил активной зоны
firewall-cmd --list-all

# Список разрешенных сервисов и портов
firewall-cmd --list-services
firewall-cmd --list-ports
```

### 2. Управление портами и сервисами

При добавлении правил рекомендуется сначала тестировать их в Runtime-режиме, а затем фиксировать.

```bash
# Добавить сервис временно (до перезагрузки)
firewall-cmd --add-service=http

# Добавить порт навсегда
firewall-cmd --permanent --add-port=8080/tcp
firewall-cmd --reload

# Перенести все временные (Runtime) настройки в постоянные (Permanent)
firewall-cmd --runtime-to-permanent

# Удалить правило
firewall-cmd --permanent --remove-service=ftp
firewall-cmd --reload
```

### 3. Работа с зонами и интерфейсами

```bash
# Назначить интерфейс eth1 в зону internal
firewall-cmd --permanent --zone=internal --change-interface=eth1

# Добавить конкретный IP-адрес источника в доверенную зону
firewall-cmd --permanent --zone=trusted --add-source=192.168.1.100

# Проверить, какой зоне принадлежит интерфейс
firewall-cmd --get-zone-of-interface=eth1
```

### 4. Rich Rules (расширенные правила)

Используются для создания сложных правил, которые нельзя описать простым добавлением порта или сервиса.

```bash
# Разрешить SSH только с определённого IP-адреса
firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.1.50" service name="ssh" accept'

# Заблокировать конкретный IP с логированием попыток (prefix в логе)
firewall-cmd --permanent --add-rich-rule='rule source address="10.0.0.99" log prefix="FIREWALL_BLOCK: " level="info" drop'

# Ограничить частоту подключений по SSH (защита от брутфорса)
firewall-cmd --permanent --add-rich-rule='rule service name="ssh" limit value="3/m" accept'
```

### 5. NAT и Port Forwarding (проброс портов)

Подробные примеры построения роутера см. в **[NAT — Практические сценарии](../../../../Networking/Concepts/nat/practical_scenarios.md)**.

```bash
# Включить Masquerading (SNAT - Source Network Address Translation) в зоне external
firewall-cmd --permanent --zone=external --add-masquerade

# Проброс порта (DNAT - Destination Network Address Translation): 5555 → 192.168.1.10:22
firewall-cmd --permanent --zone=external \
  --add-forward-port=port=5555:proto=tcp:toport=22:toaddr=192.168.1.10
```

### 6. Режим паники (Panic Mode)

Включается при активной атаке для полной изоляции хоста.

```bash
# Немедленно заблокировать ВЕСЬ входящий и исходящий трафик
firewall-cmd --panic-on

# Отключить режим паники и восстановить нормальную работу
firewall-cmd --panic-off
```

## Дополнительная информация

### Сохранение и файлы конфигурации

Firewalld хранит настройки в формате XML (Extensible Markup Language):

- `/usr/lib/firewalld/` — конфигурации по умолчанию (системные сервисы и зоны). **Не редактировать.**
- `/etc/firewalld/` — пользовательские настройки. Приоритетны над системными.

Для отладки правил можно использовать логирование через `rich rules` или включить полное логирование отброшенных пакетов:

```bash
firewall-cmd --set-log-denied=all
```

### Сравнение инструментов управления файрволом

| Инструмент | Уровень абстракции | Основная среда | Технология под капота |
| :--- | :--- | :--- | :--- |
| **firewalld** | Высокий (Зоны/Сервисы) | RHEL / CentOS / Fedora | nftables / iptables |
| **[ufw](./ufw.md)** | Высокий (Simple) | Ubuntu / Debian | iptables |
| **[iptables](./iptables_basics.md)** | Низкий (Цепочки/Таблицы) | Универсальный | Netfilter |
| **[nftables](./nftables/architecture_and_concepts.md)** | Низкий (Семейства/Хуки) | Современный Linux | Netfilter |

### Связанные темы

- **[Общие вопросы файрволов](./firewall_common.md)** — сравнение `DROP` vs `REJECT`, сохранение правил.
- **[Взаимодействие Docker и файрвола](../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — решение конфликтов с Docker.
