# Базовый рабочий процесс Vagrant

## Определения

**Vagrant workflow** — стандартный жизненный цикл управления виртуальной машиной: инициализация, запуск, подключение, применение изменений, пауза, остановка, удаление.

## Базовые концепции

### Жизненный цикл ВМ

| Этап | Команда | Описание |
| --- | --- | --- |
| **Инициализация** | `vagrant init` | Создание `Vagrantfile` |
| **Запуск** | `vagrant up` | Создание и запуск ВМ, provisioning при первом старте |
| **Подключение** | `vagrant ssh` | SSH-доступ к ВМ |
| **Применение изменений** | `vagrant reload`, `vagrant provision` | Обновление конфигурации |
| **Пауза** | `vagrant suspend` / `vagrant resume` | Сохранение/восстановление состояния |
| **Остановка** | `vagrant halt` | Корректное выключение |
| **Удаление** | `vagrant destroy` | Полное удаление ВМ |

### Что происходит при `vagrant up`

1. Проверка box в кэше (`~/.vagrant.d/boxes/`)
2. Скачивание box при отсутствии
3. Создание ВМ у провайдера
4. Настройка сети и SSH
5. Выполнение provisioning (если указан в Vagrantfile)

### reload vs provision

| Команда | Перезагрузка | Provisioning | Когда использовать |
| --- | --- | --- | --- |
| `vagrant reload` | ✅ | ❌ | Изменения CPU, RAM, сеть |
| `vagrant reload --provision` | ✅ | ✅ | Изменения + провижининг |
| `vagrant provision` | ❌ | ✅ | Только скрипты provisioning |

Подробнее о provisioning: [Vagrant Provisioning](./vagrant_provisioning.md#когда-выполняется-provisioning).

## Практические сценарии

### Сценарий 1: Инициализация проекта

```bash
mkdir my-vagrant-project && cd my-vagrant-project
vagrant init bento/ubuntu-24.04
```

**Минимальный Vagrantfile:**

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"
end
```

### Сценарий 2: Запуск окружения

```bash
# Базовый запуск
vagrant up

# Запуск с указанием провайдера
vagrant up --provider=libvirt
vagrant up --provider=virtualbox
```

Уровни логирования: [Vagrant Troubleshooting](./vagrant_troubleshooting/basic_concepts.md).

### Сценарий 3: Подключение и проверка статуса

```bash
vagrant status               # Состояние ВМ
vagrant ssh                  # Подключение по SSH
vagrant ssh -c "uptime"      # Выполнение команды без интерактива
vagrant ssh-config           # Показать SSH-конфигурацию
```

Для multi-machine: [Vagrant Advanced Usage](./vagrant_advanced_usage.md#multi-machine-архитектура).

### Сценарий 4: Пауза, остановка, удаление

**Пауза и возобновление:**

```bash
vagrant suspend              # Сохранить состояние на диск
vagrant resume               # Восстановить
```

**Остановка и запуск:**

```bash
vagrant halt                 # Корректное выключение
vagrant up                   # Запуск после остановки
```

**Удаление:**

```bash
vagrant destroy              # С подтверждением
vagrant destroy -f           # Без подтверждения
```

**Сравнение состояний:**

| Команда | Скорость | RAM | Данные на диске |
| --- | --- | --- | --- |
| `suspend` | Быстро | Освобождает | Сохраняются |
| `halt` | Медленнее | Освобождает | Сохраняются |
| `destroy` | — | Освобождает | **Удаляются** |

**Что удаляется при `destroy`:**

- Виртуальная машина у провайдера
- Виртуальные диски
- Метаданные в `.vagrant/`

**Что сохраняется:**

- Box в кэше (`~/.vagrant.d/boxes/`)
- Файл `Vagrantfile`
- Файлы проекта

## Дополнительная информация

### Быстрый старт

```bash
# 1. Создать и запустить
mkdir test && cd test && vagrant init bento/ubuntu-24.04 && vagrant up

# 2. Подключиться и проверить
vagrant ssh -c "uname -a"

# 3. Остановить и удалить
vagrant halt && vagrant destroy -f
```

### Смена провайдера

При переключении между провайдерами требуется пересоздание ВМ:

```bash
vagrant destroy -f
vagrant up --provider=virtualbox   # Вместо libvirt
```

Подробнее: [Vagrant Providers](./vagrant_providers.md).

### См. также

- [Vagrantfile Reference](./vagrantfile.md) — синтаксис конфигурации
- [Vagrant Installation](./vagrant_installation.md) — установка и настройка
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — мульти-машинные сценарии
