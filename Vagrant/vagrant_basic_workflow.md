# Базовый рабочий процесс Vagrant

## Определения

**Vagrant workflow** — стандартный жизненный цикл управления виртуальной машиной: от инициализации проекта до уничтожения окружения.

## Базовые концепции

### Жизненный цикл ВМ

| Этап | Команда | Описание |
| --- | --- | --- |
| **Инициализация** | `vagrant init` | Создание `Vagrantfile` |
| **Запуск** | `vagrant up` | Создание и запуск ВМ, provisioning |
| **Подключение** | `vagrant ssh` | SSH-доступ к ВМ |
| **Применение изменений** | `vagrant reload`, `vagrant provision` | Обновление конфигурации |
| **Пауза** | `vagrant suspend`, `vagrant resume` | Сохранение/восстановление состояния |
| **Остановка** | `vagrant halt` | Корректное выключение |
| **Удаление** | `vagrant destroy` | Полное удаление ВМ |

## Практические сценарии

### Сценарий 1: Инициализация проекта

**Создание нового проекта:**

```bash
# Создать директорию проекта
mkdir my-vagrant-project && cd my-vagrant-project

# Инициализировать с базовым образом
vagrant init bento/ubuntu-24.04

# Или с конкретной версией
vagrant init ubuntu/jammy64
```

**Минимальный Vagrantfile:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
end
```

### Сценарий 2: Запуск окружения

**Базовый запуск:**

```bash
# Скачать box и запустить ВМ
vagrant up

# Запуск с указанием провайдера
vagrant up --provider=libvirt
vagrant up --provider=virtualbox

# Запуск с выводом логов
VAGRANT_LOG=info vagrant up
```

**Что происходит при `vagrant up`:**

1. Проверка наличия box в кэше (`~/.vagrant.d/boxes/`)
2. Скачивание box при отсутствии
3. Создание ВМ у провайдера
4. Настройка сети и SSH
5. Выполнение provisioning (если указан в Vagrantfile)

### Сценарий 3: Подключение и проверка статуса

```bash
# Проверка состояния ВМ
vagrant status

# Подключение по SSH
vagrant ssh

# Подключение к конкретной машине (multi-machine)
vagrant ssh web-server

# SSH-команда без интерактивного подключения
vagrant ssh -c "uptime"

# Показать SSH-конфигурацию
vagrant ssh-config
```

### Сценарий 4: Применение изменений

**После изменения Vagrantfile:**

```bash
# Перезагрузить ВМ для применения изменений
vagrant reload

# Перезагрузить и применить provisioning
vagrant reload --provision

# Только provisioning (без перезагрузки)
vagrant provision
```

**Разница между `reload` и `provision`:**

- `vagrant reload` — перезагружает ВМ, применяет изменения конфигурации (CPU, RAM, сеть)
- `vagrant provision` — выполняет скрипты provisioning без перезагрузки

### Сценарий 5: Управление состоянием

**Пауза и возобновление:**

```bash
# Сохранить состояние на диск
vagrant suspend

# Восстановить из сохранённого состояния
vagrant resume
```

**Остановка и запуск:**

```bash
# Корректно выключить ВМ (shutdown)
vagrant halt

# Запустить после остановки
vagrant up
```

**Сравнение:**

| Команда | Скорость | Состояние | Ресурсы |
| --- | --- | --- | --- |
| `suspend` | Быстро | Сохраняется | Освобождает RAM |
| `halt` | Медленнее | Теряется | Освобождает все |

### Сценарий 6: Удаление окружения

```bash
# Удалить ВМ с подтверждением
vagrant destroy

# Удалить без подтверждения
vagrant destroy -f

# Удалить конкретную машину (multi-machine)
vagrant destroy web-server -f
```

**Что удаляется:**

- Виртуальная машина у провайдера
- Виртуальные диски
- Методанные в `.vagrant/`

**Что сохраняется:**

- Box в кэше (`~/.vagrant.d/boxes/`)
- Файл `Vagrantfile`
- Другие файлы проекта

## Дополнительная информация

### Сводная таблица команд

| Команда | Описание | Влияние на данные |
| --- | --- | --- |
| `vagrant up` | Запуск ВМ | Данные сохраняются |
| `vagrant halt` | Выключение | Данные сохраняются |
| `vagrant suspend` | Пауза | Данные сохраняются |
| `vagrant reload` | Перезагрузка | Данные сохраняются |
| `vagrant destroy` | Удаление | **Данные теряются** |

### Мульти-машинные окружения

Для работы с несколькими ВМ в одном `Vagrantfile`:

```bash
# Статус всех машин
vagrant status

# Запуск конкретной машины
vagrant up web-server

# Остановка всех машин
vagrant halt

# Удаление конкретной машины
vagrant destroy db-server -f
```

### Быстрый старт

```bash
# 1. Создать проект
mkdir test && cd test
vagrant init bento/ubuntu-24.04

# 2. Запустить
vagrant up

# 3. Подключиться
vagrant ssh

# 4. Проверить
uname -a

# 5. Выйти
exit

# 6. Остановить
vagrant halt

# 7. Удалить (если не нужно)
vagrant destroy -f
```

### См. также

- [Vagrantfile Reference](./vagrantfile.md) — синтаксис конфигурации
- [Vagrant Installation](./vagrant_installation.md) — установка и настройка
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — мульти-машинные сценарии
