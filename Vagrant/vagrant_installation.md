# Установка Vagrant

## Определения

**Vagrant** — кроссплатформенный инструмент для создания и управления воспроизводимыми средами разработки. Он автоматизирует процесс настройки виртуализации, позволяя описывать конфигурацию инфраструктуры в виде кода (Vagrantfile).

> **Актуальная версия:** 2.4.9 (январь 2026). Проект развивается под лицензией HashiCorp BSL (для новых версий) или MPL 2.0 (для legacy).

## Базовые концепции

### Компоненты системы

1.  **Бинарный пакет Vagrant:** Основное CLI-приложение. Рекомендуется использовать официальные репозитории HashiCorp для обеспечения безопасности и стабильности.
2.  **Плагины (Plugins):** Расширения для поддержки новых провайдеров (libvirt, AWS), настройки прокси или автоматизации гостевых дополнений.
3.  **Образы (Boxes):** Сжатые шаблоны ОС. Кэшируются локально в директории `~/.vagrant.d/boxes/`.

## Практические сценарии

### Сценарий 1: Установка в Linux (Debian/Ubuntu/Fedora)

Использование официального репозитория HashiCorp гарантирует корректную работу системных интеграций и своевременное получение обновлений безопасности.

**1. Debian / Ubuntu:**
```bash
# Установка необходимых утилит
sudo apt-get update && sudo apt-get install -y curl gpg software-properties-common

# Добавление GPG-ключа и репозитория
curl -fsSL https://apt.releases.hashicorp.com/gpg | \
sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | \
sudo tee /etc/apt/sources.list.d/hashicorp.list

sudo apt-get update && sudo apt-get install -y vagrant
```

**2. RHEL / CentOS / Fedora:**
```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://rpm.releases.hashicorp.com/RHEL/hashicorp.repo
sudo dnf install -y vagrant
```

### Сценарий 2: Установка в Arch Linux

В Arch Linux Vagrant доступен в официальных репозиториях (Community), что упрощает управление зависимостями для Libvirt.

```bash
sudo pacman -S vagrant
```

### Сценарий 3: Установка на других платформах

| Платформа | Команда установки | Особенности |
| :--- | :--- | :--- |
| **macOS (Homebrew)**| `brew install vagrant` | Поддержка Intel и Apple Silicon. |
| **Windows** | `winget install HashiCorp.Vagrant` | Требует перезапуска терминала для обновления PATH. |

### Сценарий 4: Настройка зависимостей для vagrant-libvirt

Для сборки плагина `vagrant-libvirt` требуются заголовочные файлы Ruby и Libvirt.

**Для Debian/Ubuntu:**
```bash
sudo apt-get install -y libvirt-dev ruby-dev ruby-libvirt qemu-utils make gcc
vagrant plugin install vagrant-libvirt
```

**Для Arch Linux:**
```bash
sudo pacman -S libvirt ruby-libvirt
vagrant plugin install vagrant-libvirt
```

## Дополнительная информация

### Пост-установочные действия

**1. Настройка прав доступа (Linux/Libvirt):**
Добавьте пользователя в группу `libvirt` для управления ВМ без `sudo`.
```bash
sudo usermod -aG libvirt $USER
# → Перезайдите в систему для применения изменений
```

**2. Включение автодополнения (Shell Autocomplete):**
```bash
# Для Bash
vagrant autocomplete install --bash
source ~/.bashrc

# Для Zsh
vagrant autocomplete install --zsh
source ~/.zshrc
```

**3. Переменные окружения:**
Рекомендуется настроить в `.bashrc` / `.zshrc`:
- `VAGRANT_HOME`: Путь к глобальному кэшу (`~/.vagrant.d/`). При нехватке места на системном диске можно перенести на другой раздел.
- `VAGRANT_DEFAULT_PROVIDER`: Установка `libvirt` или `virtualbox` по умолчанию.
```bash
export VAGRANT_HOME="/mnt/data/vagrant.d"
export VAGRANT_DEFAULT_PROVIDER="libvirt"
```

### Проверка корректности установки

```bash
# Проверка версии и путей
vagrant --version
# → Vagrant 2.4.9

# Список плагинов
vagrant plugin list

# Валидация работоспособности (требует любой Vagrantfile)
vagrant validate
```

### См. также

- [Базовый рабочий процесс](./vagrant_basic_workflow.md) — инициализация и запуск.
- [Провайдеры и образы](./vagrant_providers.md) — настройка гипервизоров.
- [Vagrant на Apple Silicon](./vagrant_macos_apple_silicon.md) — особенности для ARM64.
- [Vagrant Troubleshooting](./vagrant_troubleshooting/basic_concepts.md) — решение типичных проблем.
