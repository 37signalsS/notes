# SQL Server (MS SQL): Обзор и SRE-перспектива

**Актуально для:** SQL Server 2025 (17.x) / SQL Server 2022 (16.x)

## Определения

**SQL Server** — реляционная СУБД от Microsoft. Начиная с версии 2017, полноценно поддерживает работу в среде Linux (через уровень абстракции PAL), что позволяет эксплуатировать её в Docker и Kubernetes наравне с Windows.

**PAL (SQLPAL, SQL Platform Abstraction Layer)** — библиотека пользовательского режима (наследница проекта Drawbridge), реализующая Windows API-поверхность (Win32) поверх Linux-системных вызовов. Движок SQL Server, написанный под Windows, работает на Linux без переписывания кода; накладные расходы PAL минимальны.

**SQL Server 2025 (17.x)** — актуальная версия (GA 18.11.2025, build 17.0.1000.7; последний CU8 — 17.0.4075.5, август 2026). Ключевые новшества для эксплуатации: поддержка cgroup v2, протокол TDS 8.0 (TLS 1.3), ZSTD-сжатие бэкапов. Начиная с 2025 SLES не поддерживается.

**SQL Server 2022 (16.x)** — предыдущая версия, активно поддерживается (CU26, июль 2026). cgroup v2 — начиная с CU20. Выбор между 2022 и 2025 — вопрос политики обновлений: 2025 даёт актуальные лимиты редакций и cgroup v2 «из коробки».

**mssql-conf** — утилита командной строки (`/opt/mssql/bin/mssql-conf`) для конфигурации сервера в Linux; модифицирует файл `/var/opt/mssql/mssql.conf` (аналог `sp_configure`/реестра Windows).

**TDS (Tabular Data Stream)** — клиент-серверный сетевой протокол SQL Server; в версии 2025 — TDS 8.0 с TLS 1.3 по умолчанию.

---

## Архитектура и компоненты

1.  **Database Engine:** Основная служба обработки данных, управления памятью и выполнения запросов.
2.  **SQL Server Agent:** Планировщик задач (Job), используемый для автоматизации бэкапов и обслуживания. Поддерживается на Linux начиная с SQL Server 2017.
3.  **SQL Server Browser:** Служба (UDP 1434), помогающая клиентам находить именованные инстансы с динамическими портами.
4.  **mssql-conf:** См. «Определения».
5.  **Файлы данных:** `.mdf` (первичные данные), `.ndf` (вторичные данные), `.ldf` (журнал транзакций).

---

## Установка и настройка (Linux)

### Предварительные требования

| Параметр | Требование |
| :--- | :--- |
| Дистрибутив | RHEL 9/10, Ubuntu 22.04/24.04 (24.04 — с CU1), Docker Engine 1.8+ на Linux |
| Файловая система | XFS или ext4 (BTRFS и другие не поддерживаются) |
| Ресурсы | 2 ГБ RAM (минимум для старта), 6 ГБ диска, 2 ядра, x64 |

> **Важно:** начиная с SQL Server 2025 SUSE Linux Enterprise Server (SLES) **не поддерживается**. Существующие деплои на SLES работают на 2022 и более ранних версиях; переход на 2025 требует миграции (backup/restore) на поддерживаемый дистрибутив.

### Установка на хост (RHEL 9)

```bash
# 1. Подключение репозитория Microsoft
sudo curl -o /etc/yum.repos.d/mssql-server.repo \
  https://packages.microsoft.com/config/rhel/9/mssql-server-2025.repo

# 2. Установка пакета
sudo dnf install -y mssql-server

# 3. Первоначальная настройка (редакция + пароль sa)
sudo /opt/mssql/bin/mssql-conf setup

# 4. Проверка службы
systemctl status mssql-server
# → ● mssql-server.service - Microsoft SQL Server Database Engine
#    Active: active (running)
```

### Установка на хост (Ubuntu 22.04/24.04)

```bash
# 1. GPG-ключ и репозиторий
curl https://packages.microsoft.com/keys/microsoft.asc | \
  sudo tee /etc/apt/trusted.gpg.d/microsoft.asc
curl -fsSL https://packages.microsoft.com/config/ubuntu/24.04/mssql-server-2025.list | \
  sudo tee /etc/apt/sources.list.d/mssql-server-2025.list

# 2. Установка
sudo apt-get update && sudo apt-get install -y mssql-server
sudo /opt/mssql/bin/mssql-conf setup
```

### Docker

```bash
docker run -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=<пароль>" \
  -e "MSSQL_TCP_PORT=1433" -p 1433:1433 --name sql1 \
  -d mcr.microsoft.com/mssql/server:2025-latest
```

Переменные окружения: `ACCEPT_EULA`, `MSSQL_PID` (редакция, например `Developer`), `MSSQL_SA_PASSWORD`, `MSSQL_TCP_PORT`, `MSSQL_MEMORY_LIMIT_MB`. Переменная `MSSQL_MEMORY_LIMIT_MB` имеет приоритет над параметром `memory.memorylimitmb` в `mssql.conf`.

**Валидация установки:**

```bash
sqlcmd -S localhost -U sa -P '<пароль>' -Q "SELECT @@VERSION"
# → Microsoft SQL Server 2025 (RTM-CU...) - 17.0.xxxx.x (X64) ... on Linux (Ubuntu 24.04 ...)
```

---

## Операции и команды

| Задача | Команда |
| :--- | :--- |
| Статус / перезапуск службы | `systemctl status mssql-server` / `sudo systemctl restart mssql-server` |
| Чтение параметров | `sudo /opt/mssql/bin/mssql-conf get` |
| Установка параметра | `sudo /opt/mssql/bin/mssql-conf set memory.memorylimitmb 36864` |
| Включение HADR (AG) | `sudo /opt/mssql/bin/mssql-conf set hadr.hadrenabled 1` (требуется перезапуск) |
| Включение trace flag | `sudo /opt/mssql/bin/mssql-conf traceflag 8002 on` (требуется перезапуск) |
| Подключение | `sqlcmd -S localhost -U sa -P '<пароль>' -Q "SELECT @@VERSION"` |
| Открытие порта (firewalld) | `sudo firewall-cmd --permanent --add-port=1433/tcp && sudo firewall-cmd --reload` |

### Порты

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| 1433 | TCP | Database Engine (по умолчанию) |
| 1434 | UDP | SQL Server Browser (именованные инстансы) |
| 5022 | TCP | Endpoint Always On AG / database mirroring |
| 4022 | TCP | Service Broker |

---

## Лицензирование (SRE-контекст)

Лицензирование Microsoft остается одним из самых сложных аспектов при проектировании инфраструктуры.

### 1. Модели лицензирования
*   **Per Core (Поядерная):** Основная модель для SRE. Требует лицензирования всех ядер, на которых запущен SQL Server.
    *   *Минимум:* 4 core-лицензии на виртуальный OSE (VM или контейнер).
    *   *Преимущество:* Неограниченное количество пользователей/устройств.
*   **Server + CAL:** Лицензия на инстанс + клиентские лицензии (CAL) на каждого пользователя. Доступна только для Standard Edition и подходит для малых внутренних систем.

### 2. Software Assurance (SA) и контейнеризация
Наличие **Software Assurance (SA)** (или подписки) является обязательным требованием для:
*   **Лицензирования отдельных контейнеров/VM:** Без SA вы обязаны лицензировать все физические ядра хоста.
*   **License Mobility:** Право перемещать контейнеры между узлами Kubernetes без покупки новых лицензий.
*   **Failover Rights:** SA дает право на бесплатную лицензию для пассивной реплики в группе Always On (при условии совпадения количества ядер с основной).
*   **Unlimited Virtualization (Enterprise):** Enterprise с SA дает право на неограниченное число OSE и контейнеров на лицензированном хосте. Standard при лицензировании физического сервера — до 16 ядер (минимум 4 на процессор).

### 3. Нюансы в Kubernetes
Для соблюдения комплаенса в K8s SRE должен:
1.  Использовать `nodeSelector` или `Taints`, чтобы ограничить запуск SQL Server на конкретных лицензированных узлах.
2.  Настраивать `limits.cpu` в соответствии с купленными лицензиями (кратно 2, минимум 4).
3.  Учитывать cgroup v2: SQL Server 2025 и 2022 CU20+ корректно читают лимиты `memory.max`/`cpu.max`, что предотвращает OOM-ошибки в контейнерах (проверка: `stat -fc %T /sys/fs/cgroup` → `cgroup2fs`).

---

## Редакции и ограничения

| Редакция | Ограничения | Ключевые SRE-функции |
| :--- | :--- | :--- |
| **Enterprise** | Без лимитов | Always On AG (multi-node), Online Index Rebuild, In-Memory OLTP, Resource Governor. |
| **Standard** | 32 ядра / 256 ГБ buffer pool (в 2022 и ранее: 24 ядра / 128 ГБ) | Basic Availability Groups (2 узла, 1 БД); Resource Governor (с 2025). |
| **Developer** | Только dev/test | Полный функционал Enterprise. Бесплатна. |
| **Standard Developer** | Только dev/test | Полный функционал Standard. Бесплатна (новая в 2025). |
| **Express** | 1 сокет или 4 ядра, 1410 МБ buffer pool, 50 ГБ на БД | Бесплатная entry-level; LocalDB — облегченный вариант. |

> **Примечания:** Web edition недоступна для 2025 (только через SPLA для 2022). Express with Advanced Services упразднена — все её функции включены в базовую Express. Ограничения Standard применяются к вычислительной мощности одного инстанса Database Engine.

---

## Мониторинг (SRE)

*   **Журнал ошибок:** `/var/opt/mssql/log/errorlog` — первое место для диагностики старта и конфигурационных ошибок.
*   **DMV для здоровья:** `sys.dm_os_wait_stats`, `sys.dm_os_performance_counters`, `sys.dm_os_schedulers`.
*   **Метрики Always On AG** (Synchronization Health, Log/Redo Queue): см. [Always On AG](./high_availability.md).
*   **Метрики хоста и контейнера** (память, cgroup, планировщик): см. [Тюнинг в Linux](./performance_tuning_linux.md).

---

## Безопасность

*   Служба SQL Server на Linux работает от непривилегированного пользователя `mssql` (не root).
*   Клиентские соединения шифруются через TLS; TDS 8.0 в SQL Server 2025 использует TLS 1.3.
*   Закалка инстанса и сети: **[Безопасная установка и закалка СУБД](../installation_security.md)**.
*   Шифрование данных в покое (TDE): **[Encryption at Rest](../Concepts/encryption_at_rest.md)**.

---

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Служба не стартует | Ошибка конфигурации, нехватка памяти | `journalctl -u mssql-server`, затем `/var/opt/mssql/log/errorlog` |
| Connection refused | Файрвол закрыт порт / неверный порт | Проверить 1433/tcp, `MSSQL_TCP_PORT`; подключаться явно: `sqlcmd -S tcp:host,1433` |
| Ошибка пароля при `mssql-conf setup` | Политика сложности | Пароль ≥8 символов, символы из 3 из 4 наборов: верхний/нижний регистр, цифры, спецсимволы |
| OOM Killer в контейнере | Старая версия не учитывает cgroup-лимит | Обновить до 2025 или 2022 CU20+; выставить `MSSQL_MEMORY_LIMIT_MB` ниже лимита контейнера |
| Развертывание на SLES | 2025 не поддерживает SLES | Миграция на RHEL/Ubuntu через backup/restore |

---

## Best Practices

*   **Пинить теги образов** в production (не использовать плавающий `:latest` без контроля версий).
*   **`MSSQL_MEMORY_LIMIT_MB` всегда ниже лимита контейнера:** по умолчанию SQL Server резервирует 80% от меньшего из RAM хоста и cgroup-лимита; оставляйте headroom для ОС и PAL.
*   **Файловая система:** только XFS или ext4.
*   **Trace Flag 8002** (soft affinity на уровне SQLPAL) — рекомендуется в Kubernetes с cgroup v2, чтобы планировщики перемещались по ядрам в рамках квоты.
*   **Лицензионный комплаенс:** `nodeSelector`/`Taints` + `limits.cpu`, кратные купленным лицензиям.
*   **Обновления:** регулярно применять CU из репозитория `mssql-server-2025` (содержит и GDR-исправления).

---

## Дополнительная информация

### См. также
- **[Отказоустойчивость: Always On AG](./high_availability.md)** — архитектура кластеров на Linux.
- **[Тюнинг производительности в Linux](./performance_tuning_linux.md)** — оптимизация контейнеров и ОС.
- **[Резервное копирование и восстановление](./backup-and-recovery.md)** — стратегии защиты данных.
- **[Безопасная установка и закалка СУБД](../installation_security.md)** — общие практики hardening.
- **[Шифрование в покое](../Concepts/encryption_at_rest.md)** — TDE и управление ключами.
- **[Стратегии резервного копирования](../Concepts/backups.md)** — общая теория и метрики RPO/RTO.
- **[Installation guidance for SQL Server on Linux](https://learn.microsoft.com/en-us/sql/linux/sql-server-linux-setup)** (Microsoft Learn)
- **[Editions and supported features of SQL Server 2025](https://learn.microsoft.com/en-us/sql/sql-server/editions-and-components-of-sql-server-2025)** (Microsoft Learn)
- **[SQL Server Licensing Guidance](https://www.microsoft.com/licensing/guidance/SQL)** (Microsoft)
- **[SQL Server — официальный сайт](https://www.microsoft.com/en/sql-server)** (Microsoft)
