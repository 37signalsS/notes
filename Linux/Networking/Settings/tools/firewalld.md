# Firewalld: Динамический файрвол

> [Назад к оглавлению](../linux_firewall_management.md)

## Определения

**Firewalld** — это динамический менеджер файрвола, используемый по умолчанию в RHEL-based дистрибутивах (CentOS, RHEL, Fedora). Он является надстройкой над `nftables` (или `iptables` в старых версиях), предоставляя удобный интерфейс для управления правилами.

## Базовые концепции

Firewalld работает на основе **зон** (zones) и **сервисов** (services), что упрощает настройку. В отличие от статических правил `iptables`, firewalld позволяет изменять правила "на лету" без полной перезагрузки правил.

* **Сервисы** — это шаблоны, которые объединяют порты и протоколы. Например, сервис SSH включает порт 22/TCP.
* **Зоны** — это наборы правил, применяемые к сетевым интерфейсам или IP-адресам.
* **Важные сервисы:** `samba` (SMB/CIFS), `nfs`, `ssh`, `http`, `https`, `mysql`, `ntp` (NTP сервер, порт 123/UDP).

Пример добавления Samba:

## Основные команды firewall-cmd

```bash
# Просмотр всей информации о текущей конфигурации
firewall-cmd --list-all

# Список разрешенных сервисов
firewall-cmd --list-services

# Список открытых портов
firewall-cmd --list-ports

# Добавить порт (временный, действует до перезагрузки)
firewall-cmd --add-port=2233/tcp

# Добавить сервис
firewall-cmd --add-service=ssh

# Удалить порт или сервис
firewall-cmd --remove-port=2233/tcp
firewall-cmd --remove-service=ssh

# Пример: добавить сервис Samba (SMB/CIFS)
firewall-cmd --permanent --add-service=samba
firewall-cmd --reload

# Пример: добавить сервис NTP (для NTP сервера, порт 123/UDP)
firewall-cmd --permanent --add-service=ntp
firewall-cmd --reload

# Сохранить изменения permanent (требует перезагрузки firewalld)
firewall-cmd --permanent --add-port=2233/tcp
firewall-cmd --reload

# Переключить runtime в permanent (применить текущие настройки навсегда)
firewall-cmd --runtime-to-permanent

# Режим паники: блокирует весь входящий и исходящий трафик
firewall-cmd --panic-on
# Выключить режим паники
firewall-cmd --panic-off
```

**Важно:** Изменения без ключа `--permanent` применяются немедленно, но теряются при перезагрузке сервиса или системы.

## Работа с зонами

Firewalld по умолчанию использует зону `public`. Основные предопределенные зоны:

* **drop**: Блокирует все входящие соединения, исходящие разрешены.
* **block**: Блокирует все входящие соединения, но отправляет ICMP-ответ (в отличие от `drop`).
* **public**: Для использования в общественных сетях. По умолчанию блокирует входящие, разрешает исходящие.
* **trusted**: Разрешает весь трафик.

```bash
# Посмотреть все зоны
firewall-cmd --list-all-zones

# Назначить интерфейс на зону
firewall-cmd --zone=trusted --change-interface=eth1

# Добавить IP-адрес (source) в зону
firewall-cmd --zone=trusted --add-source=192.168.1.100
```

## Блокировка ICMP (пинга)

Для защиты от сканирования можно заблокировать ICMP-пакеты (ping):

```bash
# Заблокировать все ICMP-запросы
firewall-cmd --add-icmp-block=echo-request

# Инвертировать ICMP-блокировку (заблокировать все, кроме указанных)
firewall-cmd --add-icmp-block-inversion

# Удалить блокировку
firewall-cmd --remove-icmp-block=echo-request

# Проверить статус
firewall-cmd --list-icmp-blocks
```

## Rich Rules (Расширенные правила)

Rich Rules позволяют создавать детальные правила с указанием IP-адресов, портов, логирования и ограничения частоты.

```bash
# Разрешить SSH только с определенного IP
firewall-cmd --permanent --zone=public --add-rich-rule='rule family="ipv4" source address="192.168.1.100" service name="ssh" accept'

# Заблокировать IP-адрес с логированием
firewall-cmd --permanent --add-rich-rule='rule source address="10.0.0.50" log prefix="BLOCKED: " level="info" drop'

# Ограничить частоту подключений (защита от брутфорса)
firewall-cmd --permanent --add-rich-rule='rule service name="ssh" limit value="5/m" accept'

# Удалить rich rule
firewall-cmd --permanent --remove-rich-rule='rule ...'
```

## Политики (Policies)

Политики — это новый механизм firewalld для управления **транзитным трафиком (FORWARD)**. Они описывают правила для трафика, проходящего с одного интерфейса (зоны) на другой.

```bash
# Создать политику
firewall-cmd --permanent --new-policy myPolicy

# Задать входящую (ingress) и исходящую (egress) зоны
firewall-cmd --permanent --policy myPolicy --add-ingress-zone=dmz
firewall-cmd --permanent --policy myPolicy --add-egress-zone=internal

# Добавить разрешающее правило через rich rule
firewall-cmd --permanent --policy myPolicy --add-rich-rule='rule family="ipv4" source address="10.0.2.101" service name="ssh" accept'

# Применить изменения
firewall-cmd --reload
```

## NAT и Port Forwarding

Firewalld упрощает настройку NAT (Masquerading) и проброса портов (DNAT):

```bash
# Включить Masquerading (SNAT) — нужно для NAT-роутера
firewall-cmd --permanent --zone=external --add-masquerade

# Проброс порта (DNAT) — перенаправление трафика с одного порта на другой хост
# Пример: проброс порта 5555 на внутренний хост 192.168.1.10:22
firewall-cmd --permanent --zone=external --add-forward-port=port=5555:proto=tcp:toport=22:toaddr=192.168.1.10
```
