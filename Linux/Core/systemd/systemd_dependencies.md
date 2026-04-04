# systemd Dependencies

## Определения

**Зависимости между юнитами**: Директивы, определяющие порядок запуска и/или требования между юнитами.

| Директива | Тип | Описание |
| :--- | :--- | :--- |
| `After=` | Порядок | Запуск **после** указанного юнита (не создаёт зависимости) |
| `Before=` | Порядок | Запуск **до** указанного юнита |
| `Wants=` | Слабая | Попытка запустить зависимый юнит (неудача не влияет) |
| `Requires=` | Сильная | Если зависимость не запустится, основной юнит не запустится |
| `BindsTo=` | Очень сильная | Как `Requires=`, но связывает жизненные циклы |
| `PartOf=` | Односторонняя | Остановка/перезапуск влияет на этот юнит |
| `Conflicts=` | Конфликт | Остановка указанных юнитов при запуске этого |

**Рекомендация:** Для надёжности используйте комбинацию `Wants=` + `After=` или `Requires=` + `After=`.

> **Примечание:** `After=network.target` означает запуск после базовой сети, но не гарантирует готовность сети. Для ожидания полной готовности используйте `Wants=network-online.target` в комбинации с `After=`.

## Практические сценарии

### Комбинация Wants= + After= для сетевых сервисов

Типичный паттерн для сервисов, требующих полной готовности сети:

```ini
[Unit]
Description=My Web Application
Wants=network-online.target
After=network-online.target
```

> `Wants=` создаёт слабую зависимость, `After=` гарантирует порядок запуска. Без `After=` сервис может стартовать параллельно с `network-online.target`, что приведёт к race condition.

### Комбинация Requires= + After= для зависимых сервисов

Когда сервис **критически** зависит от другого (например, приложение от базы данных):

```ini
[Unit]
Description=Backend Application
Requires=postgresql.service
After=postgresql.service
```

Если `postgresql.service` не запустится, `backend.service` также не будет запущен.

### Использование BindsTo= для связанных жизненных циклов

Пример: монтирование ФС, привязанное к сервису:

```ini
[Unit]
Description=Backup Mount
BindsTo=backup-network.service
After=backup-network.service
```

При остановке `backup-network.service` монтирование будет автоматически остановлено.

### PartOf= для управления группой сервисов через таргет

Позволяет останавливать/перезапускать сервисы при управлении таргетом:

```ini
# /etc/systemd/system/my-app.service
[Unit]
Description=My Application
PartOf=my-app.target
```

```bash
# Остановит все юниты с PartOf=my-app.target
sudo systemctl stop my-app.target
```

### Диагностика дерева зависимостей

```bash
# Показать дерево зависимостей сервиса
systemctl list-dependencies nginx.service

# Реверсивное дерево (кто зависит от этого юнита)
systemctl list-dependencies --reverse nginx.service

# Подробный анализ зависимостей
systemctl show nginx.service | grep -E 'After=|Before=|Wants=|Requires=|BindsTo=|PartOf='

# Визуализация зависимостей (SVG)
systemd-analyze plot > boot-dependencies.svg
```

### Конфликты между сервисами

```ini
[Unit]
Description=Alternative Mail Server
Conflicts=postfix.service sendmail.service
After=postfix.service
```

При запуске этого юнита указанные сервисы будут остановлены.

## Дополнительная информация

### Матрица совместного использования директив

| Комбинация | Поведение |
| :--- | :--- |
| `Wants=` + `After=` | Попытка запуска + порядок (рекомендуется для большинства случаев) |
| `Requires=` + `After=` | Жёсткая зависимость + порядок (для критических зависимостей) |
| `BindsTo=` + `After=` | Связанные жизненные циклы + порядок (для tightly-coupled сервисов) |
| `PartOf=` (без After) | Только обратная связь при остановке/перезапуске |
| Только `After=` | Только порядок, без зависимости (сервис запустится в любом случае) |
| Только `Requires=` | Зависимость без гарантии порядка (риск race condition) |

### Визуализация порядка загрузки

```bash
# Показать время и порядок загрузки всех юнитов
systemd-analyze blame

# Показать цепочку критических путей
systemd-analyze critical-chain nginx.service

# Сгенерировать SVG-диаграмму зависимостей
systemd-analyze dot | dot -Tsvg > systemd-dependencies.svg
```

### Связанные файлы

Структура unit-файлов описана в [systemd_unit_file_structure.md](./systemd_unit_file_structure.md). Обзор типов юнитов — в [systemd_units_overview.md](./systemd_units_overview.md). Практические сценарии systemd — в [systemd_practical_scenarios.md](./systemd_practical_scenarios.md). Диагностика загрузки — в [boot_troubleshooting.md](./boot_troubleshooting.md).
