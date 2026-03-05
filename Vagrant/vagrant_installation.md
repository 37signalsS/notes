# Установка Vagrant

## Определения

**Vagrant** — инструмент для создания и управления легковесными, воспроизводимыми и портативыми средами разработки. Устанавливается на хост-машину.

> **Важно:** Текущая стабильная версия — **2.4.x** (2026). HashiCorp сохраняет Vagrant под лицензией MPL 2.0 (в отличие от Terraform).

## Базовые концепции

### Компоненты установки

1. **Основной пакет Vagrant** — исполняемый файл `vagrant` и базовая логика управления ВМ. Рекомендуется установка из официального репозитория HashiCorp.
2. **Плагины (Plugins)** — модули расширения функциональности. Пример: плагины для провайдеров (`vagrant-libvirt`, `vmware_desktop`), не входящих в стандартную поставку.
3. **Boxes (образы)** — базовые шаблоны ВМ. Хранятся в кэше `~/.vagrant.d/boxes/`.

## Практические сценарии

### Сценарий 1: Установка Vagrant в Debian/Ubuntu

**Шаг 1: Установка зависимостей**

```bash
sudo apt-get update
sudo apt-get install -y curl gpg apt-transport-https software-properties-common
```

**Шаг 2: Добавление GPG-ключа и репозитория HashiCorp**

```bash
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
```

**Шаг 3: Установка пакета Vagrant**

```bash
sudo apt-get update
sudo apt-get install -y vagrant
```

**Альтернативные способы установки:**

| Способ | Команда | Примечание |
| --- | --- | --- |
| **Snap** | `sudo snap install vagrant --classic` | Автообновление, изолированный пакет |
| **Homebrew (macOS)** | `brew install vagrant` | Рекомендуется для macOS |
| **Официальный пакет** | `.deb` с [releases.hashicorp.com](https://releases.hashicorp.com/vagrant/) | Ручная загрузка |

### Сценарий 2: Установка плагинов

**Базовая установка:**

```bash
# Установка плагина vagrant-libvirt
vagrant plugin install vagrant-libvirt

# Установка плагина vagrant-env для работы с .env файлами
vagrant plugin install vagrant-env
```

**Управление плагинами:**

```bash
# Список установленных плагинов
vagrant plugin list

# Удаление плагина
vagrant plugin uninstall vagrant-libvirt

# Обновление всех плагинов
vagrant plugin update
```

### Сценарий 3: Проверка установки

```bash
# Проверка версии
vagrant --version

# Проверка доступных провайдеров
vagrant status --provider=libvirt  # или virtualbox

# Список загруженных box'ов
vagrant box list
```

## Дополнительная информация

### Важные замечания

- **Ubuntu 24.04 Noble:** Canonical прекратила выпуск официальных Vagrant-образов Ubuntu начиная с 24.04. Используйте альтернативы:
  - [`bento/ubuntu-24.04`](https://portal.cloud.hashicorp.com/vagrant/discover/bento/ubuntu-24.04) от Chef/Bento
  - [`hashicorp/bionic64`](https://portal.cloud.hashicorp.com/vagrant/discover) и другие от HashiCorp
  - Самостоятельная сборка через `ubuntu/jammy64` + `do-release-upgrade`
  
- **Провайдеры по умолчанию:** VirtualBox (требуется отдельная установка), Libvirt (Linux, требует плагин `vagrant-libvirt`).

- **Версии и совместимость:** Всегда проверяйте совместимость версий Vagrant, провайдера и box'ов.

### См. также

- [Vagrant Providers](./vagrant_providers.md) — выбор и настройка провайдеров
- [Vagrant Basic Workflow](./vagrant_basic_workflow.md) — начало работы
