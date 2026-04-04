# Live Patching и kexec

## Определения

**Live Patching** — технология применения обновлений безопасности и исправлений к работающему ядру Linux без перезагрузки.

**`kexec`** — системный вызов, позволяющий загрузить новое ядро из текущего, минуя этапы BIOS/UEFI и аппаратной инициализации (POST).

## Основные концепции

### Live Patching: принцип работы

Инструменты live patching применяют патчи к ядру прямо в памяти, используя механизм `ftrace` для перенаправления вызовов старых функций на исправленные версии.

- **Назначение:** Критические обновления безопасности и серьёзные багфиксы.
- **Ограничение:** Не подходит для мажорных обновлений ядра — патчи затрагивают только конкретные функции.
- **Преимущество:** Максимальный uptime, отсутствие простоев.

### Реализации Live Patching

| Решение | Разработчик | Дистрибутивы |
| :--- | :--- | :--- |
| **`kpatch`** | Red Hat | RHEL, AlmaLinux, Rocky Linux |
| **`ksplice`** | Oracle | Oracle Linux |
| **Canonical Livepatch** | Canonical | Ubuntu |
| **KernelCare** | TuxCare | Множественные (коммерческий) |

### Быстрая перезагрузка: `kexec`

`kexec` загружает новое ядро из текущего, пропуская POST — самый долгий этап перезагрузки.

- **Сценарий:** Быстрая перезагрузка при обновлении ядра, переход на новую версию без задержек BIOS.
- **Отличие от Live Patching:** `kexec` требует перезагрузки (хоть и быстрой), Live Patching — полностью бесшовный.

## Практические сценарии

### Использование `kexec`

**Установка:**

```bash
# RHEL/CentOS
sudo yum install kexec-tools

# Debian/Ubuntu
sudo apt install kexec-tools
```

**Загрузка нового ядра:**

```bash
# Загрузить ядро и initramfs, используя текущие параметры командной строки
sudo kexec -l /boot/vmlinuz-$(uname -r) --initrd=/boot/initrd.img-$(uname -r) --reuse-cmdline
```

**Выполнение перезагрузки:**

```bash
# Через systemd
sudo systemctl kexec

# Напрямую
sudo kexec -e
```

### Проверка статуса Live Patching

```bash
# Проверка загруженных live-патчей (kpatch)
kpatch list

# Проверка ftrace-хуков (признак активности live patching)
cat /sys/kernel/livepatch/*/enabled
```

## Дополнительная информация

### Связанные темы

- **Паника ядра:** [Kernel Panic](./kernel_panic.md) — kdump использует `kexec` для загрузки capture-ядра
- **Процесс загрузки:** [Boot Process](./boot_process.md) — этапы, которые пропускает `kexec`
- **Модули ядра:** [Kernel Modules](./kernel_modules.md) — live patching загружает патчи как модули
- **eBPF:** [eBPF](./ebpf.md) — альтернатива для наблюдаемости без перезагрузки ядра
