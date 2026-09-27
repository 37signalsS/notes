# Firewalld: динамический межсетевой экран

## Определения

**Firewalld** — это динамический менеджер межсетевого экрана, используемый по умолчанию в дистрибутивах на базе RHEL (CentOS Stream, RHEL, Fedora, AlmaLinux, Rocky Linux). Он представляет собой высокоуровневую абстракцию над подсистемой **nftables** (или `iptables` в устаревших системах).

Основное отличие Firewalld от статических инструментов (например, `iptables-services`) — возможность изменять конфигурацию без перезагрузки всей службы и разрыва существующих соединений, а также полная поддержка концепции зон доверия.

**Firewalld daemon** (`firewalld`) работает как системный сервис и взаимодействует с клиентами (в том числе `firewall-cmd`) через шину **D-Bus**. Это позволяет локальным приложениям запрашивать динамическое изменение правил без непосредственного доступа к `nftables`/`iptables`.

## Основные концепции

### Архитектура и бэкенд

Firewalld не реализует фильтрацию самостоятельно. При получении конфигурации он транслирует высокоуровневые правила в низкоуровневые правила **nftables** (в современных системах) или **iptables** (в устаревших).

**Преимущества динамического подхода:**
- Правила применяются к текущему состоянию ядра атомарно, без перезагрузки `nftables` service.
- Существующие соединения не разрываются (stateful inspection через `conntrack`).
- Верификация и откат: при ошибке конфигурации предыдущий набор правил остается в памяти.

**Структура правил в nftables:**
Firewalld создает таблицы семейства `inet` (для unified IPv4/IPv6) или `ip`/`ip6` (legacy), содержащие цепочки вида:
- `<zone>_IN_<zone>` — входящий трафик в зону
- `<zone>_OUT_<zone>` — исходящий трафик из зоны
- `<zone>_FWD_<zone>` — транзитный трафик между интерфейсами зоны

Для просмотра сгенерированных nftables правил:
```bash
sudo nft list ruleset | grep -A5 "table inet firewalld"
```

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

**Практическое применение зон для SRE:**
- **public**: дефолтная зона для интерфейсов, смотрящих в интернет (eth0, ens3). Разрешать только 22/ssh, 443/https при необходимости.
- **external**: интерфейс с выходом в интернет при включенном MASQUERADE. Подходит для шлюзов/NAT-серверов.
- **internal**: интерфейсы в доверенной сети (LAN, VPC private subnet). Можно открыть больше сервисов (SMB, LDAP, NTP, DNS).
- **dmz**: для веб-серверов, доступных из внешней сети, но изолированных от внутренней.
- **trusted**: только для запечатанных сегментов (hypervisor management, isolated storage).

### Сервисы (Services)

Сервисы — это XML-файлы с описанием портов и протоколов (хранятся в `/usr/lib/firewalld/services/`). Использование сервисов (например, `--add-service=http`) предпочтительнее прямого открытия портов, так как это упрощает аудит и перенос конфигурации.

Создание кастомного сервиса (например, для приложения на порту 9090/tcp):
```bash
sudo cp /usr/lib/firewalld/services/ssh.xml /etc/firewalld/services/custom-app.xml
# Редактирование: изменить <port>9090/tcp</port> и <description>
sudo firewall-cmd --reload
```

### Объекты политик (Policy Objects)

Концепция (введена в Firewalld 1.0+), позволяющая фильтровать трафик **между** зонами (Forwarding), а не только входящий трафик на сам хост. Это делает Firewalld эффективным инструментом для управления трафиком виртуальных машин, контейнеров и маршрутизации между интерфейсами.

**Цели (Targets) в Policy Objects:**
- `ACCEPT` — разрешить весь трафик, соответствующий правилам
- `REJECT` — отклонить с отправкой ICMP error
- `DROP` — отбросить без ответа
- `%%REJECT%%` — стандартный reject с автоматическим выбором ICMP типа

### Режимы конфигурации

1.  **Runtime:** правила применяются немедленно к текущему состоянию ядра, но теряются после перезагрузки службы.
2.  **Permanent:** правила сохраняются в конфигурационных файлах в `/etc/firewalld/`, но вступают в силу только после перезагрузки конфигурации (`--reload`) или использования флага `--immediate` вместе с `--permanent`.

**Важно:** команда `firewall-cmd --runtime-to-permanent` сохраняет текущие runtime-правила в permanent-конфигурацию. Используйте ее перед отключением службы, чтобы не потерять правила.

### Masquerading и FORWARD

**Masquerading** (Source NAT) в Firewalld применяется к исходящему трафику из зоны и используется для скрытия внутренней адресации при выходе в интернет.

```bash
# Включить masquerading в зоне external
sudo firewall-cmd --permanent --zone=external --add-masquerade
sudo firewall-cmd --reload
```

**Forwarding** между зонами разрешается только при наличии:
1. Разрешения в исходной зоне (`--add-forward-port` или Policy Object)
2. Разрешения в целевой зоне
3. Включенной IP forwarding в ядре (`net.ipv4.ip_forward=1` или `net.ipv6.conf.all.forwarding=1`)

### ICMP-типы

Firewalld позволяет управлять ICMP-сообщениями на уровне зон. В современных дистрибутивах (RHEL 8+) используются `icmp-types` вместо блокировки всего ICMP.

```bash
# Просмотр доступных ICMP-типов
sudo firewall-cmd --get-icmptypes

# Разрешить echo-reply (ping ответ) в зоне public
sudo firewall-cmd --permanent --zone=public --add-icmp-block=echo-reply
```

## Практические сценарии

### Предварительные требования

- **ОС:** RHEL 8+/CentOS Stream 8+/AlmaLinux 8+/Rocky Linux 8+/Fedora 35+
- **Пакет:** `firewalld` (установлен по умолчанию)
- **Права:** root или sudo
- **Бэкенд:** nftables (рекомендуется). Для проверки: `firewall-cmd --get-backend`
- **Сетевое ядро:** включен `conntrack` и `netfilter` (в современных ядрах по умолчанию)

```bash
# Проверка статуса службы
sudo systemctl is-active firewalld
# → active (ожидается)

# Проверка бэкенда
firewall-cmd --get-backend
# → nftables (ожидается в RHEL 8+)

# Проверка версии firewalld
firewall-cmd --version
# → 1.0+ (для Policy Objects)
```

### 1. Начальная настройка («Безопасный старт»)

**Задача:** убедиться в доступности SSH, установить зону по умолчанию и активировать защиту.

```bash
# 1. Проверка текущего статуса
sudo firewall-cmd --state
# → running

# 2. Установка зоны по умолчанию
sudo firewall-cmd --set-default-zone=public
# → success

# 3. Разрешение SSH (постоянное правило с немедленным применением)
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --reload
# → success

# 4. Просмотр активных правил в зоне
sudo firewall-cmd --list-all
# → public (active)
#   target: default
#   services: ssh
#   ports:
#   protocols:
#   masquerade: no
#   forward-ports:
#   source-ports:
#   icmp-blocks:
#   rich rules:

# 5. Валидация: тест подключения к SSH с внешнего хоста
nc -zv <server-ip> 22
# → Connection to <server-ip> 22 port [tcp/ssh] succeeded!
```

### 2. Управление интерфейсами и зонами

**Задача:** назначить интерфейс на конкретную зону и изменить зону по умолчанию.

```bash
# Просмотр активных зон и привязанных интерфейсов
sudo firewall-cmd --get-active-zones
# → public
#     interfaces: eth0
#   trusted
#     interfaces: eth1

# Назначение интерфейса eth1 на зону internal
sudo firewall-cmd --permanent --zone=internal --add-interface=eth1
sudo firewall-cmd --reload

# Изменение зоны по умолчанию (новые интерфейсы попадают сюда)
sudo firewall-cmd --set-default-zone=internal

# Валидация
sudo firewall-cmd --list-all --zone=internal
```

### 3. Управление портами и IPsets

**IPsets** используются для высокопроизводительной фильтрации списков адресов.

```bash
# Создание IPset для списка блокировки
sudo firewall-cmd --permanent --new-ipset=blacklist --type=hash:net

# Добавление подсети в список
sudo firewall-cmd --permanent --ipset=blacklist --add-entry=192.168.100.0/24

# Применение блокировки через Rich Rule
sudo firewall-cmd --permanent --zone=public --add-rich-rule='rule source ipset="blacklist" drop'
sudo firewall-cmd --reload

# Валидация: тест с заблокированного адреса
curl -sS -o /dev/null -w "%{http_code}\n" http://<server-ip>/
# → connection timeout (ожидается)

# Удаление отдельного IP из IPset
sudo firewall-cmd --permanent --ipset=blacklist --remove-entry=192.168.100.0/24
sudo firewall-cmd --reload

# Удаление всего IPset
sudo firewall-cmd --permanent --delete-ipset=blacklist
sudo firewall-cmd --reload
```

### 4. Межзонная фильтрация (Policy Objects)

**Задача:** разрешить трафик из зоны `internal` в зону `public` только для HTTP и HTTPS.

```bash
# Создание объекта политики
sudo firewall-cmd --permanent --new-policy internal-to-public

# Настройка направлений (Ingress — вход, Egress — выход)
sudo firewall-cmd --permanent --policy internal-to-public --add-ingress-zone internal
sudo firewall-cmd --permanent --policy internal-to-public --add-egress-zone public

# Разрешение трафика и установка цели (ACCEPT/REJECT/DROP)
sudo firewall-cmd --permanent --policy internal-to-public --add-service={http,https}
sudo firewall-cmd --permanent --policy internal-to-public --set-target=ACCEPT
sudo firewall-cmd --reload

# Валидация
sudo firewall-cmd --policy internal-to-public --list-all
# → internal-to-public
#   priority: 0
#   egress zones: public
#   ingress zones: internal
#   services: http https
#   target: ACCEPT

# Удаление политики
sudo firewall-cmd --permanent --delete-policy=internal-to-public
sudo firewall-cmd --reload
```

### 5. Расширенные правила (Rich Rules)

Rich Rules позволяют создавать сложные условия фильтрации в одну команду.

```bash
# Ограничение частоты подключений к SSH (защита от перебора)
sudo firewall-cmd --permanent --add-rich-rule='rule service name="ssh" limit value="3/m" accept'

# Разрешить доступ к порту 8080 только для конкретного IP с логированием
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.50" port port="8080" protocol="tcp" log prefix="API_ACCESS " level="info" accept'

# Блокировка всего трафика из подсети с логом
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="203.0.113.0/24" log prefix="BLOCKED_SUBNET " level="warning" drop'

# Валидация: просмотр правил
sudo firewall-cmd --list-rich-rules

# Удаление конкретного rich-правила
sudo firewall-cmd --permanent --remove-rich-rule='rule family="ipv4" source address="10.0.0.50" port port="8080" protocol="tcp" log prefix="API_ACCESS " level="info" accept'
sudo firewall-cmd --reload
```

### 6. Режим блокировки (Lockdown Mode)

Предотвращает изменение правил файрвола локальными приложениями (например, запущенными от имени root), если они не внесены в белый список (`lockdown-whitelist.xml`).

```bash
# Включение режима блокировки
sudo firewall-cmd --lockdown-on

# Проверка статуса
sudo firewall-cmd --query-lockdown
# → yes

# Просмотр белого списка
sudo firewall-cmd --lockdown-whitelist-list
# → /usr/lib/firewalld/lockdown-whitelist.xml (системный)
# → /etc/firewalld/lockdown-whitelist.xml (пользовательский)

# Выключение режима блокировки
sudo firewall-cmd --lockdown-off
```

**Важно:** Lockdown Mode блокирует изменения от любых локальных клиентов, кроме тех, что указаны в whitelist. Перед включением убедитесь, что текущий `firewall-cmd` будет иметь возможность отключить режим.

### 7. Логирование отброшенных пакетов

По умолчанию Firewalld не логирует отброшенные пакеты (Deny/Drop).

```bash
# Включить логирование только для пакетов, соответствующих политике deny
sudo firewall-cmd --set-log-denied=all
# Варианты: all, unicast, broadcast, multicast, off

# Проверка: появление записей в journald
sudo journalctl -u firewalld -f --since "1 minute ago"
# → packet deny: IN=eth0 OUT= MAC=... SRC=... DST=... PROTO=TCP SPT=... DPT=80

# Валидация тестовым подключением
nc -zv <server-ip> 80
# → connection refused (ожидается для blocked порта)
```

### 8. Резервное копирование и восстановление

**Задача:** создать резервную копию конфигурации и восстановить при необходимости.

```bash
# Резервное копирование всех зон и сервисов
sudo mkdir -p /var/backups/firewalld
sudo cp -r /etc/firewalld /var/backups/firewalld/$(date +%F)

# Экспорт только runtime-правил (для сравнения)
sudo firewall-cmd --list-all-zones > /var/backups/firewalld/zones-runtime-$(date +%F).txt

# Восстановление: копирование файлов зон
sudo cp /var/backups/firewalld/2024-01-15/zones/*.xml /etc/firewalld/zones/
sudo firewall-cmd --reload

# Проверка восстановления
sudo firewall-cmd --list-all --zone=public
```

### 9. Production hardening: ограничение SSH

**Задача:** разрешить SSH только из подсети управления с ограничением по частоте.

```bash
# Создание IPset для доверенных админов
sudo firewall-cmd --permanent --new-ipset=admin-whitelist --type=hash:ip

# Добавление jump-хоста и VPN-сети
sudo firewall-cmd --permanent --ipset=admin-whitelist --add-entry=10.0.99.10
sudo firewall-cmd --permanent --ipset=admin-whitelist --add-entry=10.0.99.0/24

# Разрешение SSH только из whitelist с ограничением 3 попытки/минута
sudo firewall-cmd --permanent --add-rich-rule='rule source ipset="admin-whitelist" service name="ssh" limit value="3/m" accept'

# Открытие до всех остальных (с drop, чтобы не светить порт)
sudo firewall-cmd --permanent --add-rich-rule='rule service name="ssh" drop'

# Применение
sudo firewall-cmd --reload

# Валидация
sudo firewall-cmd --list-rich-rules
# → rule service name="ssh" drop
# → rule source ipset="admin-whitelist" service name="ssh" limit value="3/m" accept

# Тест из доверенной сети (должен пройти)
nc -zv <server-ip> 22

# Тест из внешней сети (должен быть отклонен)
nc -zv <server-ip> 22
# → Connection timed out (ожидается, так как drop без ответа)
```

### 10. Восстановление после блокировки SSH

**Симптом:** после применения правил SSH подключение отрывается, нет консольного доступа (OOB/IPMI).

```bash
# Вариант A: консольный доступ (IPMI / iDRAC / iLO)
# Подключиться через out-of-band management и откатить правила

# Вариант B: перезагрузка в rescue mode
sudo systemctl reboot
# В boot menu выбрать rescue mode, mount /etc/firewalld и откатить изменения

# Вариант C: отключение firewalld до перезагрузки (если есть root-доступ локально)
sudo systemctl stop firewalld
sudo firewall-cmd --reload  # сбросит к permanent-правилам
# Если permanent-правила тоже блокируют — нужно редактировать XML напрямую

# Валидация после восстановления
sudo firewall-cmd --list-all
sudo ss -tlnp | grep ':22'
```

## Диагностика и устранение неполадок

### Команды диагностики

```bash
# Статус службы
sudo systemctl status firewalld
# → active (running) / inactive (dead)

# Активные зоны и интерфейсы
sudo firewall-cmd --get-active-zones

# Полный список всех зон и их правил
sudo firewall-cmd --list-all-zones

# Проверка конфигурации на ошибки
sudo firewall-cmd --check-config
# → success (или error: ...)

# Просмотр сгенерированных nftables правил
sudo nft list ruleset | grep -A20 "table inet firewalld"

# Мониторинг логов в реальном времени
sudo journalctl -u firewalld -f

# Проверка текущих соединений (conntrack)
sudo conntrack -L -p tcp --dport 22
```

### Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| SSH доступ пропал | Правило добавлено в runtime без `--permanent`, или зона изменена без сохранения SSH | Всегда используйте `--permanent` + `--reload` для критичных правил |
| Docker контейнеры не могут общаться с внешним миром | Docker управляет iptables напрямую, обходя firewalld в зоне external | Настройте правильное `--zone` для docker-интерфейса или используйте `DOCKER-USER` цепочку |
| DNS не работает | ICMPv6 или UDP/53 заблокирован в зоне | Разрешите `dns` сервис и проверьте `--add-icmp-block` |
| `--check-config` возвращает error | Ошибка в XML-синтаксисе кастомных зон/сервисов | Валидация XML: `sudo xmllint --noout /etc/firewalld/zones/*.xml` |
| Правила не применяются после `--reload` | Конфигурация permanent не была изменена (работа только в runtime) | Используйте `--runtime-to-permanent` для сохранения |

### Конфликты с контейнерами и CNI

Firewalld может конфликтовать с Docker и Kubernetes CNI-плагинами (Calico, Flannel), которые управляют `nftables` напрямую.

**Симптомы:** поды/контейнеры теряют связность, `NetworkUnavailable=True`.

**Диагностика:**
```bash
# Проверка статуса firewalld
sudo systemctl status firewalld

# Проверка правил CNI
sudo nft list ruleset | grep -E "cali|flannel|kube"

# Проверка наличия конфликтующих правил
sudo iptables -L -n -v | grep -E "DOCKER|KUBE"
```

**Решение для Kubernetes:**
```bash
# Отключение firewalld на узлах кластера (рекомендация Rancher/K8s)
sudo systemctl disable --now firewalld

# ИЛИ добавление исключений для CNI-интерфейсов
sudo firewall-cmd --permanent --zone=trusted --add-interface=cni0
sudo firewall-cmd --permanent --zone=trusted --add-interface=flannel.1
sudo firewall-cmd --reload
```

**Решение для Docker (если firewalld нельзя отключать):**
```bash
# Разрешение traffic через docker-мост
sudo firewall-cmd --permanent --zone=trusted --add-interface=docker0
sudo firewall-cmd --permanent --zone=trusted --add-port=2375/tcp
sudo firewall-cmd --reload
```

## Рекомендации и лучшие практики

### Production checklist для SRE

- [ ] **Зона по умолчанию:** установлена `public` или кастомная строгая зона. Не оставляйте `trusted` по умолчанию.
- [ ] **SSH:** ограничен trusted IPset/подсетью с rate limiting. Root-login отключен на уровне sshd, но файрвол — второй рубеж.
- [ ] **Permanent + Reload:** все изменения в production должны применяться через `--permanent --reload` или `--permanent --immediate`.
- [ ] **Резервное копирование:** `/etc/firewalld/` включен в ежедневный бэкап сервера.
- [ ] **Логирование:** включено `--set-log-denied=all`, логи уходят в central SIEM (journald remote, ELK, Loki).
- [ ] **OOB доступ:** перед изменением правил убедитесь в наличии консольного доступа (IPMI/iDRAC/iLO) для восстановления при локауте.
- [ ] **Конфигурация как код:** правила проверяются через `firewall-cmd --check-config` в CI/CD пайплайне.
- [ ] **Аудит:** регулярный `firewall-cmd --list-all-zones` сравнивается с approved baseline.

### Очистка и откат изменений

```bash
# Очистка всех runtime-правил (сброс к permanent)
sudo firewall-cmd --reload

# Очистка конкретной зоны (сброс к системному шаблону)
sudo firewall-cmd --permanent --zone=public --remove-service=ssh
sudo firewall-cmd --permanent --zone=public --remove-port=8080/tcp
sudo firewall-cmd --reload

# Полный сброс к заводским настройкам (удаление всех кастомных зон и правил)
sudo rm -rf /etc/firewalld/zones/*.xml /etc/firewalld/services/*.xml
sudo firewall-cmd --reload
# Внимание: удаляет все permanent-правила!
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

Подробнее: **[Fail2ban — инструмент защиты](../../../../Linux/Security/Tools/fail2ban.md)**

### Прямой интерфейс (Direct Interface)

Устаревший способ (legacy) вставки чистых правил `iptables`/`nftables`. Используется в исключительных случаях, когда возможностей зон и Rich Rules недостаточно. Рекомендуется избегать в пользу Policy Objects.

### Сравнение с другими инструментами

| Инструмент | Уровень абстракции | Основная среда | Бэкенд |
| :--- | :--- | :--- | :--- |
| **firewalld** | Высокий (Зоны/Политики) | RHEL / Fedora | nftables |
| **[ufw](./ufw.md)** | Высокий (Simple) | Ubuntu / Debian | nftables/iptables |
| **[iptables основы](./iptables_basics.md)** | Низкий (Цепочки) | Универсальный | Netfilter |
| **[nftables](./nftables/practical_scenarios.md)** | Низкий (Семейства) | Современный Linux | Netfilter |

### Граничные случаи

- **Конфликт с Docker/Kubernetes:** файрвол на узлах кластера должен быть отключен или адаптирован под CNI. См. раздел «Диагностика».
- **IPv6:** firewalld управляет IPv4 и IPv6 независимо. Правила без указания `family` применяются к обоим стекам. Для специфичных IPv6 правил используйте `family="ipv6"` в Rich Rules.
- **Бездисковые/контейнерные окружения:** firewalld требует записываемой файловой системы для `/etc/firewalld/` и `/run/firewalld/`. Для минимальных контейнеров используйте `nftables` напрямую.
- **Высоконагруженные IPsets:** при более чем 10 000 записей используйте тип `hash:ip` вместо `hash:net` для лучшей производительности.

### Связанные темы

- **[Обзор файрволов](./firewall_common.md)** — общие принципы и сравнение инструментов.
- **[Сетевые зоны безопасности](../../../../Networking/Concepts/network_security_zones.md)** — теория сегментации сетей.
- **[NAT — Практические сценарии](../../../../Networking/Concepts/nat/practical_scenarios.md)** — глубокое погружение в трансляцию адресов.
- **[Взаимодействие Docker и файрвола](../../../../Docker/Docker_network/troubleshooting/iptables_integration.md)** — решение конфликтов с контейнеризацией.
- **[Настройка файрвола для IPv6](../ipv6_configuration/firewall.md)** — особенности IPv6 и firewalld.
