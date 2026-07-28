# Установка Vagrant

## Определения

**Vagrant** — кроссплатформенный инструмент для создания и управления воспроизводимыми средами разработки. Он автоматизирует процесс настройки виртуализации, позволяя описывать конфигурацию инфраструктуры в виде кода (Vagrantfile).

> **Актуальная версия:** 2.4.9 (январь 2026). Проект развивается под лицензией MPL 2.0.

## Базовые концепции

### Компоненты системы

1.  **Бинарный пакет Vagrant:** Основное CLI-приложение. Рекомендуется использовать официальные репозитории HashiCorp для обеспечения безопасности и стабильности.
2.  **Плагины (Plugins):** Расширения для поддержки новых провайдеров (libvirt, AWS), настройки прокси или автоматизации гостевых дополнений.
3.  **Образы (Boxes):** Сжатые шаблоны ОС. Кэшируются локально в директории `~/.vagrant.d/boxes/`.

## Практические сценарии

### Сценарий 1: Установка в Debian/Ubuntu

Использование официального репозитория гарантирует корректную работу всех системных интеграций.

**1. Настройка репозитория и ключей:**

```bash
# Установка необходимых утилит
sudo apt-get update && sudo apt-get install -y curl gpg software-properties-common

# Добавление GPG-ключа
curl -fsSL https://apt.releases.hashicorp.com/gpg | \
sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg

# Добавление официального репозитория
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | \
sudo tee /etc/apt/sources.list.d/hashicorp.list
```

**2. Установка приложения:**

```bash
sudo apt-get update && sudo apt-get install -y vagrant
```

### Сценарий 2: Альтернативные методы установки

| Платформа | Команда установки | Особенности |
| :--- | :--- | :--- |
| **Linux (Snap)** | `sudo snap install vagrant --classic` | Изолированное окружение, автообновление. |
| **macOS (Homebrew)**| `brew install vagrant` | Стандарт для macOS (поддержка Intel и Apple Silicon). |
| **Windows** | `winget install HashiCorp.Vagrant` | Установка через стандартный менеджер пакетов Windows. |

### Сценарий 3: Зависимости для плагина vagrant-libvirt (Linux)

Для корректной сборки и работы плагина `vagrant-libvirt` в Linux-системах требуются дополнительные библиотеки:

```bash
sudo apt-get install -y libvirt-dev ruby-dev ruby-libvirt qemu-utils make gcc
vagrant plugin install vagrant-libvirt
```

## Пост-установочные действия

### 1. Настройка прав доступа (Linux)

Чтобы запускать Vagrant без `sudo` при использовании Libvirt, добавьте своего пользователя в соответствующую группу:

```bash
sudo usermod -aG libvirt $USER
# Требуется перезагрузка сессии (logout/login)
```

### 2. Включение автодополнения (Shell Autocomplete)

**Для Bash:**
```bash
vagrant autocomplete install --bash
source ~/.bashrc
```

**Для Zsh:**
```bash
vagrant autocomplete install --zsh
source ~/.zshrc
```

### 3. Переменные окружения

Добавление в `.bashrc` или `.zshrc` для кастомизации работы:

- `VAGRANT_HOME`: Путь к директории с кэшем образов и плагинов (по умолчанию `~/.vagrant.d/`).
- `VAGRANT_DEFAULT_PROVIDER`: Установка провайдера по умолчанию (`libvirt`, `virtualbox`).

```bash
export VAGRANT_DEFAULT_PROVIDER=libvirt
```

## Проверка корректности установки

```bash
# Проверка версии CLI
vagrant --version

# Проверка списка установленных плагинов
vagrant plugin list

# Просмотр доступных команд и помощи
vagrant --help
```

## Дополнительная информация

### Совместимость с гипервизорами

Vagrant требует наличия установленного провайдера виртуализации:
- **Linux:** Рекомендуется **Libvirt** (KVM).
- **Windows / macOS:** Рекомендуется **VirtualBox** или **VMware Desktop**.
- **Apple Silicon (M1/M2/M3):** Специфические инструкции приведены в разделе **[Vagrant на Apple Silicon](./vagrant_macos_apple_silicon.md)**.

### См. также

- [Базовый рабочий процесс](./vagrant_basic_workflow.md) — инициализация и первый запуск.
- [Провайдеры и образы](./vagrant_providers.md) — детальная настройка гипервизоров.
- [Сетевые настройки](./vagrant_networking.md) — конфигурация доступа к ВМ.
- [Vagrant Troubleshooting](./vagrant_troubleshooting/basic_concepts.md) — диагностика ошибок.
