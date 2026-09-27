# Установка Vagrant

## Определения

**Vagrant** — кроссплатформенный инструмент для создания и управления воспроизводимыми средами разработки. Он автоматизирует процесс настройки виртуализации, позволяя описывать конфигурацию инфраструктуры в виде кода (Vagrantfile).

> **Актуальная версия:** 2.4.9 (январь 2026). Проект развивается под лицензией HashiCorp BSL (для новых версий) или MPL 2.0 (для legacy).

**Архитектура установки:**
- **CLI (`vagrant`)** — основной бинарный пакет, интерпретирующий команды и управляющий жизненным циклом ВМ.
- **Провайдер (Provider)** — движок виртуализации (VirtualBox, Libvirt/KVM, VMware, Hyper-V, QEMU), через который Vagrant создает ВМ.
- **Box** — базовый шаблон ОС, кэшируемый в `~/.vagrant.d/boxes/`. Жестко привязан к формату диска конкретного провайдера.
- **Плагин (Plugin)** — расширение CLI для поддержки провайдеров, автоматизации (vbguest, proxyconf) или интеграции с внешними системами.

## Базовые концепции

### Компоненты системы

1.  **Бинарный пакет Vagrant:** Основное CLI-приложение. Рекомендуется использовать официальные репозитории HashiCorp для обеспечения безопасности и стабильности.
2.  **Плагины (Plugins):** Расширения для поддержки новых провайдеров (libvirt, AWS), настройки прокси или автоматизации гостевых дополнений.
3.  **Образы (Boxes):** Сжатые шаблоны ОС. Кэшируются локально в директории `~/.vagrant.d/boxes/`.

### Требования к системе

Перед установкой убедитесь, что хост-система удовлетворяет минимальным требованиям:

| Компонент | Требование |
| :--- | :--- |
| **Аппаратная виртуализация** | Intel VT-x / AMD-V (для KVM/Libvirt); SVM/Virtualization (AMD); Hyper-V (Windows). Обязательно включена в BIOS/UEFI. |
| **ОС** | Linux (современные дистрибутивы), macOS 11+, Windows 10/11 Pro/Enterprise (для Hyper-V). |
| **Память** | От 4 ГБ (минимально), рекомендуется 8+ ГБ для одновременной работы нескольких ВМ. |
| **Диск** | От 10 ГБ свободного места под кэш образов и диски ВМ. |
| **Сеть** | Доступ в интернет для загрузки образов и обновлений (для изолированных сред — см. сценарий офлайн-установки). |

**Проверка аппаратной виртуализации:**

```bash
# Linux (Intel/AMD)
egrep -c '(vmx|svm)' /proc/cpuinfo
# → результат > 0 означает поддержку

# Проверка загрузки модулей KVM
lsmod | grep kvm
# → kvm_intel или kvm_amd должен быть загружен

# macOS
sysctl -a | grep machdep.cpu.features | grep VMX
# → VMX означает поддержку Intel VT-x

# Windows (PowerShell)
(Get-CimInstance -ClassName Win32_Processor).VirtualizationFirmwareEnabled
```

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
| **macOS (Homebrew)**| `brew install vagrant` | Поддержка Intel и Apple Silicon. Для ARM64 также требуется `brew install --cask vagrant`. |
| **Windows** | `winget install HashiCorp.Vagrant` | Требует перезапуска терминала для обновления PATH. Для Hyper-V включите роль в «Компонентах Windows». |

**macOS (Intel):**
```bash
brew install --cask vagrant
```

**macOS (Apple Silicon / M1/M2/M3):**
```bash
brew install --cask vagrant
vagrant plugin install vagrant-qemu
```

> Примечание: на macOS стандартный VirtualBox нестабилен на ARM64. Используйте `vagrant-qemu` с Hypervisor.framework.

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

**Для Fedora/RHEL:**
```bash
sudo dnf install -y ruby-devel libvirt-devel qemu-kvm libvirt-daemon
vagrant plugin install vagrant-libvirt
```

### Сценарий 5: Установка в среде с прокси

Если корпоративная сеть требует прокси, настройте переменные окружения ДО установки Vagrant:

```bash
export http_proxy="http://proxy.corp.example.com:3128"
export https_proxy="http://proxy.corp.example.com:3128"
export no_proxy="localhost,127.0.0.1,.local,.corp.example.com"

# Для apt
echo "Acquire::http::Proxy \"http://proxy.corp.example.com:3128\";" | \
  sudo tee /etc/apt/apt.conf.d/99proxy
```

### Сценарий 6: Офлайн-установка (air-gapped)

Для изолированных сред без доступа в интернет:

```bash
# 1. На машине с доступом в интернет скачайте пакет
# Debian/Ubuntu:
apt download vagrant
# Или скачайте .deb с https://apt.releases.hashicorp.com

# 2. Перенесите пакет в изолированную сеть
scp vagrant_*.deb isolated-host:/tmp/

# 3. Установите локально
sudo dpkg -i /tmp/vagrant_*.deb
sudo apt-get install -f

# 4. Перенесите box-файлы (.box) через внешний носитель
vagrant box add internal-image ./custom.box --provider libvirt
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

# Проверка провайдера (пример для Libvirt)
virsh list --all
# → должен отображаться демон libvirt

# Валидация работоспособности (требует любой Vagrantfile)
vagrant validate
```

### Удаление и очистка

```bash
# Debian/Ubuntu
sudo apt-get remove --purge vagrant

# Fedora/RHEL
sudo dnf remove vagrant

# Arch
sudo pacman -Rns vagrant

# Очистка глобального кэша (образы, плагины)
rm -rf ~/.vagrant.d/

# Удаление плагинов
vagrant plugin expunge
```

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `VT-x is not available` | Аппаратная виртуализация отключена в BIOS/UEFI или захвачена Hyper-V | Включите VT-x/AMD-V в BIOS; отключите Hyper-V (`bcdedit /set hypervisorlaunchtype off`) |
| `The box '...' could not be found` | Неверное имя box или отсутствует провайдер | `vagrant box add bento/ubuntu-24.04 --provider virtualbox` |
| `No matching downloader for provider` | Плагин провайдера не установлен | `vagrant plugin install vagrant-libvirt` или `vagrant plugin install vagrant-vmware-desktop` |
| `Permission denied` при работе с libvirt | Пользователь не в группе `libvirt` или демон не запущен | `sudo usermod -aG libvirt $USER && sudo systemctl start libvirtd` |
| `Plugin error` | Несовместимость версий плагинов | `vagrant plugin update` или `vagrant plugin expunge --reinstall` |
| `GPG error` при добавлении репозитория | Не установлен или устарел ключ HashiCorp | Повторите добавление GPG-ключа и обновите apt |
| `Failed to download box` | Прокси блокирует HTTPS или проблемы с DNS | Настройте `http_proxy` / `https_proxy`; проверьте `curl -I <box_url>` |
| `command not found: vagrant` после установки | PATH не обновлен или установка через Snap | Перезапустите терминал; проверьте `echo $PATH` |

### Лучшие практики

1.  **Безопасность:** Используйте официальные репозитории HashiCorp. Верифицируйте контрольные суммы образов через `box_download_checksum`.
2.  **Изоляция:** Для изолированных сред используйте внутренние зеркала (`box_url`) вместо прямого доступа к Vagrant Cloud.
3.  **Производительность:** Перенесите `VAGRANT_HOME` на быстрый диск (SSD), чтобы ускорить доступ к образам.
4.  **Версионирование:** Фиксируйте версию Vagrant в документации проекта (`Vagrant.require_version`).
5.  **Чистота:** Регулярно используйте `vagrant box prune` для удаления неиспользуемых версий образов.

### См. также

- [Базовый рабочий процесс](./vagrant_basic_workflow.md) — инициализация и запуск.
- [Провайдеры и образы](./vagrant_providers.md) — настройка гипервизоров.
- [Vagrant на Apple Silicon](./vagrant_macos_apple_silicon.md) — особенности для ARM64.
