# Firewalld: динамический файрвол

## Определения

**Firewalld** — динамический менеджер файрвола, используемый по умолчанию в RHEL-based дистрибутивах (CentOS, RHEL, Fedora). Является надстройкой над `nftables` (или `iptables` в старых версиях).

**Ключевые особенности:**

- Работа на основе **зон** (zones) и **сервисов** (services)
- Изменение правил "на лету" без перезагрузки
- Поддержка rich rules для сложных сценариев

См. также:

- **[Концепции сетевых файрволов](../../../../Networking/Concepts/firewall_concepts.md)** — теория Netfilter
- **[iptables основы](./iptables_basics.md)** — низкоуровневое управление
- **[nftables](./nftables/index.md)** — современная подсистема

---

## Basic Concepts

### Зоны и сервисы

**Сервисы** — шаблоны, объединяющие порты и протоколы:

- `ssh` (22/TCP), `http` (80/TCP), `https` (443/TCP)
- `samba` (SMB/CIFS), `nfs`, `mysql`, `ntp` (123/UDP)

**Зоны** — наборы правил, применяемые к интерфейсам или IP:

| Зона | Описание |
| :--- | :--- |
| `drop` | Блокирует всё входящее, исходящее разрешено |
| `block` | Блокирует входящее с ICMP-ответом |
| `public` | По умолчанию: блокирует входящие, разрешает исходящие |
| `trusted` | Разрешает весь трафик |
| `internal` | Для внутренней сети, доверенные хосты |
| `dmz` | Для демилитаризованной зоны |

**Важно:** Изменения без `--permanent` применяются немедленно, но теряются при перезагрузке сервиса/системы.

---

## Practical Scenarios

### Базовые команды firewall-cmd

```bash
# Просмотр конфигурации
firewall-cmd --list-all

# Список сервисов и портов
firewall-cmd --list-services
firewall-cmd --list-ports

# Добавить порт/сервис (временно)
firewall-cmd --add-port=2233/tcp
firewall-cmd --add-service=ssh

# Добавить навсегда (требует reload)
firewall-cmd --permanent --add-port=2233/tcp
firewall-cmd --permanent --add-service=samba
firewall-cmd --reload

# Применить текущие настройки навсегда
firewall-cmd --runtime-to-permanent

# Удалить порт/сервис
firewall-cmd --remove-port=2233/tcp
firewall-cmd --remove-service=ssh
```

### Работа с зонами

```bash
# Посмотреть все зоны
firewall-cmd --list-all-zones

# Назначить интерфейс на зону
firewall-cmd --zone=trusted --change-interface=eth1

# Добавить IP-адрес (source) в зону
firewall-cmd --zone=trusted --add-source=192.168.1.100
```

### Блокировка ICMP (ping)

```bash
# Заблокировать ICMP echo-request
firewall-cmd --add-icmp-block=echo-request

# Инвертировать блокировку (блокировать всё, кроме указанных)
firewall-cmd --add-icmp-block-inversion

# Проверить статус
firewall-cmd --list-icmp-blocks

# Удалить блокировку
firewall-cmd --remove-icmp-block=echo-request
```

### Rich Rules (расширенные правила)

```bash
# Разрешить SSH только с определённого IP
firewall-cmd --permanent --zone=public \
  --add-rich-rule='rule family="ipv4" source address="192.168.1.100" service name="ssh" accept'

# Заблокировать IP с логированием
firewall-cmd --permanent --add-rich-rule \
  'rule source address="10.0.0.50" log prefix="BLOCKED: " level="info" drop'

# Ограничить частоту подключений (защита от брутфорса)
firewall-cmd --permanent --add-rich-rule \
  'rule service name="ssh" limit value="5/m" accept'

# Удалить rich rule
firewall-cmd --permanent --remove-rich-rule='rule ...'
```

### Политики (Policies) — для транзитного трафика

Политики управляют трафиком **FORWARD** (между зонами):

```bash
# Создать политику
firewall-cmd --permanent --new-policy myPolicy

# Задать входящую и исходящую зоны
firewall-cmd --permanent --policy myPolicy --add-ingress-zone=dmz
firewall-cmd --permanent --policy myPolicy --add-egress-zone=internal

# Добавить разрешающее правило
firewall-cmd --permanent --policy myPolicy \
  --add-rich-rule='rule family="ipv4" source address="10.0.2.101" service name="ssh" accept'

# Применить
firewall-cmd --reload
```

### NAT и Port Forwarding

```bash
# Включить Masquerading (SNAT) для NAT-роутера
firewall-cmd --permanent --zone=external --add-masquerade

# Проброс порта (DNAT): 5555 → 192.168.1.10:22
firewall-cmd --permanent --zone=external \
  --add-forward-port=port=5555:proto=tcp:toport=22:toaddr=192.168.1.10
```

### Режим паники

```bash
# Блокировать весь входящий и исходящий трафик
firewall-cmd --panic-on

# Отключить режим паники
firewall-cmd --panic-off
```

---

## Additional Information

### Сохранение правил

Firewalld автоматически сохраняет правила при использовании `--permanent` + `--reload`. Конфигурация хранится в `/etc/firewalld/`.

### Сравнение с другими инструментами

| Инструмент | Уровень | Дистрибутив |
| :--- | :--- | :--- |
| **firewalld** | Высокий | RHEL/CentOS/Fedora |
| **ufw** | Высокий | Ubuntu/Debian |
| **iptables** | Низкий | Все |
| **nftables** | Низкий | Современные дистрибутивы |

### Ссылки по теме

- **[Общие вопросы файрволов](./firewall_common.md)** — сохранение правил, Docker
- **[Лучшие практики правил](../../../../Networking/Concepts/firewall_rules_best_practices.md)** — принципы проектирования
