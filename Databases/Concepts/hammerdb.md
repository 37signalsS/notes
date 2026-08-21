# HammerDB

## Определения

**HammerDB** — отраслевой стандарт для профессионального сравнения различных СУБД (SQL Server, Oracle, MySQL, PostgreSQL). Поддерживает профили TPC-C (OLTP) и TPC-H (OLAP). Позволяет выполнять распределенные тесты на нескольких узлах одновременно.

**NOPM (New Orders Per Minute)** — ключевая метрика HammerDB для TPC-C. Позволяет сравнивать производительность разных движков (например, SQL Server vs PostgreSQL) в одинаковых бизнес-сценариях. Аналогична tpmC в официальном TPC-C, но без привязки к конкретным условиям теста.

---

## Установка

```bash
# Linux — требует Tcl 8.6+
wget https://github.com/HammerDB/HammerDB/releases/download/v4.12/HammerDB-4.12-Linux-x86-64-OL7.tar.gz
tar xzf HammerDB-4.12-Linux-x86-64-OL7.tar.gz

# Проверка Tcl:
tclsh <<< 'puts $tcl_version'  # → 8.6
```

### Поддерживаемые СУБД

| СУБД | TPC-C | TPC-H | Примечания |
| :--- | :--- | :--- | :--- |
| **PostgreSQL** | Да | Да | Рекомендуется pgbench для TPC-B |
| **MySQL** | Да | Нет | sysbench более гибок для OLTP |
| **Oracle** | Да | Да | Требует лицензию |
| **SQL Server** | Да | Да | Требует лицензию |
| **MariaDB** | Да | Нет | Аналогичен MySQL |
| **IBM Db2** | Да | Да | Требует лицензию |

---

## Конфигурация TPC-C

### Пропорция Warehouses к CPU

Количество "складов" (Warehouses) определяет уровень блокировок в тесте. Рекомендуемая пропорция — **5:1 к количеству ядер CPU**:

| Ядра CPU | Warehouses | Ожидаемый NOPM |
| :--- | :--- | :--- |
| 4 | 20 | 20,000-50,000 |
| 8 | 40 | 50,000-150,000 |
| 16 | 80 | 150,000-400,000 |
| 32 | 160 | 400,000-1,000,000 |
| 64 | 320 | 1,000,000+ |

При меньшем количестве Warehouse наблюдается высокий Lock Contention, при большем — растет время подготовки данных.

---

## Базовый сценарий (CLI)

### PostgreSQL

```bash
hammerdbcli << 'EOF'
# Выбор СУБД
dbset db PostgreSQL

# Настройка TPC-C
setldbdict PostgreSQL 10.10.0
setdict tpcc

# Конфигурация подключения
diset connection pg_service_pool 50
diset connection pg_host 192.168.1.100
diset connection pg_port 5432
diset connection pg_user dbench
diset connection pg_pass password123
diset connection pg_dbase tpcc

# Количество Warehouses (пропорция 5:1 к ядрам CPU)
diset tpcc pg_count_ware 1000

# Запуск build (создание схемы и данных)
buildschema

# Запуск теста
unloadresult /tmp/hammerdb_results
setcommandtimeout 180
vudestroy
vucreate vudestroy
runtimer 1800
vurun
# → Результаты в /tmp/hammerdb_results/
EOF
```

### MySQL

```bash
hammerdbcli << 'EOF'
dbset db MySQL

setldbdict MySQL 8.0.0
setdict tpcc

diset connection mysql_service_pool 50
diset connection mysql_host 192.168.1.100
diset connection mysql_port 3306
diset connection mysql_user dbench
diset connection mysql_pass password123
diset connection mysql_dbase tpcc

diset tpcc mysql_count_ware 1000

buildschema

unloadresult /tmp/hammerdb_results
setcommandtimeout 180
vudestroy
vucreate vudestroy
runtimer 1800
vurun
EOF
```

---

## Ключевые команды CLI

| Команда | Описание |
| :--- | :--- |
| `dbset db <DBMS>` | Выбор СУБД (PostgreSQL, MySQL, Oracle, etc.) |
| `setdict tpcc` | Режим TPC-C |
| `setdict tpc-h` | Режим TPC-H |
| `diset connection <param> <value>` | Настройка подключения |
| `diset tpcc <param> <value>` | Настройка TPC-C параметров |
| `buildschema` | Создание схемы и заполнение данными |
| `vudestroy` | Уничтожение существующих данных |
| `vucreate` | Создание виртуальных пользователей |
| `runtimer <seconds>` | Установка времени теста |
| `vurun` | Запуск теста |
| `unloadresult <path>` | Сохранение результатов |

---

## Интерпретация результатов

```text
VU Output:
1000,+,0,150000,2500,123.45,67.89,12.34
...
EOF

test result: 150000 NOPM achieved
```

**На что смотреть:**
- **NOPM** — основная метрика. Сравнивайте между разными конфигурациями.
- **Virtual Users** — количество активных виртуальных пользователей.
- **Checkpoint** — частота сброса данных на диск. Влияет на Latency.

---

## Ограничения

- **Сложность настройки:** CLI-интерфейс неинтуитивен, требуется время на изучение.
- **Долгая подготовка:** Генерация данных для 1000+ Warehouse занимает часы.
- **Ограниченные СУБД:** Поддерживает только основные коммерческие и open-source СУБД.
- **Высокие требования к ресурсам:** Тест на 1000+ Warehouse требует значительного объема RAM и CPU.
- **Closed Loop модель:** Аналогично sysbench/pgbench, при росте Latency автоматически падает NOPM.

---

## Дополнительная информация

### См. также

- **[Нагрузочное тестирование СУБД](./benchmarking.md)** — общая методология, подготовка среды, интерпретация результатов.
- **[Ключевые концепции производительности](./database_performance_concepts.md)** — теория TPS, Latency, USE-метод.
- **[sysbench](./sysbench.md)** — кросс-СУБД бенчмаркинг (MySQL, PostgreSQL, MariaDB).
- **[pgbench](./pgbench.md)** — встроенный инструмент PostgreSQL для TPC-B нагрузки.
