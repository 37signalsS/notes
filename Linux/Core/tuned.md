# TuneD — оптимизация производительности системы

## Определения

**TuneD** — демон в Linux для автоматической оптимизации производительности системы. Использует профили с предустановленными параметрами ядра, сети, дисков и других подсистем.

**Профиль производительности** — набор предопределённых настроек для конкретного сценария использования (сервер, десктоп, виртуальная машина, низкая задержка).

## Основные концепции

### Возможности TuneD

| Возможность | Описание |
| :--- | :--- |
| **Готовые профили** | Для различных сценариев: desktop, server, virtual-guest, latency-performance, network-throughput |
| **Кастомные профили** | Создание собственных профилей на основе существующих |
| **Динамическая оптимизация** | Автоматическая корректировка настроек в зависимости от нагрузки (опционально) |
| **Централизованное управление** | Все параметры (sysctl, планировщик, диски) в одном месте |
| **Верификация** | Проверка применения настроек (`tuned-adm verify`) |

### Структура профиля

**Расположение профилей:**

- **Системные:** `/usr/lib/tuned/<имя_профиля>/`
- **Кастомные:** `/etc/tuned/<имя_профиля>/` (приоритет)

**Основной файл:** `tuned.conf`

**Структура:**

```ini
[main]
summary=Описание профиля
include=базовый-профиль  # Наследование

[sysctl]
vm.swappiness = 10
net.core.somaxconn = 4096

[cpu]
governor = performance

[disk]
elevator = deadline

[network]
timeout = 100
```

**Плагины:** `cpu`, `disk`, `network`, `sysctl`, `services`, `vm`, `bootloader`, `script`

## Практические сценарии

### 1. Установка и запуск

```bash
# RHEL/CentOS/Fedora/AlmaLinux
sudo dnf install tuned

# Debian/Ubuntu (если доступен)
sudo apt install tuned

# Запуск и включение автозапуска
sudo systemctl enable --now tuned

# Проверка статуса
systemctl status tuned
```

### 2. Управление профилями

```bash
# Просмотр доступных профилей
tuned-adm list

# Просмотр текущего профиля
tuned-adm active

# Рекомендация профиля от TuneD
tuned-adm recommend

# Установка профиля
tuned-adm profile latency-performance
```

**Распространённые профили:**

| Профиль | Назначение |
| :--- | :--- |
| `balanced` | Базовый профиль (по умолчанию) |
| `throughput-performance` | Пропускная способность дисков |
| `latency-performance` | Низкая задержка (CPU governor performance) |
| `network-throughput` | Оптимизация сети |
| `virtual-guest` | Для гостевых ВМ |
| `virtual-host` | Для хостов виртуализации |
| `oracle` | Для СУБД Oracle |
| `desktop` | Для рабочих станций |
| `powersave` | Энергосбережение |

### 3. Проверка применения настроек

```bash
# Верификация (проверка параметров)
tuned-adm verify

# Проверка активных параметров ядра
sysctl -a | grep -E 'vm.|net.'

# Проверка CPU governor
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

> **Примечание:** Если TuneD не может применить настройки (например, если параметры переопределены вручную в конфигах [sysctl](./kernel/sysctl.md)), `tuned-adm verify` выдаст предупреждение.

### 4. Управление TuneD

```bash
# Временно выключить профиль
tuned-adm off

# Включить обратно
tuned-adm profile <имя_профиля>

# Полностью отключить демон
sudo systemctl stop tuned
sudo systemctl disable tuned
```

### 5. Динамическая оптимизация

По умолчанию выключена. Позволяет автоматически менять настройки в зависимости от нагрузки.

**Включение:**

```ini
# /etc/tuned/tuned-main.conf (или основной конфиг профиля)
[main]
dynamic_tuning = 1
```

**Перезапуск:**

```bash
sudo systemctl restart tuned
```

> **Примечание:** Динамическая оптимизация поддерживается не всеми плагинами. Чаще используется на рабочих станциях, чем на серверах.

### 6. Создание кастомного профиля

```bash
# 1. Создать директорию
sudo mkdir -p /etc/tuned/my-profile

# 2. Создать tuned.conf
sudo tee /etc/tuned/my-profile/tuned.conf << 'EOF'
[main]
summary=My Custom Performance Profile
include=latency-performance

[sysctl]
vm.swappiness = 10
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 8192

[cpu]
governor = performance

[disk]
elevator = deadline
EOF

# 3. Активировать профиль
sudo tuned-adm profile my-profile

# 4. Проверить
tuned-adm active
```

### 7. Устранение неполадок

| Проблема | Решение |
| :--- | :--- |
| Профиль не применяется | Проверить `systemctl status tuned`, `journalctl -u tuned` |
| `tuned-adm verify` выдаёт ошибки | Параметры переопределены вручную в `/etc/sysctl.conf` или `/etc/sysctl.d/` |
| Демон не запускается | Проверить конфликты с другими сервисами оптимизации (например, TLP, LMT) |
| Настройки сбрасываются после перезагрузки | Убедиться, что профиль включён через `tuned-adm` и сервис `tuned` в автозагрузке |

## Дополнительная информация

### Связанные темы

- **[Настройка параметров ядра (sysctl)](./kernel/sysctl.md)** — управление параметрами через sysctl
- **[Оптимизация памяти (Memory Tuning)](./memory/performance_tuning.md)** — глубокая настройка подсистемы памяти
- **[CPU Pinning](./cpu_pinning.md)** — привязка процессов к ядрам CPU
- **[Обзор Systemd](./systemd/overview.md)** — управление системными службами
