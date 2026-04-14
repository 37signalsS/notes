# fail2ban

## Definitions → Basic Concepts → Practical Scenarios → Additional Information

## Definitions

**fail2ban** — демон предотвращения brute-force атак. Мониторит логи сервисов (`/var/log/auth.log`, логи веб-серверов) на наличие вредоносных IP-паттернов (многократные неудачные входы, сканирование эксплойтов). Автоматически блокирует IP через правила фаервола.

Связано: [brute-force атаки](../../../../Security/Concepts/brute_force_attacks.md)

## Basic Concepts

### Архитектура

1. **Мониторинг логов**: отслеживание логов сервисов (SSH, Apache, Nginx) в реальном времени.
2. **Обнаружение паттернов**: regex-фильтры выявляют вредоносную активность (неудачные входы, сканирование портов).
3. **Временная блокировка**: после `maxretry` нарушений в пределах `findtime` IP блокируется на `bantime` через фаервол.
4. **Авторазблокировка**: IP разблокируется по истечении `bantime`.

### Ключевые параметры

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `bantime` | Длительность блокировки (секунды) | 600 (10 мин) |
| `findtime` | Окно подсчёта нарушений (секунды) | 600 (10 мин) |
| `maxretry` | Неудачных попыток до блокировки | 5 |
| `backend` | Бэкенд логов (`file`, `systemd`) | `file` |
| `banaction` | Бэкенд фаервола | `iptables-multiport` |

### Бэкенды фаервола

- `iptables` (по умолчанию)
- `nftables` — требуется `banaction = nftables-multiport` ([nftables практические сценарии](../../../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md))
- `firewalld`
- `shorewall`

### Возможности

- Кастомизация фильтров через regex (`/etc/fail2ban/filter.d/`)
- Email-уведомления (`destemail`, `mta`)
- Интеграция с systemd journal (`backend = systemd`)
- IPset для крупных блоклистов (хэшированные таблицы, быстрее отдельных правил iptables)

## Practical Scenarios

### Установка

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install fail2ban ipset

# CentOS/RHEL
sudo dnf install fail2ban
```

ipset рекомендован для крупных блоклистов (см. [firewall common](../../../../Linux/Networking/Settings/tools/firewall_common.md)).

### Конфигурация

Копирование конфига в `jail.local` (**не редактировать** `jail.conf` — перезаписывается при обновлении пакета):

```bash
sudo cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
```

#### Глобальные настройки (`[DEFAULT]` в `jail.local`)

```ini
bantime = 3600
findtime = 600
maxretry = 3
banaction = iptables-ipset-protoall  # ipset для производительности
```

#### Активация jails

Включение jails для сервисов в `jail.local`:

```ini
[sshd]
enabled = true
port = ssh
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600
findtime = 600
```

Обнаружение Nginx 404 сканирования:

```ini
[nginx-404]
enabled = true
port = http,https
logpath = /var/log/nginx/access.log
maxretry = 5
findtime = 300
```

#### Интеграция с Nginx Rate Limiting

1. Настройка Nginx `limit_req` ([DDoS-защита](../../../../Security/ApplicationSecurity/ddos_overview.md#rate-limiting-nginx)):

```nginx
http {
    limit_req_zone $binary_remote_addr zone=mylimit:10m rate=3r/s;
    server {
        location / {
            limit_req zone=mylimit burst=5 nodelay;
        }
    }
}
```

1. Настройка fail2ban jail:

```ini
[nginx-limit-req]
enabled = true
port = http,https
filter = nginx-limit-req
logpath = /var/log/nginx/error.log
maxretry = 4
findtime = 600
bantime = 7200
action = iptables-ipset-protoall[name=nginx-limit-req, port="http,https", protocol=tcp]
```

Блокировка на уровне фаервола (до достижения Nginx), снижение нагрузки на веб-сервер.

#### DROP вместо REJECT

Использовать DROP (тихий дроп пакета) вместо REJECT (ответ атакующему):

```ini
# /etc/fail2ban/action.d/iptables-blocktype.local
[Definition]
blocktype = DROP
```

### Управление сервисом

```bash
# Управление сервисом
sudo systemctl start|stop|restart|reload fail2ban

# Проверка статуса
sudo systemctl status fail2ban
sudo fail2ban-client status
sudo fail2ban-client status <jail_name>

# Управление IP
sudo fail2ban-client set <jail_name> unbanip <IP>
sudo fail2ban-client set <jail_name> banip <IP>
```

## Additional Information

### Оптимизация производительности

- **ipset**: обязателен для крупных блоклистов (>100 IP). Хэшированные таблицы значительно быстрее отдельных правил iptables.
- **systemd backend**: установить `backend = systemd` в конфиге jail для чтения напрямую из journal (современный подход).

### Связанные темы

- [SSH hardening](../../ssh/server/ssh_hardening_best_practices.md) — интеграция fail2ban для SSH
- [nftables интеграция](../../../../Linux/Networking/Settings/tools/nftables/practical_scenarios.md) — специфичная настройка для nftables
- [DDoS/WAF обзор](../../../../Security/ApplicationSecurity/ddos_overview.md) — rate limiting с fail2ban
- [Linux security механизмы](../../Linux_Security_Mechanisms_Overview.md) — fail2ban в экосистеме безопасности

### Best Practices

1. Всегда использовать `jail.local` — **не редактировать** `jail.conf`
2. Мониторить статус: `fail2ban-client status`, `/var/log/fail2ban.log`
3. Использовать ipset при >100 заблокированных IP
4. Регулярная настройка фильтров для снижения ложных срабатываний
5. Документация: [fail2ban.org](https://www.fail2ban.org/wiki/index.php/Main_Page)
