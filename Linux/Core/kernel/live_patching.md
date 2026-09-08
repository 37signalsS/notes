# Живое обновление ядра: Live Patching и kexec

## Определения

**Live Patching (Живой патчинг)** — технология применения исправлений безопасности (CVE) и критических багфиксов к работающему ядру Linux без остановки системы и её перезагрузки. Механизм позволяет заменять код функций ядра «на лету», обеспечивая непрерывность работы (High Availability) критически важных сервисов.
- **Основные решения:** Upstream Livepatch, kpatch (Red Hat), kgraft (SUSE), Ksplice (Oracle), Canonical Livepatch.

**kexec** — системный вызов и механизм ядра, позволяющий загрузить и запустить новое ядро Linux непосредственно из текущего, минуя этапы инициализации оборудования (BIOS/UEFI) и самодиагностики (POST).

**Kexec Handover (KHO)** — расширение (ядро 6.16+), позволяющее передавать состояние оперативной памяти (например, память виртуальных машин или файловые дескрипторы) от старого ядра новому при переходе через kexec, что сводит время простоя к миллисекундам.

**kdump** — механизм сохранения дампа оперативной памяти (`vmcore`) в момент сбоя. Использует `kexec` для загрузки резервного ядра поверх упавшего, минуя POST и BIOS/UEFI. kdump и live patching complementarily: первый используется для аварийного анализа, второй — для планового обновления.

## Предварительные требования

### Аппаратные требования

- Архитектура **x86_64** или **s390x** (полная поддержка фреймворка livepatch). На других архитектурах (ARM64, RISC-V) поддержка может быть ограничена или отсутствовать в зависимости от версии ядра.
- Поддержка **ftrace** на уровне микрокода процессора (обязательно для механизма перенаправления вызовов).
- **Intel PT** или **ARM CoreSight** (опционально) — для расширенной трассировки при отладке патчей.

### Программные требования

- Ядро Linux **4.0+** для базового live patching (per-task consistency). Ядро **5.1+** для atomic replace. Ядро **6.16+** для Kexec Handover.
- Пакет **kexec-tools** (версия 2.0.20+ для поддержки KHO).
- Для RHEL-подобных систем: пакет **kpatch** или **kernel-livepatch** (в зависимости от версии ОС).
- Для Ubuntu/Debian: пакет **canonical-livepatch** или **livepatch-build-tools** (для сборки собственных патчей).
- Для SUSE: пакет **kgraft** (обычно входит в поставку SLE).
- Доступ в интернет для загрузки подписанных патчей (если используется корпоративный репозиторий — настройка локального зеркала).
- Права **root** или возможность выполнения через `sudo` без пароля (для автоматизации).

### Настройка окружения

```bash
# 1. Проверка версии ядра
uname -r
# → 5.15.0-105-generic

# 2. Проверка поддержки livepatch в текущем ядре
grep CONFIG_LIVEPATCH /boot/config-$(uname -r)
# → CONFIG_LIVEPATCH=y

# 3. Проверка наличия kexec-tools
which kexec
# → /usr/sbin/kexec

# 4. Проверка подписи Secure Boot (если включен)
mokutil --sb-state
# → SecureBoot enabled
```

## Основные концепции

### Требования к конфигурации ядра

Для работы механизмов требуются следующие параметры в `.config` ядра:
- `CONFIG_LIVEPATCH=y` — поддержка фреймворка Livepatch.
- `CONFIG_KEXEC=y` / `CONFIG_KEXEC_FILE=y` — поддержка системного вызова kexec (второй вариант предпочтительнее для систем с Secure Boot).
- `CONFIG_DYNAMIC_FTRACE_WITH_REGS=y` — необходим для эффективного перенаправления вызовов.
- `CONFIG_HAVE_RELIABLE_STACKTRACE=y` — критичен для модели консистентности (на x86_64 и s390x).
- `CONFIG_STACK_VALIDATION=y` — включите для проверки целостности стека при переключении патчей.

### Механизмы работы Live Patching

В основе технологии лежит механизм трассировки функций `ftrace`.
1.  **Перенаправление вызовов:** Патч поставляется как модуль ядра. При активации `ftrace` подменяет первые байты оригинальной функции (инструкция `CALL` или `NOP`) на переход к исправленной версии.
2.  **Модель консистентности (Consistency Model):** Ядро использует механизм «постепенного перехода» (per-task consistency). Переключение происходит только когда поток выполнения находится в «безопасном состоянии» — вне патчируемой функции и не в состоянии сна внутри неё.
3.  **Atomic Replace:** Механизм (ядро 5.1+), позволяющий заменить один набор патчей другим за одну операцию. Это предотвращает накопление длинных цепочек зависимых модулей.
4.  **Теневые переменные (Shadow Variables):** Техника связывания данных с объектами ядра без изменения их структур (ABI). Используется, если патч требует добавления новых полей в существующие структуры (например, `task_struct`).

### Модели консистентности

Live Patching использует две основные модели:
- **Stop-the-world (kpatch, Ksplice):** При активации патча все процессы ядра временно приостанавливаются, чтобы предотвратить выполнение в неконсистентном состоянии. Подходит для небольших патчей и систем с низкими требованиями к доступности.
- **Per-task consistency (Upstream Livepatch, kgraft):** Каждый процесс переключается индивидуально, когда покидает патчируемую функцию. Отсутствует глобальная пауза, что обеспечивает минимальное влияние на отзывчивость системы.

### Эволюция kexec: от перезагрузки к Live Update (2025–2026)

Современный стек технологий позволяет обновлять ядро без перезапуска userspace:
- **LUO (Live Update Orchestrator):** Координирует передачу ресурсов (прерывания, страницы памяти) между ядрами.
- **Интеграция с systemd (v261+):** Сохранение файловых дескрипторов в `FD Store`. При `systemctl soft-reboot` ядро обновляется через kexec, а systemd восстанавливает состояние сервисов из хранилища.

### Безопасность и Kernel Lockdown

При включенном **Secure Boot** и режиме **Lockdown (Integrity/Confidentiality)**:
- `kexec` требует проверки подписи нового ядра.
- Live Patching модули должны быть подписаны доверенным ключом, иначе загрузка будет блокирована.

## Практические сценарии

### Предварительная подготовка системы

Перед применением любого патча выполните базовую подготовку:

```bash
# 1. Создание резервной копии конфигурации ядра
cp /boot/config-$(uname -r) /root/config-backup-$(date +%F).bak

# 2. Сохранение списка загруженных модулей
lsmod > /root/modules-before-$(date +%F).txt

# 3. Создание снимка состояния (если используется виртуализация)
# Для libvirt/Virsh:
virsh snapshot-create-as $(hostname) "pre-livepatch-$(date +%F)" "Before kernel live patch"

# 4. Уведомление команд мониторинга (silence alerting)
# Отправка webhook в Slack/Telegram или создание файла-маркера
touch /etc/maintenance.livepatch
```

### Настройка kexec для быстрой перезагрузки

#### RHEL / CentOS / Fedora / Rocky Linux / AlmaLinux

```bash
# Установка пакетов
sudo dnf install kexec-tools crash kernel-debuginfo

# Проверка резервирования памяти (для kdump)
cat /proc/cmdline | grep crashkernel
# → crashkernel=256M

# Загрузка нового ядра в память
sudo kexec -l /boot/vmlinuz-$(uname -r) \
     --initrd=/boot/initramfs-$(uname -r).img \
     --reuse-cmdline

# Проверка загруженного ядра
sudo kexec -e
# → Система перезагрузится в новое ядро без прохождения POST
```

#### Debian / Ubuntu

```bash
# Установка
sudo apt install kexec-tools

# Загрузка и немедленный переход
sudo kexec -l /boot/vmlinuz-$(uname -r) \
     --initrd=/boot/initrd.img-$(uname -r) \
     --reuse-cmdline
sudo systemctl kexec
```

#### Валидация kexec

```bash
# Проверка, что kexec активен
dmesg | grep -i kexec
# → kexec: Reserving the memory...

# Проверка доступного ядра для загрузки
sudo kexec -l /boot/vmlinuz-5.15.0-105-generic \
     --initrd=/boot/initramfs-5.15.0-105-generic.img \
     --reuse-cmdline --dry-run
# → Dry-run: проверка без фактической загрузки

# Тестовый переход (без изменения текущего ядра — требует перезагрузки)
# Примечание: после sudo kexec -e система перезагрузится
```

### Использование kexec для обновления ядра

**1. Загрузка нового ядра в память:**
```bash
sudo kexec -l /boot/vmlinuz-$(uname -r) \
     --initrd=/boot/initramfs-$(uname -r).img \
     --reuse-cmdline
```

**2. Выполнение перехода:**
```bash
# Мягкая перезагрузка через systemd
sudo systemctl soft-reboot
# → Перезапуск ядра через kexec с сохранением FD Store
```

### Управление патчами (sysfs)

```bash
# Список активных патчей
ls /sys/kernel/livepatch/

# Проверка состояния перехода (0 — переход завершен, 1 — в процессе)
cat /sys/kernel/livepatch/kpatch_name/transition
# → 0

# Откат патча (выгрузка модуля)
echo 0 > /sys/kernel/livepatch/kpatch_name/enabled
sudo rmmod kpatch_name
```

### Дисциплинарное обновление: RHEL / kpatch

#### Установка и активация

```bash
# Установка клиента live patching
sudo dnf install kpatch

# Проверка доступных патчей
sudo kpatch list
# → No patches installed

# Автоматическая установка патчей безопасности
sudo dnf install kernel-livepatch

# Включение службы
sudo systemctl enable --now kpatch.service

# Проверка статуса
sudo kpatch list
# → Installed patches: CVE-2024-XXXX kernel-4.18.0-425.19.2.el8_7
```

#### Управление через DNF

```bash
# Просмотр доступных live-патчей
sudo dnf updateinfo list --security

# Применение только live-патчей (без перезагрузки)
sudo dnf update --advisory 'CVE-2024-XXXX'

# Проверка необходимости перезагрузки после установки
sudo dnf needs-restarting -r
# → No packages have been updated that require a restart
```

### Дисциплинарное обновление: Ubuntu / Canonical Livepatch

```bash
# Установка через snap (рекомендуется для Ubuntu 20.04+)
sudo snap install canonical-livepatch

# Авторизация (требуется токен с https://auth.livepatch.canonical.com)
sudo canonical-livepatch enable <TOKEN>
# → Machine installed successfully.

# Проверка статуса
canonical-livepatch status
# → kernel: 5.15.0-105-generic
# → livepatch: { "patch status": "applied", "patch version": "74.1" }

# Принудительная проверка обновлений
canonical-livepatch refresh
```

### Дисциплинарное обновление: SUSE / kgraft

```bash
# Проверка доступности патчей
sudo zypper patch --cve <CVE-ID>

# Установка патча (kgraft интегрирован в SLE Live Patching)
sudo zypper install kernel-livepatch-SLE12-SP5-2402-150200.3.50.1

# Проверка статуса
sudo kgr status
# → Patches applied: 3
```

### Дисциплинарное обновление: Oracle / Ksplice

Ksplice является коммерческим решением и требует лицензии Oracle Linux Premier:
```bash
# Установка агента (требуется подписка)
sudo apt install ksplice

# Применение патчей
sudo ksplice upgrade

# Статус
sudo ksplice status
```

### Управление патчами (sysfs) — расширенное

```bash
# Список активных патчей с детальной информацией
for patch in /sys/kernel/livepatch/*/; do
    echo "=== $(basename $patch) ==="
    cat "${patch}enabled"
    cat "${patch}transition"
    cat "${patch}force" 2>/dev/null || true
done

# Принудительный переход патча (если процессы заблокированы)
echo 1 > /sys/kernel/livepatch/<patch_name>/force

# Статистика переключений
cat /sys/kernel/livepatch/<patch_name>/stats
# → total: 42
# → succeeded: 40
# → failed: 2
```

### Сборка патчей (Инструментарий)

Для создания патчей обычно используются специализированные инструменты, автоматизирующие анализ `diff` исходного кода:
- **kpatch-build:** Основной инструмент для систем на базе RHEL. Собирает патч из двух версий исходного кода ядра.
- **livepatch-build-tools:** Используется в экосистеме Ubuntu/Debian. Поддерживает создание патчей для distro-ядер.
- **Процесс:** Сравнение двух скомпилированных объектов (.o) → извлечение измененных функций → упаковка в модуль ядра.

```bash
# Пример сборки патча с kpatch-build
git clone https://github.com/dynup/kpatch.git
cd kpatch
make -C /lib/modules/$(uname -r)/build M=$(pwd) modules

# Создание патча из diff
kpatch-build --format mod --sources /usr/src/linux-5.15/ \
    --patch /tmp/cve-2024-xxxx.patch \
    --output /tmp/kpatch-custom.ko
```

### Верификация и валидация

```bash
# 1. Проверка целостности патча после установки
sudo kpatch list
# → kernel-5.15.0-105-generic
# → CVE-2024-XXXX (applied)

# 2. Проверка функциональности исправления
# Пример для CVE, связанного с сетью:
ss -tuln
# → убедиться, что сетевые сервисы работают

# 3. Проверка отсутствия паники в логах
journalctl -k --since "10 minutes ago" | grep -i "bug\|error\|warn"
# → пусто или только известные некритичные предупреждения

# 4. Проверка процессов, которые все еще используют старое ядро
sudo needs-restarting -s
# → nginx (PID 1234)
# → postgres (PID 5678)

# 5. Проверка состояния перехода патча (если еще не завершен)
watch -n1 'cat /sys/kernel/livepatch/*/transition'
# → 0 (переход завершен)
```

### Автоматизация и интеграция

#### Bash-скрипт для автоматического применения патчей

```bash
#!/bin/bash
set -euo pipefail

PATCH_NAME="${1:-}"
LOG_FILE="/var/log/livepatch-$(date +%F).log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

check_prerequisites() {
    if [[ $EUID -ne 0 ]]; then
        log "ERROR: Запустите скрипт с правами root"
        exit 1
    fi
    if ! command -v kpatch &> /dev/null && ! command -v canonical-livepatch &> /dev/null; then
        log "ERROR: Ни kpatch, ни canonical-livepatch не найдены"
        exit 1
    fi
}

apply_patch() {
    local patch="$1"
    log "Применение патча: $patch"
    
    if command -v kpatch &> /dev/null; then
        sudo kpatch load -p "$patch"
    elif command -v canonical-livepatch &> /dev/null; then
        sudo canonical-livepatch refresh
    fi
    
    sleep 5
    verify_patch
}

verify_patch() {
    local transition
    transition=$(cat /sys/kernel/livepatch/*/transition 2>/dev/null || echo "1")
    if [[ "$transition" == "0" ]]; then
        log "SUCCESS: Патч применен успешно"
    else
        log "WARNING: Патч все еще переключается"
    fi
}

main() {
    check_prerequisites
    if [[ -n "$PATCH_NAME" ]]; then
        apply_patch "$PATCH_NAME"
    else
        log "Автоматическое применение всех доступных патчей"
        if command -v dnf &> /dev/null; then
            sudo dnf update --security -y
        elif command -v apt &> /dev/null; then
            sudo apt upgrade -y
        fi
    fi
}

main "$@"
```

#### Интеграция с мониторингом (Prometheus node_exporter)

```bash
# Создание экспортера для метрик live patching
cat <<'EOF' > /usr/local/bin/livepatch-metrics.sh
#!/bin/bash
PATCH_DIR="/sys/kernel/livepatch"
if [[ -d "$PATCH_DIR" ]]; then
    echo "# HELP livepatch_patches_active Количество активных патчей"
    echo "# TYPE livepatch_patches_active gauge"
    echo "livepatch_patches_active $(ls -1 "$PATCH_DIR" | wc -l)"
    
    echo "# HELP livepatch_transition Состояние перехода патча (0=завершено, 1=в процессе)"
    echo "# TYPE livepatch_transition gauge"
    for patch in "$PATCH_DIR"/*/; do
        name=$(basename "$patch")
        val=$(cat "${patch}transition" 2>/dev/null || echo 0)
        echo "livepatch_transition{name=\"$name\"} $val"
    done
fi
EOF
chmod +x /usr/local/bin/livepatch-metrics.sh

# Добавление в node_exporter (textfile collector)
cat <<'EOF' > /etc/systemd/system/livepatch-metrics.service
[Unit]
Description=Livepatch Metrics Exporter

[Service]
Type=oneshot
ExecStart=/usr/local/bin/livepatch-metrics.sh
User=root
EOF

# Конфигурация node_exporter для textfile collector
echo "--collector.textfile.directory=/var/lib/node_exporter/textfile_collector" > /etc/default/node_exporter
mkdir -p /var/lib/node_exporter/textfile_collector
```

#### Интеграция с Ansible (связь с существующим файлом)

См. также: **[Ansible Patch Management](../../../../Ansible/ansible_patch_management.md)** — стратегии массового обновления.

Для автоматизации live patching в Ansible используйте модуль `command` или `shell` с задачами:
```yaml
- name: Проверка доступных security-патчей
  ansible.builtin.command: dnf updateinfo list --security
  register: security_patches
  changed_when: false

- name: Применение live-патча (RHEL)
  ansible.builtin.command: kpatch load -p "{{ patch_path }}"
  when: "'CVE-2024-XXXX' in security_patches.stdout"
```

## Устранение неполадок

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Operation not permitted` при загрузке модуля | Модуль неподписан или Secure Boot включен | Подпишите модуль доверенным ключом (`kmodsign`) или отключите Secure Boot |
| `Transition failed: patch dependency` | Зависимый патч не загружен | Убедитесь, что все базовые патчи применены (`kpatch list`) |
| `kexec: failed to load` | Недостаточно памяти для резервирования | Увеличьте `crashkernel` или отключите KDUMP |
| `livepatch: no such file or directory` | Ядро собрано без `CONFIG_LIVEPATCH` | Пересоберите ядро с поддержкой livepatch или используйте distro-ядро |
| `cannot allocate memory` при `kexec -l` | Память занята другими процессами | Освободите память или уменьшите `crashkernel` |
| `Module verification failed` | Подпись модуля невалидна | Проверьте целостность пакета `rpm -V kernel-livepatch` |

### Диагностика

```bash
# 1. Проверка логов ядра на ошибки livepatch
journalctl -k --since "1 hour ago" | grep -i livepatch
dmesg | grep -i livepatch

# 2. Проверка состояния модулей
lsmod | grep -E "kpatch|livepatch|kgr"
sudo rmmod kpatch_name 2>&1 || true

# 3. Проверка подписи модуля
modinfo /path/to/patch.ko | grep signature

# 4. Проверка совместимости архитектуры
file /boot/vmlinuz-$(uname -r)
# → ELF 64-bit LSB executable, x86-64

# 5. Проверка доступной памяти для kexec
free -h
cat /proc/iomem | grep -i crash
# → 100000000-10fffffff : Crash kernel
```

## Лучшие практики

- **Соблюдайте окно обслуживания:** Даже live patching имеет риски. Применяйте патчи в Planned Maintenance Window с заранее согласованным временем.
- **Тестируйте на канареечном узле:** Примените патч к одному серверу, убедитесь в стабильности в течение 24-48 часов, затем раскатывайте на остальные.
- **Сохраняйте возможность отката:** Не выгружайте старые патчи до подтверждения стабильности нового. Atomic replace позволяет заменить патч без выгрузки, но откат через `rmmod` всегда должен быть возможен.
- **Используйте shadow variables вместо изменения ABI:** Изменение структур ядра (например, `task_struct`) ломает модули. Shadow Variables — безопасный паттерн для расширения данных.
- **Интегрируйте с уведомлениями:** Настройте алерты на `transition != 0` дольше 30 секунд — это может указывать на зависший процесс.
- **Версионируйте ядро и патчи:** Ведите журнал `kpatch list` или `cat /sys/kernel/livepatch/*/version` после каждого применения.
- **Ограничивайте параллелизм:** При массовом применении патчей используйте `serial: 1` или аналогичные ограничения в инструментах оркестрации.
- **Регулярно обновляйте kexec-tools:** KHO требует версии 2.0.20+. Старые версии могут не поддерживать флаги `--handover`.

## Ограничения и крайние случаи

### Известные ограничения Live Patching

- **Ограничение по архитектуре:** Не все архитектуры поддерживают reliable stack trace (ARM64 требует ядро 5.4+ с дополнительными патчами).
- **Зависимости функций:** Патч не может заменить функцию, если другая функция в стеке вызовов уже зависит от старой версии (возможна гонка при очень частых вызовах).
- **Время перехода:** Per-task consistency может занимать от нескольких секунд до минут на высоконагруженных системах с тысячами потоков.
- **Совместимость distro-ядер:** Вендорные патчи (RHEL, Ubuntu) могут применяться только к соответствующим ядрам. Community-патчи требуют сборки под конкретный `.config`.
- **Невозможность изменения ABI:** Live patch не может изменить размер или расположение полей в структурах ядра. Для этого требуются shadow variables.

### Известные ограничения kexec

- **Только для Linux:** kexec специфичен для Linux; на других Unix-системах аналогичный функционал отсутствует или реализован иначе.
- **Память:** Требует резервирования области памяти для нового ядра. На системах с малым объемом RAM это может быть проблемой.
- **Драйверы:** При kexec перезапускаются драйверы устройств. Время инициализации оборудования остается, если KHO не поддерживается или не включен.
- **Secure Boot:** Требует подписи нового ядра. Без этого kexec будет отклонен ядром.

### Поведение в нестандартных сценариях

- **Высоконагруженные системы (>1000 процессов):** Transition может занять длительное время. Мониторьте `/sys/kernel/livepatch/*/transition` и учитывайте это в SLA.
- **Системы реального времени (RT-PREEMPT):** Live patching может конфликтовать с приоритетами реального времени. Тестируйте тщательно.
- **Контейнерные хосты:** Живой патчинг применим к хостовому ядру, но не к ядрам внутри контейнеров. Для контейнеров используйте стандартное обновление образа.
- **Виртуализация (KVM/QEMU):** kexec работает корректно, но убедитесь, что гипервизор не блокирует системные вызовы через `seccomp`.

## Соответствие и аудит

Для соответствия требованиям регуляторов (PCI DSS, ФЗ-152, SOC 2) ведите журналирование:

```bash
# Пример формата журнала live patching
cat <<'EOF' > /etc/rsyslog.d/livepatch.conf
# Перенаправление логов livepatch в отдельный файл
:programname, isequal, "kernel" /var/log/livepatch-kernel.log
& stop
EOF

systemctl restart rsyslog
```

**Что логировать:**
- Время применения патча (`/sys/kernel/livepatch/*/version` содержит timestamp)
- Результат перехода (success/failed)
- Список примененных CVE
- Хэш модуля патча (`sha256sum /path/to/patch.ko`)
- Ссылка на maintenance window

## Сравнение технологий патчинга

| Решение | Механизм переключения | Провайдер | Поддержка архитектур | Подпись | Цена |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Livepatch (Upstream)** | Per-task consistency | Ядро Linux | x86_64, s390x, ARM64 (ограниченно) | Да (kmodsign) | Бесплатно |
| **kpatch** | Stop-the-world (остановка CPU) | Red Hat | x86_64, s390x | Да (MOK) | Бесплатно (RHEL subscription) |
| **kgraft** | Per-task consistency | SUSE | x86_64, s390x, POWER | Да | Бесплатно (SUSE subscription) |
| **Ksplice** | Stop-the-world + Binary diff | Oracle | x86_64, ARM64 (ограниченно) | Да | Коммерчески |
| **Canonical Livepatch** | Per-task consistency | Canonical | x86_64, ARM64 | Да ( snaps) | Бесплатно (до 3 машин), затем платно |

## Дополнительная информация

### Связанные темы

- **Аварийные ситуации:** [Kernel Panic](./kernel_panic.md) — использование `kexec` в `kdump`.
- **Процесс загрузки:** [Boot Process](./boot_process.md) — оптимизация этапов через `kexec`.
- **Модули ядра:** [Kernel Modules](./kernel_modules.md) — управление жизненным циклом патчей-модулей.
- **Диагностика:** [eBPF](./ebpf.md) — динамическая модификация логики для мониторинга.
- **Выключение и перезагрузка:** [Shutdown and Reboot](../../Linux/SystemAdministration/shutdown_and_reboot.md) — контекст использования kexec в процессе завершения работы.
- **Управление уязвимостями:** [Vulnerability Management](../../Linux/Security/vulnerability_management.md) — интеграция live patching в процесс устранения CVE.
- **Патч-менеджмент:** [Ansible Patch Management](../../../../Ansible/ansible_patch_management.md) — автоматизация обновлений.
