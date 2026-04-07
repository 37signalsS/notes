# SSH Access Control

## Definitions → Basic Concepts → Practical Scenarios → Additional Information

## Definitions

**SSH Access Control** — механизм ограничения доступа к SSH-серверу на основе пользователей, групп, IP-адресов или сетевых правил. Реализуется через директивы `sshd_config`, файрволы и дополнительные механизмы.

**Whitelist (белый список)** — подход, при котором доступ разрешён только явно указанным субъектам, все остальные заблокированы по умолчанию.

## Basic Concepts

### Директивы контроля доступа в sshd_config

| Директива | Описание | Пример |
| :--- | :--- | :--- |
| `AllowUsers` | Разрешает вход только указанным пользователям. Можно ограничить по IP/хосту | `AllowUsers admin user1@192.168.1.100` |
| `AllowGroups` | Разрешает вход пользователям из указанной группы | `AllowGroups sshusers` |
| `DenyUsers` | Запрещает вход указанным пользователям | `DenyUsers root guest` |
| `DenyGroups` | Запрещает вход пользователям из указанной группы | `DenyGroups nogroup` |

**Приоритет:** Директивы `Allow*` имеют приоритет над `Deny*`. Если пользователь совпадает с обоими — доступ разрешается. Рекомендуется использовать только `AllowUsers` или `AllowGroups` для избежания конфликтов.

### Ограничение по IP-адресу

**Уровень приложения (sshd_config):**

```ini
AllowUsers admin@192.168.1.100 deploy@10.0.0.0/24
```

**Уровень файрвола (iptables/nftables):**

Фильтрация на сетевом уровне до SSH-демона. См. [iptables: основы и практические сценарии](../../../Networking/Settings/tools/iptables_basics.md), [firewalld](../../../Networking/Settings/tools/firewalld.md).

```bash
# iptables: разрешить SSH только с 192.168.1.0/24
sudo iptables -A INPUT -p tcp -s 192.168.1.0/24 --dport 22 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 22 -j DROP
```

### TCP Wrappers

> **Устаревший метод**: TCP Wrappers не поддерживается в современных дистрибутивах (RHEL 8+, Debian 11+) по умолчанию. См. [TCP Wrappers: обзор и миграция](../../../Networking/tcp_wrappers.md).

### Смена стандартного порта

Изменение порта SSH с `22` на нестандартный (например, `2239`) снижает количество автоматических атак от ботов.

**Конфигурация (`/etc/ssh/sshd_config`):**

```ini
Port 2239
```

**Требования:**
- Открыть новый порт в файрволе до перезапуска SSH
- Убедиться в отсутствии конфликтов с другими службами
- После применения проверить подключение в новой сессии (не закрывая текущую)

## Practical Scenarios

### Сценарий 1: Whitelist пользователей

**Задача:** Разрешить SSH только группе `ssh-admins`.

```bash
# 1. Создать группу (если отсутствует)
sudo groupadd ssh-admins

# 2. Добавить пользователей в группу
sudo usermod -aG ssh-admins admin
sudo usermod -aG ssh-admins deploy

# 3. Настроить sshd_config
echo "AllowGroups ssh-admins" | sudo tee -a /etc/ssh/sshd_config

# 4. Перезапустить SSH
sudo systemctl restart sshd
```

### Сценарий 2: Ограничение SSH по IP через файрвол

**Задача:** Разрешить SSH только с доверенных IP.

```bash
# Разрешить SSH с 10.0.0.0/8 и 192.168.1.100
sudo iptables -A INPUT -p tcp -s 10.0.0.0/8 --dport 22 -j ACCEPT
sudo iptables -A INPUT -p tcp -s 192.168.1.100 --dport 22 -j ACCEPT

# Заблокировать остальные SSH-подключения
sudo iptables -A INPUT -p tcp --dport 22 -j DROP

# Сохранить правила
sudo netfilter-persistent save
```

### Сценарий 3: Смена порта SSH

**Задача:** Перенести SSH с порта `22` на `2239`.

```bash
# 1. Открыть новый порт в файрволе
sudo iptables -A INPUT -p tcp --dport 2239 -j ACCEPT

# 2. Изменить порт в sshd_config
sudo sed -i 's/^#Port 22/Port 2239/' /etc/ssh/sshd_config

# 3. Перезапустить SSH
sudo systemctl restart sshd

# 4. Проверить подключение (НЕ закрывая текущую сессию!)
ssh -p 2239 user@hostname

# 5. Закрыть старый порт после подтверждения
sudo iptables -D INPUT -p tcp --dport 22 -j ACCEPT
```

## Additional Information

### Связь с другими механизмами безопасности

| Механизм | Уровень | Применение |
| :--- | :--- | :--- |
| **AllowUsers/AllowGroups** | Прикладной (L7) | Встроенный контроль доступа SSH |
| **iptables/nftables** | Сетевой (L3-L4) | Фильтрация до SSH-демона |
| [TCP Wrappers](../../../Networking/tcp_wrappers.md) | Прикладной (L7) | Устаревший метод (не рекомендуется) |
| [Port Knocking](./port_knocking.md) | Сетевой (L3-L4) | Скрытие SSH от сканирования |

### Рекомендации

- **Комбинированный подход**: Использовать файрвол (сетевой уровень) + `AllowGroups` (прикладной уровень) для многослойной защиты.
- **Минимальные привилегии**: Запретить вход `root` (`PermitRootLogin no`) и использовать `AllowGroups` для контроля доступа.
- **Тестирование**: Всегда проверять подключение в новой сессии после изменения правил доступа.
- **Документация**: Вести учёт разрешённых пользователей/IP в отдельном файле или системе управления конфигурацией (Ansible, Puppet).

### Диагностика проблем

При невозможности подключения проверить:

1. **Статус SSH:** `systemctl status sshd`
2. **Логи аутентификации:** `journalctl -u sshd --since "10 min ago"`
3. **Правила файрвола:** `sudo iptables -nvL INPUT`
4. **Директивы доступа:** `grep -E "Allow|Deny" /etc/ssh/sshd_config`
5. **Сетевую связность:** `nc -zv hostname 22` или `nc -zv hostname 2239`
