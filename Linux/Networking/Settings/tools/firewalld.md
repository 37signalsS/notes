# Firewalld: динамический межсетевой экран

## Определения

**Firewalld** — это динамический менеджер межсетевого экрана, используемый по умолчанию в дистрибутивах на базе RHEL (CentOS Stream, RHEL, Fedora, AlmaLinux, Rocky Linux). Он представляет собой высокоуровневую абстракцию над подсистемой **nftables** (или `iptables` в устаревших системах).

Основное отличие Firewalld от статических инструментов (например, `iptables-services`) — возможность изменять конфигурацию без перезагрузки всей службы и разрыва существующих соединений, а также полная поддержка концепции зон доверия.

## Основные концепции

### Зоны (Zones)

Зоны определяют уровень доверия к входящему трафику на основе сетевого интерфейса или IP-адреса источника. Каждый интерфейс может принадлежать только одной зоне.

| Зона | Уровень доверия | Описание |
| :--- | :--- | :--- |
| `drop` | Нулевой | Все входящие пакеты отбрасываются без ответа (`DROP`). |
| `block` | Низкий | Входящий трафик отклоняется с ICMP-ответом (`REJECT`). |
| `public` | Низкий | **Зона по умолчанию.** Доверяются только выбранные сервисы. |
| `external` | Средний | Для внешних сетей с включенным **Masquerading (NAT)**. |
| `internal` | Высокий | Для внутренних сетей. Доверяются большинство типовых сервисов. |
| `dmz` | Средний | Для компьютеров в демилитаризованной зоне с ограниченным доступом. |
| `trusted` | Максимальный | Разрешен весь сетевой трафик. |

### Сервисы (Services)

Сервисы — это XML-файлы с описанием портов и протоколов (хранятся в `/usr/lib/firewalld/services/`). Использование сервисов (например, `--add-service=http`) предпочтительнее прямого открытия портов, так как это упрощает аудит и перенос конфигурации.

### Объекты политик (Policy Objects)

Концепция (введена в Firewalld 1.0+), позволяющая фильтровать трафик **между** зонами (Forwarding), а не только входящий трафик на сам хост. Это делает Firewalld эффективным инструментом для управления трафиком виртуальных машин, контейнеров и маршрутизации между интерфейсами.

### Режимы конфигурации

1.  **Runtime:** правила применяются немедленно к текущему состоянию ядра, но теряются после перезагрузки службы.
2.  **Permanent:** правила сохраняются в конфигурационных файлах в `/etc/firewalld/`, но вступают в силу только после перезагрузки конфигурации (`--reload`) или использования флага `--immediate` вместе с `--permanent`.

## Практические сценарии

### 1. Начальная настройка («Безопасный старт»)

**Задача:** убедиться в доступности SSH, установить зону по умолчанию и активировать защиту.

```bash
# 1. Проверка текущего статуса
firewall-cmd --state
# Результат: running

# 2. Установка зоны по умолчанию
firewall-cmd --set-default-zone=public
# Результат: success

# 3. Разрешение SSH (постоянное правило с немедленным применением)
firewall-cmd --permanent --add-service=ssh
firewall-cmd --reload
# Результат: success

# 4. Просмотр активных правил в зоне
firewall-cmd --list-all
```

### 2. Управление портами и IPsets

**IPsets** используются для высокопроизводительной фильтрации списков адресов.

```bash
# Создание IPset для списка блокировки
firewall-cmd --permanent --new-ipset=blacklist --type=hash:net

# Добавление подсети в список
firewall-cmd --permanent --ipset=blacklist --add-entry=192.168.100.0/24

# Применение блокировки через Rich Rule
firewall-cmd --permanent --zone=public --add-rich-rule='rule source ipset="blacklist" drop'
firewall-cmd --reload
```

### 3. Межзонная фильтрация (Policy Objects)

**Задача:** разрешить трафик из зоны `internal` в зону `public` только для HTTP и HTTPS.

```bash
# Создание объекта политики
firewall-cmd --permanent --new-policy internal-to-public

# Настройка направлений (Ingress — вход, Egress — выход)
firewall-cmd --permanent --policy internal-to-public --add-ingress-zone internal
firewall-cmd --permanent --policy internal-to-public --add-egress-zone public

# Разрешение трафика и установка цели (ACCEPT/REJECT/DROP)
firewall-cmd --permanent --policy internal-to-public --add-service={http,https}
firewall-cmd --permanent --policy internal-to-public --set-target=ACCEPT
firewall-cmd --reload
```

### 4. Расширенные правила (Rich Rules)

Rich Rules позволяют создавать сложные условия фильтрации в одну команду.

```bash
# Ограничение частоты подключений к SSH (защита от перебора)
firewall-cmd --permanent --add-rich-rule='rule service name="ssh" limit value="3/m" accept'

# Разрешить доступ к порту 8080 только для конкретного IP с логированием
firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.50" port port="8080" protocol="tcp" log prefix="API_ACCESS " level="info" accept'
```

### 5. Режим блокировки (Lockdown Mode)

Предотвращает изменение правил файрвола локальными приложениями (например, запущенными от имени root), если они не внесены в белый список (`lockdown-whitelist.xml`).

```bash
# Включение режима блокировки
firewall-cmd --lockdown-on

# Проверка статуса
firewall-cmd --query-lockdown
```

### 6. Логирование отброшенных пакетов

По умолчанию Firewalld не логирует отброшенные пакеты (Deny/Drop).

```bash
# Включить логирование только для пакетов, соответствующих политике deny
firewall-cmd --set-log-denied=all

# Варианты: all, unicast, broadcast, multicast, off
```

## Дополнительная информация

### Конфигурационные файлы

- `/usr/lib/firewalld/`: системные файлы по умолчанию (сервисы, зоны, ICMP-типы). Не редактировать.
- `/etc/firewalld/`: пользовательские конфигурации. Имеют абсолютный приоритет.
- `/etc/firewalld/firewalld.conf`: основной файл настроек (выбор бэкенда, логирование).

### Интеграция с Fail2ban

В дистрибутивах RHEL-семейства Fail2ban интегрируется с Firewalld через команду `firewall-cmd`.

Для активации установите пакет `fail2ban-firewalld` и убедитесь, что в `jail.local` выбрано действие:
`banaction = firewallcmd-ipset` (рекомендуется для производительности).

### Прямой интерфейс (Direct Interface)

Устаревший способ (legacy) вставки чистых правил `iptables`/`nftables`. Используется в исключительных случаях, когда возможностей зон и Rich Rules недостаточно. Рекомендуется избегать в пользу Policy Objects.

### Сравнение с другими инструментами

| Инструмент | Уровень абстракции | Основная среда | Бэкенд |
| :--- | :--- | :--- | :--- |
| **firewalld** | Высокий (Зоны/Политики) | RHEL / Fedora | nftables |
| **[ufw](./ufw.md)** | Высокий (Simple) | Ubuntu / Debian | nftables/iptables |
| **[iptables основы](./iptables_basics.md)** | Низкий (Цепочки) | Универсальный | Netfilter |
| **[nftables](./nftables/practical_scenarios.md)** | Низкий (Семейства) | Современный Linux | Netfilter |

### Связанные темы

- **[Обзор файрволов](./firewall_common.md)** — общие принципы и сравнение инструментов.
- **[Сетевые зоны безопасности](../../../../Networking/Concepts/network_security_zones.md)** — теория сегментации сетей.
- **[NAT — Практические сценарии](../../../../Networking/Concepts/nat/practical_scenarios.md)** — глубокое погружение в трансляцию адресов.
- **[Взаимодействие Docker и файрвола](../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — решение конфликтов с контейнеризацией.
