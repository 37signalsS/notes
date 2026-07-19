# Мониторинг MySQL: Zabbix Agent и Agent 2

## Определения

**Мониторинг MySQL** — процесс сбора, анализа и визуализации метрик производительности и состояния сервера БД (Базы Данных) для обеспечения стабильности, доступности и быстродействия системы.

**Zabbix Agent 2** — современная версия агента на языке Go, поддерживающая нативные плагины для мониторинга СУБД (включая MySQL/MariaDB) без использования внешних скриптов. Рекомендуется для версий Zabbix 6.0+ и MySQL 8.x/MariaDB 11.x.

**Named Sessions (Именованные сессии)** — механизм конфигурации Zabbix Agent 2, позволяющий хранить параметры подключения (URI, пользователь, пароль) в файле конфигурации агента, а не в макросах веб-интерфейса.

Основные понятия (UserParameter) и архитектура системы описаны в разделе **[Определения и основные концепции](../../Zabbix/definitions_and_concepts.md)**.

## Основные концепции

### Сравнение методов мониторинга

На июль 2026 года выделяются два основных подхода:

| Характеристика | Zabbix Agent (Classic) | Zabbix Agent 2 (Recommended) |
| :--- | :--- | :--- |
| **Реализация** | Внешние скрипты и `UserParameter` | Нативный Go-плагин |
| **Производительность** | Последовательное выполнение | **Параллельные проверки** |
| **Безопасность** | Файл `.my.cnf` | Named Sessions или секреты в окружении |
| **Сложность настройки** | Высокая (ручное копирование конфигов) | Низкая (встроено в агент) |

### Принцип работы Zabbix Agent 2

1. **Zabbix Server** отправляет запрос ключа, например `mysql.ping[NamedSession]`.
2. **Zabbix Agent 2** использует встроенный плагин `MySQL`, который устанавливает соединение с БД через драйвер Go.
3. Плагин выполняет оптимизированные SQL-запросы (включая работу с `performance_schema` и `information_schema`) и возвращает структурированные данные (обычно в формате JSON).
4. **LLD (Low Level Discovery)** автоматически обнаруживает базы данных и параметры репликации.

### Аутентификация и безопасность

Для обеспечения безопасности и исключения хранения паролей в открытом виде в веб-интерфейсе Zabbix применяется следующий подход:

1. **Выделенный пользователь MySQL**: Создается учетная запись с минимально необходимым набором привилегий.
2. **Named Sessions (для Agent 2)**: Параметры подключения описываются в `/etc/zabbix/zabbix_agent2.d/plugins.d/mysql.conf`.
3. **Файл конфигурации клиента (`.my.cnf`) (для Classic Agent)**: В домашней директории пользователя `zabbix` создается файл с правами `600`.

## Практические сценарии

### Подготовка пользователя в MySQL

Для корректной работы мониторинга (включая репликацию) необходимо создать пользователя с расширенными правами.

```sql
-- Создание пользователя
CREATE USER 'zbx_monitor'@'localhost' IDENTIFIED BY 'your_secure_password';

-- Права для MySQL 8.x / 9.x
GRANT REPLICATION CLIENT, PROCESS, SHOW DATABASES, SHOW VIEW ON *.* TO 'zbx_monitor'@'localhost';
GRANT SELECT ON performance_schema.* TO 'zbx_monitor'@'localhost';

-- Дополнительное право для MariaDB (мониторинг репликации)
GRANT SLAVE MONITOR ON *.* TO 'zbx_monitor'@'localhost';

FLUSH PRIVILEGES;
-- -> Query OK, 0 rows affected
```

### Вариант 1: Настройка через Zabbix Agent 2 (Рекомендуется)

#### 1. Конфигурация Named Session

Создайте или измените файл `/etc/zabbix/zabbix_agent2.d/plugins.d/mysql.conf`:

```ini
# Определение сессии с именем "ProdDB"
Plugins.MySQL.Sessions.ProdDB.Uri=tcp://localhost:3306
Plugins.MySQL.Sessions.ProdDB.User=zbx_monitor
Plugins.MySQL.Sessions.ProdDB.Password=your_secure_password
```

#### 2. Настройка в веб-интерфейсе Zabbix

1. Перейдите в **Data collection** → **Hosts**.
2. Добавьте шаблон `MySQL by Zabbix agent 2`.
3. В разделе **Macros** установите значение макроса `{$MYSQL.DSN}` равным имени сессии: `ProdDB`.
4. Проверьте поступление данных в **Monitoring** → **Latest data**.

---

### Вариант 2: Настройка через Classic Zabbix Agent (Legacy)

#### 1. Конфигурация UserParameter

Создайте файл `/etc/zabbix/zabbix_agentd.d/mysql.conf`:

```conf
# Проверка доступности MySQL
UserParameter=mysql.ping,mysqladmin ping | grep -c alive

# Сбор глобальных статусных переменных
UserParameter=mysql.status[*],echo "show global status where Variable_name='$1';" | mysql -N | awk '{print $2}'

# Получение размера конкретной базы данных
UserParameter=mysql.size[*],echo "SELECT sum(data_length+index_length) FROM information_schema.tables WHERE table_schema='$1';" | mysql -N
```

#### 2. Настройка файла аутентификации (.my.cnf)

```bash
# Создание файла (путь /var/lib/zabbix/.my.cnf)
cat <<EOF | sudo tee /var/lib/zabbix/.my.cnf
[client]
user=zbx_monitor
password=your_secure_password
EOF

# Установка прав доступа
sudo chown zabbix:zabbix /var/lib/zabbix/.my.cnf
sudo chmod 600 /var/lib/zabbix/.my.cnf
```

Перезапустите агент: `sudo systemctl restart zabbix-agent`.

---

### Проверка работоспособности

Для проверки Agent 2 используйте утилиту `zabbix_get`:

```bash
zabbix_get -s 127.0.0.1 -k mysql.ping[ProdDB]
# -> 1
```

## Дополнительная информация

**Ключевые метрики для мониторинга:**

- **Доступность**: `mysql.ping` (состояние сервиса).
- **Производительность**:
  - `Slow_queries` (количество медленных запросов).
  - `Threads_connected` (количество активных соединений).
  - **Innodb Buffer Pool Hit Rate**: эффективность использования оперативной памяти.
- **Репликация**:
  - `Slave_running` (статус потоков репликации).
  - `Seconds_behind_master` (отставание в секундах).

**Альтернативные методы:**

- **[Использование Prometheus mysqld_exporter](../../Prometheus/Exporters/other_exporters.md)**.
- **[Percona Monitoring and Management (PMM)](./overview.md)** — специализированное решение для глубокого анализа.

### См. также

- **[Настройка Zabbix Agent 2](../../Zabbix/installation.md)**
- **[Обзор MySQL](./overview.md)**
- **[Мониторинг PostgreSQL в Zabbix](../../Zabbix/zabbix_postgresql_monitoring.md)**
