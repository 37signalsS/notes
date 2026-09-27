# Миграция и обновление SaltStack

## Определения

- **Upgrade Salt**: Обновление версии Salt с сохранением конфигурации и данных (3006 → 3007 → 3008).
- **Migration**: Переход с другого инструмента конфигурационного управления (Puppet, Chef, Ansible) на Salt или обратно.
- **Rollback**: Откат к предыдущей версии Salt после неудачного обновления.
- **Breaking Changes**: Изменения в API или поведении между версиями, требующие адаптации кода.
- **LTS (Long Term Support)**: Версии Salt с расширенной поддержкой (3006, 3008).
- **STS (Short Term Support)**: Версии Salt с краткосрочной поддержкой (3007).
- **Tiamat/Onedir**: Новый формат дистрибуции Salt (3008+), включающий Python и зависимости в один пакет.

---

## Основные концепции

### Жизненный цикл версий Salt

| Версия | Тип | EOL | Python | Примечания |
|:---|:---|:---|:---|:---|
| 3006.x LTS | LTS | 2025+ | 3.10+ | CVE-only support |
| 3007.x STS | STS | Июль 2026 | 3.11+ | EOL скоро |
| 3008.x LTS | LTS | 2028+ | 3.12+ | Текущая рекомендуемая |

### Порядок обновления

```
3006 LTS → 3007 STS → 3008 LTS
         или
3006 LTS → 3008 LTS (irect upgrade)
```

### Что меняется между версиями

| Версия | Ключевые изменения |
|:---|:---|
| 3006 → 3007 | Новые execution modules, улучшенный scheduler, Python 3.11 |
| 3007 → 3008 | Tiamat/Onedir, `SafeDict`/`SafeList`, asymmetric module, FIPS |
| 3006 → 3008 | Все изменения 3007 + 3008, рекомендуемый путь |

---

## Практические сценарии

### 1. Подготовка к обновлению

```bash
# 1. Проверка текущей версии
salt --version
# → Salt 3006.2

# 2. Проверка версии на миньонах
salt '*' test.version
# → web-01: 3006.2
# → web-02: 3006.2

# 3. Бэкап перед обновлением
/usr/local/bin/salt_full_backup.sh

# 4. Проверка наличия breaking changes
# https://docs.saltproject.io/en/latest/topics/releases/index.html
```

### 2. Обновление Master

```bash
# Debian/Ubuntu
apt-get update
apt-get install --only-upgrade salt-master

# RHEL/CentOS
yum update salt-master

# pip (не рекомендуется в продакшене)
pip install --upgrade salt

# Проверка после обновлении
salt --version
# → Salt 3008.1

# Перезапуск
systemctl restart salt-master

# Проверка
salt-run manage.up | wc -l
# → 150
```

### 3. Обновление Minions

```bash
# Через Salt (rolling update)
salt '*' pkg.upgrade salt-minion batch=10%

# Или через пакетный менеджер
salt 'web-*' cmd.run 'apt-get update && apt-get install --only-upgrade salt-minion'

# Проверка версий
salt '*' test.version

# Перезапуск миньонов
salt '*' service.restart salt-minion batch=10%
```

### 4. Обновление до 3008 (Tiamat)

```bash
# 3008 использует Tiamat/Onedir формат
# Установка нового пакета

# Debian/Ubuntu
wget https://packages.saltproject.io/py3/ salt/3008/ubuntu22.04/amd64/salt-minion_3008.1-1_amd64.deb
dpkg -i salt-minion_3008.1-1_amd64.deb

# RHEL/CentOS
rpm -i https://packages.saltproject.io/py3/salt/3008/el9/x86_64/salt-minion-3008.1-1.el9.x86_64.rpm

# Проверка
salt-minion --version
# → Salt 3008.1
```

### 5. Тестирование после обновления

```bash
# 1. Проверка подключения
salt '*' test.ping

# 2. Проверка конфигурации
salt '*' state.show_highstate

# 3. Тестирование states
salt '*' state.apply test=True

# 4. Проверка Grains
salt '*' grains.items

# 5. Проверка Pillar
salt '*' pillar.items

# 6. Мониторинг Event Bus
salt-run state.event pretty=True | head -20
```

### 6. Rollback при проблемах

```bash
# Откат Master
systemctl stop salt-master

# Debian/Ubuntu
apt-get install --allow-downgrades salt-master=3006.2

# RHEL/CentOS
yum downgrade salt-master-3006.2

systemctl start salt-master

# Откат Minions
salt '*' pkg.installed:
  - name: salt-minion
  - version: 3006.2

salt '*' service.restart salt-minion
```

### 7. Миграция с Puppet на Salt

```bash
# 1. Установка Salt
apt-get install salt-minion salt-master

# 2. Конвертация Puppet manifests в SLS
# Использование конвертеров или ручная миграция

# 3. Параллельная работа
# - Salt и Puppet работают одновременно
# - Постепенная миграция хостов

# 4. Отключение Puppet
# - После стабилизации Salt отключаем Puppet
```

### 8. Миграция с Ansible на Salt

```bash
# 1. Установка Salt
apt-get install salt-minion salt-master

# 2. Конвертация playbooks в SLS
# Ansible → Salt state conversion

# 3. Использование salt-ssh как замена Ansible
# - Salt-SSH для agentless управления
# - Постепенная установка minions

# 4. Полный переход
# - Установка salt-minion на все хосты
# - Отключение Ansible
```

### 9. Проверка совместимости

```yaml
# /srv/salt/compatibility_check.sls
# Проверка после обновления

check_salt_version:
  module.run:
    - name: test.version
    - result_var: salt_version

check_python_version:
  module.run:
    - name: test.version
    - result_var: python_version

check_grains:
  module.run:
    - name: grains.items
    - result_var: grains_data

check_pillar:
  module.run:
    - name: pillar.items
    - result_var: pillar_data
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Minions not connecting after upgrade` | Несовместимость ключей | Принять ключи через `salt-key -A` |
| `States not working` | Breaking changes в API | Проверить release notes, адаптировать SLS |
| `Pillar not compiling` | Изменения в Jinja | Проверить шаблоны, обновить map.jinja |
| `Grains not loading` | Изменения в grains API | Проверить custom grains |
| `Performance degradation` | Новые зависимости | Проверить Tiamat/Onedir, оптимизировать |
| `FIPS mode issues` | Несовместимость | Обновить Salt, проверить crypto library |

### Best practices

1. **Бэкап**: Всегда бэкап перед обновлением.
2. **Тестирование**: Тестировать в staging перед prod.
3. **Rolling updates**: Обновлять поэтапно (batch=10%).
4. **Мониторинг**: Следить за Event Bus после обновления.
5. **Документация**: Записывать изменения и проблемы.
6. **Откат**: Готовить процедуру отката.
7. **Обновление docs**: Обновлять документацию после изменений.
8. **Обратная совместимость**: Проверять breaking changes заранее.

### Версии и совместимость

| Версия | Рекомендация |
|:---|:---|
| 3006 LTS | Использовать если нет 3008 |
| 3007 STS | Не рекомендуется (EOL скоро) |
| 3008 LTS | Рекомендуемая версия |

### См. также

- [Архитектура SaltStack](Architecture.md) — version information
- [Backup и восстановление](Backup_Restore.md) — backup procedures
- [Безопасность SaltStack](Security_Approaches.md) — FIPS mode
