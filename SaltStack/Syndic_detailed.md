# Salt Syndic подробно

## Определения

- **Salt Syndic**: Узел-посредник между Master of Masters и локальными мастерами, передающий команды сверху вниз и возвращающий результаты обратно. Позволяет масштабировать инфраструктуру до десятков тысяч миньонов.
- **Master of Masters (MoM)**: Центральный мастер, управляющий Syndic-узлами. Не подключается напрямую к миньонам, а передаёт команды через Syndic.
- **Local Master**: Мастер на уровне Syndic, подключённый напрямую к миньонам в своей зоне/кластере.
- **`syndic_master`**: Параметр конфигурации Syndic, указывающий адрес Master of Masters.
- **`syndic_log_file`**: Файл логов Syndic (по умолчанию `/var/log/salt/syndic.log`).
- **`syndic_recv_timeout`**: Таймаут ожидания результатов от локальных мастеров (по умолчанию 300 секунд).
- **`master_type`**: Тип подключения мастера (`standard`, `failover`, `distributed`).

---

## Основные концепции

### Топология Syndic

```
                    Master of Masters (MoM)
                           │
           ┌───────────────┼───────────────┐
           │               │               │
      Syndic-1         Syndic-2         Syndic-3
      (DC-1)           (DC-2)           (DC-3)
           │               │               │
     ┌─────┴─────┐   ┌─────┴─────┐   ┌─────┴─────┐
     │           │   │           │   │           │
  Master-1a  Master-1b Master-2a Master-2b Master-3a Master-3b
     │           │   │           │   │           │
  Minions    Minions  Minions   Minions  Minions   Minions
```

### Потоки данных

**Команды (сверху вниз):**
1. MoM публикует команду в шину
2. Syndic получает команду через порт 4505 MoM
3. Syndic转发 команду своим локальным миньонам

**Результаты (снизу вверх):**
1. Миньоны отправляют результаты локальному мастеру
2. Локальный мастер передаёт результаты в Syndic
3. Syndic转发 результаты в MoM

### Ключевое отличие от Multi-Master

| Параметр | Multi-Master | Syndic |
|:---|:---|:---|
| Управление | Миньон подключается к N мастерам | Миньон подключается к одному мастеру |
| Ключи | Принимаются на каждом мастере | Принимаются на локальном мастере |
| Шина | Каждый мастер независим | Syndic转发 от MoM |
| Масштабирование | Ограничено | До 100K+ миньонов |
| Сложность | Низкая | Высокая |

---

## Практические сценарии

### 1. Конфигурация Master of Masters

```yaml
# /etc/salt/master (MoM)
# MoM не управляет миньонами напрямую
file_roots:
  base:
    - /srv/salt

pillar_roots:
  base:
    - /srv/pillar

# Разрешить syndic подключаться
peer:
  syndic:
    - 'syndic.*'

# Ограничение прав syndic
publisher_acl:
  syndic_user:
    - 'state.*'
    - 'pkg.*'
    - 'service.*'
    - 'test.*'

# Настройки шины
publish_port: 4505
ret_port: 4506
```

### 2. Конфигурация Syndic

```yaml
# /etc/salt/master (Syndic节点)
# Указываем адрес MoM
syndic_master: master-of-masters.example.com

# Тип подключения
master_type: standard

# Таймаут ожидания результатов
syndic_recv_timeout: 300

# Лог-файл
syndic_log_file: /var/log/salt/syndic.log

# Локальный file_roots (если нужно)
file_roots:
  base:
    - /srv/salt

# Локальный pillar_roots
pillar_roots:
  base:
    - /srv/pillar
```

**Запуск Syndic:**

```bash
# Запуск как сервис
systemctl start salt-syndic

# Или запуск вручную
salt-syndic -l info

# Проверка статуса
systemctl status salt-syndic
```

### 3. Конфигурация локального мастера

```yaml
# /etc/salt/master (локальный мастер за Syndic)
# Локальный мастер управляет миньонами
file_roots:
  base:
    - /srv/salt

pillar_roots:
  base:
    - /srv/pillar

# Миньоны подключаются к этому мастеру
publish_port: 4505
ret_port: 4506
```

### 4. Проверка топологии

```bash
# На MoM: проверить подключённых syndic
salt-run manage.up
# → master-of-masters:
#     syndic-1:
#       True
#     syndic-2:
#       True

# На MoM: проверить все миньоны
salt-run manage.status
# → up: [web-01, web-02, db-01, ...]
# -> down: []

# На Syndic: проверить локальные миньоны
salt-run manage.up

# На MoM: запустить команду на всех миньонах
salt '*' test.ping
# → результаты приходят через Syndic
```

### 5. Multi-Syndic топология

```yaml
# MoM
peer:
  syndic:
    - 'syndic.*'

publisher_acl:
  syndic_user:
    - 'state.*'
    - 'pkg.*'

# Syndic-1 (DC-1)
syndic_master: mom.example.com
syndic_recv_timeout: 300

# Syndic-2 (DC-2)
syndic_master: mom.example.com
syndic_recv_timeout: 300

# Local Master в DC-1 (подключён к Syndic-1)
# Стандартный мастер для локальных миньонов
```

### 6. Безопасность Syndic

```yaml
# На MoM: ограничение прав syndic
peer:
  syndic:
    - 'state.*'
    - 'pkg.*'
    - 'service.*'
    - 'test.*'
    - 'grains.*'
    - 'pillar.*'

# Запрет syndic принимать ключи
syndic_master_auth: True

# Шифрование трафика между MoM и Syndic
# (используется стандартное PKI шифрование Salt)
```

### 7. Мониторинг Syndic

```bash
# Проверка логов Syndic
tail -f /var/log/salt/syndic.log

# Проверка подключений
salt-run manage.up

# Проверка активных заданий
salt-run jobs.active

# Проверка Event Bus
salt-run state.event pretty=True | grep syndic
```

### 8. Troubleshooting Syndic

```bash
# Проблема: миньоны не отвечают через MoM
# 1. Проверить Syndic запущен
systemctl status salt-syndic

# 2. Проверить логи Syndic
journalctl -u salt-syndic -f

# 3. Проверить подключение к MoM
salt-key -F master-of-masters

# 4. Проверить ключи
salt-key -L

# Проблема: задержки в ответах
# Увеличить таймаут
syndic_recv_timeout: 600

# Проблема: потеря синхронизации
# Перезапустить Syndic
systemctl restart salt-syndic
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Syndic not responding` | Syndic не запущен или недоступен MoM | `systemctl status salt-syndic`, проверить `syndic_master` |
| `Minions not returning` | Таймаут `syndic_recv_timeout` | Увеличить таймаут, проверить сеть |
| `Key rejected` | Syndic не имеет прав принимать ключи | Проверить `peer` и `publisher_acl` на MoM |
| `Duplicate JID` | Два Syndic обрабатывают одну команду | Проверить топологию, исключить дублирование |
| `Syndic lag` | Медленная сеть между MoM и Syndic | Проверить latency, увеличить таймаут |
| `Pillar not available` | pillar_roots не синхронизированы | Синхронизировать pillar_roots между уровнями |
| `File server timeout` | file_roots не доступен | Проверить NFS/GitFS, синхронизировать |

### Best practices

1. **Один Syndic на зону/кластер**: Не объединяйте несколько数据中心 через один Syndic.
2. **Резервный MoM**: Настройте Multi-Master для MoM.
3. **Таймауты**: Настройте `syndic_recv_timeout` в зависимости от размера зоны.
4. **Синхронизация**: file_roots и pillar_roots должны быть идентичны на всех уровнях.
5. **Мониторинг**: Настройте алертинг на проблемы Syndic.
6. **Логирование**: Централизуйте логи Syndic в ELK/Loki.
7. **Безопасность**: Ограничьте права Syndic через `peer` и `publisher_acl`.
8. **Тестирование**: Проверяйте топологию перед боевым запуском.

### Версии и совместимость

| Версия Salt | Особенности Syndic |
|:---|:---|
| 3006 LTS | Стандартная топология, basic security |
| 3007 STS | Улучшенная синхронизация ключей |
| 3008 LTS | Улучшенная производительность, `syndic_recv_timeout` |

### См. также

- [Архитектура SaltStack](Architecture.md) — Syndic overview
- [Безопасность SaltStack](Security_Approaches.md) — Syndic security
- [Масштабирование](Architecture.md#topologii-i-masshtabirovanie) — scaling options
