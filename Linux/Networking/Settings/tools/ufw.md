# UFW — Uncomplicated Firewall

## Определения

**UFW (Uncomplicated Firewall)** — это высокоуровневый интерфейс для управления правилами межсетевого экрана, разработанный для упрощения настройки `iptables` и `nftables`. Является стандартом по умолчанию в дистрибутиве Ubuntu и широко используется в семействе Debian.

Основная цель UFW — предоставить интуитивно понятный синтаксис для базовых задач фильтрации трафика, скрывая сложность синтаксиса Netfilter.

## Основные концепции

### Принципы работы

1.  **Default Deny Incoming:** по умолчанию весь входящий трафик блокируется.
2.  **Default Allow Outgoing:** исходящий трафик разрешен для обеспечения работы обновлений и внешних запросов.
3.  **Stateful Inspection:** UFW отслеживает состояние соединений (ESTABLISHED, RELATED), автоматически разрешая ответный трафик.
4.  **Application Profiles:** поддержка профилей приложений (хранятся в `/etc/ufw/applications.d/`), которые позволяют открывать порты по имени сервиса (например, `Nginx Full`).

### Механизм трансляции правил (nftables backend)

UFW является фронтендом и не реализует фильтрацию самостоятельно. При каждом изменении (`allow`, `deny`, `limit`) UFW:

1.  Записывает правило в `/etc/ufw/user.rules` (входящие) и `/etc/ufw/user6.rules` (IPv6).
2.  Генерирует соответствующую запись в `nftables` (или `iptables-nft`) через файлы `/etc/ufw/*.rules`.
3.  При `ufw reload` загружает правила атомарно через `ufw-init` hook.

UFW использует следующие цепочки `nftables`:
- `ufw-user-input` — пользовательские правила для INPUT
- `ufw-user-output` — пользовательские правила для OUTPUT
- `ufw-user-forward` — пользовательские правила для FORWARD
- `ufw-before-input` / `ufw-after-input` — служебные правила (до/после пользовательских)

Для просмотра сгенерированных `nftables` правил:
```bash
sudo nft list ruleset | grep ufw
```

### Application Profiles (Профили приложений)

Профили — XML-файлы в `/etc/ufw/applications.d/`, описывающие порты и протоколы сервиса.

```bash
# Просмотр доступных профилей
sudo ufw app list
# Результат:
# Available applications:
#   Nginx Full
#   Nginx HTTP
#   Nginx HTTPS
#   OpenSSH

# Использование профиля
sudo ufw allow 'Nginx Full'
```

Каждый профиль содержит поля:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<application>
  <name>Custom App</name>
  <description>Мой сервис</description>
  <port>8080/tcp</port>
  <port>9090/udp</port>
</application>
```

**Важно:** профили с пробелами в названии требуют quoting (`'Nginx Full'`).

### Базовое управление

```bash
sudo ufw status                # Проверка статуса
# Результат: Status: active (или inactive)

sudo ufw status verbose        # Расширенный статус (политики, логирование)
# Результат:
# Status: active
# Logging: on (low)
# Default: deny (incoming), allow (outgoing), disabled (routed)

sudo ufw enable                # Включение файрвола (загрузка правил)
# Результат: Firewall is active and enabled on system startup

sudo ufw disable               # Выключение файрвола
# Результат: Firewall stopped and disabled on system startup

sudo ufw reload                # Перезагрузка правил без разрыва соединений
```

### Архитектура и бэкенд

В современных дистрибутивах (Ubuntu 22.04, 24.04, 26.04, Debian 11/12) UFW использует **nftables** в качестве бэкенда через уровень совместимости `iptables-nft`. Это обеспечивает лучшую производительность и корректную обработку IPv4 и IPv6 в рамках единого набора правил.

### Управление правилами (CRUD)

```bash
# Удаление правила по номеру
sudo ufw status numbered
sudo ufw delete 3              # Удалит правило под номером 3

# Удаление по описанию
sudo ufw deny 443/tcp
sudo ufw delete deny 443/tcp

# Полная очистка правил (с подтверждением)
sudo ufw reset
```

### Приоритет и упорядочение правил

UFW обрабатывает правила в строгом порядке:

1.  `before.rules` (включая NAT)
2.  Пользовательские правила (в порядке добавления)
3.  `after.rules`

Используйте `insert` для размещения правила перед общими разрешениями:

```bash
# Просмотр пронумерованного списка
sudo ufw status numbered

# Вставить правило на позицию 1 (высший приоритет после before.rules)
sudo ufw insert 1 deny from 203.0.113.5
```

## Практические сценарии

### 1. Начальная настройка («Безопасный старт»)

**Задача:** настроить базовые политики и обеспечить доступ по SSH перед включением файрвола, чтобы не потерять доступ к удаленному серверу.

```bash
# 1. Установка политик по умолчанию
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 2. Разрешение SSH с защитой от брутфорса
# limit ограничивает количество попыток подключения (6 попыток за 30 секунд с одного IP)
sudo ufw limit ssh
# Результат: Rule added

# 3. Включение файрвола
sudo ufw enable

# 4. Проверка расширенного статуса
sudo ufw status verbose
# Результат:
# Status: active
# Logging: on (low)
# Default: deny (incoming), allow (outgoing), disabled (routed)
```

### 2. Работа с портами и протоколами

```bash
# Разрешить входящий TCP трафик на порт 80 (HTTP)
sudo ufw allow 80/tcp

# Разрешить UDP трафик (DNS)
sudo ufw allow 53/udp

# Разрешить оба протокола
sudo ufw allow 443

# Разрешить диапазон портов для пассивного FTP
sudo ufw allow 40000:40100/tcp

# Добавление комментария к правилу для аудита
sudo ufw allow 8080/tcp comment 'Custom API Service'
# Результат: Rule added

# Ограничение по протоколу и IP
sudo ufw allow proto tcp from 10.0.0.0/24 to any port 22
```

### 3. Ограничение доступа по IP и интерфейсам

```bash
# Разрешить доступ к БД PostgreSQL только с конкретного IP
sudo ufw allow from 192.168.1.50 to any port 5432

# Разрешить трафик только на конкретном сетевом интерфейсе
sudo ufw allow in on eth1 to any port 3306

# Разрешить доступ ко всей подсети
sudo ufw allow from 10.0.0.0/24

# Ограничить ICMP (ping) с определенной подсети
sudo ufw allow in from 10.0.0.0/24 to any comment 'Allow monitoring subnet'
```

### 4. Вставка и приоритет правил

По умолчанию новые правила добавляются в конец списка. Если нужно вставить правило в начало (например, для блокировки конкретного IP перед общим разрешением), используется `insert`.

```bash
# Просмотр правил с номерами
sudo ufw status numbered

# Вставить правило на первую позицию (блокировка атакующего IP)
sudo ufw insert 1 deny from 203.0.113.5

# Отменить все для подсети, кроме одного хоста
sudo ufw insert 1 deny from 10.0.0.0/24 to any port 22
sudo ufw allow from 10.0.0.5 to any port 22
```

### 5. Конфигурация NAT и перенаправления (Port Forwarding)

UFW не имеет встроенных команд CLI для настройки NAT. Для этого необходимо редактировать конфигурационные файлы.

**Шаг 1: Разрешение IP Forwarding**
В файле `/etc/ufw/sysctl.conf` раскомментируйте:
`net/ipv4/ip_forward=1`

**Шаг 2: Настройка политики Forward**
В файле `/etc/default/ufw` установите:
`DEFAULT_FORWARD_POLICY="ACCEPT"`

**Шаг 3: Добавление правил в before.rules**
Отредактируйте `/etc/ufw/before.rules`, добавив блок NAT в начало файла (перед `*filter`):

```bash
*nat
:PREROUTING ACCEPT [0:0]
:POSTROUTING ACCEPT [0:0]

# Перенаправление порта 80 на внутренний IP
-A PREROUTING -i eth0 -p tcp --dport 80 -j DNAT --to-destination 192.168.1.10:80

# Маскарадинг для выхода внутренней сети в интернет
-A POSTROUTING -s 192.168.1.0/24 -o eth0 -j MASQUERADE

COMMIT
```

**Валидация:**
```bash
sudo ufw reload
sudo iptables -t nat -L -n -v
```

### 6. Интеграция с Fail2ban

Для корректной работы Fail2ban с UFW необходимо убедиться, что Fail2ban вставляет правила блокировки в начало цепочки.

В файле `/etc/fail2ban/jail.local` установите:
```ini
banaction = ufw
banaction_allports = ufw
```

Это заставит Fail2ban использовать команду `ufw insert 1 ...` для блокировки IP.

**Проверка:**
```bash
# Симулируйте неудачные попытки и проверьте, появилось ли правило
sudo ufw status numbered
# → [1] DENY IN 203.0.113.5
```

### 7. Интеграция с Ansible

Для автоматизированного развертывания используйте модуль `community.general.ufw`:

```yaml
- name: Убедиться что UFW установлен
  ansible.builtin.apt:
    name: ufw
    state: present

- name: Настройка UFW (SSH, HTTP, HTTPS)
  community.general.ufw:
    rule: allow
    name: "{{ item }}"
  loop:
    - OpenSSH
    - 'Nginx Full'
  notify: Reload UFW

- name: Включение UFW
  community.general.ufw:
    state: enabled
  handlers:
    - name: Reload UFW
      community.general.ufw:
        state: reloaded
```

### 8. Интеграция с Docker (проблема Bypass и ufw-docker)

**Критическая особенность:** Docker по умолчанию манипулирует цепочками `iptables` (в частности `PREROUTING`) напрямую, что позволяет трафику попадать в контейнеры в обход правил `INPUT` в UFW. Если вы опубликовали порт (`-p 80:80`), он будет доступен извне, даже если в UFW стоит `deny`.

**Решение: ufw-docker**

Пакет `ufw-docker` автоматически синхронизирует правила UFW с таблицами Docker:

```bash
# Установка
sudo curl -Lo /usr/local/bin/ufw-docker https://github.com/chaifeng/ufw-docker/raw/master/ufw-docker
sudo chmod +x /usr/local/bin/ufw-docker

# Разрешить доступ к контейнеру
sudo ufw-docker allow http 80/tcp

# Запретить доступ к контейнеру
sudo ufw-docker deny http

# Проверка правил
sudo ufw-docker ls
```

**Альтернативные подходы:**
- Привязывайте порты к `127.0.0.1` (`-p 127.0.0.1:80:80`) и используйте Reverse Proxy (Nginx/Angie).
- Используйте цепочку `DOCKER-USER` для фильтрации Docker-трафика (см. **[Docker — сеть](../../../../Docker/Docker_network/docker_network.md)**).

## Дополнительная информация

### Конфигурационные файлы

- `/etc/default/ufw`: основные настройки (IPv6, политики по умолчанию).
- `/etc/ufw/before.rules`: правила, выполняемые ПЕРЕД пользовательскими правилами (подходит для NAT).
- `/etc/ufw/after.rules`: правила, выполняемые ПОСЛЕ пользовательских правил.
- `/etc/ufw/sysctl.conf`: настройки ядра (IP forwarding).
- `/lib/ufw/user.rules`: правила, созданные через CLI (не редактировать вручную).
- `/etc/ufw/applications.d/`: XML-профили приложений.

**См. также:** **[Общие вопросы файрволов](./firewall_common.md)** — персистентность правил и архитектурные различия бэкендов.

### Логирование

UFW поддерживает уровни логирования: `low` (по умолчанию), `medium`, `high`, `full`.

```bash
sudo ufw logging medium
```

Логи записываются в `/var/log/ufw.log` и системный журнал `journald`.

```bash
# Просмотр через journalctl
sudo journalctl -u ufw -f

# Просмотр логов файрвола
sudo tail -f /var/log/ufw.log
```

### IPv6

UFW автоматически управляет правилами IPv6, если в файле `/etc/default/ufw` установлено `IPV6=yes`. Большинство команд (например, `allow 80`) создают правила сразу для обоих протоколов.

**Важно:** Блокирование ICMPv6 критично. Полный разбор см. в **[Настройка файрвола для IPv6](../../../../Linux/Networking/Settings/ipv6_configuration/firewall.md)**.

### Влияние на сканирование (Nmap)

При политике `deny` (действие `DROP`) сканирование замедляется, так как `nmap` ожидает таймаута. Порты отображаются как `filtered`.

```bash
# Быстрая проверка
sudo nmap -sS -p 22,80,443 <target>

# Определение состояния файрвола
sudo ufw status
```

### Безопасность: Hardening

1.  **Минимизация поверхности атаки:** Используйте `deny (incoming)` по умолчанию, разрешайте только необходимые порты.
2.  **Rate limiting:** Защита SSH и других сервисов от brute-force.
3.  **Отключение ненужных протоколов:** Закройте IPv6, если он не используется (`IPV6=no`).
4.  **Логирование:** Включите `medium` или `high` для аудита.
5.  **Регулярный аудит:** Проверяйте правила ежеквартально.
6.  **ICMP:** Ограничьте ICMP (ping) из внешних сетей.

```bash
# Отключить ICMP (ping) из внешних сетей
sudo ufw deny in icmp

# Разрешить ping только из подсети мониторинга
sudo ufw allow from 10.0.0.0/24 to any comment 'Monitoring ping'
```

### Диагностика и устранение неполадок

**UFW не запускается:**
```bash
# Проверка статуса сервиса
sudo systemctl status ufw

# Проверка конфигурации на ошибки
sudo ufw debug
```

**Порт недоступен несмотря на правило:**
```bash
# 1. Проверка статуса UFW
sudo ufw status numbered

# 2. Проверка конкретного правила
sudo iptables -L ufw-user-input -n -v

# 3. Проверка слушающего сокета
sudo ss -tlnp | grep <port>

# 4. Проверка внешнего доступа
sudo nmap -p <port> localhost
```

**Правила не применяются после reload:**
```bash
# Очистка и перезагрузка
sudo ufw disable
sudo ufw reset
sudo ufw enable
```

**Конфликт с Docker:**
```bash
# Проверка правил Docker
sudo iptables -L DOCKER-USER -n -v
# Установите ufw-docker для синхронизации
```

### Краевые случаи и ограничения

1.  **Профили приложений:** UFW читает профили только при старте. После добавления нового XML-файла требуется `ufw reload`.
2.  **IPv6:** Если `IPV6=yes`, правило `allow 80/tcp` создаст записи и для IPv6. Для IPv6-only используйте `allow in 6 80/tcp`.
3.  **Логирование `full`:** Записывает полные дампы пакетов, что может создать нагрузку на диск. Используйте только для диагностики.
4.  **Docker:** Прямая публикация портов (`-p 80:80`) обходит UFW. Используйте `DOCKER-USER` или `ufw-docker`.
5.  **Rate limit:** Работает только для TCP. Для UDP используйте Fail2ban или `limit` через `before.rules`.
6.  **Per-interface правила:** `ufw allow in on eth1 to any port 3306` требует точного имени интерфейса (проверьте через `ip link`).

### Связанные темы

- **[Обзор файрволов](./firewall_common.md)** — сравнение инструментов и сохранение правил.
- **[Межсетевые экраны: концепции](../../../../Networking/Concepts/firewall_concepts.md)** — Netfilter, L3/L4/L7 фильтрация.
- **[Firewalld: динамический менеджер](./firewalld.md)** — альтернатива для RHEL-based систем.
- **[iptables основы](./iptables_basics.md)** — низкоуровневая настройка.
- **[Настройка файрвола для IPv6](../../../../Linux/Networking/Settings/ipv6_configuration/firewall.md)** — особенности IPv6 и ICMPv6.
- **[nftables: архитектура и концепции](../../../../Linux/Networking/Settings/tools/nftables/architecture_and_concepts.md)** — современная альтернатива.
- **[Docker — сеть](../../../../Docker/Docker_network/docker_network.md)** — интеграция и решение проблемы bypass.
- **[Ansible: модуль ufw](../../../../Ansible/Modules/ansible_service_and_system_config_modules.md)** — автоматизация через Ansible.
