# Сетевая безопасность MariaDB

Контроль сетевого доступа — первый рубеж защиты. Даже самый сильный пароль бесполезен, если порт открыт на всю сеть без ограничений.

## Привязка к интерфейсу и ограничение доступа

```ini
[mariadb]
# Привязка только к внутреннему интерфейсу (не 0.0.0.0!)
bind-address = 10.0.5.20

# Полное отключение сетевого доступа (только локальные подключения)
# skip-networking = 1

# Запрет DNS-резолва (ускоряет подключение, но требует указания IP в GRANT)
skip-name-resolve = 1
```

## Ограничение соединений (защита от DoS)

```ini
[mariadb]
# Максимальное количество одновременных соединений (весь сервер)
max_connections = 500

# Лимит соединений на одного пользователя (вместе с глобальным)
max_user_connections = 50

# Таймаут неактивных соединений (в секундах)
wait_timeout = 600
interactive_timeout = 600

# Максимальный размер пакета (защита от атак через большие запросы)
max_allowed_packet = 64M
```

```sql
-- Проверка текущих лимитов
SHOW VARIABLES LIKE 'max_connections';
SHOW VARIABLES LIKE 'max_user_connections';
SHOW VARIABLES LIKE 'wait_timeout';

-- Мониторинг активных соединений
SELECT USER, COUNT(*) as connections
FROM information_schema.PROCESSLIST
GROUP BY USER
ORDER BY connections DESC;

-- Просмотр пикового количества соединений (с момента запуска)
SHOW STATUS LIKE 'Max_used_connections';
```

## Настройка файрвола

### UFW (Debian/Ubuntu)

```bash
# Разрешить доступ к MariaDB только с конкретных подсетей
sudo ufw allow from 10.0.5.0/24 to any port 3306 proto tcp

# Или с конкретного IP (напр., приложение на том же хосте)
sudo ufw allow from 10.0.5.10 to any port 3306 proto tcp

# Проверка правил
sudo ufw status verbose
```

### firewalld (RHEL/CentOS)

```bash
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.5.0/24" port port="3306" protocol="tcp" accept'
sudo firewall-cmd --reload
```

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[SSL/TLS](ssl-tls.md)** — шифрование трафика через TLS.
- **[Дополнительные параметры](additional-parameters.md)** — `local-infile`, `skip-show-database` и другие параметры безопасности.
- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation`.
