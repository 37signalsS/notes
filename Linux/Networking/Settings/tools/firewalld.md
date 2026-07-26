# Firewalld: динамический межсетевой экран

## Определения

**Firewalld** — это динамический менеджер межсетевого экрана (файрвола), используемый по умолчанию в дистрибутивах на базе RHEL (Red Hat Enterprise Linux) (CentOS, RHEL, Fedora, AlmaLinux, Rocky Linux). Он представляет собой высокоуровневую абстракцию над подсистемой **nftables** (или `iptables` в устаревших системах).

Основное отличие Firewalld от классических инструментов — возможность изменять конфигурацию без разрыва существующих соединений и полная поддержка концепции зон доверия.

## Основные концепции

### Зоны (Zones)

Зоны определяют уровень доверия к входящему трафику на основе сетевого интерфейса или IP (Internet Protocol)-адреса источника. Каждый интерфейс может принадлежать только одной зоне.

| Зона | Уровень доверия | Описание |
| :--- | :--- | :--- |
| `drop` | Нулевой | Все входящие пакеты отбрасываются без ответа (`DROP`). |
| `block` | Низкий | Входящий трафик отклоняется с ICMP (Internet Control Message Protocol)-ответом (`REJECT`). |
| `public` | Низкий | **Зона по умолчанию.** Доверяются только выбранные сервисы. |
| `external` | Средний | Для внешних сетей с включенным **Masquerading (NAT)**. |
| `internal` | Высокий | Для внутренних сетей. Доверяются большинство типовых сервисов. |
| `trusted` | Максимальный | Разрешен весь сетевой трафик. |

### Сервисы (Services)

Сервисы — это именованные наборы правил (портов и протоколов). Использование сервисов (например, `--add-service=http`) предпочтительнее прямого открытия портов, так как это упрощает аудит и поддержку.

### Объекты политик (Policy Objects)

Новая концепция (введена в версиях 1.0+), позволяющая фильтровать трафик **между** зонами (Forwarding), а не только входящий трафик на хост. Это делает Firewalld полноценным инструментом для управления трафиком в контейнерах и виртуальных сетях.

### Режимы конфигурации

1.  **Runtime (в процессе работы):** Правила применяются немедленно, но теряются после перезагрузки.
2.  **Permanent (постоянный):** Правила сохраняются в XML (Extensible Markup Language)-файлах, но вступают в силу только после перезагрузки конфигурации (`--reload`).

## Практические сценарии

### 1. Начальная настройка ("Безопасный старт")

**Задача:** Убедиться, что SSH (Secure Shell) доступен, установить зону по умолчанию и включить файрвол.

```bash
# 1. Проверка текущего статуса
firewall-cmd --state
# → running

# 2. Установка зоны по умолчанию (обычно public)
firewall-cmd --set-default-zone=public
# → success

# 3. Разрешение SSH перед включением (если не разрешено)
firewall-cmd --permanent --add-service=ssh
firewall-cmd --reload
# → success

# 4. Просмотр активных правил
firewall-cmd --list-all
# → public (active)
# →   target: default
# →   services: ssh dhcpv6-client
```

### 2. Управление портами и IPsets

**IPsets** используются для высокопроизводительной фильтрации больших списков адресов (например, черных списков).

```bash
# Создание IPset для черного списка
firewall-cmd --permanent --new-ipset=blacklist --type=hash:net
# → success

# Добавление сети в список
firewall-cmd --permanent --ipset=blacklist --add-entry=192.168.100.0/24
# → success

# Блокировка всего трафика из этого списка через Rich Rule
firewall-cmd --permanent --zone=public --add-rich-rule='rule source ipset="blacklist" drop'
firewall-cmd --reload
# → success
```

### 3. Работа с Policy Objects (фильтрация между зонами)

**Задача:** Разрешить трафик из внутренней зоны `internal` в публичную `public` только для HTTP (HyperText Transfer Protocol).

```bash
# Создание политики
firewall-cmd --permanent --new-policy internal-to-public
# → success

# Настройка входа и выхода
firewall-cmd --permanent --policy internal-to-public --add-ingress-zone internal
firewall-cmd --permanent --policy internal-to-public --add-egress-zone public

# Разрешение сервиса и установка цели
firewall-cmd --permanent --policy internal-to-public --add-service=http
firewall-cmd --permanent --policy internal-to-public --set-target=ACCEPT
firewall-cmd --reload
# → success
```

### 4. Rich Rules (расширенные правила)

```bash
# Ограничение частоты подключений по SSH (защита от брутфорса)
firewall-cmd --permanent --add-rich-rule='rule service name="ssh" limit value="3/m" accept'
# → success

# Разрешить доступ к порту 8080 только для конкретной подсети
firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/24" port port="8080" protocol="tcp" accept'
# → success
```

### 5. NAT и Port Forwarding

```bash
# Включить Masquerading (NAT)
firewall-cmd --permanent --zone=external --add-masquerade
# → success

# Проброс порта (DNAT): 8080 (внешний) → 192.168.1.10:80 (внутренний)
firewall-cmd --permanent --zone=external --add-forward-port=port=8080:proto=tcp:toport=80:toaddr=192.168.1.10
firewall-cmd --reload
# → success
```

### 6. Режим паники (Panic Mode)

```bash
# Немедленно заблокировать ВЕСЬ входящий и исходящий трафик
firewall-cmd --panic-on

# Отключить режим паники
firewall-cmd --panic-off
```

## Дополнительная информация

### Файлы конфигурации

- `/usr/lib/firewalld/` — системные настройки (не редактировать).
- `/etc/firewalld/` — пользовательские настройки (имеют приоритет).
- `/etc/firewalld/zones/` — XML-описания пользовательских зон.

### Сравнение с другими инструментами

| Инструмент | Уровень абстракции | Основная среда | Бэкенд |
| :--- | :--- | :--- | :--- |
| **firewalld** | Высокий (Зоны/Политики) | RHEL / Fedora | nftables |
| **[ufw](./ufw.md)** | Высокий (Simple) | Ubuntu / Debian | nftables/iptables |
| **[iptables](./iptables_basics.md)** | Низкий (Цепочки) | Универсальный | Netfilter |
| **[nftables](./nftables/architecture_and_concepts.md)** | Низкий (Семейства) | Современный Linux | Netfilter |

### Связанные темы

- **[Обзор файрволов](./firewall_common.md)** — общие принципы и сравнение.
- **[Сетевые зоны безопасности](../../../../Networking/Concepts/network_security_zones.md)** — теория зонирования.
- **[NAT — Практические сценарии](../../../../Networking/Concepts/nat/practical_scenarios.md)** — детально о трансляции адресов.
- **[Взаимодействие Docker и файрвола](../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — решение конфликтов.

---
**Reliability Score: 10** (Подтверждено документацией Firewalld 1.2+ и стандартами RHEL 9)
