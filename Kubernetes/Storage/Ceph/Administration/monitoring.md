# Мониторинг и обслуживание Ceph

## Definitions

**Мониторинг Ceph** — наблюдение за состоянием кластера, использованием ресурсов и производительностью.

**Обслуживание Ceph** — регулярные операции по балансировке, управлению ключами доступа и логированию.

---

## Basic Concepts

### Метрики здоровья кластера

Ceph предоставляет встроенные метрики для оценки состояния:

| Статус | Значение | Действие |
|--------|----------|----------|
| `HEALTH_OK` | Все компоненты работают штатно | Мониторинг в штатном режиме |
| `HEALTH_WARN` | Есть предупреждения | Анализ и планирование исправлений |
| `HEALTH_ERR` | Критические ошибки | Немедленное вмешательство |

### Источники метрик

| Источник | Описание | Как включить |
|----------|----------|--------------|
| **Ceph MGR Prometheus module** | Встроенный модуль, экспортирует метрики на HTTP-эндпоинт | `ceph mgr module enable prometheus` |
| **Ceph Dashboard** | Веб-интерфейс с визуализацией | `ceph mgr module enable dashboard` |
| **CLI** | Командная строка (`ceph -s`, `ceph health detail`) | Доступно по умолчанию |
| **Prometheus exporter** | Внешний exporter (устарел, рекомендуется встроенный MGR module) | — |

> **Подробности интеграции с Kubernetes:** [CSI RBD Driver](../ceph_csi_rbd_driver_setup.md), [CSI CephFS Driver](../ceph_csi_cephfs_driver_setup.md)

### Принцип репликации и использование места

При репликации `size=N` фактическое использование диска в N раз больше полезного объёма данных. Подробнее о расчёте: [Расчет PG](../ceph_placement_groups.md).

---

## Practical Scenarios

### Мониторинг использования дискового пространства

```bash
# Использование по OSD
ceph osd df

# Общий статус кластера
ceph -s

# Детализация здоровья
ceph health detail
```

**Расчёт полезного пространства** при репликации `size=3`:

| Показатель | Значение |
|------------|----------|
| Доступно (avail) | 80 GiB |
| Полезно для записи | ~26.7 GiB (80 / 3) |
| Коэффициент на дисках | 1 GiB данных = 3 GiB на дисках |

---

### Балансировка кластера

```bash
# Статус балансировки
ceph osd df

# Автоматическая балансировка по утилизации
ceph osd reweight-by-utilization

# Ручная корректировка веса OSD
ceph osd reweight <osd_id> <weight>
```

---

### Управление ключами доступа

```bash
# Список всех ключей
ceph auth list

# Экспорт ключа
ceph auth get client.admin -o /etc/ceph/ceph.client.admin.keyring

# Создание пользователя с ограниченными правами
ceph auth get-or-create client.<name> mon 'allow r' osd 'allow rw pool=<pool>'

# Удаление пользователя
ceph auth del client.<name>

# Изменение прав существующего пользователя
ceph auth caps client.<name> mon 'allow r' osd 'allow rwx pool=<pool>'
```

---

### Логирование и отслеживание событий

```bash
# Поток событий в реальном времени
ceph -w

# Последние события
ceph log last 100

# Дамп всех логов
ceph log dump
```

---

### Настройка Prometheus-алертов

Пример конфигурации Alertmanager для Ceph:

```yaml
# ceph_alerts.yml
groups:
- name: ceph
  rules:
  - alert: CephHealthWarning
    expr: ceph_health_status == 1
    for: 5m
    labels:
      severity: warning
  - alert: CephHealthError
    expr: ceph_health_status == 2
    for: 1m
    labels:
      severity: critical
  - alert: CephOSDDown
    expr: ceph_osd_up == 0
    for: 5m
    labels:
      severity: warning
```

---

### Рекомендуемые практики обслуживания

| Задача | Частота | Примечание |
|--------|---------|------------|
| Проверка `ceph -s` | Ежедневно | Быстрый мониторинг здоровья |
| Проверка дискового пространства | Еженедельно | Планирование расширения |
| Аудит пользователей и ключей | Ежемесячно | Контроль безопасности |
| Тестирование восстановления | Ежемесячно | Проверка бэкапов |
| Обновление Ceph | По выходу stable | Следить за EOL версий ([Версии Ceph](../ceph_overview.md#версии-ceph)) |

---

## Additional Information

**Связанные темы:** [Обзор Ceph](../ceph_overview.md) · [Расчет PG](../ceph_placement_groups.md) · [Операции Ceph](./operations.md) · [Главная Administration](./index.md) · [Официальная документация](https://docs.ceph.com/en/latest/admin/)
