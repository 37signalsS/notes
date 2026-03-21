# Vagrant: Решение проблем — Дополнительная информация

## Логирование и отладка

### Уровни логирования

```bash
# Минимальный
VAGRANT_LOG=warn vagrant up

# Подробный
VAGRANT_LOG=info vagrant up

# Отладочный
VAGRANT_LOG=debug vagrant up 2>&1 | tee debug.log
```

### Полезные команды диагностики

```bash
# Глобальный статус всех ВМ
vagrant global-status

# Проверка box'ов
vagrant box list

# Проверка плагинов
vagrant plugin list

# Информация о системе Vagrant
vagrant --version
vagrant --debug
```

## Профилактика проблем

1. **Регулярная очистка:**

   ```bash
   vagrant global-status --prune
   vagrant box prune
   ```

2. **Версионирование:** Фиксируйте версии Vagrant, плагинов и box'ов в документации проекта.

3. **Бэкапы:** Перед критическими изменениями делайте snapshot ВМ или экспортируйте данные.

4. **Документирование:** Ведите журнал изменений Vagrantfile и версий компонентов.

## Таблица быстрых решений

| Проблема | Быстрое решение |
|----------|-----------------|
| Рассинхронизация | `vagrant destroy -f && rm -rf .vagrant` |
| SSH не работает | `vagrant destroy -f && vagrant up` |
| Нет места | `vagrant box prune && df -h` |
| Прокси | `export VAGRANT_HTTP_PROXY=...` |
| Конфликт имён | Изменить `config.vm.define` без `_` |

## Связанные темы

- **[Vagrant Basic Workflow](../vagrant_basic_workflow.md)** — управление жизненным циклом
- **[Vagrant Storage and Folders](../vagrant_storage_and_folders.md)** — работа с хранилищем
- **[VirtualBox](./virtualbox.md)** — настройка провайдера VirtualBox

---

## Связанные документы

- **[Определения](./definitions.md)** — базовые термины
- **[Основные концепции](./basic_concepts.md)** — источники проблем, полный сброс
- **[Практические сценарии](./practical_scenarios.md)** — прокси, диски, SSH, сети

---

*Этот файл является частью декомпозированной документации. Исходный файл: [vagrant_troubleshooting.md](./practical_scenarios.md)*
