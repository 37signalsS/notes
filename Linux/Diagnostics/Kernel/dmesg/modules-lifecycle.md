# Диагностика жизненного цикла модулей ядра через dmesg

## Определения

**Жизненный цикл модуля ядра** — процесс от компиляции до загрузки, работы и выгрузки динамически загружаемого модуля (LKM, Loadable Kernel Module). Каждый этап генерирует сообщения в kmsg, доступные через dmesg, что позволяет диагностировать проблемы с зависимостями, версиями, подписями и конфликтами модулей.

**Сообщения модулей в dmesg** — выводы ядра при выполнении операций `modprobe`, `insmod`, `rmmod`, `modprobe -r`, включая ошибки загрузки, предупреждения о taint, проблемы с Secure Boot подписью и конфликты версий.

---

## Базовые концепции

### Этапы жизненного цикла и соответствующие dmesg-сообщения

| Этап | Команда | Типичные сообщения в dmesg |
|:---|:---|:---|
| Загрузка | `modprobe`, `insmod` | `module: loaded successfully`, `Unknown symbol`, `vermagic mismatch` |
| Выгрузка | `rmmod`, `modprobe -r` | `module: unloaded`, `module is in use`, `module is being removed` |
| Ошибка | — | `FATAL: Module xyz not found`, `Invalid module format` |
| Taint | — | `module: loading out-of-tree module forces taint` |
| Secure Boot | — | `module verification failed: signature and/or required key missing` |

### Механизм загрузки модуля

```
modprobe <module>
  → modprobe читает /lib/modules/$(uname -r)/modules.dep
  → Проверяет зависимости (resolved via depmod)
  → Вызывает init_module() или finit_module()
  → Ядро выполняет module_init() функцию
  → Модуль зарегистрирован в системе
```

---

## Практические сценарии

### Поиск событий модулей в dmesg

```bash
# Все сообщения о модулях
dmesg -T | grep -iE "module|modprobe|insmod|rmmod|\.ko"

# Только ошибки загрузки
dmesg -T | grep -iE "FATAL.*module|Unknown symbol|Invalid module format|vermagic|taint|signature"

# Модули, вызвавшие taint
dmesg -T | grep -iE "taint.*module|module.*taint|loading.*out-of-tree"
```

### Диагностика ошибки «FATAL: Module xyz not found»

```bash
# 1. Проверить, существует ли модуль
find /lib/modules/$(uname -r) -name "xyz.ko*" 2>/dev/null

# 2. Проверить modules.dep
modinfo xyz 2>&1
# → modinfo: ERROR: Module xyz not found

# 3. Пересоздать modules.dep
sudo depmod -a

# 4. Проверить, не в blacklist ли модуль
grep -r "xyz" /etc/modprobe.d/ 2>/dev/null
grep -r "blacklist.*xyz" /lib/modules/$(uname -r)/modules.d/ 2>/dev/null

# 5. Проверить, не заблокирован ли через cmdline
cat /proc/cmdline | grep -o "module_blacklist=[^ ]*"
```

### Диагностика «Unknown symbol»

```bash
# 1. Найти ошибку в dmesg
dmesg -T | grep -i "Unknown symbol"
# → module: Unknown symbol xyz (err 0)

# 2. Определить, какой модуль предоставляет этот символ
modprobe --show-depends xyz 2>&1 | grep -v "^modprobe"
cat /lib/modules/$(uname -r)/modules.symbols 2>/dev/null | grep "xyz"

# 3. Проверить зависимости модуля
modinfo -F depends xyz

# 4. Загрузить зависимости вручную
sudo modprobe <dependency_module>
sudo modprobe xyz
```

### Диагностика «Invalid module format» (vermagic mismatch)

```bash
# 1. Найти ошибку
dmesg -T | grep -i "Invalid module format"
# → module: vermagic: vermagic 5.15.0-xx-generic SMP mod_unload

# 2. Проверить vermagic модуля
modinfo xyz | grep vermagic

# 3. Проверить текущее ядро
uname -r

# 4. Решение: переустановить модуль для текущего ядра
sudo apt install linux-modules-extra-$(uname -r)  # Debian/Ubuntu
sudo dnf install kernel-modules-$(uname -r)       # RHEL/Fedora
```

### Диагностика ошибки «Module is in use»

```bash
# 1. Найти, кто использует модуль
dmesg -T | grep -i "module is in use"
lsmod | grep <module_name>

# 2. Определить зависимости
lsmod | awk '{print $1, $3, $4}' | grep <module_name>

# 3. Выгрузить зависимости (в обратном порядке)
sudo modprobe -r <dependent_module_2>
sudo modprobe -r <dependent_module_1>
sudo modprobe -r <module_name>

# 4. Принудительная выгрузка (ОПАСНО — может вызвать kernel panic)
sudo rmmod -f <module_name>  # Только как крайняя мера!
```

### Диагностика taint от модулей

```bash
# 1. Проверить taint-статус
cat /proc/sys/kernel/tainted
# → 4096 = загружен проприетарный модуль (P)
# → 12288 = O + P (out-of-tree + proprietary)

# 2. Найти, какой модуль вызвал taint
dmesg -T | grep -iE "taint|module.*out-of-tree|module.*proprietary"

# 3. Расшифровка флагов taint (из dmesg)
# → P — Proprietary (например, NVIDIA, VirtualBox)
# → O — Out-of-tree (скомпилирован вне дерева ядра)
# → E — Unsigned (не подписан)
# → F — Force-loaded (загружен принудительно, игнорируя версии)

# 4. Проверить, какие модули загружены извне дерева
find /lib/modules/$(uname -r) -name "*.ko" -exec modinfo {} \; 2>/dev/null | grep -B5 "license.*Proprietary"
```

### Диагностика проблем Secure Boot / Module signing

```bash
# 1. Найти ошибки подписи
dmesg -T | grep -iE "signature|required key|module verification failed|disallowed"

# 2. Проверить, включён ли Secure Boot
mokutil --sb-state 2>/dev/null
# → SecureBoot enabled

# 3. Проверить, есть ли MOK (Machine Owner Key)
mokutil --list-enrolled 2>/dev/null

# 4. Решение: подпис модуль через MOK
sudo mokutil --import /path/to/MOK.der
# Перезагрузка → MokManager → Enroll MOK

# 5. Временное отключение Secure Boot (для отладки)
# Через BIOS/UEFI setup
```

### Мониторинг загрузки модулей при старте системы

```bash
# Просмотр модулей, загруженных при boot
dmesg -T | grep -iE "module.*loaded|modprobe.*success" | head -20

# Проверка модулей из /etc/modules-load.d/
cat /etc/modules-load.d/*.conf 2>/dev/null

# Проверка systemd-modules-load
systemctl status systemd-modules-load.service
journalctl -u systemd-modules-load -b
```

---

## Дополнительная информация

### Связанные темы

*   [**Модули ядра Linux**](../../../Core/kernel/kernel_modules.md) — полный lifecycle, DKMS, blacklist, параметры.
*   [**Обзор dmesg**](./index.md) — архитектура kmsg, уровни важности.
*   [**Поиск и устранение неисправностей**](./troubleshooting.md) — Call Trace, Oops, Panic.
*   [**Secure Boot / Hardening**](../../../Security/Mechanisms/Kernel/hardening.md) — подписание модулей, Lockdown.
*   [**Audit модулей**](../../../SystemAdministration/Logging/auditd.md) — мониторинг загрузки модулей через auditd.
*   [**Live Patching**](../../../Core/kernel/live_patching.md) — обновление модулей без перезагрузки.
