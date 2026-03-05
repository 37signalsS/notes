# Мониторинг и обслуживание Ceph

## Определения

**Мониторинг Ceph** — наблюдение за состоянием кластера, использованием ресурсов и производительностью.

**Обслуживание Ceph** — регулярные операции по балансировке, управлению ключами доступа и логированию.

> **Навигация:** [Главная Administration](./index.md) | [Операции](./operations.md)

---

## Practical Scenarios

### Использование дискового пространства

```
usage: 10 GiB used, 80 GiB / 90 GiB avail
```

**Важно**: Доступное пространство ≠ полезное пространство для записи.

При репликации `size=3`:

* Из 80 GiB доступного полезно только ~26.7 GiB (80 / 3)
* 1 GiB данных занимает 3 GiB на дисках

---

### Балансировка кластера

```bash
# Статус балансировки
ceph osd df

# Запуск балансировки
ceph osd reweight-by-utilization

# Ручная балансировка
ceph osd reweight <osd_id> <weight>
```

---

### Работа с ключами доступа

```bash
# Список ключей
ceph auth list

# Экспорт ключа
ceph auth get client.admin -o /etc/ceph/ceph.client.admin.keyring

# Создание пользователя
ceph auth get-or-create client.<name> mon 'allow r' osd 'allow rw pool=<pool>'

# Удаление пользователя
ceph auth del client.<name>
```

---

### Логирование

```bash
# Просмотр логов в реальном времени
ceph -w

# Последние события
ceph log last 100

# Дамп логов
ceph log dump
```

---

## Лучшие практики

### Рекомендуемые практики

| Задача | Частота | Примечание |
|--------|---------|------------|
| Проверка `ceph -s` | Ежедневно | Быстрый мониторинг |
| Проверка дискового пространства | Еженедельно | Планирование расширения |
| Аудит пользователей | Ежемесячно | Безопасность |
| Тестирование бэкапа | Ежемесячно | Восстановление данных |
| Обновление Ceph | По выходу stable | Следить за EOL версий |

---

### Автоматизация мониторинга

Пример Prometheus-алертов:

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

## Additional Information

### Связанные темы

* **[Обзор Ceph](../ceph_overview.md)** — общая информация о Ceph
* **[Расчет PG](../ceph_placement_groups.md)** — расчет Placement Groups
* **[Официальная документация](https://docs.ceph.com/en/latest/admin/)** — документация Ceph
